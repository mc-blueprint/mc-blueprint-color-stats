"""収集目標と分類体系を読み、検索要求を作る。"""

import random
from pathlib import Path

import yaml

from colorstats.collect import SearchRequest
from colorstats.schema.taxonomy import load_taxonomy


def load_targets(path: Path, taxonomy: Path = Path("taxonomy")) -> dict:
    """層の語彙・正の目標・集中枠を検証する。地域と年代は自由記述の識別子。"""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    scene = load_taxonomy(taxonomy)["scene"]
    if config["taxonomy_version"] != scene["taxonomy_version"]:
        raise ValueError("分類体系の版が一致しません")
    if not isinstance(config["image_budget"], int) or config["image_budget"] <= 0:
        raise ValueError("画像予算は正の整数です")
    limits = config["limits"]
    if not isinstance(limits["subject_images"], int) or limits["subject_images"] <= 0:
        raise ValueError("subject画像上限は正の整数です")
    for key in ("subject_share", "author_share", "source_share", "region_share"):
        if not 0 < limits[key] <= 1:
            raise ValueError("割合上限は0より大きく1以下です")
    search = config["search"]
    if search["pages"] <= 0 or search["max_offset"] < 0 or not search["providers"]:
        raise ValueError("検索ページ数・オフセット・ソースが不正です")
    identifiers, combinations = set(), set()
    for layer in config["strata"]:
        attrs = layer["attributes"]
        domain = attrs["domain"]
        if domain == "real_building":
            required = {"domain", "style", "building_type", "region", "era"}
        elif domain == "real_terrain":
            required = {"domain", "biome_like", "season", "time_of_day"}
        else:
            raise ValueError("層のdomainは実建築または実地形です")
        if set(attrs) != required or any(not value for value in attrs.values()):
            raise ValueError("層の属性が不足または過剰です")
        for key in required & scene["attributes"].keys():
            if attrs[key] not in scene["attributes"][key]:
                raise ValueError(f"分類体系にない語彙: {key}={attrs[key]}")
        combination = tuple(sorted(attrs.items()))
        if layer["id"] in identifiers or combination in combinations:
            raise ValueError("層のIDまたは属性が重複しています")
        identifiers.add(layer["id"])
        combinations.add(combination)
        if not isinstance(layer["subjects"], int) or layer["subjects"] <= 0:
            raise ValueError("目標subject数は正の整数です")
        if "images" in layer and (
            not isinstance(layer["images"], int) or layer["images"] <= 0
        ):
            raise ValueError("目標画像数は正の整数です")
        if len(layer["queries"]) < 2 or any(not terms for terms in layer["queries"].values()):
            raise ValueError("各層に複数言語の検索語が必要です")
        for _ in requests(config, layer, random.Random(0)):
            pass
    return config


def requests(config: dict, layer: dict, rng: random.Random):
    """各言語の先頭ページと、無作為に選んだ後続ページを検索する。"""
    search = config["search"]
    for provider in search["providers"]:
        for language, terms in layer["queries"].items():
            query = rng.choice(terms)
            offsets = range(search["limit"], search["max_offset"] + 1, search["limit"])
            starts = [0, *rng.sample(offsets, min(search["pages"] - 1, len(offsets)))]
            for page, offset in enumerate(starts):
                yield SearchRequest(
                    provider, query, language, page, offset, search["limit"], layer["id"]
                )
