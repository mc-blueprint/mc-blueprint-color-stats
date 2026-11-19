"""クラウド試行の単一writer、費用予約、回収・再開・終了の状態管理。"""

import copy
import json
import re
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from colorstats.api_budget import digest
from colorstats.trial_costs import (
    RESERVATIONS,
    charged,
    deployment_signature,
    measured_profile,
    number,
    select_candidate,
    summary,
    time_limit,
)
from colorstats.trial_inputs import (
    SHA,
    add_files,
    encoded,
    load_manifest,
    private_path,
    recheck,
    sha,
    stamp,
    validate_package,
    write_private,
)
from colorstats.trial_native import LIMITS, MODELS, PROMPT, SAM2
from colorstats.trial_native_common import (
    CONTROLLER_LOCK,
    SAM3_LOCK,
    SAM3_PYTHON,
    code_files,
    environment_reference,
)
from colorstats.trial_pages import build_pages
from colorstats.trial_results import (
    accept_results,
    configurations_valid,
    load_mask,
    read_results,
    validate_result,
)
from colorstats.trial_runpod import ProviderRejected, ProviderUnavailable


def validate_plan(plan):
    """承認計画と#141契約を照合する。未取得SHA・許可を自動補完しない。"""
    if (
        plan["version"] != "trial-execution-v1"
        or plan["provider"] != "runpod"
        or plan["product"] != "secure-on-demand"
        or not re.fullmatch(r"[A-Z0-9-]+", plan["region"])
        or plan["concurrency"] not in {1, 2}
        or type(plan["measurement"]) is not bool
        or plan["purpose"] not in {"trial", "smoke", "measurement"}
    ):
        raise ValueError("固定した提供元・地域・実行方式が必要です")
    configurations_valid(plan["configurations"])
    for key in "ABCDE":
        d = plan["deployments"][key]
        c = plan["configurations"][key]
        runtime = d["runtime"]
        registry = d["registry"]
        version = d["min_cuda_version"]
        if registry is not None and (
            not isinstance(registry, str)
            or not registry
            or any(char.isspace() for char in registry)
        ):
            raise ValueError("registryにはcredential IDまたはnullが必要です")
        if (
            not isinstance(version, str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+", version)
            or tuple(map(int, version.split("."))) < (13, 0)
        ):
            raise ValueError("CUDA下限は13.0以上のmajor.minorで指定してください")
        if (
            runtime["code_files"] != code_files()
            or digest(runtime["code_files"]) != c["code_sha256"]
            or runtime["lock"]["file"] != CONTROLLER_LOCK
            or not SHA.fullmatch(runtime["lock"]["sha256"])
        ):
            raise ValueError("実行コード・依存lockの固定参照が不正です")
        if key == "E":
            worker = runtime["sam3"]
            if (
                worker["python"] != SAM3_PYTHON
                or worker["lock"]["file"] != SAM3_LOCK
                or not SHA.fullmatch(worker["lock"]["sha256"])
                or any(
                    worker["versions"].get(k) != v
                    for k, v in {
                        "numpy": "1.26.4",
                        "torch": "2.11.0",
                        "torchvision": "0.26.0",
                        "transformers": "4.57.6",
                    }.items()
                )
            ):
                raise ValueError("SAM3専用環境の固定参照が不正です")
        if (
            not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", d["container"])
            or d["gpu_count"] not in {1, 2}
            or type(d["disk_gb"]) is not int
            or d["disk_gb"] < 1
            or not d["versions"]
            or digest(environment_reference(d["versions"], runtime)) != c["environment_sha256"]
            or c["processor_sha256"] != digest(LIMITS)
            or c["prompt_sha256"] != sha(PROMPT.encode())
            or not 0 < number(d["memory_fraction"]) < 1
        ):
            raise ValueError("container・依存lock・指示・processorの固定参照が必要です")
        if d.get("hf_secret_name") and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_./-]*", d["hf_secret_name"]
        ):
            raise ValueError("既存HF Secretの名前が不正です")
        time_limit(key, d)
        if (
            not 0 < number(d["image_timeout_seconds"]) <= 120
            or not 0 < number(d["prepare_timeout_seconds"]) <= 1800
            or not 0 < number(d["cleanup_seconds"]) <= 300
        ):
            raise ValueError("画像・準備・終了の時間枠が不正です")
        for name, expected, field in (
            ("model", MODELS[key], "weights_sha256"),
            ("segmenter", SAM2 if key in "ABC" else MODELS[key], "segmenter_sha256"),
        ):
            asset = d[name]
            if (
                (asset["repo"], asset["revision"]) != expected
                or not asset["files"]
                or not SHA.fullmatch(asset["license_ref"])
                or len({r["file"] for r in asset["files"]}) != len(asset["files"])
                or digest(asset["files"]) != c[field]
                or c["model_revision" if name == "model" else "segmenter_revision"]
                != asset["revision"]
            ):
                raise ValueError("モデル・分割器・ライセンス・既知SHAの参照が不正です")
            for r in asset["files"]:
                private_path(Path("/fixed"), r["file"])
                if not SHA.fullmatch(r["sha256"]):
                    raise ValueError("未取得物を確認済みSHAにできません")
        if number(d["usd_hour"]) > 1.5 and plan["purpose"] != "measurement":
            refs = d["measurement_evidence"]
            evidence = {k: measured_profile(refs[k]) for k in ("baseline", "candidate")}
            if (
                evidence["candidate"]["signature"] != digest(c)
                or evidence["candidate"]["deployment_sha256"] != deployment_signature(plan, key)
                or evidence["baseline"]["high"]["usd_hour"] > 1.5
                or evidence["candidate"]["inputs_sha256"] != evidence["baseline"]["inputs_sha256"]
                or not select_candidate(evidence["baseline"], evidence["candidate"])
                or evidence["candidate"]["high"]["usd_hour"] < d["usd_hour"]
            ):
                raise ValueError("高単価構成の固定費込み採用根拠が不足しています")
        if plan["purpose"] == "measurement" and (not plan["measurement"] or d["usd_hour"] > 6):
            raise ValueError("測定は6 USD/h以下・測定枠内に限定します")


@contextmanager
def writer(root):
    """OS排他で、異常終了後も再利用できる単一writerを確保する。Linux専用。"""
    import fcntl

    path = private_path(root, "execution.lock")
    if not path.exists():
        expiry = json.loads((root / "file-ledger.json").read_text())["expires_at"]
        add_files(root, [{"file": path.name, "sha256": sha(b""), "expires_at": expiry}])
        write_private(path, b"")
    with path.open("rb") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("この試行は別writerが管理中です") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Runner:
    """#141の束を固定し、1 tickで時間制限付きbackendの監視・回収を進める。

    engineは権利の読み取り用。fakeは合成入力専用で実GPUsmokeの証拠にならない。
    clockはUTC日時、monotonicはプロセス内の経過時間。再開時は保存UTCも併用する。
    利用者はwriterの中で生成し、全操作を同じwriterから呼ぶ。
    """

    def __init__(
        self,
        plan,
        backend,
        *,
        authorization=None,
        engine=None,
        fake=False,
        clock=None,
        monotonic=None,
        cleanup_only=False,
        budget=None,
    ):
        validate_plan(plan)
        self.cleanup_mode = cleanup_only
        self.budget = budget
        if not fake and budget is None:
            raise PermissionError("実実行には段階共通のUSD台帳が必要です")
        self.plan, self.backend = plan, backend
        self.authorization, self.engine, self.fake = authorization, engine, fake
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self.root = Path(plan["result_root"])
        self.manifest = load_manifest(
            self.root, now=datetime.min.replace(tzinfo=UTC) if cleanup_only else self.clock()
        )
        if not cleanup_only:
            validate_package(self.root, self.manifest)
        if fake != backend.synthetic or (fake and not self.manifest["synthetic"]):
            raise PermissionError("fakeは合成入力だけを扱います")
        self.expiry = min(stamp(r["local_expires_at"]) for r in self.manifest["images"])
        (self.root / "execution").mkdir(mode=0o700, exist_ok=True)
        self.sequence, self.state, self.origins = 0, None, {}
        ledger = json.loads((self.root / "file-ledger.json").read_text())
        records = sorted(
            (r for r in ledger["files"] if re.fullmatch(r"execution/[0-9]{6}\.json", r["file"])),
            key=lambda r: r["file"],
        )
        for record in records:
            content = private_path(self.root, record["file"]).read_bytes()
            if sha(content) != record["sha256"]:
                raise ValueError("実行台帳が変更されています")
            self.state = json.loads(content)
            self.sequence += 1
        if self.state is None:
            self.state = {
                "version": "trial-state-v1",
                "provider": plan["provider"],
                "product": plan["product"],
                "region": plan["region"],
                "plan_sha256": digest(plan),
                "manifest_sha256": sha((self.root / "manifest.json").read_bytes()),
                "synthetic": fake,
                "synthetic_inputs": self.manifest["synthetic"],
                "purpose": plan["purpose"],
                "status": "ready",
                "run_id": str(uuid4()),
                "resources": [],
                "results": [],
                "nonempty_results": [],
                "active_attempts": {
                    r["trial_id"]: dict.fromkeys("ABCDE", "not_started")
                    for r in self.manifest["images"]
                },
                "failures": 0,
                "monitor_failures": 0,
                "stop_reason": None,
                "measurement_usd": 0,
                "measurement_seconds": 0,
            }
            if plan["measurement"] and plan["purpose"] != "measurement":
                record = plan["measurement_record"]
                content = Path(record["file"]).read_bytes()
                prior = json.loads(content)
                if (
                    sha(content) != record["sha256"]
                    or prior["purpose"] != "measurement"
                    or prior["synthetic"] != fake
                    or prior["status"] not in {"complete", "stopped"}
                    or any(r["status"] != "closed" for r in prior["resources"])
                ):
                    raise ValueError("完了した測定台帳の照合が必要です")
                self.state["measurement_usd"] = sum(r["estimated_usd"] for r in prior["resources"])
                self.state["measurement_seconds"] = sum(
                    r["elapsed_seconds"] for r in prior["resources"]
                )
                if self.state["measurement_usd"] > 5 or self.state["measurement_seconds"] > 2400:
                    raise ValueError("測定費用・時間の上限を超えています")
            self.save("initialized")
        elif (
            self.state["plan_sha256"] != digest(plan)
            or self.state["manifest_sha256"] != sha((self.root / "manifest.json").read_bytes())
            or self.state["synthetic"] != fake
        ):
            raise ValueError("入力・版・精度・環境・指示・資源設定が再開前と一致しません")
        self.expiry = min(
            self.expiry, stamp(self.state.get("retention_expires_at", self.expiry.isoformat()))
        )
        if self.budget is not None:
            self.budget.update(self.state, self.root)

    def save(self, operation, detail=None):
        """台帳へ先に登録した不変checkpointだけを保存し、途切れた保存は再開拒否する。"""
        value = copy.deepcopy(self.state)
        value["event"] = {
            "operation": operation,
            "at": self.clock().isoformat(),
            "detail": detail or {},
        }
        content = encoded(value)
        name = f"execution/{self.sequence:06}.json"
        add_files(
            self.root,
            [{"file": name, "sha256": sha(content), "expires_at": self.expiry.isoformat()}],
        )
        write_private(self.root / name, content)
        self.sequence += 1
        if self.budget is not None:
            self.budget.update(self.state, self.root)

    def model_signature(self):
        return digest({k: self.plan[k] for k in ("configurations", "deployments")})

    def authorize(self):
        """送信前の対象・提供元・地域・予算・保持・ユーザー原文を再照合する。"""
        load_manifest(self.root, now=self.clock())
        validate_package(self.root, self.manifest)
        if self.fake:
            return
        auth = self.authorization
        if (
            not auth
            or auth["plan_sha256"] != digest(self.plan)
            or auth["manifest_sha256"] != self.state["manifest_sha256"]
            or auth["provider"] != "runpod"
            or auth["region"] != self.plan["region"]
            or auth["product"] != "secure-on-demand"
            or any(
                auth.get(k) is not True
                for k in ("send_images", "billing", "delete_new_resources", "retention_confirmed")
            )
            or not auth.get("user_text")
            or not auth.get("authorized_at")
            or stamp(auth["expires_at"]) <= self.clock()
            or number(auth["max_usd"])
            < (
                5
                if self.plan["purpose"] == "measurement"
                else 20
                if self.plan["measurement"]
                else 15
            )
        ):
            raise PermissionError("対象・地域・送信・課金・新設資源削除の明示許可が必要です")
        operations = auth.get("operations")
        if (
            not operations
            or operations["region"] != self.plan["region"]
            or stamp(operations["checked_at"]) > self.clock()
            or any(
                not SHA.fullmatch(operations[k])
                for k in ("status_ref", "maintenance_ref", "capacity_ref", "data_terms_ref")
            )
        ):
            raise PermissionError("直前のstatus・保守・容量・保持条件の記録が必要です")
        for d in self.plan["deployments"].values():
            if any(d[k]["license_confirmed"] is not True for k in ("model", "segmenter")):
                raise PermissionError("ライセンス未確認のため合成smokeも開始できません")
        if self.plan["purpose"] in {"smoke", "measurement"}:
            if not self.manifest["synthetic"]:
                raise PermissionError("事前smoke・測定は合成入力だけを使います")
        else:
            reference = self.plan["smoke_record"]
            content = Path(reference["file"]).read_bytes()
            if sha(content) != reference["sha256"]:
                raise ValueError("実GPUsmoke記録のSHAが一致しません")
            smoke = json.loads(content)
            if (
                smoke["purpose"] not in {"smoke", "measurement"}
                or smoke["synthetic"] is not False
                or smoke["synthetic_inputs"] is not True
                or smoke["status"] != "complete"
                or smoke["model_settings_sha256"] != self.model_signature()
            ):
                raise PermissionError("同じ構成の実GPU合成smoke成功記録が必要です")
            self.budget.verify_smoke(smoke)
            if self.manifest["synthetic"] or self.engine is None:
                raise PermissionError("実写真manifestと権利の読取専用再確認が必要です")
            self.shorten_retention(recheck(self.engine, self.root, now=self.clock()))

    def shorten_retention(self, expiry):
        """最新の保持期限を保存し、転送済みコピーの独立した期限監視へ反映する。"""
        self.expiry = min(self.expiry, expiry)
        if self.state.get("retention_expires_at") != self.expiry.isoformat():
            self.state["retention_expires_at"] = self.expiry.isoformat()
            self.save("retention_shortened")
        for r in self.state["resources"]:
            current = r["current"]
            if r["status"] == "closed" or not current or stamp(current["deadline"]) <= self.expiry:
                continue
            pod = self.backend.status(r)
            if pod is None:
                raise ProviderUnavailable("期限更新先の資源を確認できません")
            self.backend.shorten_deadline(pod, r, current["trial_id"], self.expiry.isoformat())
            current["deadline"] = self.expiry.isoformat()
            self.save("remote_retention_shortened")

    def elapsed(self, resource):
        start = self.origins.setdefault(
            resource["attempt"], (self.monotonic(), resource["elapsed_seconds"])
        )
        seconds = max(
            resource["elapsed_seconds"],
            start[1] + self.monotonic() - start[0],
            (self.clock() - stamp(resource["created_at"])).total_seconds(),
        )
        resource["elapsed_seconds"] = seconds
        return seconds

    def spending(self):
        total = (
            self.budget.prior_usd(self.state["run_id"])
            if self.budget is not None
            else self.state["measurement_usd"]
        )
        for r in self.state["resources"]:
            if r["status"] != "closed":
                self.elapsed(r)
                r["estimated_usd"] = charged(r, r["started_seconds"] + r["elapsed_seconds"])
            total += r["estimated_usd"]
        return total

    def stop(self, reason):
        if (
            reason in {"management_unavailable", "creation_unknown"}
            and self.state["stop_reason"] is None
        ):
            self.state["failures"] += 1
        self.state["stop_reason"], self.state["status"] = reason, "stopping"
        self.save("stop", {"reason": reason})

    def reserve(self, key):
        cap = (
            5 if self.plan["purpose"] == "measurement" else (20 if self.plan["measurement"] else 15)
        )
        soft = cap - (0.5 if self.plan["purpose"] == "measurement" else 2)
        spent = self.spending()
        if self.plan["purpose"] == "measurement":
            used_seconds, leases = self.measurement_usage()
            if spent >= 3.5 or used_seconds >= 1800 or leases >= 4:
                raise ValueError("測定の5USD・40分枠が不足しています")
        prior_runs = self.budget.previous(self.state["run_id"]) if self.budget else []
        resources = self.state["resources"] + [
            r
            for run in prior_runs
            if run["purpose"] != "measurement"
            for r in run["resources"]
        ]
        used = {
            k: sum(r["estimated_usd"] for r in resources if r["configuration_id"] == k)
            for k in "ABCDE"
        }
        held = sum(
            max(0, RESERVATIONS[k] - used[k])
            for k in "ABCDE"
            if any(
                r["configuration_id"] == k and r["status"] != "closed"
                for r in self.state["resources"]
            )
        )
        if spent >= soft or spent + held + RESERVATIONS[key] - used[key] > soft:
            raise ValueError("全体または構成別の費用予約が不足しています")
        return RESERVATIONS[key] - used[key]

    def measurement_usage(self):
        """共通台帳の過去測定と、現在runの有料資源時間・lease数を合算する。"""
        prior = self.budget.previous(self.state["run_id"]) if self.budget else []
        resources = [
            r for run in prior if run["purpose"] == "measurement" for r in run["resources"]
        ]
        for r in self.state["resources"]:
            if r["status"] != "closed":
                self.elapsed(r)
        resources += self.state["resources"]
        return sum(r["elapsed_seconds"] for r in resources), len(resources)

    def start(self, key):
        if self.state["stop_reason"]:
            raise ValueError("停止中は新規起動できません")
        self.authorize()
        if any(r["status"] not in {"closed", "running"} for r in self.state["resources"]):
            raise ValueError("未確認の旧資源があり、新規起動できません")
        active = [r for r in self.state["resources"] if r["status"] != "closed"]
        if len(active) >= self.plan["concurrency"] or any(
            r["configuration_id"] == key for r in active
        ):
            raise ValueError("同じ構成の二重起動または並列上限です")
        old = [r for r in self.state["resources"] if r["configuration_id"] == key]
        prior_runs = self.budget.previous(self.state["run_id"]) if self.budget else []
        if any(r["status"] != "closed" for run in prior_runs for r in run["resources"]):
            raise ValueError("別段階の旧資源の終了確認が必要です")
        if (
            len(old) >= 2
            or self.state["failures"] + sum(run["failures"] for run in prior_runs) >= 2
        ):
            raise ValueError("再起動回数の上限です")
        d = self.plan["deployments"][key]
        remaining = self.reserve(key)
        limit = min(time_limit(key, d), (remaining - d["fixed_usd"]) / d["usd_hour"] * 3600)
        if self.plan["purpose"] == "measurement":
            limit = min(
                limit,
                1200,
                2400
                - self.measurement_usage()[0]
                - sum(max(0, r["limit_seconds"] - r["elapsed_seconds"]) for r in active),
                (5 - self.spending() - d["fixed_usd"]) / d["usd_hour"] * 3600,
            )
        if limit <= d["cleanup_seconds"]:
            raise ValueError("終了処理を含む残り時間が不足しています")
        attempt = key + "_" + uuid4().hex
        r = {
            "configuration_id": key,
            "attempt": attempt,
            "id": None,
            "name": "colorstats-" + self.state["run_id"] + "-" + attempt,
            "remote": "/tmp/colorstats-" + self.state["run_id"] + "/" + attempt,
            "status": "creating",
            "created_at": self.clock().isoformat(),
            "started_seconds": self.clock().timestamp(),
            "elapsed_seconds": 0,
            "gpu": d["gpu"],
            "gpu_count": d["gpu_count"],
            "container": d["container"],
            "deployment_sha256": deployment_signature(self.plan, key),
            "usd_hour": d["usd_hour"],
            "fixed_usd": d["fixed_usd"],
            "minimum_seconds": number(d["minimum_seconds"]),
            "billed_usd": 0,
            "estimated_usd": d["fixed_usd"],
            "limit_seconds": limit,
            "prepared": False,
            "preparing": False,
            "current": None,
            "confirmed_deleted": False,
            "cleanup_failures": 0,
        }
        if not self.fake:
            self.state["authorization_sha256"] = digest(self.authorization)
        self.state["resources"].append(r)
        completed = {(x["trial_id"], x["configuration_id"]) for x in self.state["results"]}
        for image in self.manifest["images"]:
            if (image["trial_id"], key) not in completed:
                self.state["active_attempts"][image["trial_id"]][key] = attempt
        self.state["status"] = "running"
        self.save("create_requested", {"configuration_id": key})
        try:
            pod = self.backend.create(r, d)
        except ProviderRejected as error:
            r["status"] = "closed"
            r["confirmed_deleted"] = True
            r["estimated_usd"] = 0
            self.save("create_rejected", {"status": error.status})
            self.stop("provider_rejected")
            return
        r["id"], r["status"] = pod["id"], "running"
        self.save("created", {"configuration_id": key})

    def spec(self, r):
        key = r["configuration_id"]
        d = self.plan["deployments"][key]
        return {
            **{
                k: d[k]
                for k in (
                    "model",
                    "segmenter",
                    "versions",
                    "runtime",
                    "memory_fraction",
                    "gpu_count",
                    "image_timeout_seconds",
                )
            },
            "configuration_id": key,
            "attempt": r["attempt"],
            "contract": self.plan["configurations"][key],
            "model_path": r["remote"] + "/weights/model",
            "segmenter_path": r["remote"]
            + ("/weights/segmenter" if key in "ABC" else "/weights/model"),
        }

    def check_pod(self, pod, r):
        d = self.plan["deployments"][r["configuration_id"]]
        if (
            pod["cloud"] != "SECURE"
            or not (
                pod["dataCenterId"] == self.plan["region"]
                or (pod["dataCenterId"] is None and pod["status"] in {"PROVISIONING", "STARTING"})
            )
            or pod["image"] != d["container"]
            or any((pod["mounts"] or {}).values())
            or pod["gpu"]["id"] != d["gpu"]
            or pod["gpu"]["count"] != d["gpu_count"]
        ):
            raise ValueError("提供元・地域・GPU・container・保存設定が変わっています")
        observed = number(pod["cost"]) + number(d["hourly_extras_usd"])
        r["observed_usd_hour"] = observed
        if observed > d["usd_hour"]:
            raise ValueError("実単価が固定した見積を超えました")

    def receive(self, resource, image, value, blobs):
        key = resource["configuration_id"]
        expected = {
            "trial_id": image["trial_id"],
            "configuration_id": key,
            "configuration_sha256": digest(self.plan["configurations"][key]),
            "input_sha256": image["input"]["sha256"],
            "size": image["input"]["size"],
            "attempt": self.state["active_attempts"][image["trial_id"]][key],
        }
        if any(value.get(k) != v for k, v in expected.items()):
            raise ValueError("受信した入力・構成・有効attempt参照が一致しません")
        prefix = f"received/{resource['attempt']}/{image['trial_id']}"
        (self.root / prefix).mkdir(parents=True, mode=0o700, exist_ok=True)
        regions = copy.deepcopy(value["regions"])
        for region in regions:
            mask = region["mask"]
            filename = mask["file"]
            if not re.fullmatch(r"mask-[0-9]{2}\.png", filename):
                raise ValueError("受信mask名が不正です")
            content = blobs[filename]
            if sha(content) != mask["sha256"]:
                raise ValueError("受信maskのSHAが一致しません")
            mask["file"] = prefix + "/" + filename
            path = private_path(self.root, mask["file"])
            if not path.exists():
                add_files(self.root, [{**mask, "expires_at": self.expiry.isoformat()}])
                write_private(path, content)
        row = {
            "version": "trial-output-v1",
            "trial_id": image["trial_id"],
            "configuration_id": key,
            "configuration_sha256": digest(self.plan["configurations"][key]),
            "input_sha256": image["input"]["sha256"],
            "size": image["input"]["size"],
            "attempt": value["attempt"],
            "status": value["status"],
            "scene": value["scene"],
            "regions": regions,
            "elapsed_seconds": value["elapsed_seconds"],
            "peak_vram_mib": value["peak_vram_mib"],
            "expense_ref": resource["attempt"],
        }
        validate_result(
            self.root,
            self.manifest,
            self.plan["configurations"],
            row,
            active_attempts=self.state["active_attempts"],
        )
        self.state["results"].append(row)
        if any(
            load_mask(self.root, region["mask"], row["size"]).any() for region in row["regions"]
        ):
            self.state["nonempty_results"].append([row["trial_id"], key])
        self.save("received", {"configuration_id": key, "trial_id": image["trial_id"]})
        if row["status"] != "success":
            self.save(
                "native_failure",
                {"reason_code": value.get("reason_code", "unspecified"), "configuration_id": key},
            )
            self.stop("native_failed")

    def advance(self, r):
        key = r["configuration_id"]
        d = self.plan["deployments"][key]
        elapsed = self.elapsed(r)
        if elapsed + d["cleanup_seconds"] >= r["limit_seconds"]:
            self.stop("time_limit")
            return
        measurement_end = self.plan["purpose"] == "measurement" and (
            self.spending() >= 4.5
            or self.measurement_usage()[0]
            >= 2400
            - sum(
                self.plan["deployments"][x["configuration_id"]]["cleanup_seconds"]
                for x in self.state["resources"]
                if x["status"] != "closed"
            )
        )
        if measurement_end or self.spending() >= (18 if self.plan["measurement"] else 13):
            self.stop("soft_budget")
            return
        pod = self.backend.status(r)
        if pod is None or pod["status"] in {"ERROR", "EXITED", "TERMINATED"}:
            self.state["failures"] += 1
            self.stop("provider_failure")
            return
        self.check_pod(pod, r)
        if pod["status"] != "RUNNING":
            return
        if not r["preparing"]:
            r["preparing"] = True
            self.save("prepare_requested")
            self.backend.prepare(pod, r, self.spec(r))
            return
        if not r["prepared"]:
            if elapsed >= d["prepare_timeout_seconds"]:
                self.stop("prepare_timeout")
            elif self.backend.prepared(pod, r):
                r["prepared"] = True
                self.save("prepared")
            return
        if r["current"]:
            current = r["current"]
            image = next(x for x in self.manifest["images"] if x["trial_id"] == current["trial_id"])
            if (self.clock() - stamp(current["sent_at"])).total_seconds() >= 120 and not any(
                x["trial_id"] == image["trial_id"] and x["configuration_id"] == key
                for x in self.state["results"]
            ):
                self.stop("unrecovered")
                return
            if any(
                x["trial_id"] == image["trial_id"] and x["configuration_id"] == key
                for x in self.state["results"]
            ):
                self.backend.remove_image(pod, r, image["trial_id"])
                r["current"] = None
                self.save("remote_image_deleted")
                return
            response = self.backend.collect(pod, r, image["trial_id"])
            if response is None:
                if (self.clock() - stamp(current["sent_at"])).total_seconds() >= 120:
                    self.stop("unrecovered")
                return
            if self.clock() >= stamp(current["deadline"]):
                self.stop("external_expired")
                return
            self.authorize()
            if not any(
                x["trial_id"] == image["trial_id"] and x["configuration_id"] == key
                for x in self.state["results"]
            ):
                self.receive(r, image, *response)
            self.backend.remove_image(pod, r, image["trial_id"])
            r["current"] = None
            self.save("remote_image_deleted")
            return
        completed = {(x["trial_id"], x["configuration_id"]) for x in self.state["results"]}
        pending = [x for x in self.manifest["images"] if (x["trial_id"], key) not in completed]
        completed_count = sum(x["configuration_id"] == key for x in self.state["results"])
        if self.plan["purpose"] != "trial" and completed_count >= 3:
            for image in pending:
                self.state["results"].append(
                    {
                        "version": "trial-output-v1",
                        "trial_id": image["trial_id"],
                        "configuration_id": key,
                        "configuration_sha256": digest(self.plan["configurations"][key]),
                        "input_sha256": image["input"]["sha256"],
                        "size": image["input"]["size"],
                        "attempt": r["attempt"],
                        "status": "missing",
                        "scene": "unsupported" if key == "E" else "unknown",
                        "regions": [],
                        "elapsed_seconds": 0,
                        "peak_vram_mib": 0,
                        "expense_ref": r["attempt"],
                    }
                )
            pending = []
        if not pending:
            r["status"] = "cleanup"
            self.save("configuration_finished")
            return
        self.authorize()
        image = pending[0]
        r["current"] = {
            "trial_id": image["trial_id"],
            "sent_at": self.clock().isoformat(),
            "deadline": min(self.expiry, self.clock() + timedelta(hours=24)).isoformat(),
        }
        self.save("send_requested", {"configuration_id": key, "trial_id": image["trial_id"]})
        self.backend.submit(
            pod,
            r,
            image,
            private_path(self.root, image["input"]["file"]).read_bytes(),
            {
                **self.spec(r),
                "trial_id": image["trial_id"],
                "input_sha256": image["input"]["sha256"],
                "external_deadline": r["current"]["deadline"],
            },
        )
        self.save("sent")

    def cleanup(self, r):
        """課金終了と残存の両方が確認できるまで予約を解放しない。"""
        if not r["id"]:
            pod = self.backend.status(r)
            if pod is None:
                raise ProviderUnavailable("作成応答不明の資源は手動照合が必要です")
            r["id"] = pod["id"]
            self.save("creation_reconciled")
        receipt = self.backend.close(r)
        r["billed_usd"] = number(receipt["billed_usd"])
        r["confirmed_deleted"] = receipt["deleted"]
        if receipt["deleted"] and receipt["billing_confirmed"]:
            self.elapsed(r)
            r["estimated_usd"] = charged(r, r["started_seconds"] + r["elapsed_seconds"])
            r["status"] = "closed"
            if not self.fake:
                r["estimated_usd"] = r["billed_usd"]
            key = r["configuration_id"]
            prior = self.budget.previous(self.state["run_id"]) if self.budget else []
            spent = sum(
                x["estimated_usd"] for x in self.state["resources"] if x["configuration_id"] == key
            )
            spent += sum(
                x["estimated_usd"]
                for run in prior
                if run["purpose"] != "measurement"
                for x in run["resources"]
                if x["configuration_id"] == key
            )
            if self.plan["purpose"] != "measurement" and spent > RESERVATIONS[key]:
                self.stop("configuration_budget_exceeded")
        else:
            r["cleanup_failures"] += 1
        self.save("cleanup_checked")

    def tick(self):
        """60秒以内の反復を前提とし、削除不能や課金未確認も永続化して返す。"""
        if self.cleanup_mode:
            return self.cleanup_only()
        if self.state["status"] in {"complete", "stopped"}:
            return self.state["status"]
        try:
            self.authorize()
            for r in self.state["resources"]:
                if self.state["stop_reason"]:
                    break
                if r["status"] == "cleanup":
                    try:
                        self.cleanup(r)
                    except Exception:
                        self.stop("cleanup_unconfirmed")
                        break
                elif r["status"] == "running":
                    self.advance(r)
                elif r["status"] == "creating":
                    self.stop("creation_unknown")
            self.state["monitor_failures"] = 0
        except ProviderUnavailable:
            self.state["monitor_failures"] += 1
            if self.state["monitor_failures"] >= 2:
                self.stop("management_unavailable")
            self.save("monitor_unconfirmed")
        except (PermissionError, ValueError):
            self.stop("permission_or_contract")
        if self.state["stop_reason"]:
            self.cleanup_all()
            if all(r["status"] == "closed" for r in self.state["resources"]):
                self.purge_expired()
                self.state["status"] = "stopped"
                self.save("stopped")
            return self.state["status"]
        if any(r["status"] == "cleanup" for r in self.state["resources"]):
            return self.state["status"]
        done = {
            k
            for k in "ABCDE"
            if sum(x["configuration_id"] == k for x in self.state["results"]) == 30
        }
        if len(done) == 5 and all(r["status"] == "closed" for r in self.state["resources"]):
            self.finalize()
            return self.state["status"]
        active = [r["configuration_id"] for r in self.state["resources"] if r["status"] != "closed"]
        allowed = (
            ["A"]
            if "A" not in done
            else [k for k in ("BC" if not {"B", "C"} <= done else "DE") if k not in done]
        )
        for key in allowed:
            if len(active) >= self.plan["concurrency"]:
                break
            if key not in active:
                try:
                    self.start(key)
                    if self.state["stop_reason"]:
                        break
                    active.append(key)
                except ProviderUnavailable:
                    self.stop("creation_unknown")
                    break
                except (PermissionError, ValueError):
                    self.stop("start_rejected")
                    break
        return self.state["status"]

    def purge_expired(self):
        """期限に達した当試行の画像コピーだけを台帳SHAで照合して除去する。"""
        ledger = json.loads((self.root / "file-ledger.json").read_text())
        removed = []
        for record in ledger["files"]:
            path = private_path(self.root, record["file"])
            if (
                path.suffix in {".png", ".html"}
                and min(stamp(record["expires_at"]), self.expiry) <= self.clock()
                and path.exists()
            ):
                if sha(path.read_bytes()) != record["sha256"]:
                    raise ValueError("期限切れコピーのSHAが一致せず削除を保留します")
                path.unlink()
                removed.append(record["file"])
        if removed:
            self.save("expired_copies_deleted", {"files": removed})

    def cleanup_all(self):
        """全新設資源への終了を試みてから、失敗の種類だけをまとめて保存する。"""
        errors = []
        for r in self.state["resources"]:
            if r["status"] == "closed":
                continue
            r["status"] = "cleanup"
            try:
                self.cleanup(r)
            except Exception as error:
                r["cleanup_failures"] += 1
                errors.append(
                    {
                        "configuration_id": r["configuration_id"],
                        "error_type": type(error).__name__,
                    }
                )
        if errors:
            self.save("cleanup_unconfirmed", {"errors": errors})

    def cleanup_only(self):
        """期限失効後も、記録済み許可で当試行の新設資源だけを終了する。"""
        if not self.fake and (
            not self.authorization
            or self.state.get("authorization_sha256") != digest(self.authorization)
            or self.authorization.get("delete_new_resources") is not True
        ):
            raise PermissionError("起動時の新設資源削除許可が必要です")
        self.stop(self.state["stop_reason"] or "cleanup_requested")
        self.cleanup_all()
        if all(r["status"] == "closed" for r in self.state["resources"]):
            self.purge_expired()
            self.state["status"] = "stopped"
            self.save("stopped")
        return self.state["status"]

    def resume(self):
        """確認済み削除後の設備障害だけを残費用内の新attemptへ再開する。"""
        if (
            self.state["status"] != "stopped"
            or self.state["stop_reason"]
            not in {
                "provider_failure",
                "management_unavailable",
                "creation_unknown",
                "cleanup_unconfirmed",
                "provider_rejected",
            }
            or any(r["status"] != "closed" for r in self.state["resources"])
            or self.state["failures"] >= 2
        ):
            raise ValueError("再開できる設備障害の状態ではありません")
        self.authorize()
        self.state["stop_reason"], self.state["status"] = None, "ready"
        self.save("resume_authorized")

    def finalize(self):
        self.authorize()
        cap = (
            5 if self.plan["purpose"] == "measurement" else (20 if self.plan["measurement"] else 15)
        )
        if self.spending() > cap:
            self.stop("budget_exceeded")
            return
        if (self.root / "results.json").exists():
            _, configurations, results = read_results(self.root, now=self.clock())
            if configurations != self.plan["configurations"] or results != self.state["results"]:
                raise ValueError("受領記録と実行状態が一致しません")
        else:
            accept_results(
                self.root,
                self.plan["configurations"],
                self.state["results"],
                active_attempts=self.state["active_attempts"],
                now=self.clock(),
            )
        if (self.root / "number-map.json").exists():
            map_path = self.root / "number-map.json"
            ledger = json.loads((self.root / "file-ledger.json").read_text())
            saved = next(r for r in ledger["files"] if r["file"] == "number-map.json")
            if sha(map_path.read_bytes()) != saved["sha256"]:
                raise ValueError("番号表のSHAが一致しません")
            table = json.loads(map_path.read_text())
            for field, name in (
                ("manifest_sha256", "manifest.json"),
                ("results_sha256", "results.json"),
                ("configurations_sha256", "configurations.json"),
                ("active_attempts_sha256", "active-attempts.json"),
            ):
                if table[field] != sha((self.root / name).read_bytes()):
                    raise ValueError("比較ページの参照が一致しません")
            for record in table["files"]:
                content = private_path(self.root, record["file"]).read_bytes()
                if sha(content) != record["sha256"]:
                    raise ValueError("比較ページのSHAが一致しません")
        else:
            build_pages(self.root, now=self.clock())
        self.state["status"] = "complete"
        self.state["model_settings_sha256"] = self.model_signature()
        self.state["cost_summary"] = summary(self.state)
        self.save("complete")


def review_material(plan):
    """実行前の私有レビュー資料を返す。秘密値・画像別の内部対応は含めない。"""
    validate_plan(plan)
    root = Path(plan["result_root"])
    manifest = load_manifest(root)
    return {
        "version": "trial-review-v1",
        "plan_sha256": digest(plan),
        "manifest_sha256": sha((root / "manifest.json").read_bytes()),
        "count": len(manifest["images"]),
        "synthetic_inputs": manifest["synthetic"],
        "provider": plan["provider"],
        "product": plan["product"],
        "region": plan["region"],
        "result_root": str(root),
        "concurrency": plan["concurrency"],
        "hard_usd": 20 if plan["measurement"] else 15,
        "soft_usd": 18 if plan["measurement"] else 13,
        "measurement_limit_usd": 5,
        "measurement_limit_seconds": 2400,
        "external_max_seconds": 86400,
        "local_expires_at": min(r["local_expires_at"] for r in manifest["images"]),
        "models": [
            {
                "configuration_id": key,
                "repo": d["model"]["repo"],
                "revision": d["model"]["revision"],
                "gpu": d["gpu"],
                "gpu_count": d["gpu_count"],
                "container": d["container"],
                "usd_hour": d["usd_hour"],
                "reservation_usd": RESERVATIONS[key],
                "time_seconds": time_limit(key, d),
                "license_confirmed": all(d[k]["license_confirmed"] for k in ("model", "segmenter")),
            }
            for key, d in plan["deployments"].items()
        ],
        "delete_scope": "当試行で新設したPodと、そのephemeral diskの画像・mask・結果",
        "unverified": [
            "GPU動作・VRAM・速度・実精度",
            "実在庫・同一ホスト複数GPU",
            "提供元の現時点の保持条件と請求終了",
            "24時間連続稼働",
        ],
        "required_permission": [
            "対象manifestと地域を指定した送信",
            "指定枠内の課金",
            "重み取得と実GPU合成smoke",
            "新設資源の削除",
        ],
    }
