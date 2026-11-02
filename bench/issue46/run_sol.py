"""#41の判定対象マスクで3手法を比較する。DB操作・モデル取得は行わない。"""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from colorstats.analyze import shade
from colorstats.analyze.shade_evaluation import compare
from colorstats.judgment_inputs import draft_mask

LABELS = ("wall_main", "roof_surface", "door", "window_frame")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_groups(manifest, identity):
    """同名群・既存building_idの集合が一致する複数画像群だけを返す。"""
    assets = {row["asset_id"]: row for row in manifest["assets"]}
    names = defaultdict(set)
    for aid, row in identity["assets"].items():
        if row["building_name"] is not None:
            names[row["building_name"]].add(aid)
    groups = []
    for name, members in sorted(names.items()):
        if len(members) < 2:
            continue
        ids = {assets[aid]["building_id"] for aid in members}
        if len(ids) != 1 or None in ids:
            raise ValueError("同名群のbuilding_idが一致しません")
        subject = next(iter(ids))
        existing = {aid for aid, row in assets.items() if row["building_id"] == subject}
        for aid in members:
            row = identity["assets"][aid]
            if (row["comparison"] != "match" or row["building_id"] != subject
                    or set(row["judged_group"]) != members
                    or set(row["candidate_group"]) != existing or existing != members):
                raise ValueError("同名群と既存building_idのasset集合が一致しません")
        groups.append({"subject_id": subject, "building_name": name,
                       "asset_ids": sorted(members)})
    return sorted(groups, key=lambda group: group["subject_id"])


def aggregate(records):
    """領域を選別後、有効画素数で部位平均する。モデル全体も同じ経路で集計する。"""
    cells = defaultdict(list)
    for row in records:
        for source in ("model", "sol-correct"):
            if source == "sol-correct" and row["verdict"] != "correct":
                continue
            key = (source, row["subject_id"], row["asset_id"], row["sha256"],
                   row["label"], row["method"])
            cells[key].append(row)
    samples = []
    for (source, subject, aid, sha, label, method), rows in sorted(cells.items()):
        samples.append({
            "subject_id": subject, "asset_id": aid, "sha256": sha,
            "label_source": source, "label": label, "method": method,
            "material_oklab": np.average([row["material_oklab"] for row in rows], axis=0,
                                        weights=[row["valid_pixels"] for row in rows]).tolist(),
        })
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue41", type=Path, default=Path("bench/issue41"))
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = read(args.issue41 / "manifest.json")
    identity_path = args.issue41 / "judgments/building-identity.json"
    groups = select_groups(manifest, read(identity_path))
    if digest(args.draft) != manifest["draft"]["artifact_sha256"]["draft.json"]:
        raise ValueError("#41の判定対象draftと一致しません")
    drafts = {row["asset_id"]: row for row in read(args.draft)["images"].values()}
    assets = {row["asset_id"]: row for row in manifest["assets"]}
    verdicts = {}
    sources = [args.issue41 / "manifest.json", identity_path]
    for path in sorted((args.issue41 / "judgments").glob("batch-*.json")):
        sources.append(path)
        batch = read(path)
        if batch["model"] != "gpt-6.1-sol" or batch["repeat_of"] is not None:
            raise ValueError("初回sol判定だけを使用します")
        for image in batch["images"]:
            aid = image["asset_id"]
            if aid in verdicts:
                raise ValueError("判定画像が重複しています")
            verdicts[aid] = {row["draft_id"]: row["verdict"] for row in image["regions"]}
            if len(verdicts[aid]) != len(image["regions"]):
                raise ValueError("判定draft_idが重複しています")
    args.output.mkdir(parents=True, exist_ok=True)
    masks = args.output / "masks"
    masks.mkdir(exist_ok=True)
    records, inputs = [], []
    weights = {f"stage_{i}.pt": digest(args.weights / f"stage_{i}.pt") for i in range(4)}
    for group in groups:
        for aid in group["asset_ids"]:
            draft, asset = drafts[aid], assets[aid]
            if draft["sha256"] != asset["sha256"]:
                raise ValueError("draftとmanifestの原本SHAが一致しません")
            if {shape["draft_id"] for shape in draft["shapes"]} != verdicts[aid].keys():
                raise ValueError("draftと判定の領域集合が一致しません")
            image_path = args.images / asset["filename"]
            inputs.append({"asset_id": aid, "sha256": asset["sha256"],
                           "prep_sha256": digest(image_path), "prep_run_id": asset["prep_run_id"]})
            regions, labels = [], {}
            for shape in draft["shapes"]:
                if shape["label"] not in LABELS:
                    continue
                did = shape["draft_id"]
                mask_path = masks / f"{aid}-{did.replace(':', '-')}.png"
                Image.fromarray(draft_mask(shape["mask"], draft["annotation_size"])
                                .astype(np.uint8) * 255).save(mask_path)
                regions.append({"region_id": did, "label_source": "model",
                                "size": draft["annotation_size"], "mask_path": str(mask_path)})
                labels[did] = shape["label"]
            with Image.open(image_path) as image:
                if list(image.size) != draft["annotation_size"]:
                    raise ValueError("判定時と入力画像寸法が一致しません")
                for method in shade.METHODS:
                    corrected = shade.correct(image, method, model_path=str(args.weights),
                                              weights_hash=json.dumps(weights, sort_keys=True))
                    for part in shade.observations(image, corrected, regions):
                        did = part["region_id"]
                        obs = part["observations"][0]
                        records.append({
                            "subject_id": group["subject_id"], "asset_id": aid,
                            "sha256": asset["sha256"], "draft_id": did, "label": labels[did],
                            "verdict": verdicts[aid][did], "method": method,
                            "valid_pixels": round(part["area"] * obs["material_confidence"]),
                            "material_oklab": obs["material_oklab"]["dominant"],
                        })
            print(group["subject_id"], aid, "完了", flush=True)
    samples = aggregate(records)
    save(args.output / "region-samples.json", records)
    save(args.output / "samples.json", samples)
    save(args.output / "comparison.json", compare(samples))
    save(args.output / "manifest.json", {
        "basis": "#41 gpt-6.1-sol初回判定。人手正解ではない。",
        "labels": LABELS, "groups": groups, "inputs": inputs,
        "sources_sha256": {str(p.relative_to(args.issue41)): digest(p) for p in sources},
        "draft_sha256": digest(args.draft), "weights_sha256": weights,
        "intrinsic_license_class": "academic_only", "implementation": shade._implementation(),
        "code_sha256": {"run_sol.py": digest(Path(__file__)),
                        "shade.py": digest(Path(shade.__file__))},
    })


if __name__ == "__main__":
    main()
