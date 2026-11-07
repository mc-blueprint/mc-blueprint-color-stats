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


def select(cohorts, known, output):
    """空混入既知例・重複既知例・残りcohortを各1件抽出する。母集団推定には使わない。"""
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
    rng = random.Random(SEED)
    selected = []
    for stratum in ("sky_building", "overlap_reported", "cohort"):
        candidates = [row for row in eligible if row not in selected and (
            stratum == "cohort" or flags.get(row["asset_id"], {}).get(stratum))]
        if not candidates:
            raise ValueError("抽出層に対象がありません")
        selected.append(rng.choice(candidates))
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
    manifest = {"seed": SEED, "selection": "sky-known/overlap-known/cohortの層別各1件",
                "eligible": len(eligible), "cohort_hashes": [digest(path) for path in cohorts],
                "known_sha256": digest(known), "assets": records}
    (output / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "selection.json").chmod(0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, action="append", required=True)
    parser.add_argument("--known", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = select(args.cohort, args.known, args.output)
    print(json.dumps({"selected": len(manifest["assets"]), "eligible": manifest["eligible"],
                      "seed": manifest["seed"]}))


if __name__ == "__main__":
    main()
