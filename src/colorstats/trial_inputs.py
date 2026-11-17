"""非本番VLM試行の選定・画像束。DBは明示した読取専用取引で参照する。"""

import hashlib
import io
import json
import os
import random
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats import image_gate, retention
from colorstats.api_budget import digest
from colorstats.rights import combine_license
from colorstats.schema.models import Asset, AssetDuplicate, Retention, Source

SEED = 20261116
SPLITS = {
    "tune": {"single": 4, "interior": 1, "group": 1},
    "confirm": {"single": 20, "interior": 1, "group": 1, "gate": 1, "closeup": 1},
}
SCENES = {"single", "interior", "group", "gate", "closeup", "terrain", "unknown"}
SHA = re.compile(r"[0-9a-f]{64}")


def sha(content):
    return hashlib.sha256(content).hexdigest()


def stamp(value):
    """タイムゾーンを持つ私有台帳の日時だけを受け付ける。"""
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("期限にはタイムゾーンが必要です")
    return result


@contextmanager
def read_session(engine):
    """外から渡された接続先を読取専用にし、終了時は常にrollbackする。"""
    with Session(engine, autoflush=False) as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        try:
            yield session
        finally:
            session.rollback()


def current(session, asset_id, now):
    """既存rights・停止台帳に加え、openと明示保持登録を必須にする。"""
    asset_id = UUID(str(asset_id))
    retention.assert_usable(session, asset_id, images=True, now=now)
    asset = session.get(Asset, asset_id)
    source = session.get(Source, asset.source_id)
    record = session.scalar(select(Retention).where(Retention.asset_id == asset_id))
    if (
        combine_license(asset.license_class, source.license_class) != "open"
        or record is None
        or not asset.storage_path
    ):
        raise PermissionError("open・明示保持登録・原画像の参照が必要です")
    expiry = record.expires_at
    if value := asset.quality.get("retention_until"):
        expiry = min(expiry, stamp(value))
    if expiry <= now:
        raise PermissionError("元画像の期限が切れています")
    return asset, expiry


def read_candidates(engine, reviews, *, now=None):
    """私有の場面・人物確認表をDBのSHA・subjectへ結ぶ。書込み・送信はしない。

    reviewsはsource_sha256、scene、subject_group、scene_ref、person_ref、
    peopleを持つ行。確認根拠がない写真をモデルの旧判定から推測しない。
    戻り値は私有候補と既存重複関係。実写真の選定完了は別のselectで判断する。
    """
    now = now or datetime.now(UTC)
    rows = []
    with read_session(engine) as session:
        for review in reviews:
            asset, expiry = current(session, review["asset_id"], now)
            if (
                review["source_sha256"] != asset.sha256
                or asset.subject_id is None
                or review["subject_group"] != str(asset.subject_id)
                or asset.domain != "real_building"
            ):
                raise ValueError("確認した画像SHA・建物参照が現在のDBと一致しません")
            row = {
                **review,
                "path": asset.storage_path,
                "phash": asset.phash,
                "expires_at": expiry.isoformat(),
            }
            check_candidate(row, now)
            rows.append(row)
        pairs = [
            (str(a), str(b))
            for a, b in session.execute(select(AssetDuplicate.asset_a, AssetDuplicate.asset_b))
        ]
    return rows, pairs


def check_candidate(row, now):
    if (
        not SHA.fullmatch(row["source_sha256"])
        or not re.fullmatch(r"[0-9a-f]{16}", row.get("phash") or "")
        or row.get("scene") not in SCENES - {"terrain", "unknown"}
        or row.get("people") != "absent"
        or any(not row.get(k) for k in ("asset_id", "subject_group", "scene_ref", "person_ref"))
    ):
        raise ValueError("場面・建物・人物陰性・確認参照・SHA・pHashが必要です")
    if stamp(row["expires_at"]) <= now:
        raise PermissionError("選定候補の期限が切れています")


def select_candidates(candidates, legacy, pairs=(), *, now=None):
    """旧108件・SHA/pHash・既知重複を除き、建物単位で6/24件へ固定選定する。

    legacyはdelivery-v3の提示SHAと108件の元SHA/pHashを持つ私有記録。
    不足時は別区分で補充せずValueError。入力一覧の順に結果は依存しない。
    """
    now = now or datetime.now(UTC)
    if (
        legacy.get("version") != "delivery-v3"
        or not SHA.fullmatch(legacy.get("presentation_sha256", ""))
        or len(legacy.get("images", [])) != 108
    ):
        raise ValueError("旧delivery-v3の108件と提示SHAが必要です")
    old = legacy["images"]
    if len({r["asset_id"] for r in old}) != 108:
        raise ValueError("旧提示の対象が重複しています")
    for row in old:
        if not SHA.fullmatch(row["source_sha256"]) or not re.fullmatch(
            r"[0-9a-f]{16}", row.get("phash") or ""
        ):
            raise ValueError("旧提示のSHA・pHashが不足しています")
    if len({r["asset_id"] for r in candidates}) != len(candidates):
        raise ValueError("候補の内部対応が重複しています")
    for row in candidates:
        check_candidate(row, now)
    parents = {}

    def group(key):
        while parents.get(key, key) != key:
            key = parents[key]
        return key

    for a, b in pairs:
        parents[group(a)] = group(b)
    forbidden = {group(r["asset_id"]) for r in old}
    used = list(old)
    phases = {}
    pool = sorted(candidates, key=lambda r: r["asset_id"])
    random.Random(SEED).shuffle(pool)
    chosen = []
    for split, strata in SPLITS.items():
        for scene, count in strata.items():
            available = 0
            for row in pool:
                if row["scene"] != scene or phases.get(row["subject_group"], split) != split:
                    continue
                if group(row["asset_id"]) in forbidden:
                    continue
                if any(
                    row["source_sha256"] == r["source_sha256"]
                    or (int(row["phash"], 16) ^ int(r["phash"], 16)).bit_count() <= 6
                    for r in used
                ):
                    continue
                chosen.append({**row, "split": split})
                phases[row["subject_group"]] = split
                forbidden.add(group(row["asset_id"]))
                used.append(row)
                available += 1
                if available == count:
                    break
            if available != count:
                raise ValueError(f"層不足: {split}/{scene} 必要{count}件・選定{available}件")
    return [
        {**row, "number": n, "trial_id": f"T{n:03}", "legacy_sha256": digest(legacy)}
        for n, row in enumerate(chosen, 1)
    ]


def private_path(root, relative):
    """試行root内の通常ファイルだけを解決し、symlink・脱出を拒否する。"""
    root = Path(root)
    path = root / relative
    if (
        Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or "\\" in str(relative)
        or path.resolve() != path
        or not path.is_relative_to(root)
    ):
        raise ValueError("試行内の相対パスが必要です")
    return path


def new_root(result_root):
    root = Path(result_root)
    if (
        not root.is_absolute()
        or root.resolve() != root
        or root.exists()
        or not root.parent.is_dir()
        or not os.access(root.parent, os.W_OK)
        or any((p / ".git").exists() for p in (root, *root.parents))
    ):
        raise ValueError("Gitの外にある新規・絶対・書込可能なresult_rootが必要です")
    root.mkdir(mode=0o700)
    return root


def write_private(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(content)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def add_files(root, records):
    """新規試行コピーを保存前に台帳へ加える。既存台帳以外は置換しない。"""
    path = root / "file-ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if {r["file"] for r in records} & {r["file"] for r in ledger["files"]}:
        raise ValueError("試行出力は上書きしません")
    ledger["files"].extend(records)
    temporary = root / ".file-ledger.pending"
    write_private(temporary, encoded(ledger))
    temporary.replace(path)


def prepare(selected, result_root, *, now=None, synthetic=False):
    """選定済み30件をprivate束へ保存する。外部用packageは番号と画像だけ。

    元画像のSHAを再照合してnormalizeを再利用する。途中失敗時も新規コピーを
    台帳に残し、既存データを清掃しない。DB登録・送信は一切行わない。
    """
    now = now or datetime.now(UTC)
    if len(selected) != 30 or [r["trial_id"] for r in selected] != [
        f"T{i:03}" for i in range(1, 31)
    ]:
        raise ValueError("選定済み30件と連番が必要です")
    expected = {
        (phase, scene): count for phase, strata in SPLITS.items() for scene, count in strata.items()
    }
    actual = {}
    phases = {}
    for row in selected:
        key = row["split"], row["scene"]
        actual[key] = actual.get(key, 0) + 1
        if phases.setdefault(row["subject_group"], row["split"]) != row["split"]:
            raise ValueError("同じ建物が調整用と確認用にまたがっています")
    if (
        actual != expected
        or len({r["asset_id"] for r in selected}) != 30
        or [r["number"] for r in selected] != list(range(1, 31))
        or len({r.get("legacy_sha256") for r in selected}) != 1
        or not SHA.fullmatch(selected[0].get("legacy_sha256", ""))
    ):
        raise ValueError("選定の層・連番・重複・旧提示参照が不正です")
    images, blobs = [], {}
    for row in selected:
        check_candidate(row, now)
        raw = Path(row["path"]).read_bytes()
        if sha(raw) != row["source_sha256"]:
            raise ValueError("元画像SHAが選定時から変わっています")
        content = image_gate.normalize(raw)
        with Image.open(io.BytesIO(content)) as image:
            size = list(image.size)
        item = {
            **row,
            "input": {
                "file": f"package/{row['trial_id']}.png",
                "sha256": sha(content),
                "size": size,
            },
            "local_expires_at": min(stamp(row["expires_at"]), now + timedelta(days=7)).isoformat(),
        }
        images.append(item)
        blobs[item["input"]["file"]] = content
    if len({sha(b) for b in blobs.values()}) != 30:
        raise ValueError("正規化後の入力画像が重複しています")
    manifest = {
        "version": "trial-input-v1",
        "seed": SEED,
        "created_at": now.isoformat(),
        "external_max_seconds": 86400,
        "synthetic": synthetic,
        "images": images,
    }
    public = {
        "version": "trial-package-v1",
        "images": [
            {
                "trial_id": r["trial_id"],
                "file": Path(r["input"]["file"]).name,
                "sha256": r["input"]["sha256"],
                "size": r["input"]["size"],
            }
            for r in images
        ],
    }
    blobs["package/inputs.json"] = encoded(public)
    blobs["manifest.json"] = encoded(manifest)
    root = new_root(result_root)
    (root / "package").mkdir(mode=0o700)
    expiry = min((r["local_expires_at"] for r in images), key=stamp)
    ledger = {
        "version": "trial-files-v1",
        "expires_at": expiry,
        "files": [
            {"file": name, "sha256": sha(blob), "expires_at": expiry}
            for name, blob in blobs.items()
        ],
    }
    write_private(root / "file-ledger.json", encoded(ledger))
    for name, blob in blobs.items():
        write_private(root / name, blob)
    return manifest


def load_manifest(root, *, now=None):
    root = Path(root)
    if (
        not root.is_absolute()
        or root.resolve() != root
        or any((p / ".git").exists() for p in (root, *root.parents))
    ):
        raise ValueError("試行rootが不正です")
    ledger = json.loads(private_path(root, "file-ledger.json").read_text(encoding="utf-8"))
    if ledger.get("version") != "trial-files-v1":
        raise ValueError("未対応の試行台帳の版です")
    if stamp(ledger["expires_at"]) <= (now or datetime.now(UTC)):
        raise PermissionError("試行コピーの期限が切れています")
    manifest = private_path(root, "manifest.json")
    record = next(r for r in ledger["files"] if r["file"] == "manifest.json")
    if sha(manifest.read_bytes()) != record["sha256"]:
        raise ValueError("固定manifestが変わっています")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        value.get("version") != "trial-input-v1"
        or value.get("seed") != SEED
        or type(value.get("synthetic")) is not bool
    ):
        raise ValueError("入力manifestの版・seed・合成区分が一致しません")
    return value


def validate_package(root, manifest):
    """外部用ディレクトリを完全列挙し、追加情報・metadata・改変を拒否する。"""
    root = Path(root)
    images = manifest["images"]
    expected = {"inputs.json"} | {f"{r['trial_id']}.png" for r in images}
    directory = private_path(root, "package")
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError("外部用packageに未知または不足するファイルがあります")
    public = json.loads(private_path(root, "package/inputs.json").read_text(encoding="utf-8"))
    wanted = {
        "version": "trial-package-v1",
        "images": [
            {
                "trial_id": r["trial_id"],
                "file": f"{r['trial_id']}.png",
                "sha256": r["input"]["sha256"],
                "size": r["input"]["size"],
            }
            for r in images
        ],
    }
    if public != wanted:
        raise ValueError("外部用の項目・入力参照が固定manifestと一致しません")
    for row in images:
        path = private_path(root, row["input"]["file"])
        if sha(path.read_bytes()) != row["input"]["sha256"]:
            raise ValueError("外部用画像SHAが一致しません")
        with Image.open(path) as image:
            if (
                image.format != "PNG"
                or image.mode != "RGB"
                or image.info
                or list(image.size) != row["input"]["size"]
                or max(image.size) > 1024
            ):
                raise ValueError("外部用画像の寸法・形式・metadataが不正です")
    return public


def recheck(engine, root, *, now=None):
    """送信直前／回収後に現在の停止・期限・元SHAとコピーを再検査する。

    送信許可を与える関数ではない。戻り値の期限は#142が別途得る明示許可を
    前提に、送信後24hとローカル・元期限の早い方である。
    """
    now = now or datetime.now(UTC)
    manifest = load_manifest(root, now=now)
    validate_package(root, manifest)
    if manifest["synthetic"]:
        raise PermissionError("合成試行を実写真の送信対象にできません")
    expiry = now + timedelta(hours=24)
    with read_session(engine) as session:
        for row in manifest["images"]:
            asset, source_expiry = current(session, row["asset_id"], now)
            image = private_path(Path(root), row["input"]["file"])
            if (
                asset.sha256 != row["source_sha256"]
                or sha(Path(asset.storage_path).read_bytes()) != asset.sha256
                or sha(image.read_bytes()) != row["input"]["sha256"]
            ):
                raise ValueError("元画像または試行コピーが変わっています")
            expiry = min(expiry, source_expiry, stamp(row["local_expires_at"]))
    return expiry
