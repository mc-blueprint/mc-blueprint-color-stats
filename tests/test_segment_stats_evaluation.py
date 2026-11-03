import json
from types import SimpleNamespace

import numpy as np
import pytest
from bench.issue73.evaluate import digest, evaluate, verify_plan
from PIL import Image

from colorstats.segmentation_quality import GATES


def test_fixed_plan_rejects_changed_mapping(tmp_path):
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("original", encoding="utf-8")
    plan = {"mapping_sha256": digest(mapping), "gates": GATES,
            "archives": {}, "code_sha256": {}}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    baseline = {"plan_sha256": digest(tmp_path / "plan.json")}
    (tmp_path / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
    args = SimpleNamespace(output=tmp_path, mapping=mapping, data=tmp_path)
    assert verify_plan(args)[0] == plan
    mapping.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="対応表"):
        verify_plan(args)


def test_cache_rejects_mask_mutation_before_scoring(tmp_path):
    directory = tmp_path / "cmp" / "sample"
    directory.mkdir(parents=True)
    record = directory / "result.json"
    record.write_text("{}", encoding="utf-8")
    mask = directory / "0000.png"
    Image.fromarray(np.ones((2, 2), dtype=np.uint8) * 255).save(mask)
    region = {"mask": mask.name, "sha256": digest(mask), "label": "door", "confidence": 0.9}
    row = {"dataset": "cmp", "image": "sample.jpg", "record_sha256": digest(record),
           "regions": [region]}
    Image.fromarray(np.zeros((2, 2), dtype=np.uint8)).save(mask)
    mapping = {"datasets": {d: {"groups": {}} for d in ("cmp", "ade")}}
    with pytest.raises(ValueError, match="予測マスク"):
        evaluate([row], SimpleNamespace(cache=tmp_path), mapping, 0.45, {})
