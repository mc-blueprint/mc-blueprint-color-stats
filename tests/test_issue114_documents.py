import re
from pathlib import Path


def test_公開診断は番号別所見や個別画像表を含まない():
    document = (Path(__file__).resolve().parents[1]
                / "bench/issue114/review-diagnosis.md").read_text(encoding="utf-8")
    assert not re.search(r"\d+番|\|\s*番号\s*\||旧T\d", document)
    assert not re.search(r"(?:指摘の|候補)1枚|同一画像内", document)
    assert "138枚" in document and "16.0%" in document


def test_公開ベンチ文書と集計JSONへ画像単位の番号対応を含めない():
    import json

    root = Path(__file__).resolve().parents[1] / "bench/issue114"
    for path in root.rglob("*.md"):
        assert not re.search(r"\d+番|\|\s*番号\s*\||旧T\d", path.read_text(encoding="utf-8")), path

    def check(value):
        if isinstance(value, dict):
            assert "asset_id" not in value
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    for path in root.rglob("*.json"):
        check(json.loads(path.read_text(encoding="utf-8")))
