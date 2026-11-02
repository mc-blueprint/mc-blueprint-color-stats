"""M2評価の保存形式と、GPUを使わない再生成経路を確認する。"""

import copy
import csv
import hashlib
import io
import json
import runpy
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from colorstats.judgment_inputs import summarize_judgments

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = runpy.run_path(ROOT / "bench/issue41/run_public.py")
SUMMARY = runpy.run_path(ROOT / "bench/issue41/summarize.py")
SOL = runpy.run_path(ROOT / "bench/issue46/run_sol.py")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value, newline="\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline=newline)


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_sol_sources_and_saved_aggregates(tmp_path, newline):
    manifest = read(ROOT / "bench/issue46/sol/manifest.json")
    for name, expected in manifest["sources_sha256"].items():
        content = (ROOT / "bench/issue41" / name).read_bytes().replace(b"\r\n", b"\n")
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.replace(b"\n", newline))
        assert SOL["digest"](path, text=True) == expected
        path.write_bytes(path.read_bytes() + b" ")
        assert SOL["digest"](path, text=True) != expected
    binary = tmp_path / "weights.pt"
    binary.write_bytes(b"\x00\r\n\xff")
    assert SOL["digest"](binary) == hashlib.sha256(binary.read_bytes()).hexdigest()
    samples = SOL["aggregate"](read(ROOT / "bench/issue46/sol/region-samples.json"))
    assert samples == read(ROOT / "bench/issue46/sol/samples.json")
    assert SOL["compare"](samples) == read(ROOT / "bench/issue46/sol/comparison.json")


def test_saved_identity_regenerates_from_first_judgments():
    root = ROOT / "bench/issue41"
    expected = read(root / "judgments/building-identity.json")
    judgments, executions = {}, []
    for path in sorted((root / "judgments").glob("batch-*.json")):
        batch = read(path)
        judgments.update({image["asset_id"]: image for image in batch["images"]})
        executions.append({key: batch[key] for key in
                           ("batch_id", "model", "execution_id", "repeat_of")})
    # 同定には領域ラベルを使わない。候補の根拠は保存済み同定記録から復元する。
    selection = expected["assets"]
    assets = {row["asset_id"]: row for row in read(root / "manifest.json")["assets"]}
    selection = {aid: {**row, "domain": assets[aid]["domain"],
                      "stratum": assets[aid]["stratum"]} for aid, row in selection.items()}
    inputs = {aid: {"regions": [{**region, "label": "wall_main"}
                               for region in image["regions"]]}
              for aid, image in judgments.items()}
    repeated = {image["asset_id"]: image
                for image in read(root / "judgments/repeat.json")["images"]}
    summary, identity = summarize_judgments(inputs, judgments, repeated, selection)
    identity["executions"] = executions
    identity["sources_sha256"] = expected["sources_sha256"]
    assert identity == expected
    saved = read(root / "judgment-summary.json")
    for key in ("images", "overall", "domains", "missed_major_parts", "repeat", "identity"):
        assert summary[key] == saved[key]
    for path in sorted((root / "judgments").glob("batch-*.json")):
        source = f"data/issue41/judge/{path.stem}/judgment.json"
        assert hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == (
            expected["sources_sha256"][source])


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_summary_writes_identity_and_normalized_sources(tmp_path, newline):
    root = tmp_path / "bench/issue41"
    data = tmp_path / "data/issue41"
    shutil.copytree(ROOT / "bench/issue41", root)
    rows = []
    for index in range(1, 11):
        aid, batch_id = f"a{index}", f"batch-{index:02d}"
        row = {"asset_id": aid, "domain": "real_building", "stratum": "test",
               "building_id": "same", "building_evidence": "候補根拠",
               "title": "名称", "source_url": "url"}
        rows.append(row)
        image = {"asset_id": aid, "regions": [{"draft_id": "0:0", "label": "wall_main"}],
                 **{key: row[key] for key in
                    ("building_id", "building_evidence", "title", "source_url")}}
        save(data / f"judge/{batch_id}/input.json",
             {"batch_id": batch_id, "images": [image]}, newline)
        result = {"batch_id": batch_id, "model": "gpt-6.1-sol", "execution_id": batch_id,
                  "repeat_of": None, "images": [{"asset_id": aid,
                  "regions": [{"draft_id": "0:0", "verdict": "correct", "evidence": "壁"}],
                  "building_name": "名称", "evidence": ["根拠"], "missed_major_parts": []}]}
        save(root / f"judgments/{batch_id}.json", result, newline)
        if index == 1:
            save(data / "judge/repeat/input.json", {"batch_id": "repeat", "images": [image]},
                 newline)
            repeat = copy.deepcopy(result)
            repeat.update(batch_id="repeat", execution_id="repeat-run", repeat_of=batch_id)
            save(root / "judgments/repeat.json", repeat, newline)
    save(data / "judge/repeat-plan.json", {"images": ["a1"]}, newline)
    selection = data / "gold100/selection.csv"
    selection.parent.mkdir(parents=True)
    with selection.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator=newline)
        writer.writeheader()
        writer.writerows(rows)
    summary = SUMMARY["summarize_results"](root)
    identity = read(root / "judgments/building-identity.json")
    assert len(identity["assets"]) == 10
    assert identity["assets"]["a1"]["comparison"] == "match"
    assert identity["executions"] == summary["executions"][:-1]
    for name, expected in summary["sources_sha256"].items():
        assert expected == hashlib.sha256(
            (tmp_path / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert identity["sources_sha256"]["data/issue41/judge/batch-01/judgment.json"] == (
        summary["sources_sha256"]["bench/issue41/judgments/batch-01.json"])


def test_public_report_resumes_and_connects_to_summary(tmp_path, monkeypatch):
    root = tmp_path / "bench/issue41"
    shutil.copytree(ROOT / "bench/issue41", root)
    document = tmp_path / "docs/evaluation.md"
    document.parent.mkdir()
    document.write_text("# 評価\n", encoding="utf-8")
    output = tmp_path / "public"
    mapping = root / "label-map.yaml"
    mapping.write_bytes(mapping.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    annotation = io.BytesIO()
    Image.fromarray(np.full((2, 2), 5, dtype=np.uint8)).save(annotation, format="PNG")
    sky = io.BytesIO()
    Image.fromarray(np.full((2, 2), 3, dtype=np.uint8)).save(sky, format="PNG")
    excluded = io.BytesIO()
    Image.fromarray(np.zeros((2, 2), dtype=np.uint8)).save(excluded, format="PNG")
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="JPEG")
    archive_path = tmp_path / "ADEChallengeData2016.zip"
    manifest = read(root / "ade-dataset-manifest.json")
    info = "Idx\tName\n" + "\n".join(f"{key}\t{name}"
                                          for key, name in manifest["class_names"].items())
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("objectInfo150.txt", info)
        for index in range(2000):
            name = f"ADEChallengeData2016/images/validation/{index:04d}.jpg"
            archive.writestr(name, image.getvalue())
            archive.writestr(name.replace("/images/", "/annotations/").replace(".jpg", ".png"),
                             annotation.getvalue() if index == 0 else
                             sky.getvalue() if index == 1 else excluded.getvalue())
    public = PUBLIC["main"].__globals__
    monkeypatch.setitem(public, "select_ade", lambda truth, rule: bool(truth.any()))
    monkeypatch.setattr(public["subprocess"], "check_output", lambda *args, **kwargs: "")
    calls = []

    def predict(*args):
        calls.append(True)
        return [("vegetation_tree_canopy", np.ones((2, 2), dtype=bool), 1.0)], {}

    monkeypatch.setitem(public, "predict", predict)
    monkeypatch.setattr(sys, "argv", ["run_public.py", "--data", str(tmp_path), "--output",
                                     str(output), "--mapping", str(mapping), "--models",
                                     str(tmp_path / "models"), "--dataset", "ade"])
    PUBLIC["main"]()
    first = read(output / "report.json")
    assert first["coverage"] == {"valid_pixels": 4, "total_pixels": 8,
                                 "zero_valid_images": [
                                     "ADEChallengeData2016/images/validation/0001.jpg"],
                                 "predicted_regions": 2}
    assert len(calls) == 2
    # 再開時もチェックポイントを一度ずつ集計する。
    PUBLIC["main"]()
    report = read(output / "report.json")
    assert len(calls) == 2
    assert report == first
    shutil.copyfile(output / "report.json", root / "ade-report.json")
    shutil.copyfile(output / "dataset-manifest.json", root / "ade-dataset-manifest.json")
    summary = SUMMARY["main"].__globals__
    monkeypatch.setitem(summary, "__file__", str(root / "summarize.py"))
    monkeypatch.setitem(summary, "summarize_results",
                        lambda path: read(path / "judgment-summary.json"))
    SUMMARY["main"]()
    assert "4/8画素" in (root / "results.md").read_text(encoding="utf-8")
    assert "[保存版](../bench/issue41/judgments/building-identity.json)" in document.read_text(
        encoding="utf-8")
    assert "[保存版](judgments/building-identity.json)" in (root / "results.md").read_text(
        encoding="utf-8")
