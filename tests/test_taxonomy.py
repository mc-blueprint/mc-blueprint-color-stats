from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError

from colorstats.schema.taxonomy import load_taxonomy

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy"


def test_分類体系と固定版プリセットの全役割が対応する():
    docs = load_taxonomy(TAXONOMY)
    assert {doc["taxonomy_version"] for doc in docs.values()} == {"0.1.0"}
    assert 15 <= len(docs["scene"]["attributes"]["style"]) <= 25
    assert docs["mcblueprint"]["upstream_commit"] == ("6ece64ae40b5b2e3b23e0b566135eb0d7c8d5774")
    assert {name: set(roles) for name, roles in docs["mcblueprint"]["presets"].items()} == {
        "medieval": {"stone_wall", "foundation", "plaster", "timber", "floor", "roof_tile"},
        "japanese": {"plaster", "timber", "floor", "foundation", "gravel_garden"},
        "modern": {"concrete", "dark_concrete", "floor", "deck", "foundation"},
    }


def test_YAMLの重複キーによる分類の上書きを拒否する(tmp_path):
    for path in TAXONOMY.iterdir():
        if path.suffix in {".json", ".yaml"}:
            (tmp_path / path.name).write_bytes(path.read_bytes())
    with (tmp_path / "parts.yaml").open("a", encoding="utf-8") as file:
        file.write("\ngroups:\n  wall: [wall_main]\n")
    with pytest.raises(ValueError, match="キーが重複"):
        load_taxonomy(tmp_path)


@pytest.mark.parametrize(
    "case,error,match",
    [
        ("multiple_parents", ValueError, "親子関係"),
        ("parent_as_child", ValueError, "親子関係"),
        ("terrain_collision", ValueError, "部位と地形"),
        ("missing_target", ValueError, "対応先"),
        ("missing_style", ValueError, "style"),
        ("version_mismatch", ValueError, "taxonomy_version"),
        ("invalid_version", ValidationError, None),
        ("duplicate_child", ValidationError, None),
        ("unknown_field", ValidationError, None),
        ("missing_document", ValueError, "4種類"),
        ("duplicate_kind", ValueError, "kindが重複"),
    ],
)
def test_構造と文書間参照の破損を拒否する(tmp_path, case, error, match):
    docs = deepcopy(load_taxonomy(TAXONOMY))
    if case == "multiple_parents":
        docs["parts"]["groups"]["wall"].append("plinth")
    elif case == "parent_as_child":
        docs["parts"]["groups"]["wall"].append("foundation")
    elif case == "terrain_collision":
        docs["terrain"]["labels"].append("plinth")
    elif case == "missing_target":
        docs["mcblueprint"]["presets"]["modern"]["deck"] = ["absent"]
    elif case == "missing_style":
        docs["scene"]["attributes"]["style"].remove("modern")
    elif case == "version_mismatch":
        docs["parts"]["taxonomy_version"] = "0.2.0"
    elif case == "invalid_version":
        docs["parts"]["taxonomy_version"] = "v1"
    elif case == "duplicate_child":
        docs["parts"]["groups"]["wall"].append("wall_main")
    elif case == "unknown_field":
        docs["parts"]["unexpected"] = []
    elif case == "missing_document":
        del docs["parts"]
    elif case == "duplicate_kind":
        docs["extra"] = docs["parts"]
    (tmp_path / "schema.json").write_bytes((TAXONOMY / "schema.json").read_bytes())
    for name, document in docs.items():
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(error, match=match):
        load_taxonomy(tmp_path)
