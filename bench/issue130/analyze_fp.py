"""固定確認集合の壁FPとOKLab平均色の事後分析。推論・policy変更はしない。"""

import argparse
import hashlib
import io
import zipfile
from collections import Counter, defaultdict
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from bench.issue73.evaluate import digest, read, truth_for, write
from bench.issue130.diagnose import role, stages, verify
from PIL import Image

from colorstats.colors import rgb_to_oklab

NAMES = {0: "void", 1: "background", 2: "facade", 3: "window", 4: "door",
         5: "cornice", 6: "sill", 7: "balcony", 8: "blind", 9: "deco",
         10: "molding", 11: "pillar", 12: "shop"}
PARTS = tuple(range(3, 13))
PROXIES = {"sky": [2], "vegetation": [4, 9, 17, 66, 72],
           "ground": [3, 6, 11, 13, 29, 46, 52, 91, 94]}


def boundary(truth):
    """4近傍でGT IDが異なる画素の両側。画像外枠は境界としない。"""
    edge = np.zeros(truth.shape, dtype=bool)
    vertical, horizontal = truth[1:] != truth[:-1], truth[:, 1:] != truth[:, :-1]
    edge[1:] |= vertical
    edge[:-1] |= vertical
    edge[:, 1:] |= horizontal
    edge[:, :-1] |= horizontal
    wide = edge.copy()
    wide[1:] |= edge[:-1]
    wide[:-1] |= edge[1:]
    wide[:, 1:] |= edge[:, :-1]
    wide[:, :-1] |= edge[:, 1:]
    return edge, wide


def distribution(values):
    array = np.asarray(values)
    return {"images": len(values), "mean": float(array.mean()) if array.size else None,
            "median": float(np.median(array)) if array.size else None,
            "p95": float(np.quantile(array, 0.95)) if array.size else None,
            "max": float(array.max()) if array.size else None}


def main():
    from bench.issue121.public import cached_predictions

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "cache", "semantic", "freeze", "summary", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    spec, summary = read(args.freeze), read(args.summary)
    verify(spec)
    if summary["freeze_sha256"] != digest(args.freeze):
        raise ValueError("元評価のfreeze SHAが不一致です")
    plan = read(Path("bench/issue73/plan.json"))
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    counts, sums, distances, lightness = {}, {}, defaultdict(list), defaultdict(list)
    private = []
    variants = ("baseline", summary["selected"])
    for variant in variants:
        counts[variant] = Counter()
        sums[variant] = {key: {"pixels": 0, "sum": np.zeros(3)} for key in (
            "prediction", "tp", "fp_parts", "fp_background", "gt_wall", "minus_parts",
            "minus_window_door")}
    with ExitStack() as stack:
        archives = {}
        for name, sha in spec["archives"].items():
            if digest(args.data / name) != sha:
                raise ValueError("入力ZIPのSHAが不一致です")
            archives[name] = stack.enter_context(zipfile.ZipFile(args.data / name))
        for index, row in enumerate(plan["rows"]):
            if row["dataset"] != "cmp" or row["split"] != "holdout":
                continue
            truth = truth_for(row, archives)
            raw = archives[row["archive"]].read(row["image"])
            annotation = archives[row["archive"]].read(row["annotation"])
            if (hashlib.sha256(raw).hexdigest() != row["sha256"] or hashlib.sha256(
                    annotation).hexdigest() != row["truth_sha256"]):
                raise ValueError("固定画像・GTのSHAが不一致です")
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            if (list(image.size) != row["size"] or hashlib.sha256(image.tobytes()).hexdigest()
                    != row["resized_rgb_sha256"]):
                raise ValueError("RGB色・座標の固定SHAが不一致です")
            semantic_path = args.semantic / f"semantic-{index:04d}.png"
            if digest(semantic_path) != spec["semantic_sha256"][index]:
                raise ValueError("semantic SHAが不一致です")
            semantic = np.array(Image.open(semantic_path))
            rows, record = cached_predictions(row, args.cache)
            if record["settings"] != plan["source_settings"]["cmp"]:
                raise ValueError("候補設定が不一致です")
            lab = rgb_to_oklab(np.asarray(image, dtype=np.float64) / 255)
            edge, wide = boundary(truth)
            for variant in variants:
                predictions, _, _ = stages(semantic, rows, list(record["settings"]["prompts"]),
                                           variant)
                predicted = {role(label): mask for label, mask in predictions["effective"]}[
                    "real_building/wall"]
                tp, fp = predicted & (truth == 2), predicted & (truth != 2) & (truth != 0)
                masks = {"prediction": predicted, "tp": tp,
                         "fp_parts": fp & np.isin(truth, PARTS),
                         "fp_background": fp & (truth == 1), "gt_wall": truth == 2,
                         "minus_parts": predicted & ~np.isin(truth, PARTS),
                         "minus_window_door": predicted & ~np.isin(truth, [3, 4])}
                count = counts[variant]
                count.update({"images": 1, "fp": int(fp.sum()), "tp": int(tp.sum()),
                              "predicted_on_void": int((predicted & (truth == 0)).sum()),
                              "fp_boundary1": int((fp & edge).sum()),
                              "fp_boundary2": int((fp & wide).sum()),
                              "fp_parts_interior2": int((masks["fp_parts"] & ~wide).sum())})
                count.update({f"gt_{i}_{name}": int((predicted & (truth == i)).sum())
                              for i, name in NAMES.items()})
                for name, ids in PROXIES.items():
                    count[f"background_semantic_{name}"] += int((
                        masks["fp_background"] & np.isin(semantic, ids)).sum())
                means = {}
                for name, mask in masks.items():
                    number = int(mask.sum())
                    total = lab[mask].sum(axis=0)
                    sums[variant][name]["pixels"] += number
                    sums[variant][name]["sum"] += total
                    means[name] = (total / number).tolist() if number else None
                differences = {}
                for name in ("tp", "gt_wall", "minus_parts", "minus_window_door"):
                    if means["prediction"] is not None and means[name] is not None:
                        difference = np.asarray(means["prediction"]) - means[name]
                        value = float(np.linalg.norm(difference))
                        distances[variant, name].append(value)
                        lightness[variant, name].append(float(difference[0]))
                        differences[name] = value
                private.append({"image": row["image"], "sha256": row["sha256"],
                                "variant": variant, "means": means, "delta_ok": differences})
    result = {}
    for variant in variants:
        count = counts[variant]
        histogram = [count[f"gt_{i}_{name}"] for i, name in NAMES.items()]
        if histogram != summary["reports"][f"{variant}/cmp/holdout/effective"]["groups"][
                "wall"]["truth_histogram"]:
            raise ValueError("既存評価のFP/TPヒストグラムを再現できません")
        pooled = {name: {"pixels": value["pixels"], "mean_oklab": (
            value["sum"] / value["pixels"]).tolist() if value["pixels"] else None}
                  for name, value in sums[variant].items()}
        reference = np.asarray(pooled["prediction"]["mean_oklab"])
        result[variant] = {"counts": dict(count), "fp_class_fraction": {
            name: count[f"gt_{i}_{name}"] / count["fp"] for i, name in NAMES.items() if i != 2},
            "pooled": pooled, "pooled_delta_ok": {name: float(np.linalg.norm(reference - value[
                "mean_oklab"])) for name, value in pooled.items() if value["pixels"]},
            "image_delta_ok": {name: distribution(distances[variant, name]) for name in (
                "tp", "gt_wall", "minus_parts", "minus_window_door")},
            "image_delta_L": {name: distribution(lightness[variant, name]) for name in (
                "tp", "gt_wall", "minus_parts", "minus_window_door")}}
    write(args.output / "private.json", private)
    write(args.output / "summary.json", {
        "version": "issue130-fp-color-posthoc-v1", "freeze_sha256": digest(args.freeze),
        "evaluation_summary_sha256": digest(args.summary), "code_sha256": digest(Path(__file__)),
        "variants": result, "gt_names": NAMES, "background_proxy_model_ids": PROXIES,
        "gt_histogram_matches_original": True, "new_predictions": False,
        "scope": "固定CMP確認集合282枚。方式変更・再選定・合格条件変更なし。",
        "limitations": ["CMP背景は空・植生・地面を区別しない。semantic内訳はモデルによる代理値。",
                        "GTは矩形由来で遮蔽を必ずしも除かない。真の壁材色を保証しない。",
                        "GT部位の差引きは分析用oracle。予測で実現した改善ではない。",
                        "OKLab画素平均の差。shade補正・k-meansパレット・本番統計とは異なる。",
                        "画像平均は両maskが非空の画像だけ。件数と未定義を明示する。"]})


if __name__ == "__main__":
    main()
