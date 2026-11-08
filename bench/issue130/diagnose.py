"""#121固定キャッシュの段階別診断。旧runや本番policyは変更しない。"""

import argparse
import hashlib
import zipfile
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from bench.issue73.evaluate import digest, read, truth_for, write
from bench.issue81.evaluate import text_digest
from PIL import Image

from colorstats.analyze import region_policy
from colorstats.analyze.segment import _digest

VERSION = "issue130-region-candidates-v1"
REFERENCE = "17b8ddc652a610f7132bf739c690983ed87250b9"
VARIANTS = ("baseline", "specific", "specific45", "specific55")
SPECIFIC = {"window_glass": [8], "window_frame": [8], "door": [14, 58],
            "shutter": [63], "column": [42], "roof_surface": [86, 106],
            "stairs_entry": [53, 59, 121]}
FILES = ("bench/issue130/plan.md", "bench/issue130/diagnose.py",
         "bench/issue130/gpu.py", "bench/issue73/plan.json", "bench/issue81/label-map.yaml",
         "configs/segment_stats.yaml", "src/colorstats/analyze/region_policy.py",
         "src/colorstats/analyze/segment_models.py", "src/colorstats/segmentation_evaluation.py")


def role(label):
    domain = "real_terrain/" if label in region_policy.TERRAIN else "real_building/"
    return region_policy.PARENTS.get(label, domain + label)


def policy():
    """旧契約と区別した実験版。class-infoはJSONの内容で識別する。"""
    return {"version": VERSION, "variants": list(VARIANTS), "specific": SPECIFIC,
            "thresholds": {"baseline": 0.35, "specific": 0.35,
                           "specific45": 0.45, "specific55": 0.55},
            "terrain_threshold": 0.35, "text_threshold": 0.25,
            "parents": region_policy.PARENT_TABLE, "roles": region_policy.PARENTS,
            "transform": region_policy.TRANSFORM,
            "class_info_sha256": _digest(read(Path(region_policy.__file__).with_name(
                "oneformer-classes.json"))), "conflict": "different-role-void"}


def stages(semantic, rows, labels, variant):
    """候補・親積・同親union・排他maskと、候補別の除去画素を返す。入力は変更しない。"""
    if variant not in VARIANTS:
        raise ValueError("固定候補以外は評価できません")
    # 入力契約の検査は本番実装と共通にする。
    region_policy.constrain(semantic, rows, labels)
    threshold = policy()["thresholds"][variant]
    accepted = [(label, mask, score) for label, mask, score in rows
                if score > (0.35 if label in region_policy.TERRAIN else threshold)]
    clipped = [(label, mask & np.isin(semantic, (
        SPECIFIC.get(label, region_policy.ALLOW[label]) if variant != "baseline"
        else region_policy.ALLOW[label])), score) for label, mask, score in accepted]
    merged = {key: np.zeros(semantic.shape, dtype=bool) for key in {role(x) for x in labels}}
    for label, mask, _ in clipped:
        merged[role(label)] |= mask
    overlap = np.zeros(semantic.shape, dtype=np.uint16)
    for mask in merged.values():
        overlap += mask
    conflict = overlap > 1
    effective = {key: mask & ~conflict for key, mask in merged.items()}
    names = {role(label): label for label in labels}
    result = {"raw": [(label, mask) for label, mask, _ in rows],
              "threshold": [(label, mask) for label, mask, _ in accepted],
              "parent": [(label, mask) for label, mask, _ in clipped],
              "union": [(names[key], mask) for key, mask in merged.items()],
              "effective": [(names[key], mask) for key, mask in effective.items()]}
    diagnostics = {"candidate_count": len(rows), "accepted_count": len(accepted),
                   "candidate_overlap_pixels": int((sum((mask.astype(np.uint16) for _, mask, _
                                                         in rows), np.zeros(semantic.shape,
                                                                            dtype=np.uint16))
                                                    > 1).sum()),
                   "same_parent_duplicate_pixels": sum(int(mask.sum()) for _, mask, _ in clipped)
                   - sum(int(mask.sum()) for mask in merged.values()),
                   "conflict_pixels": int(conflict.sum()),
                   "missing_roles": sum(not mask.any() for mask in effective.values())}
    removed = {"parent": [], "conflict": []}
    for (label, raw, _), (_, mask, _) in zip(accepted, clipped, strict=True):
        removed["parent"].append((label, raw & ~mask))
        removed["conflict"].append((label, mask & conflict))
    return result, removed, diagnostics


def freeze(args):
    """新予測前に入力・参照コード・semantic実byte・候補仕様を固定する。"""
    from bench.issue121 import public, quality

    plan = read(Path("bench/issue73/plan.json"))
    if len(plan["rows"]) != 1223 or plan["seed"] != 73:
        raise ValueError("#73の固定集合と一致しません")
    identities = {split: {r["sha256"] for r in plan["rows"] if r["split"] == split}
                  for split in ("tune", "holdout")}
    if identities["tune"] & identities["holdout"]:
        raise ValueError("分割間のSHA重複があります")
    for name, sha in plan["archives"].items():
        if digest(args.data / name) != sha:
            raise ValueError("公開ZIPが固定版と異なります")
    semantic_hashes = []
    for index, row in enumerate(plan["rows"]):
        public.cached_predictions(row, args.cache)
        semantic_hashes.append(digest(args.semantic / f"semantic-{index:04d}.png"))
    sources = {"public": text_digest(Path(public.__file__)),
               "quality": text_digest(Path(quality.__file__))}
    source_freeze = read(args.reference_freeze)
    for name, sha in sources.items():
        if sha != source_freeze["files"][f"bench/issue121/{name}.py"]:
            raise ValueError("#121参照読取器・指標が固定版と異なります")
    labels = read(Path("src/colorstats/analyze/oneformer-labels.json"))
    value = {"version": VERSION, "base_commit": "9698f12", "reference_commit": REFERENCE,
             "reference_sources": sources, "reference_freeze_sha256": digest(args.reference_freeze),
             "files": {name: text_digest(Path(name)) for name in FILES},
             "archives": plan["archives"], "seed": 73, "images": 1223,
             "split_counts": plan["split_counts"], "split_sha_overlap": 0,
             "gates": {"precision": 0.80, "recall": 0.30},
             "semantic_sha256": semantic_hashes,
             "policy": policy(), "policy_hash": _digest(policy()),
             "legacy_policy_hash": region_policy.policy_hash(),
             "legacy_model": source_freeze["oneformer"], "models": source_freeze["models"],
             "class_audit": [{"model_id": i, "annotation_id": i + 1, "name": labels[str(i)]}
                             for i in (0, 1, 2, 8, 12, 14, 42, 58, 63, 86, 106)],
             "production_prompts": yaml.safe_load(Path("configs/segment_stats.yaml").read_text(
                 "utf-8"))["segment"]["prompts"],
             "cached_prompts": {d: s["prompts"] for d, s in plan["source_settings"].items()},
             "before_new_predictions": True, "frozen_at": datetime.now(UTC).isoformat(),
             "quality_eligible": False}
    write(args.output, value)


def verify(spec):
    if spec["policy_hash"] != _digest(policy()):
        raise ValueError("実験版policyが固定後に変わっています")
    for name, sha in spec["files"].items():
        if text_digest(Path(name)) != sha:
            raise ValueError("固定後にコードまたは評価仕様が変わっています")
    from bench.issue121 import public, quality

    for name, module in (("public", public), ("quality", quality)):
        if text_digest(Path(module.__file__)) != spec["reference_sources"][name]:
            raise ValueError("#121参照読取器・指標が変わっています")


def run(args):
    from bench.issue121.public import cached_predictions
    from bench.issue121.quality import aggregate, measure, part_decision

    spec = read(args.freeze)
    verify(spec)
    plan = read(Path("bench/issue73/plan.json"))
    mapping = yaml.safe_load(Path("bench/issue81/label-map.yaml").read_text("utf-8"))
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, sha in spec["archives"].items():
        if digest(args.data / name) != sha:
            raise ValueError("入力ZIPが固定後に変わっています")
    totals = defaultdict(list)
    counts = defaultdict(Counter)
    prompt_totals = defaultdict(list)
    with ExitStack() as stack:
        archives = {name: stack.enter_context(zipfile.ZipFile(args.data / name))
                    for name in spec["archives"]}
        # tuneの選定を固定してからholdoutへ進む。
        for split in ("tune", "holdout"):
            for index, row in enumerate(plan["rows"]):
                if row["split"] != split:
                    continue
                dataset = row["dataset"]
                for field, sha_field in (("image", "sha256"), ("annotation", "truth_sha256")):
                    if hashlib.sha256(archives[row["archive"]].read(row[field])).hexdigest() != row[
                            sha_field]:
                        raise ValueError("固定画像・正解SHAが不一致です")
                semantic_path = args.semantic / f"semantic-{index:04d}.png"
                if digest(semantic_path) != spec["semantic_sha256"][index]:
                    raise ValueError("semantic SHAが不一致です")
                with Image.open(semantic_path) as source:
                    semantic = np.array(source)
                truth = truth_for(row, archives)
                candidates, record = cached_predictions(row, args.cache)
                if (record["settings"] != plan["source_settings"][dataset]
                        or semantic.shape != truth.shape):
                    raise ValueError("候補設定または座標が不一致です")
                groups = mapping["datasets"][dataset]["groups"]
                labels = list(record["settings"]["prompts"])
                maximum = 12 if dataset == "cmp" else 150
                for variant in VARIANTS:
                    predictions, removed, diagnostic = stages(semantic, candidates, labels, variant)
                    counts[variant, dataset, split].update(diagnostic)
                    for stage, masks in {**predictions, **{
                            "removed_" + k: v for k, v in removed.items()}}.items():
                        totals[variant, dataset, split, stage].append(
                            measure(truth, masks, groups, max_id=maximum))
                        union = np.zeros(truth.shape, dtype=bool)
                        for _, mask in masks:
                            union |= mask
                        counts[variant, dataset, split, stage].update({
                            name + "_pixels": int((union & (semantic == i)).sum())
                            for name, i in (("sky", 2), ("person", 12))})
                    for label in labels:
                        group = {key: value for key, value in groups.items()
                                 if label in value["labels"]}
                        if group:
                            prompt_totals[variant, dataset, split, label].append(measure(
                                truth, [(name, mask) for name, mask in predictions["threshold"]
                                        if name == label], group, max_id=maximum))
            if split == "tune":
                metrics = {variant: aggregate(totals[variant, "cmp", "tune", "effective"])[
                    "groups"]["wall"] for variant in VARIANTS}
                passed = [v for v in VARIANTS if part_decision({"wall": metrics[v]})[
                    "wall"]["status"] == "passed"]
                selected = max(passed or list(VARIANTS), key=lambda v: (
                    metrics[v]["iou"] if passed else 2 * metrics[v]["tp"] / max(
                        1, 2 * metrics[v]["tp"] + metrics[v]["fp"] + metrics[v]["fn"])))
                write(args.output / "selection.json", {"freeze_sha256": digest(args.freeze),
                      "selected": selected, "tune_wall": metrics, "before_holdout": True,
                      "frozen_at": datetime.now(UTC).isoformat()})
    reports = {"/".join(key): aggregate(values) for key, values in totals.items()}
    decision = {dataset: part_decision(reports[f"{selected}/{dataset}/holdout/effective"]["groups"])
                for dataset in ("cmp", "ade")}
    write(args.output / "summary.json", {"freeze_sha256": digest(args.freeze),
          "selection_sha256": digest(args.output / "selection.json"), "selected": selected,
          "reports": reports, "diagnostics": {"/".join(k): dict(v) for k, v in counts.items()},
          "prompts": {"/".join(k): aggregate(v) for k, v in prompt_totals.items()},
          "decision": decision, "quality_eligible": False, "allowed_building_parts": [],
          "unverified": ["所有画像", "本番全promptの全件GT評価", "未対応建物部位",
                         "新実験版の本番run契約"],
          "limitation": "公開既知GTの回帰比較。新たな盲検・所有画像の独立保証ではない。"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    for name in ("data", "cache", "semantic", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--reference-freeze", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        if not args.reference_freeze:
            parser.error("freezeには--reference-freezeが必要です")
        freeze(args)
    else:
        if not args.freeze:
            parser.error("runには--freezeが必要です")
        run(args)


if __name__ == "__main__":
    main()
