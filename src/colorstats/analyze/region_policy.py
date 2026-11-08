"""region-policy-v1の排他領域と、不変artifact参照。"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

from colorstats.analyze.segment import _digest, _hash
from colorstats.store import temporary_path

METHOD = "oneformer-region-v1"
VERSION = "region-policy-v1"
OOM_REASON = "region-policy-v1 GPU_OOM"
REPOSITORY = "shi-labs/oneformer_ade20k_swin_large"
REVISION = "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2"
MODEL_FILES = json.loads(Path(__file__).with_name("oneformer-files.json").read_text("utf-8"))
TRANSFORM = {"shortest_edge": 640, "longest_edge": 2560, "batch_size": 1,
             "restore": "semantic-logits-bilinear-align_corners_false-argmax",
             "orientation": "prep-pixels-exif-1", "pad": "bottom-right-batch-1",
             "processor": "fixed-json-local-class-info-CLIPTokenizer",
             "position_embedding_cache": "disabled"}

PARENT_TABLE = json.loads(Path(__file__).with_name("region-parents-v2.json").read_text("utf-8"))
ALLOW = PARENT_TABLE["allow"]
PARENTS = {**dict.fromkeys(("wall_main", "wall_secondary", "gable_wall"), "real_building/wall"),
           **dict.fromkeys(("vegetation_tree_canopy", "tree_trunk"), "real_terrain/tree")}
TERRAIN = {"ground_soil", "ground_grass", "rock_face", "rock_scree", "sand", "snow_ice",
           "water", "vegetation_low", "vegetation_tree_canopy", "tree_trunk", "path_natural"}


def policy_hash():
    """許容クラス・親役割・座標復元の固定仕様のSHA-256。"""
    return _digest({"version": VERSION, "parent_table": parent_table_reference(),
                    "parents": PARENTS,
                    "terrain": sorted(TERRAIN), "transform": TRANSFORM,
                    "class_info_sha256": _hash(Path(__file__).with_name("oneformer-classes.json")),
                    "versions": {"transformers": "4.57.6", "torch": "2.11.0"}})


def parent_table_reference():
    """粗いsemantic親と部位候補の対応表を版とSHAで識別する。"""
    return {"version": PARENT_TABLE["version"], "sha256": _digest(PARENT_TABLE)}


def validate_labels(id2label):
    """モデルIDは0始まり。ADE注釈ID（1始まり）の表や別checkpointを拒否する。"""
    expected = json.loads(Path(__file__).with_name("oneformer-labels.json").read_text("utf-8"))
    if id2label != expected:
        raise ValueError("OneFormerのid2labelが固定モデルIDと一致しません（ADE注釈IDは不可）")
    return _digest(id2label)


def model_configuration(path):
    """取得済みローカルモデルと取得証跡を照合する。通信・重み取得は行わない。"""
    root = Path(path)
    provenance = json.loads((root / "provenance.json").read_text("utf-8"))
    files = {str(p.relative_to(root)): _hash(p) for p in sorted(root.rglob("*"))
             if p.is_file() and p.name != "provenance.json"}
    if (provenance["repository"] != REPOSITORY or provenance["revision"] != REVISION
            or provenance["license"] != "MIT" or provenance["files"] != files
            or files != MODEL_FILES):
        raise ValueError("OneFormerのrevision・全ファイルSHA・MIT証跡が一致しません")
    config = json.loads((root / "config.json").read_text("utf-8"))
    processor = json.loads((root / "preprocessor_config.json").read_text("utf-8"))
    labels_hash = validate_labels(config["id2label"])
    if {str(i): processor["metadata"][str(i)] for i in range(150)} != config["id2label"]:
        raise ValueError("processorとモデルのクラス対応が一致しません")
    return {"repository": REPOSITORY, "revision": REVISION, "files": files,
            "license_class": "open", "id2label_hash": labels_hash}


def constrain(class_map, rows, labels):
    """同寸の整数semantic mapと(label,bool mask,score)から排他role maskと診断を返す。

    scoreは競合解消に用いない。同親は和集合、異なるroleの残存交差は全てvoid。
    入力は変更しない。sky/person/対象外を含む全面欠測も成功として診断を返す。
    """
    if (class_map.ndim != 2 or not np.issubdtype(class_map.dtype, np.integer)
            or np.any((class_map < 0) | (class_map >= 150))):
        raise ValueError("semantic mapは0〜149の整数モデルIDで指定してください")
    masks = {}
    raw = np.zeros(class_map.shape, dtype=bool)
    for label in labels:
        domain = "real_terrain/" if label in TERRAIN else "real_building/"
        role = PARENTS.get(label, domain + label)
        masks.setdefault(role, np.zeros(class_map.shape, dtype=bool))
    for label, mask, _ in rows:
        if label not in labels or mask.dtype != np.bool_ or mask.shape != class_map.shape:
            raise ValueError("候補maskのラベル・寸法・型が不正です")
        raw |= mask
        domain = "real_terrain/" if label in TERRAIN else "real_building/"
        role = PARENTS.get(label, domain + label)
        masks[role] |= mask & np.isin(class_map, ALLOW.get(label, []))
    count = np.zeros(class_map.shape, dtype=np.uint16)
    for mask in masks.values():
        count += mask
    conflict = count > 1
    for mask in masks.values():
        mask[conflict] = False
    effective = count == 1
    reasons = {"sky": class_map == 2, "person": class_map == 12,
               "conflict": conflict, "semantic_mismatch": raw & (count == 0)
               & ~np.isin(class_map, [2, 12]), "void": ~effective}
    metrics = {"pixels": int(class_map.size), "raw_pixels": int(raw.sum()),
               "effective_pixels": int(effective.sum()), "coverage": float(effective.mean()),
               "void_rate": float((~effective).mean()),
               "excluded_pixels": {key: int((mask & raw).sum())
                                   for key, mask in reasons.items() if key != "void"},
               "semantic_pixels": {key: int(reasons[key].sum()) for key in ("sky", "person")},
               "void_pixels": int((~effective).sum()),
               "missing_roles": sorted(role for role, mask in masks.items() if not mask.any())}
    return masks, reasons, metrics


def save_artifacts(target, token, class_map, rows, labels, parameters, *, exclusion_rows=()):
    """PNGと除外理由を試行専用に保存し、論理path/SHA付き契約と公開対象列を返す。"""
    from colorstats.analyze import visible_wall

    visible = parameters.get("payload", {}).get("method") == visible_wall.METHOD
    masks, reasons, metrics = (visible_wall.constrain(class_map, rows, labels, exclusion_rows)
                               if visible else constrain(class_map, rows, labels))
    files = []

    def save(name, array):
        path = target.with_name(f"{target.stem}-{name}.png")
        temp = temporary_path(path, token)
        Image.fromarray(array).save(temp, format="PNG")
        files.append((temp, path))
        return {"path": str(path), "sha256": _hash(temp)}

    contract = {"version": visible_wall.VERSION if visible else VERSION,
                "policy_hash": visible_wall.policy_hash() if visible else policy_hash(),
                "parent_table": parent_table_reference(),
                "input_sha256": parameters["input_sha256"],
                "size": [class_map.shape[1], class_map.shape[0]],
                "model": parameters["models"]["oneformer"],
                "semantic": save("semantic", class_map.astype(np.uint8)),
                "roles": {role: save(f"role-{role.replace('/', '-')}", mask.astype(np.uint8) * 255)
                          for role, mask in sorted(masks.items())},
                "exclusions": {reason: save(reason, mask.astype(np.uint8) * 255)
                               for reason, mask in reasons.items()}, "metrics": metrics}
    if visible:
        contract["wall_policy"] = visible_wall.configuration()
        contract["wall_candidates"] = [
            {"label": label, "confidence": score, "mask": save(
                f"exclude-candidate-{index}", mask.astype(np.uint8) * 255)}
            for index, (label, mask, score) in enumerate(exclusion_rows)]
    return contract, files


def reference(run):
    """segment runの契約を確定済みpathへ解決する。旧方式にはNoneを返す。"""
    policy = run.parameters.get("region_policy")
    if policy is None:
        from colorstats.analyze.visible_wall import METHOD as WALL_METHOD

        if run.parameters.get("payload", {}).get("method") in (METHOD, WALL_METHOD):
            raise ValueError("新segment runにregion_policyがありません")
        return None
    result = json.loads(json.dumps(policy))
    result["run_id"] = str(run.id)
    for record in [result["semantic"], *result["roles"].values(), *result["exclusions"].values()]:
        record["path"] = run.output_paths[record["path"]]
    for candidate in result.get("wall_candidates", []):
        record = candidate["mask"]
        record["path"] = run.output_paths[record["path"]]
    return result


def load_masks(payload):
    """共有payloadの全SHA・座標・排他性を検証し、有効role maskだけを読み込む。

    契約不一致・入力の差替え・JPEGや非二値maskはValueError。raw Regionへの代替はしない。
    """
    policy = payload["region_policy"]
    from colorstats.analyze import visible_wall

    visible = policy["version"] == visible_wall.VERSION
    expected_hash = visible_wall.policy_hash() if visible else policy_hash()
    if payload.get("mask_path") or payload.get("person_mask"):
        raise ValueError("新policyに別のmaskを重ねず、新segment runへ固定してください")
    if (policy["version"] not in (VERSION, visible_wall.VERSION)
            or policy["policy_hash"] != expected_hash
            or policy.get("parent_table") != parent_table_reference()
            or policy["run_id"] != str(payload["region_run_id"])
            or policy["input_sha256"] != _hash(payload["input_path"])
            or payload.get("input_sha256") != policy["input_sha256"]):
        raise ValueError("region-policyの入力SHA・run・policy hashが一致しません")
    if visible and policy.get("wall_policy") != visible_wall.configuration():
        raise ValueError("可視壁材のpolicy仕様が一致しません")
    with Image.open(payload["input_path"]) as image:
        if list(image.size) != policy["size"] or image.getexif().get(274, 1) != 1:
            raise ValueError("region-policyの寸法・向きが一致しません")
    arrays = {}
    for key, record in [("semantic", policy["semantic"]), *policy["roles"].items(),
                        *(("exclude/" + k, v) for k, v in policy["exclusions"].items()),
                        *((f"candidate/{i}", row["mask"]) for i, row in enumerate(
                            policy.get("wall_candidates", [])))]:
        if _hash(record["path"]) != record["sha256"]:
            raise ValueError("region-policyの出力SHAが一致しません")
        with Image.open(record["path"]) as image:
            array = np.array(image)
            if (image.format != "PNG" or list(image.size) != policy["size"]
                    or array.ndim != 2):
                raise ValueError("region-policyのPNG・寸法が不正です")
        if key == "semantic":
            if not np.issubdtype(array.dtype, np.integer) or np.any((array < 0) | (array >= 150)):
                raise ValueError("semantic mapのモデルIDが不正です")
        elif not np.isin(array, [0, 255]).all():
            raise ValueError("region-policyのmaskは二値PNGが必要です")
        arrays[key] = array
    masks = {role: arrays[role] != 0 for role in policy["roles"]}
    count = np.zeros(arrays["semantic"].shape, dtype=np.uint16)
    for mask in masks.values():
        count += mask
    if np.any(count > 1) or np.any((count > 0) & np.isin(arrays["semantic"], [2, 12])):
        raise ValueError("有効role maskに競合またはsky/personがあります")
    if visible and ("exclude/wall_parts" not in arrays or np.any(
            masks.get(visible_wall.WALL, np.zeros(count.shape, dtype=bool))
            & (arrays["exclude/wall_parts"] != 0))):
        raise ValueError("壁maskに差引き対象の部位が残っています")
    return masks
