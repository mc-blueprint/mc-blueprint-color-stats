import json

import pytest
import yaml
from bench.issue114 import batch1


def analysis_report(ids, pending=0):
    return {"violations": [], "unclosed_attempts": 0, "completed_assets": len(ids),
            "pending_assets": pending,
            "jobs": [{"asset_id": aid, "stage": stage, "status": "succeeded", "run_id": "run"}
                     for aid in ids for stage in ("segment", "shade", "color")]}


@pytest.mark.parametrize("assets,limit,completed", [(1040, 3, 3), (2, 3, 2), (1560, None, 1560)])
def test_smokeと全量は三段階の完了件数を照合する(assets, limit, completed):
    batch1.check_analysis(analysis_report(list(map(str, range(completed))), assets - completed),
                          assets, limit=limit)


@pytest.mark.parametrize("fault", ["failed_shade", "different_asset", "missing_jobs"])
def test_colorの件数が一致しても三段階の同一画像完了がなければ拒否する(fault):
    result = analysis_report(["a"])
    if fault == "missing_jobs":
        result.pop("jobs")
    elif fault == "failed_shade":
        result["jobs"][1]["status"] = "failed"
    else:
        result["jobs"][1]["asset_id"] = "b"
    with pytest.raises(ValueError, match="三段階"):
        batch1.check_analysis(result, 1)


def test_smokeは全量の再利用segmentがあってもshadeとcolorの同一画像を照合する():
    result = analysis_report(["a"], pending=1)
    result["jobs"].append({"asset_id": "b", "stage": "segment", "status": "succeeded",
                           "run_id": "reused"})
    batch1.check_analysis(result, 2, limit=1)


@pytest.mark.parametrize("limit", [3, None])
def test_segment成功だけでshade失敗を完了にしない(limit):
    result = {"violations": [], "unclosed_attempts": 0,
              "completed_assets": 0, "pending_assets": 1040,
              "stages": {"segment": {"status": {"succeeded": 3}},
                         "shade": {"status": {"failed": 3}}, "color": {"status": {}}}}
    with pytest.raises(ValueError, match="shade・color"):
        batch1.check_analysis(result, 1040, limit=limit)


def test_再開は同じ予算policyを照合して旧出力を保全し基準を変更しない(tmp_path, monkeypatch):
    policy = yaml.safe_load((batch1.ROOT / "configs/source_policy.yaml").read_text())
    for name in ("upload.wikimedia.org", "thumb.wikimedia.org"):
        policy["sources"]["wikimedia_commons"]["hosts"][name][
            "media_bytes_per_10_seconds"
        ] = 25000000
    (tmp_path / "source_policy.yaml").write_text(yaml.safe_dump(policy))
    contents = {"budget.json": batch1.BUDGET, "baseline-assets.json": {"old": "hash"},
                "collect-jobs.json": [], "collection.json": {"reason": "operator_stop"},
                "new-assets.json": []}
    for name, data in contents.items():
        (tmp_path / name).write_text(json.dumps(data))
    (tmp_path / "collect.stop").touch()

    def no_process(*args, **kwargs):
        raise RuntimeError("起動境界まで確認")

    monkeypatch.setattr(batch1.subprocess, "Popen", no_process)
    with pytest.raises(RuntimeError, match="起動境界まで確認"):
        batch1.collect(None, tmp_path, "test", resume=True)
    archive = next(tmp_path.glob("attempt-*"))
    assert json.loads((archive / "collection.json").read_text()) == contents["collection.json"]
    assert (archive / "collect.stop").exists()
    assert json.loads((tmp_path / "baseline-assets.json").read_text()) == {"old": "hash"}
    assert json.loads((tmp_path / "budget.json").read_text()) == batch1.BUDGET


def test_異なる予算での再開は保全前に拒否する(tmp_path):
    (tmp_path / "budget.json").write_text(json.dumps(batch1.BUDGET | {"images": 3001}))
    with pytest.raises(ValueError, match="予算が一致"):
        batch1.collect(None, tmp_path, "test", resume=True)
    assert not list(tmp_path.glob("attempt-*"))
