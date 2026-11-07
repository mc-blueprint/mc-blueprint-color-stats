"""既存cohortから固定seedでsmoke 3件をprivateへ固定する。DBは使わない。"""

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

from PIL import Image

SEED = 11820261107


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def select(cohorts, known, output, *, previous=None, seed=SEED, count=3):
    """初回3件は層別、追加はpreviousのID/SHAを除いて無作為抽出する。元入力は変更しない。"""
    flags = {row["asset_id"]: row for row in json.loads(known.read_text())}
    rows = [row for path in cohorts for row in json.loads(path.read_text())["assets"]]
    eligible = []
    for row in rows:
        flag = flags.get(row["asset_id"], {})
        if (row["prep_status"] != "succeeded" or row.get("person_mask")
                or flag.get("off_target") or flag.get("person_missed")
                or flag.get("reason", "person_not_detected") != "person_not_detected"):
            continue
        eligible.append(row)
    eligible.sort(key=lambda row: row["asset_id"])
    if len({row["asset_id"] for row in eligible}) != len(eligible):
        raise ValueError("cohortに重複があります")
    rng = random.Random(seed)
    if previous is not None:
        baseline = json.loads(previous.read_text())["assets"]
        ids = {row["asset_id"] for row in baseline}
        hashes = {row["input_sha256"] for row in baseline}
        unique = {}
        for row in eligible:
            if row["asset_id"] not in ids and row["input_sha256"] not in hashes:
                unique.setdefault(row["input_sha256"], row)
        eligible = list(unique.values())
    if previous is None and count == 3:
        selected = []
        for stratum in ("sky_building", "overlap_reported", "cohort"):
            candidates = [row for row in eligible if row not in selected and (
                stratum == "cohort" or flags.get(row["asset_id"], {}).get(stratum))]
            if not candidates:
                raise ValueError("抽出層に対象がありません")
            selected.append(rng.choice(candidates))
        protocol = "sky-known/overlap-known/cohortの層別各1件"
    else:
        selected = rng.sample(eligible, count)
        protocol = "既存cohortから追加無作為抽出（既出ID/SHAと同一SHA重複を除外）"
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for index, row in enumerate(selected, 1):
        source = Path(row["input_path"])
        if digest(source) != row["input_sha256"]:
            raise ValueError("cohortの入力SHAが一致しません")
        target = output / f"sample-{index:02d}{source.suffix}"
        shutil.copyfile(source, target)
        target.chmod(0o600)
        with Image.open(source) as image:
            size = list(image.size)
        records.append({**row, "sample_id": f"sample-{index:02d}", "file": target.name,
                        "size": size, "known": {key: bool(flags.get(row["asset_id"], {}).get(key))
                                                for key in ("sky_building", "overlap_reported")}})
    manifest = {"seed": seed, "selection": protocol,
                "eligible": len(eligible), "cohort_hashes": [digest(path) for path in cohorts],
                "known_sha256": digest(known), "assets": records}
    if previous is not None:
        manifest["previous_sha256"] = digest(previous)
    (output / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "selection.json").chmod(0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, action="append", required=True)
    parser.add_argument("--known", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    manifest = select(args.cohort, args.known, args.output, previous=args.previous,
                      seed=args.seed, count=args.count)
    print(json.dumps({"selected": len(manifest["assets"]), "eligible": manifest["eligible"],
                      "seed": manifest["seed"]}))


if __name__ == "__main__":
    main()
