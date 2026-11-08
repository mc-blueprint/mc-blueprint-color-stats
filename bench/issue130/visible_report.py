"""固定した両GPUの新評価を照合し、旧decisionと別の品質判定を保存する。"""

import argparse
from pathlib import Path

from bench.issue73.evaluate import digest, read, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gpu1", "gpu2", "freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    from bench.issue121.quality import aggregate

    spec = read(args.freeze)
    plan = read(Path("bench/issue73/plan.json"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result, colors = {}, {}
    for host, path in (("ubuntu-1", args.gpu1), ("ubuntu-2", args.gpu2)):
        value = read(path)
        if (value["freeze_sha256"] != spec["freeze_sha256"]
                or value["policy_hash"] != spec["policy_hash"]
                or value["tree_water_pixel_changes"] != 0):
            raise ValueError("固定仕様または地形回帰が一致しません")
        for key, expected in plan["split_counts"].items():
            if value["reports"][key]["coverage"]["images"] != expected:
                raise ValueError("固定分割の評価件数が不一致です")
        wall = value["reports"]["cmp/holdout"]["groups"]["wall"]
        observed = wall["tp"] + wall["fn"] > 0
        passed = (wall["tp"] > 0 and (wall["precision"] or 0) >= spec["gates"]["precision"]
                  and (wall["recall"] or 0) >= spec["gates"]["recall"])
        status = "unverified" if not observed else "passed" if passed else "failed"
        if value["decisions"]["cmp"]["wall"]["status"] != status:
            raise ValueError("固定基準と計数器の判定が不一致です")
        # 画像ごとのsmoke記録はprivate原本に残し、Gitへはdataset集計だけを出す。
        public = {key: item for key, item in value.items() if key != "smoke"}
        public["source_summary_sha256"] = digest(path)
        public["production_smoke"] = {
            dataset: aggregate([row["evaluation"] for row in value["smoke"]
                                if row["dataset"] == dataset]) for dataset in ("cmp", "ade")}
        public["production_smoke_runtime"] = {
            "images": len(value["smoke"]),
            "seconds": sum(row["runtime"][key] for row in value["smoke"]
                           for key in ("oneformer_seconds", "load_seconds", "inference_seconds")),
            "peak_allocated_bytes": max(max(row["runtime"]["oneformer_peak_allocated_bytes"],
                                            row["runtime"]["peak_allocated_bytes"])
                                        for row in value["smoke"]),
            "peak_reserved_bytes": max(max(row["runtime"]["oneformer_peak_reserved_bytes"],
                                           row["runtime"]["peak_reserved_bytes"])
                                       for row in value["smoke"])}
        public_path = args.output.with_name(f"visible-v2-{host.replace('-', '')}.json")
        write(public_path, public)
        result[host] = {"status": status, "wall": wall,
                        "diagnostics": value["diagnostics"]["cmp/holdout"],
                        "coverage": value["reports"]["cmp/holdout"]["coverage"],
                        "summary_sha256": digest(public_path), "gpu": value["gpu"]}
        colors[host] = value["color"]
    statuses = {value["status"] for value in result.values()}
    overall = "failed" if "failed" in statuses else "passed" if statuses == {"passed"} else (
        "unverified")
    write(args.output, {"version": "issue130-visible-wall-quality-v2", "status": overall,
          "freeze_sha256": spec["freeze_sha256"], "policy_hash": spec["policy_hash"],
          "gates": spec["gates"], "definition": spec["definition"], "hosts": result,
          "color": colors, "tree_water_pixel_changes": 0,
          "public_gt_passed_wall": overall == "passed", "quality_eligible": False,
          "supported_labels": [], "supported_groups": [], "allowed_building_parts": [],
          "pr_relation": "Closes #130" if overall == "passed" else "Refs #130",
          "scope": "CMP holdout282枚の同じ旧regular候補と新規補助3prompt。両GPU個別判定。",
          "known_regression_images": 1223, "fresh_auxiliary_images_per_gpu": 606,
          "full_production_prompt_smoke_per_gpu": 6, "independent_blind_confirmation": False,
          "unverified": ["独立した所有画像GT", "本番全29promptの全件品質", "本番統計への採用"],
          "next": "削り過ぎと残る部位FPを分け、部位候補自体のmask精度と採否を次版で検証する。"
          "現行の閾値や正解を結果に合わせて変更せず、建物統計の見送りを維持する。"})


if __name__ == "__main__":
    main()
