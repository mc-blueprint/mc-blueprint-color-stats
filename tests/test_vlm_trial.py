import copy
import json
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, PngImagePlugin

from colorstats.api_budget import digest
from colorstats.review_html import image_tag, jpeg, validate_html
from colorstats.trial_cli import demo
from colorstats.trial_inputs import (
    SEED,
    SPLITS,
    load_manifest,
    prepare,
    select_candidates,
    sha,
    validate_package,
)
from colorstats.trial_pages import build_pages
from colorstats.trial_results import accept_results, read_results, validate_results


def attempts(root):
    return json.loads((root / "active-attempts.json").read_text())


@pytest.fixture
def candidates(tmp_path):
    now = datetime.now(UTC)
    rows = []
    for n, scene in enumerate(
        scene for strata in SPLITS.values() for scene, count in strata.items() for _ in range(count)
    ):
        path = tmp_path / f"source-{n}.png"
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("title", "非送信の取得情報")
        Image.new("RGB", (64, 48), (n * 7, 60, 100)).save(path, pnginfo=metadata)
        rows.append(
            {
                "asset_id": str(uuid4()),
                "subject_group": str(uuid4()),
                "scene": scene,
                "source_sha256": sha(path.read_bytes()),
                "phash": digest(n)[:16],
                "people": "absent",
                "scene_ref": "local-scene",
                "person_ref": "local-person",
                "expires_at": (now + timedelta(days=3)).isoformat(),
                "path": str(path),
            }
        )
    legacy = {
        "version": "delivery-v3",
        "presentation_sha256": digest("presentation"),
        "images": [
            {
                "asset_id": str(uuid4()),
                "source_sha256": digest(["old", n]),
                "phash": digest(["old-phash", n])[:16],
            }
            for n in range(108)
        ],
    }
    return rows, legacy, now


@pytest.fixture
def bundle(tmp_path, candidates):
    rows, legacy, now = candidates
    root = tmp_path / "private"
    selected = select_candidates(rows, legacy, now=now)
    manifest = prepare(selected, root, now=now)
    return root, manifest, now


@pytest.fixture
def completed(tmp_path):
    root = tmp_path / "demo"
    table = demo(root)
    manifest, configs, results = read_results(root)
    return root, manifest, configs, results, table


def test_固定seedと建物分離を入力順に依存せず再現する(candidates):
    rows, legacy, now = candidates
    selected = select_candidates(rows, legacy, now=now)
    random.Random(4).shuffle(rows)
    assert selected == select_candidates(rows, legacy, now=now)
    assert Counter(r["split"] for r in selected) == {"tune": 6, "confirm": 24}
    assert selected[0]["trial_id"] == "T001" and selected[-1]["trial_id"] == "T030"
    assert SEED == 20261116
    assert not (
        {r["subject_group"] for r in selected[:6]} & {r["subject_group"] for r in selected[6:]}
    )


@pytest.fixture
def phase_candidates(tmp_path, candidates, monkeypatch):
    from colorstats import trial_inputs

    template, legacy, now = candidates
    splits = {
        "tune": {"single": 4, "interior": 1, "group": 1},
        "confirm": {"single": 16, "interior": 3, "group": 2, "closeup": 3},
    }
    monkeypatch.setattr(trial_inputs, "SPLITS", splits)
    capacities = [
        ("mixed", {"single": 3, "group": 4, "closeup": 1}),
        ("four", {"single": 4}),
        ("tune-single", {"single": 1}),
        ("tune-interior", {"interior": 9}),
        ("interior", {"interior": 3}),
        ("cross", {"single": 2, "interior": 1, "group": 1}),
        ("group", {"group": 1}),
        ("two", {"single": 2}),
        ("single-closeup", {"single": 1, "closeup": 1}),
        *((f"single-{n}", {"single": 1}) for n in range(7)),
        *((f"closeup-{n}", {"closeup": 1}) for n in range(7)),
    ]
    rows = []
    for n in range(48):
        path = tmp_path / f"phase-source-{n}.png"
        Image.new("RGB", (64, 48), (n * 5, 80, 110)).save(path)
        rows.append(
            {
                **template[0],
                "asset_id": f"synthetic-{n:03}",
                "source_sha256": sha(path.read_bytes()),
                "phash": digest(["phase", n])[:16],
                "path": str(path),
            }
        )
    pool = list(rows)
    random.Random(SEED).shuffle(pool)
    for row, (subject, scene) in zip(
        pool,
        (
            (subject, scene)
            for subject, counts in capacities
            for scene, count in counts.items()
            for _ in range(count)
        ),
        strict=True,
    ):
        row.update(subject_group=subject, scene=scene)
    phases = {
        subject: "tune" if subject in {"mixed", "tune-single", "tune-interior"} else "confirm"
        for subject, _ in capacities
    }
    return rows, legacy, now, phases, splits


def test_建物別指定で先着選定の不足を解消し同じphaseの複数写真を準備する(
    phase_candidates, tmp_path
):
    rows, legacy, now, phases, splits = phase_candidates
    before = copy.deepcopy((rows, phases))
    with pytest.raises(ValueError, match="confirm/single 必要16件・選定13件"):
        select_candidates(rows, legacy, now=now)
    selected = select_candidates(rows, legacy, now=now, subject_phases=phases)
    assert selected == select_candidates(rows[::-1], legacy, now=now, subject_phases=phases)
    assert (rows, phases) == before
    assert Counter((r["split"], r["scene"]) for r in selected) == {
        (phase, scene): count for phase, strata in splits.items() for scene, count in strata.items()
    }
    assert [r["trial_id"] for r in selected] == [f"T{i:03}" for i in range(1, 31)]
    tune, confirm = selected[:6], selected[6:]
    assert {r["split"] for r in tune} == {"tune"}
    assert {r["split"] for r in confirm} == {"confirm"}
    assert not ({r["subject_group"] for r in tune} & {r["subject_group"] for r in confirm})
    mixed = [r for r in selected if r["subject_group"] == "mixed"]
    assert Counter(r["scene"] for r in mixed) == {"single": 3, "group": 1}
    assert all(phases[r["subject_group"]] == r["split"] for r in selected)
    root = tmp_path / "reserved"
    manifest = prepare(selected, root, now=now)
    assert len(validate_package(root, manifest)["images"]) == 30


@pytest.mark.parametrize("change", ["missing", "extra", "phase", "empty"])
def test_不完全な建物phase表は保存前に拒否する(phase_candidates, tmp_path, change):
    rows, legacy, now, phases, _ = phase_candidates
    if change == "missing":
        phases.pop(next(iter(phases)))
    elif change == "extra":
        phases["unknown"] = "confirm"
    elif change == "phase":
        phases["mixed"] = "unknown"
    else:
        phases.clear()
    root = tmp_path / "invalid"
    with pytest.raises(ValueError, match="全候補の建物"):
        prepare(
            select_candidates(rows, legacy, now=now, subject_phases=phases), root, now=now
        )
    assert not root.exists()


def test_指定表で不足しても別建物へ割り当て直さない(phase_candidates):
    rows, legacy, now, phases, _ = phase_candidates
    phases["tune-single"] = "confirm"
    before = dict(phases)
    with pytest.raises(ValueError, match="tune/single 必要4件・選定3件"):
        select_candidates(rows, legacy, now=now, subject_phases=phases)
    assert phases == before


@pytest.mark.parametrize("kind", ["sha", "phash", "relation"])
def test_建物指定でも選定内の重複を除外する(candidates, kind):
    rows, legacy, now = candidates
    phases = {r["subject_group"]: "tune" if i < 6 else "confirm" for i, r in enumerate(rows)}
    target = next(r for r in rows if r["scene"] == "gate")
    other = rows[0]
    pairs = []
    if kind == "sha":
        target["source_sha256"] = other["source_sha256"]
    elif kind == "phash":
        target["phash"] = f"{int(other['phash'], 16) ^ 63:016x}"
    else:
        pairs = [(target["asset_id"], other["asset_id"])]
    with pytest.raises(ValueError, match="層不足"):
        select_candidates(rows, legacy, pairs, now=now, subject_phases=phases)


@pytest.mark.parametrize("kind", ["sha", "phash", "relation", "legacy", "subject"])
@pytest.mark.parametrize("reserved", [False, True])
def test_重複と建物分離で不足したら補充しない(candidates, kind, reserved):
    rows, legacy, now = candidates
    target = next(r for r in rows if r["scene"] == "gate")
    pairs = []
    if kind == "legacy":
        target["asset_id"] = legacy["images"][0]["asset_id"]
    elif kind == "sha":
        target["source_sha256"] = legacy["images"][0]["source_sha256"]
    elif kind == "phash":
        target["phash"] = f"{int(legacy['images'][0]['phash'], 16) ^ 63:016x}"
    elif kind == "relation":
        pairs = [(target["asset_id"], legacy["images"][0]["asset_id"])]
    else:
        for row in rows:
            if row["scene"] == "single":
                row["subject_group"] = "same-building"
    phases = (
        {r["subject_group"]: "tune" if i < 6 else "confirm" for i, r in enumerate(rows)}
        if reserved
        else None
    )
    with pytest.raises(ValueError, match="層不足"):
        select_candidates(rows, legacy, pairs, now=now, subject_phases=phases)


@pytest.mark.parametrize(
    "key,value", [("people", "uncertain"), ("scene_ref", ""), ("person_ref", ""), ("phash", None)]
)
def test_不足する確認根拠を旧返信で補わない(candidates, key, value):
    rows, legacy, now = candidates
    rows[0][key] = value
    with pytest.raises(ValueError):
        select_candidates(rows, legacy, now=now)


def test_旧提示の対象不足と候補期限切れを拒否する(candidates):
    rows, legacy, now = candidates
    with pytest.raises(ValueError):
        select_candidates(rows, {**legacy, "images": []}, now=now)
    rows[0]["expires_at"] = now.isoformat()
    with pytest.raises(PermissionError):
        select_candidates(rows, legacy, now=now)


def test_外部用は連番と正規化画像だけで内部情報を渡さない(bundle):
    root, manifest, now = bundle
    public = validate_package(root, manifest)
    assert set(public) == {"version", "images"}
    assert len(list((root / "package").iterdir())) == 31
    for row in public["images"]:
        assert set(row) == {"trial_id", "file", "sha256", "size"}
        with Image.open(root / "package" / row["file"]) as image:
            assert image.mode == "RGB" and not image.info
    text = (root / "package/inputs.json").read_text()
    for row in manifest["images"]:
        assert row["asset_id"] not in text and row["subject_group"] not in text
    assert "source_url" not in text and "title" not in text and "database" not in text
    ledger = json.loads((root / "file-ledger.json").read_text())
    assert len(ledger["files"]) == 32
    assert all(
        datetime.fromisoformat(r["expires_at"]) <= now + timedelta(days=3) for r in ledger["files"]
    )


def test_正規化で向き補正と縮小とmetadata除去をする(tmp_path, candidates):
    rows, legacy, now = candidates
    path = Path(rows[0]["path"])
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "非送信"
    Image.new("RGB", (1600, 800), "red").save(path, format="JPEG", exif=exif)
    rows[0]["source_sha256"] = sha(path.read_bytes())
    manifest = prepare(select_candidates(rows, legacy, now=now), tmp_path / "private", now=now)
    item = next(r for r in manifest["images"] if r["asset_id"] == rows[0]["asset_id"])
    assert item["input"]["size"] == [512, 1024]


def test_追加ファイルとPNGmetadataと画像改変を送信前に拒否する(bundle):
    root, manifest, _ = bundle
    extra = root / "package" / "private.json"
    extra.write_text("{}")
    with pytest.raises(ValueError):
        validate_package(root, manifest)
    extra.unlink()
    image = root / manifest["images"][0]["input"]["file"]
    with Image.open(image) as source:
        clean = source.copy()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("source_url", "非送信")
    clean.save(image, pnginfo=metadata)
    with pytest.raises(ValueError):
        validate_package(root, manifest)


@pytest.mark.parametrize("kind", ["relative", "existing", "symlink", "unwritable", "git"])
def test_回収先の不備を自動fallbackしない(tmp_path, candidates, monkeypatch, kind):
    rows, legacy, now = candidates
    target = tmp_path / "output"
    if kind == "relative":
        target = Path("relative")
    elif kind == "existing":
        target.mkdir()
        (target / "keep").write_text("keep")
    elif kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(tmp_path, target_is_directory=True)
        target = link / "output"
    elif kind == "unwritable":
        monkeypatch.setattr("colorstats.trial_inputs.os.access", lambda *args: False)
    else:
        (tmp_path / ".git").write_text("gitdir: fixture")
    with pytest.raises(ValueError):
        prepare(select_candidates(rows, legacy, now=now), target, now=now)
    if kind == "existing":
        assert (target / "keep").read_text() == "keep"


def test_失敗途中の新規コピーにも保存前の台帳がある(tmp_path, candidates, monkeypatch):
    from colorstats import trial_inputs

    rows, legacy, now = candidates
    root = tmp_path / "private"
    original = trial_inputs.write_private

    def fail(path, content):
        if path.suffix == ".png":
            raise OSError("模擬I/O障害")
        original(path, content)

    monkeypatch.setattr(trial_inputs, "write_private", fail)
    with pytest.raises(OSError):
        prepare(select_candidates(rows, legacy, now=now), root, now=now)
    assert len(json.loads((root / "file-ledger.json").read_text())["files"]) == 32
    assert not list((root / "package").glob("*.png"))


def test_合成30件150結果からスマホ比較と番号表まで通る(completed):
    root, manifest, configs, results, table = completed
    assert len(results) == 150 and len(table["rows"]) == 30
    assert [r["number"] for r in table["rows"]] == list(range(1, 31))
    assert table["manifest_sha256"] == sha((root / "manifest.json").read_bytes())
    assert table["results_sha256"] == sha((root / "results.json").read_bytes())
    for item in table["files"]:
        page = root / item["file"]
        content = page.read_text()
        validate_html(content, item["numbers"])
        assert sha(page.read_bytes()) == item["sha256"]
        assert set(item["numbers"]) <= (
            set(range(1, 7)) if "tune" in item["file"] else set(range(7, 31))
        )
        assert "合成画像" in content and "写真＋壁の輪郭線" in content
        assert "repeat(2,minmax(0,1fr))" in content
        assert "窓・扉" in content and "1: A,C" in content
        assert "Qwen" not in content and "source-" not in content
    assert len({tuple(r["positions"].values()) for r in table["rows"]}) > 1
    assert set(table["rows"][0]["positions"]) == set("ABCDE")
    with pytest.raises(ValueError, match="既存"):
        build_pages(root)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "input",
        "config",
        "size",
        "box",
        "nan",
        "status",
        "scene",
        "extra",
        "mask-sha",
        "mask-size",
        "mask-value",
        "mask-outside",
        "mask-symlink",
    ],
)
def test_結果の欠落と照合座標mask不正を拒否する(completed, tmp_path, change):
    root, manifest, configs, results, _ = completed
    rows = copy.deepcopy(results)
    row = rows[0]
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[-1] = copy.deepcopy(row)
    elif change == "input":
        row["input_sha256"] = "0" * 64
    elif change == "config":
        configs["A"]["prompt_sha256"] = "0" * 64
    elif change == "size":
        row["size"] = [1, 1]
    elif change == "box":
        row["regions"][0]["box"] = [1, 0, 0, 1]
    elif change == "nan":
        row["regions"][0]["box"][0] = float("nan")
    elif change == "status":
        row["status"] = "truncated"
    elif change == "scene":
        row["scene"] = "unsupported"
    elif change == "extra":
        row["private_url"] = "非送信"
    else:
        mask = row["regions"][0]["mask"]
        path = root / mask["file"]
        if change == "mask-sha":
            mask["sha256"] = "0" * 64
        elif change == "mask-outside":
            mask["file"] = "../outside.png"
        elif change == "mask-symlink":
            outside = tmp_path / "outside.png"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(outside)
        else:
            Image.new(
                "L",
                (1, 1) if change == "mask-size" else tuple(row["size"]),
                127 if change == "mask-value" else 255,
            ).save(path)
            mask["sha256"] = sha(path.read_bytes())
    with pytest.raises(ValueError):
        validate_results(root, manifest, configs, rows, active_attempts=attempts(root))


def test_窓全体と細部の包含を一律排他にしない(completed):
    root, manifest, configs, rows, _ = completed
    region = rows[0]["regions"][0]
    rows[0]["regions"] = [
        {**region, "part": part} for part in ("window", "window_glass", "window_frame")
    ]
    validate_results(root, manifest, configs, rows, active_attempts=attempts(root))


@pytest.mark.parametrize(
    "attack",
    [
        "<script>alert(1)</script>",
        '<img src="https://example.test/a.png">',
        '<iframe src="data:text/html,x"></iframe>',
        '<style>@import "x";</style>',
        "<style>a{background:url(https://example.test/a)}</style>",
        '<img srcset="https://example.test/a 2x">',
        '<meta http-equiv="refresh" content="0;url=x">',
    ],
)
def test_HTMLの外部参照と能動要素を拒否する(attack):
    with pytest.raises(ValueError):
        validate_html('<article id="n1"></article>' + attack, [1])


def test_埋込画像SHAと連番とbyte上限を照合する():
    tag = image_tag(jpeg(Image.new("RGB", (8, 8))), "写真", "original")
    content = '<article id="n1">' + tag + "</article>"
    validate_html(content, [1])
    with pytest.raises(ValueError):
        validate_html(content.replace("data-sha256=", "data-other="), [1])
    with pytest.raises(ValueError):
        validate_html(content, [2])
    with pytest.raises(ValueError):
        validate_html(content, [1], limit=10)


def test_期限切れと固定manifest改変を拒否する(bundle):
    root, _, now = bundle
    with pytest.raises(PermissionError):
        load_manifest(root, now=now + timedelta(days=4))
    path = root / "manifest.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError):
        load_manifest(root, now=now)


def test_結果と構成の受領後改変および上書きを拒否する(completed):
    root, _, configs, results, _ = completed
    with pytest.raises(ValueError):
        accept_results(root, configs, results, active_attempts=attempts(root))
    path = root / "results.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError):
        read_results(root)


def test_ページを容量で分割しても番号と調整確認を混ぜない(completed, tmp_path):
    import shutil

    from colorstats.trial_pages import _card, page

    source, manifest, _, results, _ = completed
    root = tmp_path / "split"
    shutil.copytree(source, root, ignore=shutil.ignore_patterns("pages", "number-map.json"))
    ledger_path = root / "file-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    ledger["files"] = [
        r
        for r in ledger["files"]
        if not r["file"].startswith("pages/") and r["file"] != "number-map.json"
    ]
    ledger_path.write_text(json.dumps(ledger))
    outputs = {(r["trial_id"], r["configuration_id"]): r for r in results}
    sizes = []
    for image in manifest["images"]:
        card, _ = _card(root, image, {c: outputs[image["trial_id"], c] for c in "ABCDE"})
        sizes.append(len(page([card], image["split"], True).encode()))
    limit = max(sizes) + 100
    table = build_pages(root, limit=limit)
    assert len(table["files"]) == 30
    assert [n for f in table["files"] for n in f["numbers"]] == list(range(1, 31))
    assert all(f["bytes"] <= limit for f in table["files"])


def test_構成や受領manifestの必須参照を省略しない(completed):
    root, manifest, configs, rows, _ = completed
    configs["A"].pop("weights_sha256")
    with pytest.raises(ValueError):
        validate_results(root, manifest, configs, rows, active_attempts=attempts(root))


def test_共通分割器の違いを許容しない(completed):
    root, manifest, configs, rows, _ = completed
    configs["B"]["segmenter_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="同じ分割器"):
        validate_results(root, manifest, configs, rows, active_attempts=attempts(root))


def test_合成試行は実写真の再検査へ流用しない(completed):
    from colorstats.trial_inputs import recheck

    root, *_ = completed
    with pytest.raises(PermissionError, match="合成"):
        recheck(None, root)


def test_逐次回収も一括確定と同じ参照検査を使う(completed):
    from colorstats.trial_results import validate_result

    root, manifest, configs, results, _ = completed
    validate_result(root, manifest, configs, results[0], active_attempts=attempts(root))
    row = {**results[0], "input_sha256": "0" * 64}
    with pytest.raises(ValueError):
        validate_result(root, manifest, configs, row, active_attempts=attempts(root))


@pytest.mark.parametrize("full", [False, True])
def test_全面と空の領域を見えない輪郭だけで示さない(full):
    import numpy as np

    from colorstats.trial_pages import _section

    mask = np.full((16, 16), full, dtype=bool)
    photo = image_tag(jpeg(Image.new("RGB", (16, 16))), "写真", "original")
    content = _section("wall", mask, (16, 16), photo, 1, "A")
    assert ("写真全体が選ばれています" if full else "選ばれた場所がありません") in content


@pytest.mark.parametrize("kind", ["manifest", "ledger", "synthetic"])
def test_照合値を持っていても未対応版と合成区分を受け付けない(bundle, kind):
    root, _, now = bundle
    manifest_path = root / "manifest.json"
    ledger_path = root / "file-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    if kind == "ledger":
        ledger["version"] = "unknown"
    else:
        manifest = json.loads(manifest_path.read_text())
        if kind == "manifest":
            manifest["version"] = "unknown"
        else:
            manifest["synthetic"] = "false"
        manifest_path.write_text(json.dumps(manifest))
        for record in ledger["files"]:
            if record["file"] == "manifest.json":
                record["sha256"] = sha(manifest_path.read_bytes())
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError):
        load_manifest(root, now=now)


def test_重複属性と空白付きrefreshでも外部参照を通さない():
    tag = image_tag(jpeg(Image.new("RGB", (8, 8))), "写真", "original")
    duplicate = tag.replace("<img ", '<img src="https://example.test/outside" ', 1)
    for attack in [duplicate, '<meta http-equiv=" refresh " content="0;url=https://example.test">']:
        with pytest.raises(ValueError):
            validate_html('<article id="n1">' + attack + "</article>", [1])


def incoming(bundle, completed, *, preregister=True):
    from colorstats.trial_inputs import add_files, stamp, write_private

    root, manifest, now = bundle
    source, _, configurations, old_results, _ = completed
    results = copy.deepcopy(old_results)
    inputs = {image["trial_id"]: image["input"] for image in manifest["images"]}
    for row in results:
        row["input_sha256"] = inputs[row["trial_id"]]["sha256"]
    active = attempts(source)
    files = {
        region["mask"]["file"]: region["mask"]["sha256"]
        for row in results
        for region in row["regions"]
    }
    expiry = min((row["local_expires_at"] for row in manifest["images"]), key=stamp)
    (root / "masks").mkdir()
    if preregister:
        add_files(
            root,
            [
                {"file": name, "sha256": value, "expires_at": expiry}
                for name, value in files.items()
            ],
        )
    for name in files:
        write_private(root / name, (source / name).read_bytes())
    return root, manifest, configurations, results, active, now


@pytest.mark.parametrize("preregister", [True, False])
def test_受信maskの事前登録から150結果の受領とHTMLまで通る(bundle, completed, preregister):
    root, _, configurations, results, active, now = incoming(
        bundle, completed, preregister=preregister
    )
    ledger_path = root / "file-ledger.json"
    before = json.loads(ledger_path.read_text())
    accept_results(root, configurations, results, active_attempts=active, now=now)
    after = json.loads(ledger_path.read_text())
    files = [row["file"] for row in after["files"]]
    assert len(files) == len(set(files))
    for row in before["files"]:
        assert row in after["files"]
    assert len(read_results(root, now=now)[2]) == 150
    table = build_pages(root, now=now)
    assert table["active_attempts_sha256"] == sha((root / "active-attempts.json").read_bytes())


@pytest.mark.parametrize(
    "field,days",
    [("sha256", None), ("expires_at", 4), ("expires_at", -1)],
    ids=["sha-mismatch", "extended", "expired"],
)
def test_事前登録maskの照合不一致では受領記録を作らない(bundle, completed, field, days):
    root, _, configurations, results, active, now = incoming(bundle, completed)
    ledger_path = root / "file-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    row = next(r for r in ledger["files"] if r["file"].startswith("masks/"))
    row[field] = "0" * 64 if field == "sha256" else (now + timedelta(days=days)).isoformat()
    ledger_path.write_text(json.dumps(ledger))
    before = ledger_path.read_bytes()
    with pytest.raises(ValueError, match="事前登録mask"):
        accept_results(root, configurations, results, active_attempts=active, now=now)
    assert ledger_path.read_bytes() == before
    assert not (root / "results.json").exists()
    assert not (root / "active-attempts.json").exists()


@pytest.mark.parametrize("all_old", [False, True])
def test_旧attemptは逐次検査と150件検査と受領確定ですべて拒否する(
    bundle,
    completed,
    all_old,
):
    from colorstats.trial_results import validate_result

    root, manifest, configurations, results, active, now = incoming(bundle, completed)
    for row in results if all_old else results[:1]:
        row["attempt"] = "old"
    with pytest.raises(ValueError, match="有効attempt"):
        validate_result(root, manifest, configurations, results[0], active_attempts=active)
    with pytest.raises(ValueError, match="有効attempt"):
        validate_results(root, manifest, configurations, results, active_attempts=active)
    with pytest.raises(ValueError, match="有効attempt"):
        accept_results(root, configurations, results, active_attempts=active, now=now)
    assert not (root / "results.json").exists()


def test_画像構成ごとに明示した有効な再試行を受領し参照を固定する(bundle, completed):
    root, _, configurations, results, active, now = incoming(bundle, completed)
    row = results[0]
    row["attempt"] = "retry2"
    active[row["trial_id"]][row["configuration_id"]] = "retry2"
    accept_results(root, configurations, results, active_attempts=active, now=now)
    assert read_results(root, now=now)[2][0]["attempt"] == "retry2"
    path = root / "active-attempts.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="変更"):
        read_results(root, now=now)


@pytest.mark.parametrize(
    "css",
    [
        'background-image:image-set("https://example.test/a" 1x)',
        'background-image:-webkit-image-set("https://example.test/a" 1x)',
        'background-image:image("https://example.test/a")',
        '@import "https://example.test/a.css"',
        'background-image:url("https://example.test/a")',
    ],
)
@pytest.mark.parametrize("inline", [False, True])
def test_CSSの画像参照構文を固定スタイルの外では受け付けない(css, inline):
    import html

    body = (
        '<article id="n1" style="' + html.escape(css, quote=True) + '"></article>'
        if inline
        else "<style>a{" + css + '}</style><article id="n1"></article>'
    )
    with pytest.raises(ValueError):
        validate_html(body, [1])


@pytest.mark.parametrize("hours", [23, 24, 25])
def test_事前登録maskは72時間から24時間へ短縮した期限を受領と再読込みで守る(
    bundle, completed, hours
):
    from colorstats.trial_inputs import add_files, stamp

    root, manifest, configurations, results, active, now = incoming(
        bundle, completed, preregister=False
    )
    assert min(stamp(row["local_expires_at"]) for row in manifest["images"]) == now + timedelta(
        hours=72
    )
    shorter = (now + timedelta(hours=24)).isoformat()
    records = {
        region["mask"]["file"]: {
            **region["mask"],
            "expires_at": shorter,
        }
        for row in results
        for region in row["regions"]
    }
    add_files(root, list(records.values()))
    validate_results(root, manifest, configurations, results, active_attempts=active)
    accept_results(root, configurations, results, active_attempts=active, now=now)
    assert len(read_results(root, now=now)[2]) == 150
    ledger = json.loads((root / "file-ledger.json").read_text())
    for record in ledger["files"]:
        if record["file"] in records:
            assert record == records[record["file"]]
    later = now + timedelta(hours=hours)
    if hours < 24:
        assert len(read_results(root, now=later)[2]) == 150
        assert len(build_pages(root, now=later)["rows"]) == 30
    else:
        before = (root / "file-ledger.json").read_bytes()
        for operation in (read_results, build_pages):
            with pytest.raises(ValueError, match="期限切れ"):
                operation(root, now=later)
        assert (root / "file-ledger.json").read_bytes() == before
        assert not (root / "pages").exists()
        assert not (root / "number-map.json").exists()
        assert all((root / name).exists() for name in records)


@pytest.mark.parametrize("change", ["sha256", "extended", "unregistered"])
def test_再読込みとHTML生成も受領時と同じmask登録条件を使う(completed, change):
    from colorstats.trial_inputs import stamp

    root, manifest, _, _, _ = completed
    now = stamp(manifest["created_at"])
    path = root / "file-ledger.json"
    ledger = json.loads(path.read_text())
    record = next(r for r in ledger["files"] if r["file"].startswith("masks/"))
    if change == "sha256":
        record["sha256"] = "0" * 64
    elif change == "extended":
        record["expires_at"] = (now + timedelta(days=4)).isoformat()
    else:
        ledger["files"].remove(record)
    path.write_text(json.dumps(ledger))
    before = path.read_bytes()
    for operation in (read_results, build_pages):
        with pytest.raises(ValueError, match="mask"):
            operation(root, now=now)
    assert path.read_bytes() == before

@pytest.mark.parametrize("kind", ["selected_out", "missing", "duplicate", "unknown"])
def test_四構成の選択外不足重複未知構成を受領しない(tmp_path, kind):
    root = tmp_path / "contract-four"
    demo(root)
    manifest, configurations, results = read_results(root)
    del configurations["D"]
    if kind == "unknown":
        configurations["F"] = configurations.pop("E")
    elif kind == "missing":
        results = [r for r in results if r["configuration_id"] != "D"][:-1]
    elif kind == "duplicate":
        results = [r for r in results if r["configuration_id"] != "D"]
        results[-1] = results[0]
    with pytest.raises(ValueError):
        validate_results(
            root, manifest, configurations, results, active_attempts=attempts(root)
        )


@pytest.mark.parametrize("operation", ["accept", "render"])
def test_空構成と空結果を受領もrenderも確定しない(tmp_path, monkeypatch, operation):
    from colorstats.trial_cli import main, synthetic_inputs

    root = tmp_path / "empty"
    synthetic_inputs(root)
    before = (root / "file-ledger.json").read_bytes()
    if operation == "accept":
        with pytest.raises(ValueError, match="ABCDEまたはABCE"):
            accept_results(root, {}, [], active_attempts={})
    else:
        paths = {}
        for name, value in (("configurations", {}), ("results", []), ("active-attempts", {})):
            paths[name] = tmp_path / f"{name}.json"
            paths[name].write_text(json.dumps(value))
        monkeypatch.setattr(
            "sys.argv",
            [
                "trial", "render", "--result-root", str(root),
                "--configurations", str(paths["configurations"]),
                "--results", str(paths["results"]),
                "--active-attempts", str(paths["active-attempts"]),
            ],
        )
        with pytest.raises(ValueError, match="ABCDEまたはABCE"):
            main()
    assert (root / "file-ledger.json").read_bytes() == before
    assert not (root / "results.json").exists()
    assert not (root / "pages").exists()


@pytest.mark.parametrize("operation", [read_results, build_pages])
def test_保存済みの空構成と空結果も再読込みとHTML生成で拒否する(tmp_path, operation):
    from colorstats.trial_cli import synthetic_inputs
    from colorstats.trial_inputs import add_files, encoded, write_private

    root = tmp_path / "empty-saved"
    manifest = synthetic_inputs(root)
    expiry = manifest["images"][0]["local_expires_at"]
    for name, value in (("configurations", {}), ("results", []), ("active-attempts", {})):
        blob = encoded(value)
        filename = f"{name}.json"
        add_files(root, [{"file": filename, "sha256": sha(blob), "expires_at": expiry}])
        write_private(root / filename, blob)
    before = (root / "file-ledger.json").read_bytes()
    with pytest.raises(ValueError, match="ABCDEまたはABCE"):
        operation(root)
    assert (root / "file-ledger.json").read_bytes() == before
    assert not (root / "pages").exists()
    assert not (root / "number-map.json").exists()
