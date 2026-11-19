"""trial-output-v1の受領契約。モデルの精度や実行許可を判定しない。"""

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from colorstats.api_budget import digest
from colorstats.trial_inputs import (
    SCENES,
    SHA,
    add_files,
    encoded,
    load_manifest,
    private_path,
    sha,
    stamp,
    write_private,
)

PARTS = {
    "wall": ("壁", "建物の外側の壁。屋根、窓、扉は含みません。"),
    "roof": ("屋根", "建物の上を覆う屋根の見えている部分。壁は含みません。"),
    "window": ("窓全体", "窓ガラスと、そのまわりの枠を合わせた部分。壁は含みません。"),
    "window_glass": ("窓ガラス", "窓のガラス部分。まわりの枠は含みません。"),
    "window_frame": ("窓枠", "窓ガラスのまわりの枠。ガラス部分は含みません。"),
    "door": ("扉", "出入り口を開け閉めする扉の見えている部分。まわりの壁は含みません。"),
}
CONFIG_FIELDS = {
    "model_revision",
    "weights_sha256",
    "precision",
    "environment_sha256",
    "code_sha256",
    "prompt_sha256",
    "processor_sha256",
    "segmenter_revision",
    "segmenter_sha256",
}
RESULT_FIELDS = {
    "version",
    "trial_id",
    "configuration_id",
    "configuration_sha256",
    "input_sha256",
    "size",
    "attempt",
    "status",
    "scene",
    "regions",
    "elapsed_seconds",
    "peak_vram_mib",
    "expense_ref",
}
STATUSES = {"success", "missing", "failed", "rejected", "truncated"}


def configurations_valid(configurations):
    if set(configurations) not in (set("ABCDE"), set("ABCE")):
        raise ValueError("構成はABCDEまたはABCEに固定してください")
    for config in configurations.values():
        if (
            set(config) != CONFIG_FIELDS
            or config["precision"] not in {"BF16", "AWQ4", "FP32"}
            or any(not SHA.fullmatch(config[k]) for k in CONFIG_FIELDS if k.endswith("sha256"))
            or any(
                not re.fullmatch(r"[0-9a-f]{40}", config[k])
                for k in ("model_revision", "segmenter_revision")
            )
        ):
            raise ValueError("モデル・重み・精度・環境・指示・分割器の固定参照が必要です")
    precisions = {"A": "BF16", "B": "BF16", "C": "AWQ4", "D": "BF16", "E": "FP32"}
    if any(config["precision"] != precisions[k] for k, config in configurations.items()):
        raise ValueError("承認済み構成の精度と一致しません")
    if (
        len(
            {
                (configurations[c]["segmenter_revision"], configurations[c]["segmenter_sha256"])
                for c in "ABC"
            }
        )
        != 1
    ):
        raise ValueError("A/B/Cは同じ分割器へ固定してください")


def load_mask(root, record, size):
    if set(record) != {"file", "sha256"} or not SHA.fullmatch(record["sha256"]):
        raise ValueError("maskの必須参照が不正です")
    path = private_path(root, record["file"])
    if path.suffix != ".png" or sha(path.read_bytes()) != record["sha256"]:
        raise ValueError("maskの形式またはSHAが一致しません")
    with Image.open(path) as image:
        values = np.asarray(image)
        if (
            image.format != "PNG"
            or image.mode not in {"1", "L"}
            or list(image.size) != size
            or not np.isin(values, [0, 1, 255]).all()
        ):
            raise ValueError("元入力と同寸法の二値PNG maskが必要です")
    return values != 0


def validate_result(root, manifest, configurations, row, *, active_attempts):
    """#142が逐次回収した1件を検査する。受領保存・DB登録は行わない。"""
    root = Path(root)
    configurations_valid(configurations)
    if [r["trial_id"] for r in manifest["images"]] != [f"T{i:03}" for i in range(1, 31)]:
        raise ValueError("固定manifestには30件の連番が必要です")
    inputs = {r["trial_id"]: r["input"] for r in manifest["images"]}
    if set(row) != RESULT_FIELDS or row["version"] != "trial-output-v1":
        raise ValueError("trial-output-v1の項目が一致しません")
    key = row["trial_id"], row["configuration_id"]
    if key[0] not in inputs or key[1] not in configurations:
        raise ValueError("対象・構成が未知または重複しています")
    if active_attempts.get(key[0], {}).get(key[1]) != row["attempt"]:
        raise ValueError("有効attemptと受信結果が一致しません")
    source = inputs[key[0]]
    if (
        row["configuration_sha256"] != digest(configurations[key[1]])
        or row["input_sha256"] != source["sha256"]
        or row["size"] != source["size"]
        or sha(private_path(root, source["file"]).read_bytes()) != source["sha256"]
    ):
        raise ValueError("入力・寸法・構成の固定参照が一致しません")
    if (
        row["status"] not in STATUSES
        or row["scene"] not in SCENES | {"unsupported"}
        or (key[1] == "E") != (row["scene"] == "unsupported")
        or any(not re.fullmatch(r"[A-Za-z0-9_-]+", row[k]) for k in ("attempt", "expense_ref"))
        or any(
            type(row[k]) not in {float, int} or not math.isfinite(row[k]) or row[k] < 0
            for k in ("elapsed_seconds", "peak_vram_mib")
        )
        or not isinstance(row["regions"], list)
        or len(row["regions"]) > 24
    ):
        raise ValueError("状態・場面・実行・費用・計測参照が不正です")
    if row["status"] != "success" and row["regions"]:
        raise ValueError("欠測・失敗・打切りを有効領域として受け付けません")
    for region in row["regions"]:
        if set(region) != {"part", "box", "mask"} or region["part"] not in PARTS:
            raise ValueError("未定義の部位または領域項目です")
        box = region["box"]
        if (
            not isinstance(box, list)
            or len(box) != 4
            or any(
                type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 1 for v in box
            )
            or box[0] >= box[2]
            or box[1] >= box[3]
        ):
            raise ValueError("箱は0～1の左上・右下座標で指定してください")
        load_mask(root, region["mask"], row["size"])


def validate_results(root, manifest, configurations, results, *, active_attempts):
    """30件×選択構成を一対一照合する。個々の検査は逐次回収と同じ関数を使う。"""
    configurations_valid(configurations)
    seen = set()
    for row in results:
        validate_result(root, manifest, configurations, row, active_attempts=active_attempts)
        key = row["trial_id"], row["configuration_id"]
        if key in seen:
            raise ValueError("対象・構成が重複しています")
        seen.add(key)
    if seen != {(f"T{i:03}", c) for i in range(1, 31) for c in configurations}:
        raise ValueError("30件×選択構成の状態に不足があります")


def _pending_masks(manifest, results, ledger, now):
    """登録maskのSHA・期限を照合し、未登録分の台帳行を返す。"""
    expiry = min((row["local_expires_at"] for row in manifest["images"]), key=stamp)
    records = {r["mask"]["file"]: r["mask"]["sha256"] for row in results for r in row["regions"]}
    registered = {record["file"]: record for record in ledger["files"]}
    pending = []
    for name, value in records.items():
        saved = registered.get(name)
        if saved is None:
            pending.append({"file": name, "sha256": value, "expires_at": expiry})
        elif saved["sha256"] != value or not now < stamp(saved["expires_at"]) <= stamp(expiry):
            raise ValueError("事前登録maskのSHA不一致・期限切れ・元期限超過の登録です")
    return pending


def accept_results(root, configurations, results, *, active_attempts, now=None):
    """回収結果を私有台帳へ追加する。既存maskのSHAを照合し、期限の延長は拒否する。"""
    now = now or datetime.now(UTC)
    root = Path(root)
    manifest = load_manifest(root, now=now)
    validate_results(root, manifest, configurations, results, active_attempts=active_attempts)
    blobs = {
        "configurations.json": encoded(configurations),
        "results.json": encoded(results),
        "active-attempts.json": encoded(active_attempts),
    }
    expiry = min((row["local_expires_at"] for row in manifest["images"]), key=stamp)
    ledger = json.loads((root / "file-ledger.json").read_text(encoding="utf-8"))
    pending = _pending_masks(manifest, results, ledger, now)
    pending.extend(
        {"file": name, "sha256": sha(blob), "expires_at": expiry} for name, blob in blobs.items()
    )
    add_files(root, pending)
    for name, blob in blobs.items():
        write_private(root / name, blob)


def read_results(root, *, now=None):
    """受領記録と登録maskを再照合する。短縮期限切れのmaskは再利用しない。"""
    now = now or datetime.now(UTC)
    root = Path(root)
    manifest = load_manifest(root, now=now)
    ledger = json.loads((root / "file-ledger.json").read_text(encoding="utf-8"))
    for name in ("configurations.json", "results.json", "active-attempts.json"):
        saved = next(r for r in ledger["files"] if r["file"] == name)
        if sha(private_path(root, name).read_bytes()) != saved["sha256"]:
            raise ValueError("受領済みの結果・構成が変更されています")
    configurations = json.loads((root / "configurations.json").read_text(encoding="utf-8"))
    results = json.loads((root / "results.json").read_text(encoding="utf-8"))
    active_attempts = json.loads((root / "active-attempts.json").read_text(encoding="utf-8"))
    if _pending_masks(manifest, results, ledger, now):
        raise ValueError("受領済みmaskが台帳に登録されていません")
    validate_results(root, manifest, configurations, results, active_attempts=active_attempts)
    return manifest, configurations, results
