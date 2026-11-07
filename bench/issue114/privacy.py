"""人物補助検出の採否記録と、非公開の目視サンプル作成・取込み。"""

import argparse
import hashlib
import html
import json
import os
import random
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats.retention import lock, register_file, review_privacy
from colorstats.schema.models import Asset

VERSION = "person-sam2-dino-v2"
SEED = 11420261107


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                   "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def classify(scan, policy):
    coverage = scan["subject_coverage"]
    subject = max(coverage, key=coverage.get)
    if coverage[subject] < policy["subject_min"]:
        return "pending", None, "subject_unresolved"
    if abs(coverage["building"] - coverage["terrain"]) < policy["subject_margin"]:
        return "pending", None, "subject_ambiguous"
    if scan["mask_ratio"] > policy["mask_max"]:
        return "pending", subject, "person_over_limit"
    return "accepted", subject, "person_masked" if scan["person_ratio"] else "person_not_detected"


def review_state(db, identifiers):
    with Session(db) as session:
        state = {str(aid): quality.get("privacy_review") for aid, quality in session.execute(
            select(Asset.id, Asset.quality).where(
                Asset.id.in_([UUID(aid) for aid in identifiers])))}
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def prepare(db, root, policy, execution):
    rows = []
    for host in ("ubuntu1", "ubuntu2"):
        if not (root / host / "done").exists():
            raise ValueError("人物検出が未完了です")
        (root / host).chmod(0o700)
        for path in sorted((root / host).glob("*.json")):
            if path.name == "scan-manifest.json":
                continue
            scan = json.loads(path.read_text())
            if scan["version"] != VERSION or digest(scan["mask_path"]) != scan["mask_sha256"]:
                raise ValueError("人物検出の版またはmask hashが一致しません")
            decision, subject, reason = classify(scan, policy)
            rows.append({**scan, "host": host, "decision": decision, "subject": subject,
                         "reason": reason, "scan_path": str(path), "scan_sha256": digest(path)})
    ids = [row["asset_id"] for row in rows]
    expected = json.loads((root.parent / "new-assets.json").read_text())
    if sorted(ids) != sorted(expected):
        raise ValueError("元の新規cohortと人物検出の対象が一致しません")
    execution.mkdir(mode=0o700, exist_ok=False)
    save(execution / "policy.json", policy)
    save(execution / "privacy-decisions.json", rows)
    with Session(db) as session, session.begin():
        for row in rows:
            asset = session.get(Asset, UUID(row["asset_id"]))
            if asset.quality.get("privacy_review"):
                raise ValueError("既存の人物判定を自動判定で上書きできません")
            review_privacy(
                session, asset.id, reviewer="auto:" + VERSION, method=VERSION,
                decision=row["decision"], subject=row["subject"], thresholds=policy,
                person_mask=row["mask_path"] if row["person_ratio"] else None,
                host=row["host"].replace("ubuntu", "ubuntu-"), note=row["reason"], evidence={
                    "scan_path": row["scan_path"], "scan_sha256": row["scan_sha256"],
                    "detector_manifest_sha256": digest(root / row["host"] / "scan-manifest.json"),
                    "input_sha256": row["input_sha256"], "region_run_id": row["region_run_id"],
                    "person_ratio": row["person_ratio"], "mask_ratio": row["mask_ratio"],
                },
            )
            for version in ("privacy-v1", "privacy-v2"):
                directory = root.parent / version / row["host"]
                for suffix in (".png", ".json"):
                    path = directory / (row["asset_id"] + suffix)
                    if path.exists():
                        path.chmod(0o600)
                        register_file(session, asset.id, row["host"].replace("ubuntu", "ubuntu-"),
                                      path, "mask" if suffix == ".png" else "cache")
    accepted = [row for row in rows if row["decision"] == "accepted"]
    for filename in ("baseline-assets.json", "baseline-runs.json", "prep-report.json"):
        shutil.copyfile(root.parent / filename, execution / filename)
    save(execution / "new-assets.json", sorted(row["asset_id"] for row in accepted))
    for host in ("ubuntu1", "ubuntu2"):
        save(execution / f"{host}-assets.json", sorted(
            row["asset_id"] for row in accepted if row["host"] == host))
    summary = {"total": len(rows), "decisions": dict(Counter(row["decision"] for row in rows)),
               "reasons": dict(Counter(row["reason"] for row in rows)),
               "masked_accepted": sum(row["decision"] == "accepted" and row["person_ratio"] > 0
                                      for row in rows),
               "person_ratio_quantiles": np.quantile(
                   [row["person_ratio"] for row in rows], [0, .5, .9, .95, .99, 1]).tolist(),
               "policy": policy, "method": VERSION}
    save(execution / "privacy-summary.json", summary)
    import pwd

    owner = pwd.getpwnam("nobody")
    os.chown(execution, owner.pw_uid, owner.pw_gid)
    for path in execution.iterdir():
        path.chmod(0o600)
        os.chown(path, owner.pw_uid, owner.pw_gid)
    print(json.dumps(summary), flush=True)


def save_image(path, image):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        image.save(stream, format="PNG")


def selection(rows, policy):
    """固定seedの無作為群・閾値付近・保留群を同じ規則で選ぶ。"""
    ordered = sorted(rows, key=lambda row: row["asset_id"])
    random_ids = set(random.Random(SEED).sample([row["asset_id"] for row in ordered],
                                              min(100, len(ordered))))
    boundary = sorted((row for row in ordered if row["person_ratio"] > 0),
                      key=lambda row: abs(row["mask_ratio"] - policy["mask_max"]))[:40]
    boundary_ids = {row["asset_id"] for row in boundary}
    selected = [row for row in ordered if row["asset_id"] in random_ids | boundary_ids
                or row["decision"] == "pending"]
    return selected, random_ids, boundary_ids


def review_bundle(db, execution, output, raw_paths=None):
    rows = json.loads((execution / "privacy-decisions.json").read_text())
    policy = json.loads((execution / "policy.json").read_text())
    selected, random_ids, boundary_ids = selection(rows, policy)
    output.mkdir(mode=0o700, exist_ok=False)
    (output / "images").mkdir(mode=0o700)
    with Session(db) as session, session.begin():
        lock(session)
        for row in selected:
            aid = row["asset_id"]
            asset = session.get(Asset, UUID(aid))
            raw_path = asset.storage_path
            if raw_paths is not None:
                replica = raw_paths[aid]
                if (digest(replica["path"]) != replica["sha256"]
                        or replica["sha256"] != asset.sha256):
                    raise ValueError("閲覧用の取得画像replicaが元のSHAと一致しません")
                raw_path = replica["path"]
            for label, path in (("raw", raw_path), ("prep", row["input_path"])):
                with Image.open(path) as image:
                    destination = output / "images" / f"{aid}-{label}.png"
                    save_image(destination, image.convert("RGB"))
                    register_file(session, asset.id, "ubuntu-2", destination, "cache")
            with Image.open(row["input_path"]) as image, Image.open(row["mask_path"]) as mask:
                image = image.convert("RGB")
                red = Image.new("RGB", image.size, "red")
                overlay = Image.blend(image, red, .55)
                destination = output / "images" / f"{aid}-overlay.png"
                save_image(destination, Image.composite(overlay, image, mask.convert("L")))
                register_file(session, asset.id, "ubuntu-2", destination, "cache")
    manifest = {"seed": SEED, "method": VERSION, "policy": policy,
                "decisions_sha256": digest(execution / "privacy-decisions.json"),
                "random_ids": sorted(random_ids), "boundary_ids": sorted(boundary_ids),
                "required_ids": sorted(random_ids | boundary_ids),
                "rows": [{k: row[k] for k in ("asset_id", "decision", "subject", "reason",
                                              "person_ratio", "mask_ratio")} for row in selected]}
    save(output / "manifest.json", manifest)
    save(execution / "review-manifest.json", manifest)
    cards = []
    for row in selected:
        aid = row["asset_id"]
        labels = ("無作為 " if aid in random_ids else "")
        labels += "閾値付近 " if aid in boundary_ids else ""
        cards.append(f'''<article data-id="{aid}"><h3>{aid}</h3><p>{labels}
{html.escape(row['decision'])} / {html.escape(row['reason'])} / mask {row['mask_ratio']:.4%}</p>
<a href="images/{aid}-raw.png" target="_blank">取得画像を開く</a>
<div class="images"><img src="images/{aid}-prep.png" loading="lazy">
<img src="images/{aid}-overlay.png" loading="lazy"></div>
<label>判定 <select class="decision"><option value="">未記入</option>
<option value="same">自動判定どおり</option><option value="accepted">採用</option>
<option value="rejected">不採用</option><option value="pending">保留</option></select></label>
<label>主体 <select class="subject">
<option value="{row['subject'] or ''}">{row['subject'] or '未確定'}</option>
<option>building</option><option>terrain</option></select></label>
<label><input class="error" type="checkbox">人物の見落とし・判定誤りあり</label>
<input class="mask" placeholder="修正人物maskのPNGファイル名（必要時）">
<input class="note" placeholder="理由・必要なmaskの作成状況"></article>''')
    template = Path(__file__).with_name("privacy-review.html").read_text(encoding="utf-8")
    page = template.replace("__CARDS__", "\n".join(cards)).replace(
        "__MANIFEST__", json.dumps(manifest, ensure_ascii=False))
    with os.fdopen(os.open(output / "index.html", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                   "w", encoding="utf-8") as stream:
        stream.write(page)
    with Session(db) as session, session.begin():
        lock(session)
        for row in selected:
            for filename in ("index.html", "manifest.json"):
                register_file(session, UUID(row["asset_id"]), "ubuntu-2",
                              output / filename, "cache")
    print(json.dumps({"random": len(random_ids), "boundary": len(boundary_ids),
                      "listed": len(selected), "path": str(output)}), flush=True)


def import_reviews(db, execution, source):
    data = json.loads(source.read_text())
    manifest = json.loads((execution / "review-manifest.json").read_text())
    decisions = {row["asset_id"]: row for row in json.loads(
        (execution / "privacy-decisions.json").read_text())}
    if (not data["reviewer"].strip()
            or data["decisions_sha256"] != digest(execution / "privacy-decisions.json")):
        raise ValueError("確認者または固定した自動判定が一致しません")
    seen = set()
    changed = False
    with Session(db) as session, session.begin():
        for row in data["rows"]:
            aid = row["asset_id"]
            if aid in seen or aid not in {item["asset_id"] for item in manifest["rows"]}:
                raise ValueError("未提示または重複した目視結果です")
            seen.add(aid)
            original = decisions[aid]
            decision = original["decision"] if row["decision"] == "same" else row["decision"]
            replacement = row.get("mask_filename")
            if row["error_found"] and decision == "accepted" and not replacement:
                raise ValueError("見落とし画像はmask修正・再解析まで保留か不採用にしてください")
            changed |= decision != original["decision"] or row["subject"] != original["subject"]
            asset = session.get(Asset, UUID(aid))
            review = asset.quality["privacy_review"]
            person_mask = review["person_mask"]
            if replacement:
                import pwd

                if Path(replacement).name != replacement or Path(replacement).suffix != ".png":
                    raise ValueError("修正maskはhuman-masks内のPNGファイル名で指定してください")
                person_mask = str(execution / "human-masks" / replacement)
                with Image.open(person_mask) as mask, Image.open(original["input_path"]) as image:
                    if mask.size != image.size:
                        raise ValueError("修正人物maskの寸法が解析画像と一致しません")
                owner = pwd.getpwnam("nobody")
                Path(person_mask).parent.chmod(0o700)
                os.chown(Path(person_mask).parent, owner.pw_uid, owner.pw_gid)
                Path(person_mask).chmod(0o600)
                os.chown(person_mask, owner.pw_uid, owner.pw_gid)
                changed = True
            review_privacy(session, asset.id, reviewer=data["reviewer"], subject=row["subject"],
                           person_mask=person_mask, method="human", decision=decision,
                           evidence=review["evidence"], note=row["note"])
    token = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    save(execution / f"human-review-{token}.json", data)
    with Session(db) as session:
        for asset in session.scalars(select(Asset).where(
            Asset.id.in_([UUID(aid) for aid in decisions]),
        )):
            original = decisions[str(asset.id)]
            current = asset.quality["privacy_review"]
            expected_mask = original["mask_path"] if original["person_ratio"] else None
            expected_hash = original["mask_sha256"] if original["person_ratio"] else None
            changed |= (current["decision"] != original["decision"]
                        or current["subject"] != original["subject"]
                        or current["person_mask"] != expected_mask
                        or current["mask_sha256"] != expected_hash)
    approved = (set(manifest["required_ids"]) <= seen and data["confirm_no_errors"]
                and not any(row["error_found"] for row in data["rows"]) and not changed)
    validation = {"approved": approved, "reviewer": data["reviewer"], "reviewed": len(seen),
                  "requires_reanalysis": changed, "decisions_sha256": data["decisions_sha256"],
                  "review_state_sha256": review_state(db, decisions)}
    save(execution / f"privacy-validation-{token}.json", validation)
    with os.fdopen(os.open(execution / "privacy-validation.json",
                           os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "w") as stream:
        stream.write(json.dumps(validation) + "\n")
    print(json.dumps(validation, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "review", "import"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--raw-manifest", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    from bench.issue105.production import engine

    db = engine(False)
    try:
        if args.action == "prepare":
            prepare(db, args.root, json.loads(args.policy.read_text()), args.execution)
        elif args.action == "review":
            review_bundle(db, args.execution, args.output,
                          json.loads(args.raw_manifest.read_text()) if args.raw_manifest else None)
        else:
            import_reviews(db, args.execution, args.input)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
