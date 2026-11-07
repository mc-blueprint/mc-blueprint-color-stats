"""匿名集計だけから新しい品質decisionを作る。旧#81や本番選択は更新しない。"""

import argparse
from pathlib import Path

from bench.issue73.evaluate import digest, read, write
from bench.issue121.quality import part_decision, person_decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paired", type=Path, required=True)
    parser.add_argument("--ade", type=Path, required=True)
    parser.add_argument("--owned", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--class-info", type=Path, required=True)
    parser.add_argument("--gpu", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paired, ade, owned = (read(path) for path in (args.paired, args.ade, args.owned))
    gpu = [read(path) for path in args.gpu]
    legacy = read(args.legacy)
    class_info = read(args.class_info)
    parts = {key: part_decision(value["groups"]) for key, value in paired["reports"].items()
             if key.startswith("oneformer/") and key.endswith("/holdout")}
    failed = any(row["status"] == "failed" for group in parts.values() for row in group.values())
    expected_reports = {f"{method}/{dataset}/{split}" for method in (
        "raw", "prompt_post", "oneformer") for dataset in ("cmp", "ade")
        for split in ("tune", "holdout")}
    write(args.output, {
        "version": "issue121-v1", "status": "failed" if failed else "unverified",
        "quality_eligible": False, "supported_labels": [], "supported_groups": [],
        "evidence": {str(path): digest(path) for path in (
            args.paired, args.ade, args.owned, args.legacy, args.class_info, *args.gpu)},
        "part_criteria": parts,
        "criteria": {
            "legacy81_reproduction": {"status": "passed" if paired["old81_reproduced"]
                                      else "failed", "images": paired["runtime"]["images"]},
            "three_methods_same_inputs": {"status": "passed" if
                set(paired["reports"]) == expected_reports and paired["runtime"]["images"] == 1223
                else "unverified", "reason":
                "固定plan・画像/正解/cache mask SHAを各入力で照合し、3方式を同じ正解で計数"},
            "ade_all_validation": {"status": "passed" if ade["runtime"]["images"] == 2000
                                   else "unverified", "images": ade["runtime"]["images"],
                                   "reason": "ADE学習済みsemanticの公開診断。部位保証ではない"},
            "both_gpus": {"status": "passed" if len(gpu) == 2 and all(
                row["images"] == 3 for row in gpu) and len({row["input_manifest_sha256"]
                                                          for row in gpu}) == 1 else "unverified",
                          "reason": "同じ公開3枚、各host 1 slot・batch 1の工程別計測"},
            "owned_selection": {"status": "passed" if owned["random"] == {
                "old": 50, "new": 50} and owned["known_overlap"] == 0
                and owned["sha_duplicates"] == 0 else "failed",
                                "selection_sha256": owned["selection_sha256"]},
            "owned_people": {cohort: person_decision(selected=50, reviewed=0, accepted=0,
                                                     missed=0) for cohort in ("old", "new")},
            "owned_html": {"status": "unverified", "reason":
                "原画像がubuntu-2になく、固定選択台帳のubuntu-1への転送承認待ち"},
            "gate_target_subject_people": {"status": "unverified", "reason":
                "#117完了後に固定runと目視のTP/FP/FN/TNをcohort別に計数する"},
            "legacy21_vs16": {"status": "passed" if legacy["new_outside_set_sha256"]
                == legacy["diagnostic_outside_set_sha256"] and legacy["old_outside"] == 21
                and legacy["building_details_reclassified"] == 5 else "unverified", "reason":
                "旧試験の対象外21件から接写5件を除くと16件。元診断16件とID集合SHAが完全一致。"
                "旧93.5%を新方針の精度へ継承しない"},
            "color_contamination": {"status": "unverified", "reason":
                "公開GTの誤採用画素はFPとして計数済み。所有画像での色の汚染は目視未確認"},
            "production_prompt_coverage": {"status": "unverified", "reason":
                "3方式の候補は旧公開評価のdataset別prompt集合。"
                "本番全prompt集合の候補・競合まで検証したとは扱わない"},
            "policy_hash_portability": {"status": "passed" if class_info["byte_equal"]
                                        else "unverified", "reason":
                "class-infoのJSON内容は同一だが、作業時CRLFとGit blobのLFで実byte SHAが異なる。"
                "現行policy_hashはこのbyte SHAを含むため、別環境での照合を保証しない"},
        },
        "cost": {"additional_api_usd": 0, "additional_cap_usd": 5,
                 "parent_cap_usd": 50, "parent_budget": "issue114-image-gate"},
        "downstream": {"baseline_regeneration": "blocked", "issue114_rerun": "blocked",
                       "reason": "wallは不合格、所有画像・人物は未検証。旧runへの代替禁止"},
    })


if __name__ == "__main__":
    main()
