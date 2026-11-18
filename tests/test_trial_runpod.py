"""提供元・転送・native境界はスタブで検証し、認証やGPUを使わない。"""

import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from colorstats.trial_fake import synthetic_plan
from colorstats.trial_inputs import sha
from colorstats.trial_native import checked_boxes, provision, qwen, sa2va, sam2, verify_files
from colorstats.trial_runpod import ProviderUnavailable, RunPod
from colorstats.trial_sam3 import sam3


def settings(tmp_path):
    return {
        "region": "US-TX-3",
        "api_key_file": str(tmp_path / "unread-secret"),
        "known_hosts": str(tmp_path / "known-hosts"),
        "ssh_key_file": str(tmp_path / "ssh-key"),
        "billing_receipts": str(tmp_path / "receipts.json"),
    }


def resource():
    return {
        "id": "new-pod",
        "name": "colorstats-new",
        "attempt": "A_new",
        "remote": "/tmp/colorstats-abcd/A_new",
        "created_at": "2026-11-17T00:00:00+00:00",
    }


def pod():
    return {
        "id": "new-pod",
        "name": "colorstats-new",
        "status": "RUNNING",
        "ssh": {"direct": {"host": "203.0.113.10", "port": 17445, "username": "root"}},
        "cost": 0.7,
    }


def page(key, rows, cursor=None):
    return {key: rows, "pagination": {"hasNextPage": bool(cursor), "nextCursor": cursor}}


@pytest.mark.parametrize("hf_secret", [None, "synthetic-hf", "synthetic/hf"])
def test_v2の作成payloadは地域GPUdigestとSSHだけへ固定する(tmp_path, hf_secret):
    calls = []
    backend = RunPod(
        settings(tmp_path), audit=lambda e: None, request=lambda *args: calls.append(args) or pod()
    )
    plan = synthetic_plan(tmp_path)
    deployment = plan["deployments"]["A"]
    deployment["hf_secret_name"] = hf_secret
    from colorstats.trial_runner import validate_plan

    validate_plan(plan)
    backend.create(resource(), deployment)
    method, path, payload = calls[0]
    assert (method, path) == ("POST", "/pods")
    assert payload["cloud"] == "SECURE"
    assert payload["dataCenterIds"] == ["US-TX-3"]
    assert payload["ports"] == ["22/tcp"]
    assert payload["startJupyter"] is False
    assert payload["env"] == (
        {"HF_TOKEN": "{{ RUNPOD_SECRET_" + hf_secret + " }}"} if hf_secret else {}
    )
    assert payload["mounts"] == {} and "queue" not in payload
    assert "@sha256:" in payload["image"]
    assert not (tmp_path / "unread-secret").exists()


def test_全ページを列挙して当試行名だけを照合する(tmp_path):
    calls = []

    def request(method, path, body=None):
        calls.append(path)
        if path == "/pods/new-pod":
            return pod()
        if "cursor=" not in path:
            return page("pods", [{"id": "old", "name": "existing"}], "next")
        listed = pod()
        listed["ssh"]["direct"] = None
        return page("pods", [listed])

    backend = RunPod(settings(tmp_path), audit=lambda e: None, request=request)
    assert backend.status(resource())["ssh"]["direct"]["host"] == "203.0.113.10"
    assert calls == ["/pods", "/pods?cursor=next", "/pods/new-pod"]


def test_同名の複数資源を自動選択しない(tmp_path):
    backend = RunPod(
        settings(tmp_path), audit=lambda e: None, request=lambda *args: page("pods", [pod(), pod()])
    )
    with pytest.raises(ProviderUnavailable, match="複数"):
        backend.status(resource())


def test_終了は新設Podだけで既存volumeに触らず請求未確定を残す(tmp_path):
    calls = []
    alive = True

    def request(method, path, body=None):
        nonlocal alive
        calls.append((method, path))
        if method == "DELETE":
            assert path == "/pods/new-pod"
            alive = False
            return {}
        if path == "/pods":
            return page("pods", ([pod()] if alive else []) + [{"id": "old", "name": "existing"}])
        if path == "/pods/new-pod":
            return pod()
        if path == "/network-volumes":
            return page("networkVolumes", [{"id": "shared", "name": "existing"}])
        if path.startswith("/billing/pods?"):
            return {"records": [{"podId": "new-pod", "totalAmount": 0.25}]}
        raise AssertionError(path)

    config = settings(tmp_path)
    backend = RunPod(config, audit=lambda e: None, request=request)
    receipt = backend.close(resource())
    assert receipt == {"deleted": True, "billing_confirmed": False, "billed_usd": 0.25}
    Path(config["billing_receipts"]).write_text(
        json.dumps(
            {
                "new-pod": {
                    "amount_usd": 0.3,
                    "ended_at": "2026-11-17T00:10:00+00:00",
                    "evidence_sha256": "a" * 64,
                },
            }
        )
    )
    assert backend.close(resource())["billing_confirmed"] is True
    assert [path for method, path in calls if method == "DELETE"] == ["/pods/new-pod"]


def test_SSHはhost_key照合と非対話を必須にして出力値を記録しない(tmp_path, monkeypatch):
    calls, events = [], []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"private", stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    backend = RunPod(settings(tmp_path), audit=events.append)
    assert backend._transport(pod(), "done", resource()["remote"] + "/T001")
    argv, kwargs = calls[0]
    assert "StrictHostKeyChecking=yes" in argv
    assert "BatchMode=yes" in argv and kwargs["timeout"] <= 3
    assert not any("private" in json.dumps(event) for event in events)
    assert events[-1]["stdout_sha256"] == sha(b"private")


@pytest.mark.parametrize("kind", ["host", "username", "path", "traversal"])
def test_未知のSSH先や試行外パスを拒否する(tmp_path, kind):
    remote = resource()["remote"]
    target = pod()
    if kind == "path":
        remote = "/etc/data"
    elif kind == "traversal":
        remote += "/../outside.png"
    else:
        target["ssh"]["direct"][kind] = "untrusted;command"
    backend = RunPod(settings(tmp_path), audit=lambda e: None)
    with pytest.raises(ValueError):
        backend._transport(target, "done", remote)


def test_受信maskの脱出名を転送前に拒否する(tmp_path):
    def transfer(pod, operation, remote, local=None):
        if operation == "get":
            Path(local).write_text(json.dumps({"regions": [{"mask": {"file": "../other.png"}}]}))
        return True

    backend = RunPod(settings(tmp_path), audit=lambda e: None, transport=transfer)
    with pytest.raises(ValueError, match="ファイル名"):
        backend.collect(pod(), resource(), "T001")


def test_重み取得は固定revisionとファイル一覧を渡し既知SHAへ照合する(tmp_path, monkeypatch):
    calls = []
    blob = b"synthetic-weights"
    spec = {
        "repo": "official/example",
        "revision": "a" * 40,
        "files": [{"file": "weights.bin", "sha256": sha(blob)}],
    }

    def download(**kwargs):
        calls.append(kwargs)
        (tmp_path / "weights.bin").write_bytes(blob)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    provision(spec, tmp_path)
    assert calls[0]["revision"] == "a" * 40
    assert calls[0]["allow_patterns"] == ["weights.bin"]
    (tmp_path / "weights.bin").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="SHA"):
        verify_files(tmp_path, spec["files"])


@pytest.mark.parametrize("key", ["A", "B", "C"])
def test_Qwenはvllm_nativeと8192_1536の固定境界へ接続する(monkeypatch, key):
    calls = []

    class Processor:
        def apply_chat_template(self, messages, **kwargs):
            return "chat-template"

        def __call__(self, **kwargs):
            return {"input_ids": SimpleNamespace(shape=(1, 4000))}

    class LLM:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def generate(self, inputs, sampling, **kwargs):
            calls.append(inputs)
            return [
                SimpleNamespace(
                    outputs=[
                        SimpleNamespace(
                            finish_reason="stop",
                            token_ids=[1],
                            text='{"scene":"single","regions":[]}',
                        )
                    ]
                )
            ]

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoProcessor=SimpleNamespace(from_pretrained=lambda *a, **k: Processor())),
    )
    monkeypatch.setitem(
        sys.modules, "vllm", SimpleNamespace(LLM=LLM, SamplingParams=lambda **kw: kw)
    )
    result, tokens = qwen(
        {"model_path": "/fixed", "gpu_count": 2, "configuration_id": key, "memory_fraction": 0.85},
        Image.new("RGB", (64, 48)),
    )
    assert result["scene"] == "single" and tokens == 4000
    assert calls[0]["quantization"] == ("awq" if key == "C" else None)
    assert calls[0]["dtype"] == ("half" if key == "C" else "bfloat16")
    assert calls[0]["max_model_len"] == 8192 and calls[0]["max_num_seqs"] == 1
    assert calls[1][0]["prompt"] == "chat-template"


@pytest.mark.parametrize(
    "response",
    [
        {"scene": "single", "regions": [{"part": "wall", "box": [1, 0, 0, 1]}]},
        {"scene": "single", "regions": [{"part": "unknown", "box": [0, 0, 1, 1]}]},
        {"scene": "single", "regions": [{"part": "wall", "box": [0, 0, 1, 1]}] * 25},
    ],
)
def test_nativeの箱を補正せず不正値と上限超過を拒否する(response):
    with pytest.raises(ValueError):
        checked_boxes(response)


def test_SAM2は共通largeへ元座標の箱を渡す(monkeypatch):
    calls = []

    class Predictor:
        def __init__(self, model):
            pass

        def set_image(self, image):
            calls.append(image.shape)

        def predict(self, **kwargs):
            calls.append(kwargs)
            return np.ones((1, 48, 64), dtype=bool), None, None

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    monkeypatch.setitem(
        sys.modules,
        "sam2.build_sam",
        SimpleNamespace(build_sam2=lambda *a, **k: SimpleNamespace(float=lambda: "model")),
    )
    monkeypatch.setitem(
        sys.modules, "sam2.sam2_image_predictor", SimpleNamespace(SAM2ImagePredictor=Predictor)
    )
    _, masks = sam2(
        {"segmenter_path": "/fixed"},
        Image.new("RGB", (64, 48)),
        {"scene": "single", "regions": [{"part": "roof", "box": [0.1, 0.2, 0.8, 0.7]}]},
    )
    assert len(masks) == 1
    assert calls[1]["box"].tolist() == pytest.approx([6.4, 9.6, 51.2, 33.6])
    assert calls[1]["multimask_output"] is False


def test_Sa2VAは著者predict_forwardと内蔵maskを使う(monkeypatch):
    calls = []

    class Model:
        def eval(self):
            return self

        def cuda(self):
            return self

        def preparing_for_generation(self, tokenizer, **kwargs):
            calls.append(kwargs)

        def generate(self, **kwargs):
            return SimpleNamespace(shape=(1, 1))

        def predict_forward(self, **kwargs):
            self.generate(input_ids=SimpleNamespace(shape=(1, 100)))
            calls.append(kwargs["text"])
            return {
                "prediction": '{"scene":"single","regions":[]}',
                "prediction_masks": [np.ones((1, 48, 64), dtype=bool)],
            }

    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext, bfloat16="bf16")
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoModel=SimpleNamespace(from_pretrained=lambda *a, **k: Model()),
            AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **k: object()),
        ),
    )
    scene, masks, tokens = sa2va({"model_path": "/fixed"}, Image.new("RGB", (64, 48)))
    assert scene == "single" and len(masks) == 6 and tokens == 100
    assert calls[0]["max_new_tokens"] == 1536
    assert all("segment" in value for value in calls[2:])


def test_SAM3は単体FP32で6部位を照会し場面は非対応(monkeypatch):
    calls = []

    class Tensor:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.ones((1, 48, 64), dtype=bool)

    class Processor:
        def __init__(self, model, **kwargs):
            calls.append(kwargs)

        def set_image(self, image):
            return {}

        def set_text_prompt(self, **kwargs):
            return {"masks": [Tensor()]}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    monkeypatch.setitem(
        sys.modules, "sam3.model.sam3_image_processor", SimpleNamespace(Sam3Processor=Processor)
    )
    monkeypatch.setitem(
        sys.modules,
        "sam3.model_builder",
        SimpleNamespace(
            build_sam3_image_model=lambda **kwargs: SimpleNamespace(float=lambda: "fp32")
        ),
    )
    scene, masks = sam3({"model_path": "/fixed"}, Image.new("RGB", (64, 48)))
    assert scene == "unsupported" and len(masks) == 6
    assert calls[0]["confidence_threshold"] == 0.5


def test_GPU使用量の監視は子workerを含めるがテストでは実行しない(tmp_path, monkeypatch):
    import threading

    from colorstats.trial_native import run_phases

    observed = threading.Event()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "nvidia-smi":
            observed.set()
            return SimpleNamespace(stdout=b"10000, 49152\n20000, 49152\n")
        assert observed.wait(1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    peaks = run_phases(
        {
            "gpu_count": 2,
            "configuration_id": "B",
            "image_timeout_seconds": 120,
            "external_deadline": "2099-01-01T00:00:00+00:00",
        },
        tmp_path,
        ["qwen", "sam2"],
    )
    assert peaks == [10000, 20000]
    assert any("--phase" in row for row in calls)


def test_外部期限削除は当試行ディレクトリの既知ファイルだけに限る(tmp_path):
    from colorstats.trial_native import expire_job

    with pytest.raises(ValueError, match="当試行"):
        expire_job(tmp_path, "2026-01-01T00:00:00+00:00")
    assert tmp_path.exists()


def test_測定profileはfakeの成功を実測として使わない(tmp_path):
    from colorstats.trial_costs import measured_profile

    path = tmp_path / "checkpoint.json"
    content = json.dumps(
        {"purpose": "measurement", "synthetic": True, "status": "complete"}
    ).encode()
    path.write_bytes(content)
    with pytest.raises(ValueError, match="実GPU"):
        measured_profile({"file": str(path), "sha256": sha(content), "configuration_id": "A"})


@pytest.mark.parametrize(
    "error,expected",
    [
        (ValueError("context上限です"), "context_limit"),
        (ValueError("回答が打ち切られました"), "truncated"),
        (ImportError("private-message"), "unsupported"),
        (RuntimeError("private-message"), "invalid_output"),
    ],
)
def test_nativeの停止分類に例外原文を含めない(error, expected):
    from colorstats.trial_native import failure_code

    assert failure_code(error) == expected


def test_外部期限削除は既知の新設コピーだけを除去する():
    import shutil
    from uuid import uuid4

    from colorstats.trial_native import expire_job

    root = Path("/tmp") / ("colorstats-" + uuid4().hex)
    job = root / ("A_" + uuid4().hex) / "T001"
    job.mkdir(parents=True, mode=0o700)
    try:
        (job / "input.png").write_bytes(b"synthetic")
        (job / "mask-00.png").write_bytes(b"synthetic")
        (job / "unknown.txt").write_text("keep")
        expire_job(job, "2026-01-01T00:00:00+00:00")
        assert not (job / "input.png").exists()
        assert not (job / "mask-00.png").exists()
        assert (job / "unknown.txt").exists()
    finally:
        assert root.parent == Path("/tmp")
        shutil.rmtree(root)


def test_不正な認証参照の値をHTTPへ渡さず例外にも含めない(tmp_path, monkeypatch):
    from colorstats import trial_runpod

    config = settings(tmp_path)
    Path(config["api_key_file"]).write_text("synthetic-value\nsecond-line")

    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP呼出し禁止")

    monkeypatch.setattr(trial_runpod, "build_opener", forbidden)
    events = []
    backend = RunPod(config, audit=events.append)
    with pytest.raises(ProviderUnavailable) as error:
        backend._request("GET", "/pods")
    assert "synthetic-value" not in str(error.value)
    assert events == []


def test_プロキシのみではSCPを開始せず公開IP経由で転送する(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: (
            calls.append(argv) or SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        ),
    )
    backend = RunPod(settings(tmp_path), audit=lambda e: None)
    target = pod()
    target["ssh"]["proxy"] = {"host": "ssh.runpod.io", "username": "proxy", "port": 22}
    assert backend._transport(
        target, "put", resource()["remote"] + "/input.png", tmp_path / "input.png"
    )
    assert calls[0][0] == "scp"
    assert "root@203.0.113.10:" in calls[0][-1]
    assert calls[0][calls[0].index("-P") + 1] == "17445"
    target["ssh"]["direct"] = None
    with pytest.raises(ProviderUnavailable, match="公開IP"):
        backend._transport(
            target, "put", resource()["remote"] + "/input.png", tmp_path / "input.png"
        )
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["id", "name"])
def test_個別Podの取得結果も当試行の資源識別と照合する(tmp_path, field):
    def request(method, path, body=None):
        value = pod()
        if path == "/pods":
            return page("pods", [value])
        assert path == "/pods/new-pod"
        value[field] = "other"
        return value

    backend = RunPod(settings(tmp_path), audit=lambda e: None, request=request)
    with pytest.raises(ProviderUnavailable, match="資源識別"):
        backend.status(resource())


def test_壊れた課金証跡でも全Podに終了要求し未確認として返す(tmp_path):
    config = settings(tmp_path)
    Path(config["billing_receipts"]).write_text("{broken")
    alive = {"new-pod": "colorstats-new", "second": "second-name"}
    deleted = []

    def request(method, path, body=None):
        if method == "DELETE":
            key = path.rsplit("/", 1)[-1]
            deleted.append(key)
            del alive[key]
            return {}
        if path == "/pods":
            return page(
                "pods",
                [{"id": key, "name": name, "status": "RUNNING"} for key, name in alive.items()],
            )
        if path == "/network-volumes":
            return page("networkVolumes", [])
        if path.startswith("/billing/"):
            return {"records": []}
        key = path.rsplit("/", 1)[-1]
        return {"id": key, "name": alive[key], "status": "RUNNING"}

    backend = RunPod(config, audit=lambda e: None, request=request)
    for value in [resource(), {**resource(), "id": "second", "name": "second-name"}]:
        with pytest.raises(ProviderUnavailable, match="証跡"):
            backend.close(value)
    assert deleted == ["new-pod", "second"] and not alive


def test_HTTP本文が少量ずつ届いても総時間枠で中断し監視を復元する(tmp_path, monkeypatch):
    import signal
    import time

    from colorstats import trial_runpod

    config = settings(tmp_path)
    Path(config["api_key_file"]).write_text("synthetic-only")
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.setitimer

    def short_timer(which, seconds, *args):
        return timer(which, min(seconds, 0.03), *args)

    class SlowResponse:
        status = 200
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def read(self):
            for _ in range(100):
                time.sleep(0.005)
            raise AssertionError("本文全体を待ってはいけません")

    response = SlowResponse()
    monkeypatch.setattr(signal, "setitimer", short_timer)
    monkeypatch.setattr(
        trial_runpod, "build_opener", lambda *a: SimpleNamespace(open=lambda *a, **k: response)
    )
    backend = RunPod(config, audit=lambda e: None)
    with pytest.raises(ProviderUnavailable, match="総時間枠"):
        backend._request("GET", "/pods")
    assert response.closed
    assert backend.deadline is None
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)


def test_期限更新は新規ファイルを転送してから同じ画像区画で確定する(tmp_path):
    calls = []

    def transfer(pod, operation, remote, local=None):
        calls.append((operation, remote))
        if operation == "put":
            assert (
                json.loads(Path(local).read_text())["external_deadline"]
                == "2099-01-01T00:00:00+00:00"
            )
        return True

    backend = RunPod(settings(tmp_path), audit=lambda e: None, transport=transfer)
    backend.shorten_deadline(pod(), resource(), "T001", "2099-01-01T00:00:00+00:00")
    assert calls == [
        ("put", resource()["remote"] + "/T001/deadline-next.json"),
        ("deadline", resource()["remote"] + "/T001"),
    ]


def test_独立期限監視はcontroller停止後も短縮期限を読み直す(monkeypatch):
    import shutil
    from uuid import uuid4

    from colorstats import trial_native

    root = Path("/tmp") / ("colorstats-" + uuid4().hex)
    job = root / ("A_" + uuid4().hex) / "T001"
    job.mkdir(parents=True)
    (job / "input.png").write_bytes(b"synthetic")
    killed = []
    monkeypatch.setattr(trial_native.os, "killpg", lambda group, signum: killed.append(group))

    def update(seconds):
        (job / "deadline.json").write_text('{"external_deadline":"2026-01-01T00:00:00+00:00"}')

    monkeypatch.setattr(trial_native.time, "sleep", update)
    try:
        trial_native.expire_job(job, "2099-01-01T00:00:00+00:00", group=999999)
        assert killed == [999999]
        assert not (job / "input.png").exists()
        assert not (job / "deadline.json").exists()
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("operation", ["prepare", "submit"])
def test_SAM3専用環境の固定参照をSSH要求JSONへ保持する(tmp_path, operation):
    captured = []

    def transport(pod, action, remote, local=None):
        if action == "put" and remote.endswith("request.json"):
            captured.append(json.loads(local.read_text()))
        return True

    plan = synthetic_plan(tmp_path / "trial")
    spec = {
        "runtime": plan["deployments"]["E"]["runtime"],
        "contract": plan["configurations"]["E"],
    }
    backend = RunPod(settings(tmp_path), audit=lambda event: None, transport=transport)
    if operation == "prepare":
        backend.prepare(pod(), resource(), spec)
    else:
        backend.submit(pod(), resource(), {"trial_id": "T001"}, b"synthetic", spec)
    assert captured == [spec]


@pytest.mark.parametrize("operation", ["prepare", "start"])
def test_SSH起動は絶対Pythonと明示コードパスを使う(tmp_path, monkeypatch, operation):
    from colorstats.trial_native_common import CODE_PATH, CONTROLLER_PYTHON

    calls = []
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    backend = RunPod(settings(tmp_path), audit=lambda event: None)
    backend._transport(pod(), operation, resource()["remote"] + "/T001")
    argv = calls[0]
    index = argv.index("/usr/bin/env")
    assert argv[index : index + 5] == [
        "/usr/bin/env",
        f"PYTHONPATH={CODE_PATH}",
        CONTROLLER_PYTHON,
        "-m",
        "colorstats.trial_native",
    ]
    assert Path(CONTROLLER_PYTHON).is_absolute()
    assert Path(CODE_PATH).is_absolute()
    assert "python" not in argv
