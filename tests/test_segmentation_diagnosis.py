import numpy as np

from colorstats.segmentation_evaluation import pixel_counts
from colorstats.segmentation_quality import group_support


def test_removed_mapping_does_not_remove_negative_pixels():
    truth = np.array([[1, 2, 0, 3]])
    predictions = [("grass", np.ones(truth.shape, dtype=bool))]
    groups = {"grass": {"ids": [2], "labels": ["grass"]}}
    assert pixel_counts(truth, predictions, groups)["grass"]["fp"] == 0
    assert pixel_counts(truth, predictions, groups, valid_ids=[1, 2, 3])["grass"] == {
        "tp": 1, "fp": 2, "fn": 0,
    }


def test_coarse_support_needs_exact_union_and_all_datasets():
    roles = {"wall": ["main", "secondary"], "opening": ["glass", "frame", "door"]}
    mapping = {"datasets": {dataset: {"groups": {
        "wall": {"labels": ["secondary", "main"]},
        "window": {"labels": ["glass", "frame"]},
    }} for dataset in ("cmp", "ade")}}
    reports = {dataset: {"wall": {"precision": 0.5, "tp": 10},
                         "window": {"precision": 0.99, "tp": 99}}
               for dataset in ("cmp", "ade")}
    result = group_support(reports, mapping, roles)
    assert result["wall"]["supported"]
    assert result["opening"]["status"] == "unmapped"
    reports["ade"]["wall"]["precision"] = 0.499999
    assert not group_support(reports, mapping, roles)["wall"]["supported"]
    reports["ade"]["wall"].update(precision=1.0, tp=0)
    assert not group_support(reports, mapping, roles)["wall"]["supported"]


def test_saved_support_and_settings_match_the_evidence():
    import hashlib
    import json
    from pathlib import Path

    import yaml

    from colorstats.segmentation_quality import GATES, label_support

    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "configs/segment_stats.yaml").read_text(encoding="utf-8"))
    decision = json.loads((root / config["evaluation"]["decision"]).read_text(encoding="utf-8"))
    mapping = yaml.safe_load((root / config["evaluation"]["mapping"]).read_text(encoding="utf-8"))
    for field in ("decision", "mapping", "definition"):
        content = (root / config["evaluation"][field]).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == config["evaluation"][field + "_sha256"]
    for name, expected in decision["code_sha256"].items():
        content = (root / name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == expected
    reports = decision["reports"]["after"]["holdout"]
    assert group_support(reports, mapping, mapping["roles"]) == decision["group_support"]
    assert label_support(reports, mapping, decision["label_support"]) == decision["label_support"]
    assert config["quality"]["supported_labels"] == decision["supported_labels"]
    assert config["quality"]["supported_groups"] == decision["supported_groups"]
    assert (config["quality"]["precision_threshold"]
            == decision["threshold"] == GATES["label_precision"])
    settings = {key: config[key] for key in ("segment", "shade")}
    encoded = json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == config["settings_sha256"]
    old = yaml.safe_load((root / "bench/issue41/label-map.yaml").read_text(encoding="utf-8"))
    for dataset, definition in mapping["datasets"].items():
        assert set(definition["valid_ids"]) == {
            index for group in old["datasets"][dataset]["groups"].values() for index in group["ids"]
        }
        for split in ("tune", "holdout"):
            for name in definition["groups"]:
                assert (decision["reports"]["before"][split][dataset][name]
                        == decision["reports"]["after"][split][dataset][name])


def test_text_evidence_hash_is_independent_of_checkout_newlines(tmp_path):
    from bench.issue81.evaluate import text_digest

    path = tmp_path / "evidence.json"
    path.write_bytes(b'{"seed":73}\n')
    expected = text_digest(path)
    path.write_bytes(b'{"seed":73}\r\n')
    assert text_digest(path) == expected
