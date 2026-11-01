from mcblueprint.blockdata import supported_versions
from mcblueprint.validator import validate


def blueprint(blocks: list[str]) -> dict:
    return {
        "formatVersion": 1,
        "minecraftVersion": supported_versions()[0],
        "name": "palette check",
        "palettes": {"wall": [{"block": block, "weight": 1} for block in blocks]},
        "operations": [{"type": "fill", "from": [0, 0, 0], "to": [0, 0, 0], "palette": "wall"}],
    }


def test_配色パックの検証に使うPalette検証が固定版で動く():
    assert validate(blueprint(["minecraft:stone_bricks", "minecraft:white_terracotta"])) == []
    errors = validate(blueprint(["minecraft:stone_bricks", "minecraft:no_such_block"]))
    assert [error.path for error in errors] == ["palettes.wall[1].block"]
