"""リポジトリの分類定義を読み取り、構造と参照の整合性を検証する。"""

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise ValueError("YAMLのキーが重複しています")
        return mapping


def load_taxonomy(directory: Path) -> dict[str, dict]:
    """YAMLをkindで引ける辞書として返す。

    directoryにはschema.jsonと4種類のYAMLが必要。構造違反は
    jsonschema.ValidationError、文書間の不整合はValueErrorを送出する。
    """
    schema = json.loads((directory / "schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    documents = {}
    for path in sorted(directory.glob("*.yaml")):
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
        validator.validate(document)
        kind = document["kind"]
        if kind in documents:
            raise ValueError(f"kindが重複しています: {kind}")
        documents[kind] = document
    if set(documents) != {"parts", "terrain", "scene", "mcblueprint"}:
        raise ValueError("分類定義はparts・terrain・scene・mcblueprintの4種類が必要です")
    if len({doc["taxonomy_version"] for doc in documents.values()}) != 1:
        raise ValueError("taxonomy_versionが一致しません")
    groups = documents["parts"]["groups"]
    children = [label for labels in groups.values() for label in labels]
    terrain = documents["terrain"]["labels"]
    if len(set(children)) != len(children) or set(groups) & set(children):
        raise ValueError("部位の親子関係が重複しています")
    if (set(groups) | set(children)) & set(terrain):
        raise ValueError("部位と地形のラベルが重複しています")
    labels = set(children) | set(terrain)
    styles = documents["scene"]["attributes"]["style"]
    for preset, roles in documents["mcblueprint"]["presets"].items():
        if preset not in styles:
            raise ValueError(f"未定義のstyleです: {preset}")
        for role, targets in roles.items():
            if missing := set(targets) - labels:
                raise ValueError(f"対応先ラベルが存在しません: {preset}.{role}: {sorted(missing)}")
    return documents
