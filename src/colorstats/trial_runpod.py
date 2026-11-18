"""RunPod Secure On-DemandのREST v2と、host key照合付きSSH回収。"""

import json
import re
import signal
import subprocess
import tempfile
import time
from functools import wraps
from ipaddress import IPv4Address
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from colorstats.trial_inputs import encoded, sha, stamp
from colorstats.trial_native_common import python_command

API = "https://api.runpod.io/v2"


class ProviderUnavailable(RuntimeError):
    """管理・転送が未確認。旧workerの消失や再起動許可を意味しない。"""


class ProviderRejected(ProviderUnavailable):
    """作成が処理されなかった4xx応答。未確認の作成要求と区別する。"""

    def __init__(self, status):
        super().__init__("提供元が新規作成を拒否しました")
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _deadline_expired(signum, frame):
    raise ProviderUnavailable("監視・回収操作の総時間枠です")


def bounded(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        outer = self.deadline is None
        if outer:
            if any(signal.getitimer(signal.ITIMER_REAL)):
                raise ProviderUnavailable("既存の時間監視と併用できません")
            previous = signal.signal(signal.SIGALRM, _deadline_expired)
            self.deadline = time.monotonic() + 14
            signal.setitimer(signal.ITIMER_REAL, 14)
        try:
            return method(self, *args, **kwargs)
        finally:
            if outer:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
                self.deadline = None

    return call


class RunPod:
    """許可確認後にrunnerが呼ぶ単一提供元。認証値は要求時だけ読む。

    transportとrequestはテスト差替え用。実接続ではapi_key_file、SSH鍵、
    host keyを記録済みのknown_hostsを私有設定で指定する。公開portはSSHだけ。
    """

    synthetic = False

    def __init__(self, settings, *, audit, request=None, transport=None):
        self.settings = settings
        self.deadline = None
        self.audit = audit
        self.request = request or self._request
        self.transport = transport or self._transport

    def timeout(self):
        remaining = self.deadline - time.monotonic() if self.deadline is not None else 3
        if remaining <= 0:
            raise ProviderUnavailable("監視・回収操作の時間枠です")
        return min(3, remaining)

    @bounded
    def _request(self, method, path, body=None):
        try:
            key = Path(self.settings["api_key_file"]).read_text().strip()
        except (OSError, UnicodeError):
            raise ProviderUnavailable("専用の認証参照を利用できません") from None
        if not key or any(c.isspace() for c in key):
            raise ProviderUnavailable("専用の認証参照の形式が不正です")
        req = Request(
            API + path,
            data=encoded(body) if body is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        self.audit({"operation": method, "path": path, "phase": "requested"})
        try:
            with build_opener(_NoRedirect()).open(req, timeout=self.timeout()) as response:
                data = response.read()
                status = response.status
        except HTTPError as error:
            self.audit({"operation": method, "path": path, "status": error.code})
            if (
                method == "POST"
                and path == "/pods"
                and error.code
                in {
                    400,
                    401,
                    402,
                    403,
                    404,
                    409,
                    413,
                    422,
                    429,
                }
            ):
                raise ProviderRejected(error.code) from None
            raise ProviderUnavailable("提供元APIの応答を確認できません") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ProviderUnavailable("提供元APIへ到達できません") from None
        self.audit({"operation": method, "path": path, "status": status, "sha256": sha(data)})
        try:
            return json.loads(data) if data else {}
        except (ValueError, UnicodeError):
            raise ProviderUnavailable("提供元APIの形式を確認できません") from None

    def listing(self, endpoint, key):
        rows = []
        cursor = None
        while True:
            path = endpoint + ("?" + urlencode({"cursor": cursor}) if cursor else "")
            value = self.request("GET", path)
            rows.extend(value[key])
            if not value["pagination"]["hasNextPage"]:
                return rows
            next_cursor = value["pagination"]["nextCursor"]
            if not next_cursor or next_cursor == cursor:
                raise ProviderUnavailable("資源一覧の全ページを確認できません")
            cursor = next_cursor

    @bounded
    def create(self, resource, deployment):
        """作成要求を再送しない。応答不明はnameで照合するまで未解決にする。"""
        return self.request(
            "POST",
            "/pods",
            {
                "name": resource["name"],
                "image": deployment["container"],
                "gpu": {"id": deployment["gpu"], "count": deployment["gpu_count"]},
                "dataCenterIds": [self.settings["region"]],
                "cloud": "SECURE",
                "disk": deployment["disk_gb"],
                "mounts": {},
                "env": {"HF_TOKEN": "{{ RUNPOD_SECRET_" + deployment["hf_secret_name"] + " }}"}
                if deployment.get("hf_secret_name")
                else {},
                "ports": ["22/tcp"],
                "startSsh": True,
                "startJupyter": False,
                "globalNetworking": False,
            },
        )

    @bounded
    def status(self, resource):
        matches = [p for p in self.listing("/pods", "pods") if p["name"] == resource["name"]]
        if len(matches) > 1:
            raise ProviderUnavailable("同じ試行名の資源が複数あります")
        if not matches:
            return None
        pod = matches[0]
        if resource.get("id") and pod["id"] != resource["id"]:
            raise ProviderUnavailable("資源識別が一致しません")
        if pod["status"] == "RUNNING":
            detail = self.request("GET", "/pods/" + pod["id"])
            if detail["id"] != pod["id"] or detail["name"] != resource["name"]:
                raise ProviderUnavailable("個別取得した資源識別が一致しません")
            pod = detail
        return pod

    def _transport(self, pod, operation, remote, local=None):
        endpoint = pod["ssh"].get("direct")
        if not endpoint:
            raise ProviderUnavailable("ファイル転送用の公開IP経由SSHが未準備です")
        host, user, port = endpoint["host"], endpoint["username"], endpoint["port"]
        if (
            not isinstance(host, str)
            or type(port) is not int
            or not 1 <= port <= 65535
            or not re.fullmatch(r"[A-Za-z0-9_-]+", user)
            or not re.fullmatch(
                r"/tmp/colorstats-[a-f0-9-]+/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+", remote
            )
        ):
            raise ValueError("公開IP経由SSH・試行専用ディレクトリが必要です")
        if any(part in {".", ".."} for part in remote.split("/")):
            raise ValueError("試行外への相対参照は使えません")
        IPv4Address(host)
        if operation in {"remove", "deadline"} and not re.fullmatch(
            r"/tmp/colorstats-[a-f0-9-]+/[A-E]_[a-f0-9]+/T[0-9]{3}", remote
        ):
            raise ValueError("削除対象は当試行の1画像分に限ります")
        options = [
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=" + self.settings["known_hosts"],
            "-o",
            "ConnectTimeout=10",
            "-i",
            self.settings["ssh_key_file"],
        ]
        if operation in {"put", "get"}:
            address = user + "@" + host + ":" + remote
            operands = [str(local), address] if operation == "put" else [address, str(local)]
            argv = ["scp", "-O", "-P", str(port), *options, *operands]
        else:
            commands = {
                "mkdir": ["mkdir", "-p", "-m", "700", remote],
                "ready": ["test", "-f", remote + "/prepared.json"],
                "done": ["test", "-f", remote + "/output.json"],
                "remove": ["rm", "-rf", "--", remote],
                "deadline": [
                    "mv",
                    "-f",
                    "--",
                    remote + "/deadline-next.json",
                    remote + "/deadline.json",
                ],
                "prepare": [
                    "nohup",
                    "timeout",
                    "1800",
                    *python_command(),
                    "--directory",
                    remote,
                    "--phase",
                    "prepare",
                    ">/dev/null",
                    "2>&1",
                    "<",
                    "/dev/null",
                    "&",
                ],
                "start": [
                    "nohup",
                    "timeout",
                    "120",
                    *python_command(),
                    "--directory",
                    remote,
                    ">/dev/null",
                    "2>&1",
                    "<",
                    "/dev/null",
                    "&",
                ],
            }
            argv = ["ssh", "-p", str(port), *options, user + "@" + host, *commands[operation]]
        self.audit({"operation": operation, "argv": argv, "phase": "requested"})
        try:
            result = subprocess.run(argv, capture_output=True, timeout=self.timeout(), check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ProviderUnavailable("SSH操作の完了を確認できません") from None
        self.audit(
            {
                "operation": operation,
                "exit": result.returncode,
                "stdout_sha256": sha(result.stdout),
                "stderr_sha256": sha(result.stderr),
            }
        )
        if operation in {"ready", "done"} and result.returncode == 1:
            return False
        if result.returncode:
            raise ProviderUnavailable("SSH操作が完了していません")
        return True

    @bounded
    def prepare(self, pod, resource, spec):
        remote = resource["remote"] + "/prepare"
        self.transport(pod, "mkdir", remote)
        self._put_json(pod, remote, spec)
        self.transport(pod, "prepare", remote)

    def _put_json(self, pod, remote, value, filename="request.json"):
        with tempfile.TemporaryDirectory(prefix="colorstats-request-") as name:
            path = Path(name) / "request.json"
            path.write_bytes(encoded(value))
            self.transport(pod, "put", remote + "/" + filename, path)

    @bounded
    def prepared(self, pod, resource):
        return self.transport(pod, "ready", resource["remote"] + "/prepare")

    @bounded
    def submit(self, pod, resource, image, content, spec):
        remote = resource["remote"] + "/" + image["trial_id"]
        self.transport(pod, "mkdir", remote)
        self._put_json(pod, remote, spec)
        with tempfile.TemporaryDirectory(prefix="colorstats-input-") as name:
            path = Path(name) / "input.png"
            path.write_bytes(content)
            self.transport(pod, "put", remote + "/input.png", path)
        self.transport(pod, "start", remote)

    @bounded
    def collect(self, pod, resource, trial_id):
        remote = resource["remote"] + "/" + trial_id
        if not self.transport(pod, "done", remote):
            return None
        with tempfile.TemporaryDirectory(prefix="colorstats-receive-") as name:
            path = Path(name)
            self.transport(pod, "get", remote + "/output.json", path / "output.json")
            value = json.loads((path / "output.json").read_text())
            if not isinstance(value.get("regions"), list) or len(value["regions"]) > 24:
                raise ValueError("受信領域数が不正です")
            blobs = {}
            for region in value["regions"]:
                filename = region["mask"]["file"]
                if not re.fullmatch(r"mask-[0-9]{2}\.png", filename):
                    raise ValueError("受信ファイル名が不正です")
                if filename not in blobs:
                    self.transport(pod, "get", remote + "/" + filename, path / filename)
                    blobs[filename] = (path / filename).read_bytes()
            return value, blobs

    @bounded
    def shorten_deadline(self, pod, resource, trial_id, deadline):
        remote = resource["remote"] + "/" + trial_id
        self._put_json(pod, remote, {"external_deadline": deadline}, "deadline-next.json")
        self.transport(pod, "deadline", remote)

    @bounded
    def remove_image(self, pod, resource, trial_id):
        self.transport(pod, "remove", resource["remote"] + "/" + trial_id)

    @bounded
    def close(self, resource):
        """当試行のname/ID一致Podだけを終了し、一覧・volume・請求証跡を照合する。"""
        pod = self.status(resource)
        if pod:
            self.request("DELETE", "/pods/" + pod["id"])
        remaining = self.status(resource)
        volumes = self.listing("/network-volumes", "networkVolumes")
        orphan = any(v["name"] == resource["name"] for v in volumes)
        billing = self.request("GET", "/billing/pods?" + urlencode({"podId": resource["id"]}))
        billed = sum(
            float(r["totalAmount"]) for r in billing["records"] if r["podId"] == resource["id"]
        )
        # APIの時間bucketは請求確定印ではないため、私有の照合証跡も要求する。
        receipt_path = Path(self.settings["billing_receipts"])
        try:
            receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
            receipt = receipts.get(resource["id"])
            confirmed = bool(
                receipt
                and re.fullmatch(r"[0-9a-f]{64}", receipt["evidence_sha256"])
                and stamp(receipt["ended_at"]) >= stamp(resource["created_at"])
                and receipt["amount_usd"] >= billed
            )
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise ProviderUnavailable("課金終了の照合証跡を確認できません") from None
        return {
            "deleted": remaining is None and not orphan,
            "billing_confirmed": confirmed,
            "billed_usd": float(receipt["amount_usd"]) if confirmed else billed,
        }
