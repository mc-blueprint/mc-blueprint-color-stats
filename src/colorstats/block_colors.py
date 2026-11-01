"""バニラjarからブロック面ごとのOKLab分布を抽出する。"""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from mcblueprint.blockdata import load_block_data, supported_versions
from PIL import Image
from sqlalchemy.orm import Session

from colorstats.colors import QUANTILES, rgb_to_oklab
from colorstats.schema.models import BlockColor

FACES = ("top", "side", "bottom")


def _resource(value: str, directory: str) -> str:
    if ":" in value:
        namespace, path = value.split(":", 1)
    else:
        namespace, path = "minecraft", value
    return f"assets/{namespace}/{directory}/{path}"


def _model(archive: zipfile.ZipFile, model_id: str, cache: dict) -> dict:
    if model_id in cache:
        return cache[model_id]
    name = _resource(model_id, "models") + ".json"
    model = json.loads(archive.read(name))
    parent = model.pop("parent", None)
    if parent:
        inherited = _model(archive, parent, cache)
        model = {
            **inherited,
            **model,
            "textures": inherited.get("textures", {}) | model.get("textures", {}),
            "elements": model.get("elements", inherited.get("elements", [])),
        }
    cache[model_id] = model
    return model


def _state_models(state: dict, default: dict[str, str]) -> list[str]:
    selected = []
    for key, value in state.get("variants", {}).items():
        requirements = dict(part.split("=", 1) for part in key.split(",") if part)
        if all(default.get(name) == expected for name, expected in requirements.items()):
            choices = value if isinstance(value, list) else [value]
            selected.extend(choice["model"] for choice in choices)
    if selected:
        return selected
    for part in state.get("multipart", []):
        apply = part["apply"]
        choices = apply if isinstance(apply, list) else [apply]
        selected.extend(choice["model"] for choice in choices)
    return selected


def _face_for(direction: str, face: dict) -> str:
    cull = face.get("cullface", direction)
    if cull == "up":
        return "top"
    if cull == "down":
        return "bottom"
    return "side"


def _pixels(image: Image.Image) -> np.ndarray:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float64) / 255
    rgb = rgba[rgba[:, :, 3] == 1.0, :3]
    if not len(rgb):
        return np.empty((0, 3), dtype=np.float64)
    return rgb_to_oklab(rgb)


def _distribution(pixels: np.ndarray) -> dict:
    median = np.median(pixels, axis=0)
    return {
        "dominant": median.tolist(),
        "quantiles": [
            {"q": q, "value": np.quantile(pixels, q, axis=0).tolist()} for q in QUANTILES
        ],
    }


def extract_block_colors(jar: Path, version: str) -> list[dict]:
    """対応版のjarからブロックID・面・OKLab分布・材質タグを返す。

    分布のdominantはチャンネル別中央値、quantilesはQUANTILESの分位点。
    不透明画素や参照画像のない面は返さず、材質タグは空配列とする。
    非対応版はValueError、jarの読込み失敗は元の例外を送出する。
    """
    if version not in supported_versions():
        raise ValueError(f"MCBlueprint非対応のMinecraft版: {version}")
    blocks = load_block_data(version)
    with zipfile.ZipFile(jar) as archive:
        names = set(archive.namelist())
        model_cache = {}
        records = []
        state_names = sorted(
            name
            for name in names
            if name.startswith("assets/minecraft/blockstates/") and name.endswith(".json")
        )
        for state_name in state_names:
            block_id = "minecraft:" + Path(state_name).stem
            info = blocks.get(block_id)
            if info is None:
                continue
            state = json.loads(archive.read(state_name))
            by_face = defaultdict(list)
            for model_id in _state_models(state, info.default):
                model = _model(archive, model_id, model_cache)
                textures = {
                    key: value["sprite"] if isinstance(value, dict) else value
                    for key, value in model.get("textures", {}).items()
                }
                for element in model.get("elements", []):
                    for direction, face_data in element.get("faces", {}).items():
                        texture = face_data["texture"]
                        seen = set()
                        while texture.startswith("#"):
                            key = texture[1:]
                            if key in seen or key not in textures:
                                break
                            seen.add(key)
                            texture = textures[key]
                        if texture.startswith("#"):
                            continue
                        texture_name = _resource(texture, "textures") + ".png"
                        if texture_name not in names:
                            continue
                        with archive.open(texture_name) as texture_file:
                            with Image.open(texture_file) as image:
                                pixels = _pixels(image)
                        if len(pixels):
                            by_face[_face_for(direction, face_data)].append(pixels)
            for face in FACES:
                if by_face[face]:
                    records.append({
                        "minecraft_version": version,
                        "block_id": block_id,
                        "face": face,
                        "oklab": _distribution(np.concatenate(by_face[face])),
                        "material_tags": [],
                    })
    return records


def write_block_colors(records: list[dict], output: Path) -> None:
    """抽出結果をJSONへ保存する。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def register_block_colors(session: Session, records: list[dict], processing_run_id) -> None:
    """抽出結果をblock_colorへ登録する。呼び出し側がトランザクションを管理する。"""
    session.add_all(
        BlockColor(processing_run_id=processing_run_id, **record) for record in records
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="バニラjarからブロック面色を抽出")
    parser.add_argument("jar", type=Path)
    parser.add_argument("version", choices=supported_versions())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = extract_block_colors(args.jar, args.version)
    output = args.output or Path("data/block-colors") / f"{args.version}.json"
    write_block_colors(records, output)
    print(f"{args.version}: {len(records)}面を{output}へ保存")


if __name__ == "__main__":
    main()
