import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from colorstats.segmentation_evaluation import pixel_counts, scores, select_ade

MAPPING = yaml.safe_load(Path("bench/issue41/label-map.yaml").read_text(encoding="utf-8"))


def test_merging_overlap_and_ignored_pixels():
    groups = MAPPING["datasets"]["cmp"]["groups"]
    truth = np.array([[3, 3, 2], [4, 1, 6]])
    glass = np.array([[1, 0, 1], [0, 1, 0]], dtype=bool)
    frame = np.array([[1, 1, 0], [0, 0, 1]], dtype=bool)
    counts = pixel_counts(truth, [
        ("window_glass", glass), ("window_frame", frame), ("door", glass),
    ], groups)
    assert counts["window"] == {"tp": 2, "fp": 1, "fn": 0}
    assert counts["door"] == {"tp": 0, "fp": 2, "fn": 1}
    assert counts["wall"] == {"tp": 0, "fp": 0, "fn": 1}
    assert scores(counts["window"])["iou"] == pytest.approx(2 / 3)
    assert scores(counts["window"])["precision"] == pytest.approx(2 / 3)
    assert scores(counts["window"])["recall"] == 1
    assert scores({"tp": 0, "fp": 0, "fn": 0})["iou"] is None


def test_mapping_taxonomy_and_unique_ground_truth():
    parts = yaml.safe_load(Path("taxonomy/parts.yaml").read_text(encoding="utf-8"))
    terrain = yaml.safe_load(Path("taxonomy/terrain.yaml").read_text(encoding="utf-8"))
    vocabulary = {label for labels in parts["groups"].values() for label in labels}
    vocabulary.update(terrain["labels"])
    for dataset in MAPPING["datasets"].values():
        ids = []
        labels = []
        for group in dataset["groups"].values():
            ids.extend(group["ids"])
            labels.extend(group["labels"])
        assert len(ids) == len(set(ids))
        assert len(labels) == len(set(labels))
        assert set(labels) <= vocabulary


def test_mapping_matches_downloaded_class_definitions():
    for dataset, definitions in MAPPING["datasets"].items():
        manifest = json.loads(Path(f"bench/issue41/{dataset}-dataset-manifest.json").read_text(
            encoding="utf-8"))
        names = manifest["observed_class_names" if dataset == "cmp" else "class_names"]
        for group in definitions["groups"].values():
            for index, source in zip(group["ids"], group["source"], strict=True):
                assert source in names[str(index)].strip().split(", ")


def test_ade_outdoor_selection():
    rule = MAPPING["ade_selection"]
    assert select_ade(np.array([[3, 2], [2, 1]]), rule)
    assert select_ade(np.full((4, 4), 10), rule)
    assert not select_ade(np.array([[3, 4], [2, 1]]), rule)
    assert not select_ade(np.full((4, 4), 1), rule)
    assert not select_ade(np.array([[3, 3], [1, 1]]), rule)


def test_shape_mismatch():
    with pytest.raises(ValueError):
        pixel_counts(np.ones((2, 2)), [("door", np.ones((1, 2), dtype=bool))],
                     MAPPING["datasets"]["cmp"]["groups"])
