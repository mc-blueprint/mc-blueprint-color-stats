import csv
import json
import uuid
import zipfile
from pathlib import Path

import pytest

from colorstats.cvat import (
    annotation_diff,
    part_labels,
    prepare_draft,
    read_cvat_export,
    select_assets,
)

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy"


def test_parts_yamlの第2階層を全てラベル化する():
    labels = part_labels(TAXONOMY)
    assert len(labels) == 41
    assert {row["name"] for row in labels} >= {
        "wall_main", "floor_visible", "dormer", "ground_grass", "water", "tree_trunk",
    }
    assert all(row["type"] == "any" for row in labels)


def test選定をseed固定し層と作者を分散する():
    rows = [
        {
            "asset_id": str(i),
            "author": f"author-{i // 2}",
            "stratum": f"layer-{i % 3}",
            "filename": f"{i}.png",
            "sha256": f"{i:064x}",
        }
        for i in range(24)
    ]
    selected = select_assets(rows, 12, "issue-41", author_limit=1)
    assert selected == select_assets(rows, 12, "issue-41", author_limit=1)
    assert len({row["author"] for row in selected}) == 12
    assert {row["stratum"] for row in selected} == {"layer-0", "layer-1", "layer-2"}
    assert all(row["selection_reason"] for row in selected)
    assert {row["selection_seed"] for row in selected} == {"issue-41"}


def test作者上限では件数を満たせない候補を拒否する():
    rows = [
        {
            "asset_id": str(i),
            "author": "one",
            "stratum": "a",
            "filename": f"{i}.png",
            "sha256": f"{i:064x}",
        }
        for i in range(3)
    ]
    with pytest.raises(ValueError, match="作者上限内"):
        select_assets(rows, 2, "seed", author_limit=1)


def test_cvat_xmlのポリゴンをasset_manifestへ結び付ける(tmp_path):
    manifest = tmp_path / "selection.csv"
    with manifest.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file, fieldnames=["asset_id", "author", "stratum", "filename", "sha256"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "asset_id": str(uuid.uuid4()),
                "author": "author",
                "stratum": "layer",
                "filename": "front.png",
                "sha256": "0" * 64,
            }
        )
    export = tmp_path / "export.zip"
    xml = (
        b'<annotations><version>1.1</version><image id="0" name="front.png" '
        b'width="100" height="100">'
        b'<polygon label="wall_main" points="10,10;80,10;80,80;10,80"/></image></annotations>'
    )
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("annotations.xml", xml)
        archive.writestr("images/front.png", b"test image")
    assets, polygons = read_cvat_export(export, manifest, TAXONOMY)
    assert set(assets) == {"front.png"}
    assert polygons["front.png"][0]["points"] == [[10, 10], [80, 10], [80, 80], [10, 80]]
    assert polygons["front.png"][0]["area"] == 4900


@pytest.mark.parametrize(
    "xml,label",
    [
        (b"<annotations><version>1.0</version></annotations>", None),
        (
            b'<annotations><version>1.1</version><image name="front.png" width="100" height="100">'
            b'<polygon label="unknown" points="1,1;10,1;10,10"/></image></annotations>',
            "unknown",
        ),
    ],
)
def test不正なCVAT形式とtaxonomy外ラベルを拒否する(tmp_path, xml, label):
    manifest = tmp_path / "selection.csv"
    manifest.write_text(
        "asset_id,author,stratum,filename,sha256\na,a,s,front.png," + "0" * 64 + "\n",
        encoding="utf-8",
    )
    export = tmp_path / "export.zip"
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("annotations.xml", xml)
        archive.writestr("images/front.png", b"test image")
    expected = "taxonomy外" if label else "CVAT for images"
    with pytest.raises(ValueError, match=expected):
        read_cvat_export(export, manifest, TAXONOMY)


@pytest.fixture
def draft_export(tmp_path):
    manifest = tmp_path / "selection.csv"
    manifest.write_text(
        "asset_id,filename,sha256,segment_xml,original_width,original_height\n"
        f"{uuid.uuid4()},front.png,{'a' * 64},segment.xml,200,300\n", encoding="utf-8",
    )
    (tmp_path / "segment.xml").write_text(
        '<annotations><version>1.1</version><image name="prep.png" width="100" height="100">'
        '<mask label="ground_grass" left="0" top="0" width="50" height="50" '
        'rle="0,2500"/></image></annotations>', encoding="utf-8",
    )
    draft = tmp_path / "draft.xml"
    prepare_draft(manifest, draft, TAXONOMY)
    archive = tmp_path / "export.zip"
    xml = (
        '<annotations><version>1.1</version><image name="front.png" width="100" height="100">'
        '<polygon label="wall_main" points="10,10;80,10;80,80;10,80">'
        '<attribute name="draft_id">0:0</attribute></polygon></image></annotations>'
    )
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("annotations.xml", xml)
        file.writestr("images/front.png", b"resized image")
    return archive, manifest, draft.with_suffix(".json")


def test下書きRLEを保持して非等方の縮小座標を原画像へ戻す(draft_export):
    archive, manifest, draft = draft_export
    baseline = json.loads(draft.read_text())
    assert baseline["label_source"] == "model"
    assert baseline["images"]["front.png"]["shapes"][0]["mask"]["rle"] == "0,2500"
    _, polygons = read_cvat_export(archive, manifest, TAXONOMY, draft)
    assert polygons["front.png"][0]["points"] == [[20, 30], [160, 30], [160, 240], [20, 240]]
    diff = annotation_diff(baseline, polygons)["front.png"][0]
    assert diff["label_changed"]
    assert diff["before_label"] == "ground_grass" and diff["after_label"] == "wall_main"
    assert diff["before_area_ratio"] == 0.25
    assert diff["after_area_ratio"] == 0.49
    assert diff["area_pixels_delta"] == 14400
    deleted = annotation_diff(baseline, {"front.png": []})["front.png"][0]
    assert deleted["status"] == "deleted" and deleted["area_pixels_delta"] == -15000
    polygons["front.png"][0]["draft_id"] = ""
    changes = annotation_diff(baseline, polygons)["front.png"]
    assert {row["status"] for row in changes} == {"added", "deleted"}


@pytest.mark.parametrize("field", ["draft_id", "annotation_size"])
def test不明な下書きIDと寸法違いを拒否する(draft_export, field):
    archive, manifest, draft = draft_export
    baseline = json.loads(draft.read_text())
    if field == "draft_id":
        baseline["images"]["front.png"]["shapes"][0]["draft_id"] = "99:0"
    else:
        baseline["images"]["front.png"]["annotation_size"] = [50, 50]
    draft.write_text(json.dumps(baseline))
    with pytest.raises(ValueError, match="draft_id|不一致"):
        read_cvat_export(archive, manifest, TAXONOMY, draft)


def test既存下書きを上書きしない(draft_export):
    archive, manifest, draft = draft_export
    before = draft.read_bytes()
    with pytest.raises(FileExistsError):
        prepare_draft(manifest, draft.with_suffix(".xml"), TAXONOMY)
    assert draft.read_bytes() == before


def test同じ下書きIDを複数polygonへ割り当てたexportを拒否する(draft_export):
    archive, manifest, draft = draft_export
    with zipfile.ZipFile(archive) as file:
        xml = file.read("annotations.xml").decode()
    polygon = xml[xml.index("<polygon"):xml.index("</polygon>") + len("</polygon>")]
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("annotations.xml", xml.replace("</image>", polygon + "</image>"))
        file.writestr("images/front.png", b"resized image")
    with pytest.raises(ValueError, match="重複したdraft_id"):
        read_cvat_export(archive, manifest, TAXONOMY, draft)


def test不正なRLEを下書きとして受け付けない(draft_export):
    _, manifest, draft = draft_export
    source = manifest.parent / "segment.xml"
    source.write_text(source.read_text().replace('rle="0,2500"', 'rle="0,2501"'))
    output = draft.parent / "invalid.xml"
    with pytest.raises(ValueError, match="RLE"):
        prepare_draft(manifest, output, TAXONOMY)
    assert not output.exists() and not output.with_suffix(".json").exists()


@pytest.mark.parametrize("points", [
    "10,10;90,90;10,90;50,10",
    "10,10;90,90;10,90;90,10",
    "10,10;90,10;50,10;50,90;10,90",
    "10,10;90,10;50,10;90,90;10,90",
])
def test自己交差や非隣接辺の接触と重なりを拒否する(draft_export, points):
    archive, manifest, draft = draft_export
    with zipfile.ZipFile(archive) as file:
        xml = file.read("annotations.xml").decode()
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("annotations.xml", xml.replace("10,10;80,10;80,80;10,80", points))
        file.writestr("images/front.png", b"resized image")
    with pytest.raises(ValueError, match="自己交差"):
        read_cvat_export(archive, manifest, TAXONOMY, draft)


@pytest.mark.parametrize("points", [
    "10,10;90,10;50,50;90,90;10,90",
    "10,90;90,90;50,50;90,10;10,10",
    "10,10;50,10;90,10;90,90;10,90",
])
def test凹形状や一直線上の中間頂点がある単純polygonを受け付ける(draft_export, points):
    archive, manifest, draft = draft_export
    with zipfile.ZipFile(archive) as file:
        xml = file.read("annotations.xml").decode()
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("annotations.xml", xml.replace("10,10;80,10;80,80;10,80", points))
        file.writestr("images/front.png", b"resized image")
    _, polygons = read_cvat_export(archive, manifest, TAXONOMY, draft)
    assert polygons["front.png"][0]["area"] == (38400 if "50,10" in points else 28800)
