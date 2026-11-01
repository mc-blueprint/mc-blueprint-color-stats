import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from colorstats.block_colors import extract_block_colors


def _write(archive, name, value):
    archive.writestr(name, json.dumps(value))


@pytest.mark.parametrize(
    ("version", "texture"),
    [
        ("1.21.11", "minecraft:block/white"),
        ("26.1.2", {"sprite": "minecraft:block/white", "force_translucent": True}),
        ("26.2", {"sprite": "minecraft:block/white", "force_translucent": True}),
        ("26.3", {"sprite": "minecraft:block/white", "force_translucent": True}),
    ],
)
def test_合成jarから面別分位点を抽出する(tmp_path: Path, version, texture):
    jar = tmp_path / "synthetic.jar"
    with zipfile.ZipFile(jar, "w") as archive:
        _write(
            archive,
            "assets/minecraft/blockstates/stone_bricks.json",
            {"variants": {"": {"model": "minecraft:block/stone_bricks"}}},
        )
        _write(
            archive,
            "assets/minecraft/models/block/stone_bricks.json",
            {
                "parent": "minecraft:block/stone_bricks_parent",
            },
        )
        _write(
            archive,
            "assets/minecraft/models/block/stone_bricks_parent.json",
            {
                "textures": {"all": "#base", "base": texture},
                "elements": [
                    {
                        "from": [0, 0, 0],
                        "to": [16, 16, 16],
                        "faces": {
                            "up": {"texture": "#all"},
                            "down": {"texture": "minecraft:block/black"},
                            "north": {"texture": "minecraft:block/half"},
                        },
                    }
                ],
            },
        )
        for name, color in (
            ("white", (255, 255, 255, 255)),
            ("black", (0, 0, 0, 255)),
            ("half", (128, 128, 128, 255)),
            ("stone", (255, 0, 0, 0)),
        ):
            image = Image.new("RGBA", (2, 1), color)
            if name == "white":
                image.putpixel((1, 0), (255, 0, 0, 128))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            archive.writestr(f"assets/minecraft/textures/block/{name}.png", buffer.getvalue())

    records = extract_block_colors(jar, version)
    assert [record["face"] for record in records] == ["top", "side", "bottom"]
    assert all(record["block_id"] == "minecraft:stone_bricks" for record in records)
    assert records[0]["oklab"]["dominant"][0] == pytest.approx(1.0, abs=3e-6)
    assert records[1]["oklab"]["dominant"][0] == pytest.approx(0.599872, abs=2e-6)
    assert records[2]["oklab"]["dominant"][0] == pytest.approx(0.0)
    assert records[0]["oklab"]["quantiles"][2]["q"] == 0.5


def test_MCBlueprint非対応版を拒否する(tmp_path: Path):
    with pytest.raises(ValueError, match="非対応"):
        extract_block_colors(tmp_path / "missing.jar", "1.20")
