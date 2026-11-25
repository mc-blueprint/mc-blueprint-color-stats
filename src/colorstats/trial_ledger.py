"""smoke・測定・本体をまたぐ、試行専用の私有USD台帳。"""

import json
import os
from pathlib import Path

from colorstats.trial_costs import number
from colorstats.trial_inputs import encoded, write_private


class Budget:
    """処理中はOS排他を保持する。並列GPUは同じrunnerの最大2資源から管理する。"""

    def __init__(self, path, cap):
        self.path = Path(path)
        self.cap = cap
        self.data = None
        self.stream = None

    def __enter__(self):
        import fcntl

        if (
            not self.path.is_absolute()
            or self.path.resolve() != self.path
            or not self.path.parent.is_dir()
            or any((p / ".git").exists() for p in self.path.parents)
        ):
            raise ValueError("USD台帳はGit外の私有絶対パスで指定してください")
        self.stream = os.fdopen(
            os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600), "rb"
        )
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists():
                self.data = json.loads(self.path.read_text())
                if self.data["version"] != "trial-usd-v1" or self.data["cap_usd"] != self.cap:
                    raise ValueError("USD台帳の版・総枠が一致しません")
            else:
                self.data = {
                    "version": "trial-usd-v1",
                    "currency": "USD",
                    "cap_usd": self.cap,
                    "runs": {},
                }
                write_private(self.path, encoded(self.data))
        except BaseException:
            self.stream.close()
            raise
        return self

    def __exit__(self, *args):
        self.stream.close()

    def previous(self, run_id):
        return [run for key, run in self.data["runs"].items() if key != run_id]

    def prior_usd(self, run_id):
        return sum(
            number(r["estimated_usd"]) for run in self.previous(run_id) for r in run["resources"]
        )

    def update(self, state, root):
        if any(run["synthetic"] != state["synthetic"] for run in self.data["runs"].values()):
            raise ValueError("fakeと実GPUのUSD台帳は分けてください")
        self.data["runs"][state["run_id"]] = {
            "root": str(root),
            "plan_sha256": state["plan_sha256"],
            "provider": state["provider"],
            "product": state["product"],
            "region": state["region"],
            "purpose": state["purpose"],
            "synthetic": state["synthetic"],
            "status": state["status"],
            "failures": state["failures"],
            "resources": [
                {
                    k: r[k]
                    for k in (
                        "configuration_id",
                        "gpu",
                        "gpu_count",
                        "container",
                        "deployment_sha256",
                        "attempt",
                        "id",
                        "status",
                        "estimated_usd",
                        "billed_usd",
                        "elapsed_seconds",
                    )
                }
                for r in state["resources"]
            ],
        }
        pending = Path(str(self.path) + ".pending")
        write_private(pending, encoded(self.data))
        pending.replace(self.path)

    def verify_smoke(self, state):
        """削除済み実smokeのrun・資源・費用が同じ台帳にあることを照合する。"""
        run = self.data["runs"].get(state["run_id"])
        if (
            not run
            or run["synthetic"]
            or run["status"] not in {"complete", "stopped"}
            or any(r["status"] != "closed" for r in run["resources"])
            or run["purpose"] not in {"smoke", "measurement"}
            or any(run[k] != state[k] for k in (
                "plan_sha256", "provider", "product", "region", "purpose", "status"
            ))
            or len(run["resources"]) != len(state["resources"])
            or any(
                saved != {k: resource[k] for k in saved}
                for saved, resource in zip(run["resources"], state["resources"], strict=True)
            )
        ):
            raise ValueError("実GPUsmokeの費用を同じUSD台帳へ引き継いでください")
        return run
