"""個別画像情報を含まない集計・契約監査を作る。予測や候補選定は行わない。"""

import argparse
import hashlib
from pathlib import Path

import yaml
from bench.issue73.evaluate import digest, read, write
from bench.issue130.diagnose import VARIANTS

from colorstats.analyze import region_policy
from colorstats.analyze.segment import _digest


def audit(summary, old):
    """baselineの#121完全再現と、既合格地形の全候補での不変性を必須にする。"""
    for dataset in ("cmp", "ade"):
        for split in ("tune", "holdout"):
            if summary["reports"][f"baseline/{dataset}/{split}/effective"] != old["reports"][
                    f"oneformer/{dataset}/{split}"]:
                raise ValueError("#121のbaseline指標を完全再現できません")
    for variant in VARIANTS:
        for split in ("tune", "holdout"):
            for group in ("tree", "water"):
                if summary["reports"][f"{variant}/ade/{split}/effective"]["groups"][group] != (
                        summary["reports"][f"baseline/ade/{split}/effective"]["groups"][group]):
                    raise ValueError("既合格地形の指標が変わっています")
    return {"baseline_matches_issue121": True, "tree_water_all_variants_unchanged": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("summary", "old", "freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    summary, spec = read(args.summary), read(args.freeze)
    if summary["freeze_sha256"] != digest(args.freeze):
        raise ValueError("集計と固定仕様のSHAが不一致です")
    result = audit(summary, read(args.old))
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "summary.json", {**summary, "regression": result})
    # 個別semanticのSHA列はprivate固定台帳に残し、Gitには集合hashだけを出す。
    public_spec = {key: value for key, value in spec.items() if key != "semantic_sha256"}
    public_spec.update(freeze_sha256=digest(args.freeze),
                       semantic_manifest_sha256=_digest(spec["semantic_sha256"]))
    class_info = Path(region_policy.__file__).with_name("oneformer-classes.json")
    raw = class_info.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    public_spec["class_info_provenance"] = {
        "runtime_byte_sha256": hashlib.sha256(raw).hexdigest(),
        "lf_byte_sha256": hashlib.sha256(lf).hexdigest(),
        "crlf_byte_sha256": hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest(),
        "experimental_json_sha256": _digest(read(class_info)),
        "legacy_contract_changed": False, "production_portability": "unverified"}
    write(args.output / "freeze.json", public_spec)
    known = set().union(*(set(prompts) for prompts in spec["cached_prompts"].values()))
    production = set(spec["production_prompts"])
    mapping = yaml.safe_load(Path("bench/issue81/label-map.yaml").read_text("utf-8"))
    parts = {}
    for label in sorted(production - region_policy.TERRAIN):
        matches = [(dataset, group, rule) for dataset, config in mapping["datasets"].items()
                   for group, rule in config["groups"].items() if label in rule["labels"]]
        if not matches:
            parts[label] = {"status": "unverified", "supported": False, "reason": "部位GT対応なし"}
        else:
            dataset, group, rule = matches[0]
            grouped = len(rule["labels"]) > 1
            parts[label] = {"status": "unverified" if grouped else summary["decision"][dataset][
                group]["status"], "supported": False, "group": f"{dataset}/{group}",
                "reason": "群の評価のみ・個別未検証" if grouped else "公開GTの群と同じ範囲。"
                "本番同一run契約は未検証"}
    write(args.output / "decision.json", {
        "version": "issue130-quality-v1", "freeze_sha256": digest(args.freeze),
        "summary_sha256": digest(args.output / "summary.json"), "selected": summary["selected"],
        "gates": spec["gates"], "public_gt": summary["decision"], "building_parts": parts,
        "regression": result,
        "supported_labels": [], "supported_groups": [], "allowed_building_parts": [],
        "quality_eligible": False, "production_contract": "unverified",
        "production_prompt_difference": {
            "production_only": sorted(production - known),
            "cached_only": sorted(known - production),
            "dataset_missing_production_labels": {dataset: sorted(production - set(prompts))
                                                   for dataset, prompts in spec[
                                                       "cached_prompts"].items()}},
        "unverified": summary["unverified"],
        "downstream": "#129/#118/#119/#120の同一run契約が揃うまで建物を追加しない。"
        "既合格tree親群/waterの先行を妨げない。",
        "limitation": summary["limitation"]})


if __name__ == "__main__":
    main()
