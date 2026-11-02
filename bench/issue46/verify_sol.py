"""公開した領域観測・判定・同定を照合し、画像やGPUなしで再集計する。"""

from pathlib import Path

from run_sol import LABELS, aggregate, digest, read, select_groups

from colorstats.analyze.shade import METHODS
from colorstats.analyze.shade_evaluation import compare

root = Path(__file__).resolve().parent
issue41 = root.parent / "issue41"
result = root / "sol"
manifest = read(result / "manifest.json")
for path, expected in manifest["sources_sha256"].items():
    assert digest(issue41 / path, text=True) == expected, path
assert select_groups(read(issue41 / "manifest.json"),
                     read(issue41 / "judgments/building-identity.json")) == manifest["groups"]
assets = {row["asset_id"]: row for row in read(issue41 / "manifest.json")["assets"]}
subjects = {aid: group["subject_id"] for group in manifest["groups"] for aid in group["asset_ids"]}
verdicts = {(image["asset_id"], row["draft_id"]): row["verdict"]
            for path in sorted((issue41 / "judgments").glob("batch-*.json"))
            for image in read(path)["images"] for row in image["regions"]}
records = read(result / "region-samples.json")
seen = set()
for row in records:
    aid, did, method = row["asset_id"], row["draft_id"], row["method"]
    assert row["subject_id"] == subjects[aid]
    assert row["sha256"] == assets[aid]["sha256"]
    assert row["verdict"] == verdicts[aid, did]
    assert row["label"] in LABELS and method in METHODS and row["valid_pixels"] > 0
    assert (aid, did, method) not in seen
    seen.add((aid, did, method))
assert {aid for aid, _, _ in seen} == subjects.keys()
assert all((aid, did, method) in seen for aid, did, _ in seen for method in METHODS)
samples = aggregate(records)
assert samples == read(result / "samples.json")
assert compare(samples) == read(result / "comparison.json")
assert compare(read(root / "samples.json")) == read(root / "comparison.json")
print("判定hash・同定群・領域選別・再集計・既存形式の照合: 成功")
