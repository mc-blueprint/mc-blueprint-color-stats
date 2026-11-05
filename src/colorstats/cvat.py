"""CVAT用ラベル生成、正解画像選定、注釈エクスポート取込み。"""

import argparse
import csv
import hashlib
import json
import math
import os
import random
import socket
import uuid
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.schema.models import Asset, ProcessingRun, Region
from colorstats.schema.taxonomy import load_taxonomy


def part_labels(taxonomy_dir: Path) -> list[dict]:
    """部位・地形の全語彙と、修正前後を対応付ける属性を返す。"""
    taxonomy = load_taxonomy(taxonomy_dir)
    names = [label for labels in taxonomy["parts"]["groups"].values() for label in labels]
    return [
        {"name": label, "type": "any", "attributes": [{
            "name": "draft_id", "mutable": False, "input_type": "text",
            "default_value": "", "values": [],
        }]}
        for label in names + taxonomy["terrain"]["labels"]
    ]


def prepare_draft(manifest: Path, output: Path, taxonomy_dir: Path,
                  *, database_url=None, host=None):
    """停止・画像期限をDBで確認し、内部CVAT下書きと共有依存を同じ取引で登録する。

    database_urlまたはDATABASE_URLは必須。旧画像を含む共有出力は期限削除に登録しない。
    出力先は未使用パスとする。DB・I/O失敗時は今回の生成物だけを清掃する。
    """
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("下書き生成には停止台帳を照会するDATABASE_URLが必要です")
    with manifest.open(encoding="utf-8", newline="") as file:
        ids = {uuid.UUID(row["asset_id"]) for row in csv.DictReader(file)}
    engine = create_engine(database_url)
    created = False
    paths = [output, output.with_suffix(".json")]
    try:
        with Session(engine) as session, session.begin():
            retention.lock(session)
            for asset_id in ids:
                retention.assert_usable(session, asset_id, images=True)
            _write_draft(manifest, output, taxonomy_dir)
            created = True
            _register_shared(session, ids, host or socket.gethostname(), paths)
    except BaseException:
        if created:
            for path in paths:
                path.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()


def _register_shared(session, asset_ids, host, paths):
    managed = set(session.scalars(select(retention.Retention.asset_id).where(
        retention.Retention.asset_id.in_(asset_ids),
    )))
    if managed == set(asset_ids):
        for asset_id in managed:
            for path in paths:
                retention.register_file(session, asset_id, host, path, "cvat")
    return managed


def _write_draft(manifest: Path, output: Path, taxonomy_dir: Path):
    """各行のsegment_xmlを結合し、CVAT XMLと比較用JSONを新規作成する。

    manifestには選定列に加え原画像のoriginal_width/original_heightが必要。
    filenameはCVATへ渡す縮小画像名。画像の拡縮は行わず、RLEをそのまま保持する。
    outputと同名の.jsonには原画像寸法、出典SHA、model下書きを保存する。
    内部整形処理。呼出し前の認可と生成物の保持登録はprepare_draftが担う。
    """
    with manifest.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows or len({row["filename"] for row in rows}) != len(rows):
        raise ValueError("manifestが空またはfilenameが重複しています")
    labels = part_labels(taxonomy_dir)
    names = {label["name"] for label in labels}
    root = ElementTree.Element("annotations")
    ElementTree.SubElement(root, "version").text = "1.1"
    task = ElementTree.SubElement(ElementTree.SubElement(root, "meta"), "task")
    ElementTree.SubElement(task, "name").text = "colorstats-model-draft"
    ElementTree.SubElement(task, "size").text = str(len(rows))
    ElementTree.SubElement(task, "mode").text = "annotation"
    definitions = ElementTree.SubElement(task, "labels")
    for label in labels:
        definition = ElementTree.SubElement(definitions, "label")
        ElementTree.SubElement(definition, "name").text = label["name"]
        ElementTree.SubElement(definition, "type").text = "any"
        attribute = ElementTree.SubElement(
            ElementTree.SubElement(definition, "attributes"), "attribute"
        )
        for key, value in {"name": "draft_id", "mutable": "False", "input_type": "text",
                           "default_value": "", "values": ""}.items():
            ElementTree.SubElement(attribute, key).text = value
    baseline = {"format": "cvat-draft-v1", "label_source": "model", "images": {}}
    for index, row in enumerate(rows):
        source = manifest.parent / row["segment_xml"]
        content = source.read_bytes()
        segment = ElementTree.fromstring(content)
        images = segment.findall("image")
        if segment.findtext("version") != "1.1" or len(images) != 1:
            raise ValueError("segment_xmlは1画像のCVAT 1.1 XMLが必要です")
        image = images[0]
        width, height = int(image.get("width")), int(image.get("height"))
        original = [int(row["original_width"]), int(row["original_height"])]
        if min(width, height, *original) < 1:
            raise ValueError("画像寸法は正の整数が必要です")
        image.set("id", str(index))
        image.set("name", row["filename"])
        records = []
        for number, shape in enumerate(image):
            if shape.tag != "mask" or shape.get("label") not in names:
                raise ValueError("segment_xmlにはtaxonomy内のmaskだけを指定してください")
            left, top = int(shape.get("left")), int(shape.get("top"))
            w, h = int(shape.get("width")), int(shape.get("height"))
            counts = [int(value.strip()) for value in shape.get("rle", "").split(",")]
            if (min(left, top) < 0 or min(w, h) < 1 or left + w > width
                    or top + h > height or min(counts) < 0 or sum(counts) != w * h):
                raise ValueError("RLEまたはmaskの範囲が不正です")
            draft_id = f"{index}:{number}"
            shape.set("source", "auto")
            ElementTree.SubElement(shape, "attribute", {"name": "draft_id"}).text = draft_id
            records.append({"draft_id": draft_id, "label": shape.get("label"),
                            "area_ratio": sum(counts[1::2]) / (width * height),
                            "mask": dict(shape.attrib)})
        root.append(image)
        baseline["images"][row["filename"]] = {
            "asset_id": row["asset_id"], "sha256": row["sha256"],
            "annotation_size": [width, height], "original_size": original,
            "segment_xml_sha256": hashlib.sha256(content).hexdigest(), "shapes": records,
        }
    xml = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    baseline["xml_sha256"] = hashlib.sha256(xml).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    try:
        for path, data in [(output, xml), (output.with_suffix(".json"),
                           json.dumps(baseline, ensure_ascii=False, indent=2).encode())]:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                paths.append(path)
                file.write(data)
    except BaseException:
        for path in paths:
            path.unlink()
        raise


def select_assets(rows: list[dict[str, str]], count: int, seed: str, author_limit: int = 5):
    """層を均等に巡回し、作者上限内で固定seedの候補を選ぶ。"""
    if count < 1 or author_limit < 1:
        raise ValueError("countとauthor_limitは1以上が必要です")
    by_stratum = defaultdict(list)
    seen_ids = set()
    seen_files = set()
    for row in rows:
        required = {"asset_id", "author", "stratum", "filename", "sha256"}
        if not required <= row.keys() or any(not row[key].strip() for key in required):
            raise ValueError("候補CSVにはasset_id,author,stratum,filename,sha256が必要です")
        filename = row["filename"].replace("\\", "/")
        if "/" in filename or filename in seen_files or row["asset_id"] in seen_ids:
            raise ValueError(
                f"filenameまたはasset_idが重複、あるいはfilenameがパスです: {filename}"
            )
        if len(row["sha256"]) != 64 or any(
            c not in "0123456789abcdef" for c in row["sha256"].lower()
        ):
            raise ValueError(f"SHA-256が不正です: {filename}")
        seen_files.add(filename)
        seen_ids.add(row["asset_id"])
        by_stratum[row["stratum"]].append(row | {"filename": filename})
    rng = random.Random(seed)
    for candidates in by_stratum.values():
        rng.shuffle(candidates)
    selected = []
    counts = defaultdict(int)
    while len(selected) < count:
        progressed = False
        for stratum in sorted(by_stratum):
            for row in by_stratum[stratum]:
                if row["author"] not in counts or counts[row["author"]] < author_limit:
                    selected.append(
                        row
                        | {
                            "selection_seed": seed,
                            "selection_reason": f"層{stratum}を巡回、作者上限{author_limit}件",
                        }
                    )
                    counts[row["author"]] += 1
                    by_stratum[stratum].remove(row)
                    progressed = True
                    break
            if len(selected) == count:
                break
        if not progressed:
            raise ValueError(f"作者上限内で{count}件選べません（選定可能: {len(selected)}件）")
    return selected


def _segments_intersect(a, b, c, d):
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    if any(max(a[i], b[i]) < min(c[i], d[i]) or max(c[i], d[i]) < min(a[i], b[i])
           for i in (0, 1)):
        return False
    ab_c, ab_d = cross(a, b, c), cross(a, b, d)
    cd_a, cd_b = cross(c, d, a), cross(c, d, b)
    return ((ab_c <= 0 <= ab_d or ab_d <= 0 <= ab_c)
            and (cd_a <= 0 <= cd_b or cd_b <= 0 <= cd_a))


def read_cvat_export(archive: Path, manifest: Path, taxonomy_dir: Path, draft: Path | None = None):
    """CVAT XMLを検証し、下書き指定時は原画像座標へ戻したpolygonを返す。

    拡縮は左上原点の幅・高さ比で行う。crop・回転した画像は対象外。
    自己交差、下書きIDの不明・重複、画像集合・寸法・asset対応の不一致はValueError。
    """
    with manifest.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
        assets = {row["filename"]: row for row in rows}
    if not assets or len(assets) != len(rows):
        raise ValueError("選定manifestが空またはfilenameが重複しています")
    baseline = json.loads(draft.read_text(encoding="utf-8")) if draft else None
    if baseline and (baseline["format"] != "cvat-draft-v1"
                     or set(baseline["images"]) != set(assets)):
        raise ValueError("下書きとmanifestの画像が一致しません")
    labels = {item["name"] for item in part_labels(taxonomy_dir)}
    with zipfile.ZipFile(archive) as zf:
        xml_names = [name for name in zf.namelist() if Path(name).name == "annotations.xml"]
        if len(xml_names) != 1:
            raise ValueError("ZIPにはannotations.xmlが1つ必要です")
        image_names = {
            Path(name).name
            for name in zf.namelist()
            if name.startswith("images/") and not name.endswith("/")
        }
        if image_names != set(assets):
            raise ValueError("ZIP内imagesと選定manifestが一致しません")
        root = ElementTree.fromstring(zf.read(xml_names[0]))
    if root.tag != "annotations" or root.findtext("version") != "1.1":
        raise ValueError("CVAT for images 1.1 XMLではありません")
    polygons = defaultdict(list)
    image_names = set()
    for image in root.findall("image"):
        filename = Path(image.get("name", "").replace("\\", "/")).name
        if filename not in assets or filename in image_names:
            raise ValueError(f"manifest外または重複したimageです: {filename}")
        image_names.add(filename)
        width, height = int(image.get("width", "0")), int(image.get("height", "0"))
        if width < 1 or height < 1:
            raise ValueError(f"画像サイズが不正です: {filename}")
        scale_x = scale_y = 1.0
        original_width, original_height = width, height
        draft_ids = set()
        if baseline:
            before = baseline["images"][filename]
            row = assets[filename]
            if (before["asset_id"] != row["asset_id"]
                    or before["sha256"].lower() != row["sha256"].lower()
                    or before["annotation_size"] != [width, height]):
                raise ValueError(f"下書きのasset・SHA・画像寸法が不一致です: {filename}")
            original_width, original_height = before["original_size"]
            scale_x, scale_y = original_width / width, original_height / height
        assets[filename]["export_width"] = str(original_width)
        assets[filename]["export_height"] = str(original_height)
        shapes = list(image)
        if any(shape.tag != "polygon" for shape in shapes):
            raise ValueError(f"polygon以外のannotation shapeがあります: {filename}")
        for index, polygon in enumerate(shapes):
            label = polygon.get("label")
            if label not in labels:
                raise ValueError(f"taxonomy外のlabelです: {label}")
            points = []
            for pair in polygon.get("points", "").split(";"):
                try:
                    x, y = (float(value) for value in pair.split(","))
                except ValueError as exc:
                    raise ValueError(f"ポリゴン座標が不正です: {filename}") from exc
                if (
                    not math.isfinite(x)
                    or not math.isfinite(y)
                    or not 0 <= x <= width
                    or not 0 <= y <= height
                ):
                    raise ValueError(f"ポリゴン座標が画像外です: {filename}")
                points.append([x * scale_x, y * scale_y])
            if len(points) < 3:
                raise ValueError(f"ポリゴン頂点が3点未満です: {filename}")
            for i in range(len(points)):
                for j in range(i + 2, len(points)):
                    if i == 0 and j == len(points) - 1:
                        continue
                    if _segments_intersect(points[i], points[(i + 1) % len(points)],
                                           points[j], points[(j + 1) % len(points)]):
                        raise ValueError(f"自己交差したポリゴンです: {filename}")
            area = abs(
                sum(
                    points[i][0] * points[(i + 1) % len(points)][1]
                    - points[(i + 1) % len(points)][0] * points[i][1]
                    for i in range(len(points))
                )
                / 2
            )
            if area <= 0:
                raise ValueError(f"面積0のポリゴンです: {filename}")
            draft_id = polygon.findtext("attribute[@name='draft_id']", "").strip()
            if baseline and draft_id:
                known_ids = {shape["draft_id"] for shape in before["shapes"]}
                if draft_id not in known_ids or draft_id in draft_ids:
                    raise ValueError(f"不明または重複したdraft_idです: {draft_id}")
                draft_ids.add(draft_id)
            polygons[filename].append(
                {
                    "label": label,
                    "points": points,
                    "area": area,
                    "width": original_width,
                    "height": original_height,
                    "shape_id": str(index),
                    "draft_id": draft_id,
                }
            )
    if image_names != set(assets):
        raise ValueError(
            f"エクスポート画像とmanifestが不一致です: {sorted(set(assets) - image_names)}"
        )
    return assets, polygons


def annotation_diff(baseline: dict, polygons: dict) -> dict:
    """ID単位の追加・削除・ラベル変更と面積の符号付き差を記録する。

    beforeはRLEの画素面積比、afterは原画像座標polygonの幾何面積比。
    同面積の移動・輪郭変更はこの値だけでは測れないため両形状も保存する。
    """
    result = {}
    for filename, image in baseline["images"].items():
        before = {shape["draft_id"]: shape for shape in image["shapes"]}
        after = {shape["draft_id"] or f"new:{shape['shape_id']}": shape
                 for shape in polygons[filename]}
        area = math.prod(image["original_size"])
        changes = []
        for key in sorted(before.keys() | after.keys()):
            old, new = before.get(key), after.get(key)
            old_area = old["area_ratio"] if old else 0
            new_area = new["area"] / area if new else 0
            changes.append({
                "draft_id": key, "status": "matched" if old and new else (
                    "added" if new else "deleted"),
                "before_label": old["label"] if old else None,
                "after_label": new["label"] if new else None,
                "label_changed": bool(old and new and old["label"] != new["label"]),
                "before_area_ratio": old_area, "after_area_ratio": new_area,
                "area_ratio_delta": new_area - old_area,
                "area_pixels_delta": (new_area - old_area) * area,
            })
        result[filename] = changes
    return result


def import_cvat(
    archive: Path, manifest: Path, mask_dir: Path, taxonomy_dir: Path, database_url: str,
    draft: Path,
    *, host=None,
):
    """選定manifestとDBのID・SHA・寸法を照合し、人手注釈を新しいrunへ登録する。

    archiveは画像を含むCVAT for images 1.1 ZIP、draftはprepare_draftのJSON。
    mask_dirに原画像座標polygonとmodel下書きのコピーを保存する。
    形式・照合不一致や同一ZIPの再取込みはValueError。
    DB/I/O失敗は呼出し元へ伝播し、この取込みのDB変更と作成ファイルを戻す。
    PostgreSQLのREAD COMMITTEDで、ZIPのSHAごとに取引単位の排他を行う。
    """
    assets, polygons = read_cvat_export(archive, manifest, taxonomy_dir, draft)
    baseline = json.loads(draft.read_text(encoding="utf-8"))
    differences = annotation_diff(baseline, polygons)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    taxonomy = load_taxonomy(taxonomy_dir)
    engine = create_engine(database_url)
    files = []
    host = host or socket.gethostname()
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                text("SELECT pg_advisory_xact_lock(41, :key)"),
                {"key": int.from_bytes(bytes.fromhex(digest[:8]), signed=True)},
            )
            retention.lock(session)
            if session.execute(
                select(ProcessingRun.id).where(
                    ProcessingRun.stage == "human_annotation", ProcessingRun.config_hash == digest
                )
            ).first():
                raise ValueError("このCVATエクスポートはすでに登録済みです")
            db_assets = {}
            for row in assets.values():
                asset_id = uuid.UUID(row["asset_id"])
                asset = session.get(Asset, asset_id)
                retention.assert_usable(session, asset_id, images=True)
                if asset is None or asset.sha256.lower() != row["sha256"].lower():
                    raise ValueError(f"asset IDまたはSHA-256が一致しません: {row['filename']}")
                if (int(row["export_width"]), int(row["export_height"])) != (
                        asset.width, asset.height):
                    raise ValueError(
                        f"エクスポートとassetの画像寸法が異なります: {row['filename']}"
                    )
                db_assets[row["filename"]] = asset
            output_paths = {
                "masks": str(mask_dir.resolve()), "archive": str(archive.resolve()),
                "manifest": str(manifest.resolve()), "input_draft": str(draft.resolve()),
            }
            path = mask_dir / f"{uuid.uuid4()}-draft.json"
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            files.append(path)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(baseline, file, ensure_ascii=False)
            output_paths["draft"] = str(path.resolve())
            license_classes = {asset.license_class for asset in db_assets.values()}
            run_ids = {}
            for license_class in license_classes:
                run = ProcessingRun(
                    stage="human_annotation",
                    license_class=license_class,
                    config_hash=digest,
                    parameters={
                        "asset_ids": [str(asset.id) for asset in db_assets.values()],
                        "format": "CVAT for images 1.1",
                        "label_source": "human",
                        "taxonomy_version": taxonomy["parts"]["taxonomy_version"],
                        "draft_sha256": hashlib.sha256(draft.read_bytes()).hexdigest(),
                        "annotation_diff": {name: changes for name, changes in differences.items()
                                            if db_assets[name].license_class == license_class},
                    },
                    output_paths=output_paths,
                    code_version="issue-41",
                    taxonomy_version=taxonomy["parts"]["taxonomy_version"],
                    node="local-cvat",
                    finished_at=datetime.now(UTC),
                )
                session.add(run)
                session.flush()
                run_ids[license_class] = run.id
            session.flush()
            shared_paths = [archive, manifest, draft, *files]
            managed = _register_shared(
                session, {asset.id for asset in db_assets.values()}, host, shared_paths,
            )
            for filename, shapes in polygons.items():
                row = assets[filename]
                asset = db_assets[filename]
                width, height = asset.width, asset.height
                for shape in shapes:
                    region_id = uuid.uuid4()
                    relative = Path(str(row["asset_id"])) / f"{region_id}.json"
                    path = mask_dir / relative
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    files.append(path)
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                        json.dump({"format": "polygon-pixels-v1", "points": shape["points"]}, file)
                    if asset.id in managed:
                        retention.register_file(session, asset.id, host, path, "cvat")
                    bbox = [
                        min(p[0] for p in shape["points"]),
                        min(p[1] for p in shape["points"]),
                        max(p[0] for p in shape["points"]),
                        max(p[1] for p in shape["points"]),
                    ]
                    session.add(
                        Region(
                            id=region_id,
                            asset_id=uuid.UUID(row["asset_id"]),
                            processing_run_id=run_ids[asset.license_class],
                            taxonomy_version=taxonomy["parts"]["taxonomy_version"],
                            label=shape["label"],
                            instance_id=f"cvat:{shape['draft_id'] or shape['shape_id']}",
                            mask_path=relative.as_posix(),
                            bbox=bbox,
                            label_source="human",
                            confidence=1.0,
                            area_ratio=min(shape["area"] / (width * height), 1.0),
                        )
                    )
    except BaseException:
        for path in files:
            path.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    labels = commands.add_parser("labels")
    labels.add_argument("--taxonomy", type=Path, required=True)
    labels.add_argument("--output", type=Path, required=True)
    draft_parser = commands.add_parser("prepare-draft")
    draft_parser.add_argument("--manifest", type=Path, required=True)
    draft_parser.add_argument("--output", type=Path, required=True)
    draft_parser.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    select = commands.add_parser("select")
    select.add_argument("--input", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("--count", type=int, default=100)
    select.add_argument("--seed", default="issue-41")
    select.add_argument("--author-limit", type=int, default=5)
    importer = commands.add_parser("import-cvat")
    importer.add_argument("--export", type=Path, required=True)
    importer.add_argument("--manifest", type=Path, required=True)
    importer.add_argument("--mask-dir", type=Path, required=True)
    importer.add_argument("--taxonomy", type=Path, default=Path("taxonomy"))
    importer.add_argument("--draft", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "labels":
        args.output.write_text(
            json.dumps({"labels": part_labels(args.taxonomy)}, indent=2), encoding="utf-8"
        )
    elif args.command == "select":
        with args.input.open(encoding="utf-8", newline="") as file:
            result = select_assets(
                list(csv.DictReader(file)), args.count, args.seed, args.author_limit
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=[*result[0]])
            writer.writeheader()
            writer.writerows(result)
    elif args.command == "prepare-draft":
        prepare_draft(args.manifest, args.output, args.taxonomy)
    else:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            parser.error("取込みには専用DBのDATABASE_URLが必要です")
        import_cvat(args.export, args.manifest, args.mask_dir, args.taxonomy, database_url,
                    args.draft)


if __name__ == "__main__":
    main()
