"""クラウドを使わない合成backendと、実行不能な合成専用設定。"""

import io

import numpy as np
from PIL import Image

from colorstats.api_budget import digest
from colorstats.trial_inputs import sha
from colorstats.trial_native import LIMITS, MODELS, PROMPT, SAM2
from colorstats.trial_native_common import (
    CONTROLLER_LOCK,
    SAM3_LOCK,
    SAM3_PYTHON,
    code_files,
    environment_reference,
)


def synthetic_plan(root, *, concurrency=1, measurement=False, purpose="trial"):
    """合成検証用の固定形式を作る。ライセンス・重み・環境は実確認として扱わない。"""
    configurations, deployments = {}, {}
    for key, precision in zip("ABCDE", ["BF16", "BF16", "AWQ4", "BF16", "FP32"], strict=True):
        model = {
            "repo": MODELS[key][0],
            "revision": MODELS[key][1],
            "files": [{"file": "synthetic.bin", "sha256": sha(key.encode())}],
            "license_confirmed": False,
            "license_ref": sha(b"synthetic"),
        }
        segmenter = {
            "repo": SAM2[0],
            "revision": SAM2[1],
            "files": [{"file": "synthetic.bin", "sha256": sha(b"sam2")}],
            "license_confirmed": False,
            "license_ref": sha(b"synthetic"),
        }
        if key in "DE":
            segmenter = model
        versions = {"synthetic-unverified": "0"}
        runtime = {
            "code_files": code_files(),
            "lock": {"file": CONTROLLER_LOCK, "sha256": sha(b"synthetic-controller-lock")},
        }
        if key == "E":
            runtime["sam3"] = {
                "python": SAM3_PYTHON,
                "lock": {"file": SAM3_LOCK, "sha256": sha(b"synthetic-sam3-lock")},
                "versions": {
                    "numpy": "1.26.4",
                    "torch": "2.11.0",
                    "torchvision": "0.26.0",
                    "transformers": "4.57.6",
                },
            }
        configurations[key] = {
            "model_revision": model["revision"],
            "weights_sha256": digest(model["files"]),
            "precision": precision,
            "environment_sha256": digest(environment_reference(versions, runtime)),
            "code_sha256": digest(runtime["code_files"]),
            "prompt_sha256": sha(PROMPT.encode()),
            "processor_sha256": digest(LIMITS),
            "segmenter_revision": segmenter["revision"],
            "segmenter_sha256": digest(segmenter["files"]),
        }
        deployments[key] = {
            "container": "synthetic/image@sha256:" + sha(b"not-a-container"),
            "gpu": "NVIDIA A40",
            "gpu_count": 2 if key in "BC" else 1,
            "disk_gb": 100,
            "usd_hour": 1.4 if key in "BC" else 0.7,
            "hourly_extras_usd": 0,
            "fixed_usd": 0,
            "minimum_seconds": 1,
            "time_seconds": 3600,
            "cleanup_seconds": 30,
            "memory_fraction": 0.85,
            "image_timeout_seconds": 120,
            "prepare_timeout_seconds": 1800,
            "versions": versions,
            "runtime": runtime,
            "model": model,
            "segmenter": segmenter,
        }
    return {
        "version": "trial-execution-v1",
        "provider": "runpod",
        "product": "secure-on-demand",
        "region": "SYNTHETIC",
        "result_root": str(root),
        "budget_ledger": str(root.parent / (root.name + "-usd.json")),
        "configurations": configurations,
        "deployments": deployments,
        "concurrency": concurrency,
        "measurement": measurement,
        "purpose": purpose,
    }


class FakeRunPod:
    """ネットワークなしで、#141の回収契約と資源終了まで同じrunnerを通す。"""

    synthetic = True

    def __init__(self, region):
        self.region = region
        self.pods, self.jobs, self.deleted, self.events = {}, {}, [], []

    def create(self, resource, deployment):
        pod = {
            "id": resource["attempt"],
            "name": resource["name"],
            "status": "RUNNING",
            "image": deployment["container"],
            "cloud": "SECURE",
            "dataCenterId": self.region,
            "gpu": {"id": deployment["gpu"], "count": deployment["gpu_count"]},
            "mounts": {},
            "cost": deployment["usd_hour"] - deployment["hourly_extras_usd"],
        }
        self.pods[resource["attempt"]] = pod
        self.events.append("create")
        return pod

    def status(self, resource):
        return self.pods.get(resource["attempt"])

    def prepare(self, pod, resource, spec):
        self.events.append("prepare")

    def prepared(self, pod, resource):
        return True

    def submit(self, pod, resource, image, content, spec):
        with Image.open(io.BytesIO(content)) as source:
            mask = np.zeros((source.height, source.width), dtype="uint8")
            mask[source.height // 3 :, source.width // 4 : source.width * 3 // 4] = 255
        stream = io.BytesIO()
        Image.fromarray(mask).save(stream, format="PNG")
        blob = stream.getvalue()
        value = {
            "attempt": resource["attempt"],
            "trial_id": image["trial_id"],
            "configuration_id": resource["configuration_id"],
            "configuration_sha256": digest(spec["contract"]),
            "input_sha256": sha(content),
            "size": image["input"]["size"],
            "status": "success",
            "scene": "unsupported" if resource["configuration_id"] == "E" else image["scene"],
            "regions": [
                {
                    "part": "wall",
                    "box": [0.25, 0.3, 0.75, 1],
                    "mask": {"file": "mask-00.png", "sha256": sha(blob)},
                }
            ],
            "elapsed_seconds": 1,
            "peak_vram_mib": 0,
        }
        self.jobs[(resource["attempt"], image["trial_id"])] = (value, {"mask-00.png": blob})
        self.events.append("submit")

    def collect(self, pod, resource, trial_id):
        return self.jobs.get((resource["attempt"], trial_id))

    def shorten_deadline(self, pod, resource, trial_id, deadline):
        self.events.append("shorten_deadline")

    def remove_image(self, pod, resource, trial_id):
        self.jobs.pop((resource["attempt"], trial_id))
        self.events.append("remove_image")

    def close(self, resource):
        self.pods.pop(resource["attempt"], None)
        self.jobs = {k: v for k, v in self.jobs.items() if k[0] != resource["attempt"]}
        self.deleted.append(resource["attempt"])
        self.events.append("close")
        return {"deleted": True, "billing_confirmed": True, "billed_usd": 0}
