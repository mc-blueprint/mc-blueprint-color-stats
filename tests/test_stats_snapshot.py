import copy
import json
from pathlib import Path

import duckdb
import pytest

from colorstats.stats.licenses import exclusion_reasons
from colorstats.stats.snapshot import TABLES, canonical, digest, verify


@pytest.fixture
def rights():
    asset = {"license_class": "open", "quality": {
        "license": "cc-by-4.0", "author": "作者", "license_url": "https://license.test/by",
    }}
    source = {"license": "cc-by-4.0", "license_class": "open",
              "url": "https://example.test/source", "author": "作者", "attribution": "作者・出典"}
    return asset, source, [{"license_class": "open", "parameters": {}}]


@pytest.mark.parametrize("license_name", ["cc-by-sa-4.0", "cc-by-nc-4.0", "cc-by-nd-4.0"])
def test_selected_license_cannot_be_replaced_by_categories(rights, license_name):
    asset, source, runs = rights
    asset["quality"]["license"] = source["license"] = license_name
    asset["quality"]["metadata"] = {"categories": ["CC0"]}
    assert "license_conditions" in exclusion_reasons(asset, source, runs)


@pytest.mark.parametrize("license_name", ["pd", "pdm", "cc0", "cc-by-4.0"])
def test_attribution_is_retained_for_allowed_licenses(rights, license_name):
    asset, source, runs = rights
    asset["quality"]["license"] = source["license"] = license_name
    before = copy.deepcopy(rights)
    assert exclusion_reasons(asset, source, runs) == []
    assert before == rights


def test_missing_provenance_mismatch_and_nested_weight_restriction(rights):
    asset, source, runs = rights
    source["attribution"] = None
    assert exclusion_reasons(asset, source, runs) == ["missing_provenance"]
    source["license"] = "cc0"
    runs[0]["parameters"] = {"models": {"evaluation": {"license_class": "academic_only"}}}
    assert set(exclusion_reasons(asset, source, runs)) == {
        "license_missing_or_mismatch", "missing_provenance", "restricted_weights",
    }


@pytest.fixture
def parquet_fixture(tmp_path):
    import hashlib

    root = tmp_path / "fixture"
    root.mkdir()
    manifest = {"format_version": 1, "files": {}}
    with duckdb.connect() as db:
        for table, schema in TABLES.items():
            db.execute(f"CREATE TABLE {table} ({schema})")
        db.execute("INSERT INTO provenance VALUES (?, ?, ?)", [
            "asset-1", "source-1", canonical({"attribution": "作者・出典", "license": "CC0"}),
        ])
        for table in TABLES:
            path = root / (table + ".parquet")
            db.execute(f"COPY {table} TO ? (FORMAT PARQUET)", [str(path)])
            manifest["files"][path.name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": db.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            }
    manifest["snapshot_id"] = digest(manifest)
    (root / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
    return root, manifest["snapshot_id"]


def test_parquet_read_and_manifest_and_file_tamper(parquet_fixture):
    root, expected = parquet_fixture
    manifest = verify(root, expected)
    with duckdb.connect() as db:
        row = db.execute("SELECT data FROM read_parquet(?)",
                         [str(root / "provenance.parquet")]).fetchone()
    assert json.loads(row[0])["attribution"] == "作者・出典"
    path = root / "provenance.parquet"
    original = path.read_bytes()
    path.write_bytes(original[:-1] + b"x")
    with pytest.raises(ValueError, match="Parquet"):
        verify(root, expected)
    path.write_bytes(original)
    manifest["format_version"] = 2
    (root / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        verify(root, expected)


def test_missing_file_and_untrusted_manifest(parquet_fixture):
    root, expected = parquet_fixture
    with pytest.raises(ValueError, match="manifest"):
        verify(root, "0" * 64)
    Path(root / "runs.parquet").unlink()
    with pytest.raises(FileNotFoundError):
        verify(root, expected)

def test_quality_artifacts_are_fixed_and_crlf_independent(tmp_path):
    from colorstats.stats.snapshot_cli import load_quality

    root = Path(__file__).resolve().parents[1]
    quality = load_quality(root / "configs/segment_stats.yaml")
    assert quality["group_members"]["real_building/wall"] == [
        "wall_main", "wall_secondary", "gable_wall",
    ]
    import yaml

    config = yaml.safe_load((root / "configs/segment_stats.yaml").read_text(encoding="utf-8"))
    copied = tmp_path / "configs/segment_stats.yaml"
    copied.parent.mkdir()
    copied.write_text(yaml.safe_dump(config), encoding="utf-8")
    for key in ("plan", "decision", "mapping", "definition"):
        source = root / config["evaluation"][key]
        target = tmp_path / config["evaluation"][key]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_text(encoding="utf-8").replace("\n", "\r\n").encode())
    assert load_quality(copied) == quality
    target.write_text("改変", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_quality(copied)
