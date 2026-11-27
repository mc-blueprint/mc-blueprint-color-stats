"""同一SHAの全項目と未提示保留を、実writerとP6入口で検証する。"""

import copy
import os
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from bench.issue114 import mobile, terrain_statistics
from bench.issue122 import production, runtime, statistics
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import privacy_review, retention
from colorstats.schema.models import Asset, ProcessingRun, Retention, RetentionFile
from tests import test_privacy_review_db as privacy_fixtures
from tests import test_region_policy as region_fixtures
from tests import test_region_policy_db as policy_fixtures
from tests import test_segment as segment_fixtures
from tests import test_segment_db as prep_fixtures
from tests.test_queue import asset as asset
from tests.test_queue import database as database
from tests.test_queue import queue as queue

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離DB専用")


@pytest.fixture
def grouped(queue, asset, tmp_path, monkeypatch):
    ids = [asset, uuid4(), uuid4()]
    with Session(queue.engine) as session, session.begin():
        original = session.get(Asset, asset)
        for index, aid in enumerate(ids[1:], 1):
            values = {
                c.name: getattr(original, c.name) for c in Asset.__table__.columns if c.name != "id"
            }
            values["url"] += f"/sample-{index}"
            session.add(Asset(id=aid, **values))
    decisions, originals = [], {}
    for index, aid in enumerate(ids):
        directory = tmp_path / f"source-{index}"
        directory.mkdir()
        payload = segment_fixtures.payload.__wrapped__(directory)
        payload = region_fixtures.regional_payload.__wrapped__(payload, monkeypatch)
        prep = prep_fixtures.prep_source.__wrapped__(queue, aid, payload)
        policy = policy_fixtures.policy_source.__wrapped__(queue, aid, payload, prep, monkeypatch)
        source, gate, sha = privacy_fixtures.review_source.__wrapped__(
            queue, aid, policy, directory, SimpleNamespace()
        )
        with Session(queue.engine) as session, session.begin():
            retention.register_asset(session, session.get(Asset, aid), {}, "fixture")
        rid = privacy_review.write(
            queue, aid, gate, source["region_run_id"], code_version="synthetic"
        )
        originals[str(aid)] = {"run": str(rid), "sha": sha, "source": source, "gate": str(gate)}
        if index == 2:
            held = privacy_review.record_hold(
                queue,
                aid,
                rid,
                code_version="synthetic-hold",
                reviewer="ユーザー",
                presented_source_sha256=sha,
                note="向きの不一致・未提示（合成）",
            )
            continue
        with Session(queue.engine) as session:
            selected = privacy_review.selection(session, aid, rid)
        mask = source["region_policy"]["exclusions"]["person"]
        decisions.append(
            {
                "asset_id": str(aid),
                "selection": selected,
                "input_path": source["input_path"],
                "input_sha256": source["input_sha256"],
                "mask_path": mask["path"],
                "mask_sha256": mask["sha256"],
                "decision": "accepted",
                "subject": "building",
                "reason": f"合成比較{index}",
                "person_ratio": 0.0,
                "mask_ratio": 0.0,
            }
        )
    bundle, execution, human = (tmp_path / name for name in ("bundle", "presentation", "human"))
    production.save(execution / "privacy-decisions.json", decisions)
    sampling = {"seed": 173, "criteria": {"max_problems": 0}, "required_ids": list(map(str, ids))}
    manifest = {
        "sampling": sampling,
        "required_ids": [row["asset_id"] for row in decisions],
        "random_ids": [row["asset_id"] for row in decisions],
        "boundary_ids": [],
        "population": 3,
        "decisions_sha256": production.segment._hash(execution / "privacy-decisions.json"),
        "nonpresented_holds": [{"asset_id": str(ids[2]), "privacy_review_run_id": str(held)}],
        "rows": [
            {
                k: v
                for k, v in row.items()
                if k
                in {
                    "asset_id",
                    "input_sha256",
                    "decision",
                    "subject",
                    "reason",
                    "person_ratio",
                    "mask_ratio",
                }
            }
            for row in decisions
        ],
    }
    production.save(bundle / "manifest.json", manifest)
    production.save(execution / "review-manifest.json", manifest)
    return SimpleNamespace(
        bundle=bundle,
        execution=execution,
        human=human,
        manifest=manifest,
        sampling=sampling,
        ids=list(map(str, ids)),
        originals=originals,
    )


def build(queue, data):
    mobile.build(queue.engine, data.bundle, data.execution, data.human, Path("taxonomy"))
    production.save(data.human / "review-manifest.json", data.manifest)
    return production.read(data.human / "number-map.json")


def confirm(queue, data):
    mapping = build(queue, data)
    total = len({row["number"] for row in mapping["rows"]})
    reply = mobile.reply_reviews(
        mapping,
        data.human / "review-manifest.json",
        data.manifest["decisions_sha256"],
        f"全{total}枚確認済み\n問題なし",
        directory=data.human,
    )
    applied = mobile.apply_privacy_reply(queue, reply)
    production.save(data.human / "converted-review.json", applied)
    return mapping, applied


def test_同一SHAを一番号にまとめ全項目の比較と保持参照を残す(queue, grouped):
    mapping = build(queue, grouped)
    assert len(mapping["rows"]) == 2 and [r["number"] for r in mapping["rows"]] == [1, 1]
    assert mapping["files"][0]["first"] == mapping["files"][0]["last"] == 1
    page = (grouped.human / "review-01.html").read_text()
    assert page.count('class="raw"') == 1 and page.count("data-sample-sha256=") == 2
    assert "合成比較0" in page and "合成比較1" in page
    with Session(queue.engine) as session:
        refs = session.scalars(
            select(RetentionFile).where(RetentionFile.path == str(grouped.human / "review-01.html"))
        ).all()
        assert {str(r.asset_id) for r in refs} == set(grouped.ids[:2])
    shared = grouped.human.parent / "delivery"
    mobile.share(queue.engine, grouped.human, shared, host="fixture")
    mobile.validate_delivery(mapping, shared)


def test_共有番号の問題を全項目へ展開し未提示には確認を書かない(queue, grouped):
    mapping = build(queue, grouped)
    reply = mobile.reply_reviews(
        mapping,
        grouped.human / "review-manifest.json",
        grouped.manifest["decisions_sha256"],
        "全1枚確認済み\n1: 輪郭の過不足",
        directory=grouped.human,
    )
    assert len(reply["rows"]) == 2 and all(r["error_found"] for r in reply["rows"])
    assert {r["asset_id"] for r in reply["rows"]} == set(grouped.ids[:2])
    applied = mobile.apply_privacy_reply(queue, reply)
    with Session(queue.engine) as session:
        for row in applied["rows"]:
            run = privacy_review.review(
                session, row["asset_id"], row["recorded_privacy_review_run_id"]
            )
            assert run.parameters["evidence"]["human_hold"]
            assert run.parameters["note"] == "輪郭の過不足"
    production.save(grouped.human / "converted-review.json", applied)
    with Session(queue.engine) as session, pytest.raises(PermissionError, match="問題"):
        runtime.human_reviews(session, grouped.human.parent, {"human_sampling": grouped.sampling})


def test_提示と未提示の非交和をP6で受理し未提示を確認済みにしない(queue, grouped):
    mapping, applied = confirm(queue, grouped)
    assert len(applied["rows"]) == 2
    with Session(queue.engine) as session:
        refs = runtime.human_reviews(
            session, grouped.human.parent, {"human_sampling": grouped.sampling}
        )
        assert set(refs) == set(grouped.ids)
        hold = grouped.manifest["nonpresented_holds"][0]
        assert refs[grouped.ids[2]] == hold["privacy_review_run_id"]
        assert all(r["asset_id"] != grouped.ids[2] for r in applied["rows"])
        with pytest.raises(PermissionError):
            privacy_review.selection(session, grouped.ids[2], refs[grouped.ids[2]])


def test_単一提示と二つの未提示保留をP6で受理する(queue, grouped):
    aid = grouped.ids[1]
    original = grouped.originals[aid]
    held = privacy_review.record_hold(
        queue,
        aid,
        original["run"],
        code_version="synthetic-hold",
        reviewer="ユーザー",
        presented_source_sha256=original["sha"],
        note="未提示の合成保留",
    )
    manifest = grouped.manifest
    manifest["required_ids"].remove(aid)
    manifest["random_ids"].remove(aid)
    manifest["rows"] = [r for r in manifest["rows"] if r["asset_id"] != aid]
    manifest["nonpresented_holds"].append({"asset_id": aid, "privacy_review_run_id": str(held)})
    production.save(grouped.bundle / "manifest.json", manifest)
    production.save(grouped.execution / "review-manifest.json", manifest)
    _, applied = confirm(queue, grouped)
    assert len(applied["rows"]) == 1
    with Session(queue.engine) as session:
        refs = runtime.human_reviews(
            session, grouped.human.parent, {"human_sampling": grouped.sampling}
        )
        assert len(refs) == 3 and refs[aid] == str(held)


@pytest.mark.parametrize(
    "change", ["missing", "extra", "overlap", "duplicate", "stale", "accepted"]
)
def test_未提示保留の欠落余分重複と古いrunや採用runを拒否する(queue, grouped, change):
    manifest = grouped.manifest
    if change == "missing":
        manifest["nonpresented_holds"] = []
    elif change == "extra":
        manifest["nonpresented_holds"].append(
            {"asset_id": str(uuid4()), "privacy_review_run_id": str(uuid4())}
        )
    elif change == "overlap":
        manifest["nonpresented_holds"].append(
            {
                "asset_id": grouped.ids[0],
                "privacy_review_run_id": grouped.originals[grouped.ids[0]]["run"],
            }
        )
    elif change == "duplicate":
        manifest["nonpresented_holds"] *= 2
    elif change == "stale":
        manifest["nonpresented_holds"][0]["privacy_review_run_id"] = grouped.originals[
            grouped.ids[2]
        ]["run"]
    else:
        manifest["required_ids"].remove(grouped.ids[1])
        manifest["random_ids"].remove(grouped.ids[1])
        manifest["nonpresented_holds"].append(
            {
                "asset_id": grouped.ids[1],
                "privacy_review_run_id": grouped.originals[grouped.ids[1]]["run"],
            }
        )
    with Session(queue.engine) as session, pytest.raises((ValueError, PermissionError)):
        mobile.nonpresented_reviews(session, manifest)


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "split", "mixed", "unshown"])
def test_番号表の欠落余分重複SHA分割混同と未提示追加を拒否する(queue, grouped, change):
    mapping = build(queue, grouped)
    if change == "missing":
        mapping["rows"].pop()
    elif change == "extra":
        mapping["rows"].append({**mapping["rows"][0], "asset_id": str(uuid4())})
    elif change == "duplicate":
        mapping["rows"].append(copy.deepcopy(mapping["rows"][0]))
    elif change == "split":
        mapping["rows"][1]["number"] = 2
    elif change == "mixed":
        mapping["rows"][1]["presented_source_sha256"] = "0" * 64
    else:
        mapping["rows"].append({**mapping["rows"][0], "asset_id": grouped.ids[2]})
    with pytest.raises(ValueError):
        mobile.reply_reviews(
            mapping,
            grouped.human / "review-manifest.json",
            grouped.manifest["decisions_sha256"],
            "全1枚確認済み\n問題なし",
            directory=grouped.human,
        )


def test_番号表とHTMLの項目対応を消してファイルSHAを付け直しても拒否する(queue, grouped):
    mapping = build(queue, grouped)
    path = grouped.human / mapping["files"][0]["file"]
    token = mobile.contract_digest(mapping["rows"][1])
    path.write_text(
        path.read_text().replace('data-sample-sha256="' + token, 'data-removed="' + token)
    )
    mapping["files"][0].update(bytes=path.stat().st_size, sha256=mobile.digest(path))
    with pytest.raises(ValueError, match="項目区画"):
        mobile.validate_delivery(mapping, grouped.human)


@pytest.mark.parametrize("entry", ["delivery", "reply"])
@pytest.mark.parametrize("change", ["missing", "prediction"])
def test_属性とファイルSHAを残した比較の欠落や差替えを拒否する(queue, grouped, entry, change):
    mapping = build(queue, grouped)
    path = grouped.human / mapping["files"][0]["file"]
    token = mobile.contract_digest(mapping["rows"][1])
    original = path.read_text()
    source_uri = re.search(r'<img class="raw"[^>]*src="([^"]+)"', original)[1]

    def change_content(match):
        content = match[2]
        if change == "missing":
            content = ""
        else:
            content, count = re.subn(
                r'<img class="mask"[^>]*>',
                mobile._image(source_uri, "合成の予測差替え", "mask"),
                content,
                count=1,
            )
            assert count == 1
        return match[1] + content + match[3]

    content, count = re.subn(
        r'(<section\b[^>]*data-sample-sha256="' + token + r'"[^>]*>)(.*?)(</section></article>)',
        change_content,
        original,
        flags=re.S,
    )
    assert count == 1 and token in content
    path.write_text(content)
    mapping["files"][0].update(bytes=path.stat().st_size, sha256=mobile.digest(path))
    with pytest.raises(ValueError, match="比較内容"):
        if entry == "delivery":
            mobile.validate_delivery(mapping, grouped.human)
        else:
            mobile.reply_reviews(
                mapping,
                grouped.human / "review-manifest.json",
                grouped.manifest["decisions_sha256"],
                "全1枚確認済み\n問題なし",
                directory=grouped.human,
            )


@pytest.mark.parametrize("entry", ["delivery", "reply"])
@pytest.mark.parametrize("attribute", ['hidden', 'style="display:none"'])
@pytest.mark.parametrize("outside", ["section", "article", "container", "html"])
def test_比較区画の外側を非表示にしたら拒否する(queue, grouped, entry, attribute, outside):
    mapping = build(queue, grouped)
    path = grouped.human / mapping["files"][0]["file"]
    token = mobile.contract_digest(mapping["rows"][1])
    content = path.read_text()
    if outside == "container":
        content = content.replace(
            f'<section data-sample-sha256="{token}">',
            f'<div {attribute}><section data-sample-sha256="{token}">',
        ).replace('</section></article>', '</section></div></article>')
    else:
        target = {"section": f'<section data-sample-sha256="{token}">',
                  "article": '<article id="n1">', "html": '<html lang="ja">'}[outside]
        content = content.replace(target, target[:-1] + f" {attribute}>")
    path.write_text(content)
    mapping["files"][0].update(bytes=path.stat().st_size, sha256=mobile.digest(path))
    with pytest.raises(ValueError):
        if entry == "delivery":
            mobile.validate_delivery(mapping, grouped.human)
        else:
            mobile.reply_reviews(
                mapping, grouped.human / "review-manifest.json",
                grouped.manifest["decisions_sha256"], "全1枚確認済み\n問題なし",
                directory=grouped.human,
            )


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\v", "\f"])
def test_文字位置と異なる改行を含む正規の比較表示を受理する(queue, grouped, separator):
    path = grouped.execution / "privacy-decisions.json"
    decisions = production.read(path)
    for row in decisions:
        row["reason"] = "合成" + separator + "説明"
    production.save(path, decisions)
    grouped.manifest["decisions_sha256"] = mobile.digest(path)
    for row in grouped.manifest["rows"]:
        row["reason"] = "合成" + separator + "説明"
    production.save(grouped.bundle / "manifest.json", grouped.manifest)
    mapping = build(queue, grouped)
    mobile.validate_delivery(mapping, grouped.human)
    converted = mobile.reply_reviews(
        mapping, grouped.human / "review-manifest.json",
        grouped.manifest["decisions_sha256"], "全1枚確認済み\n問題なし",
        directory=grouped.human,
    )
    assert len(converted["rows"]) == 2


@pytest.mark.parametrize("entry", ["delivery", "reply", "reply_default"])
@pytest.mark.parametrize("change", ["style", "template", "byte"])
def test_自己終了タグと一byteの改変をファイルSHA更新後も拒否する(queue, grouped, entry, change):
    mapping = build(queue, grouped)
    path = grouped.human / mapping["files"][0]["file"]
    content = path.read_text()
    if change == "byte":
        # UTF-8の1 byteだけを変え、復号できるままにする。
        raw = path.read_bytes().replace(b"<title>", b"<Title>", 1)
        assert sum(a != b for a, b in zip(raw, path.read_bytes(), strict=True)) == 1
        path.write_bytes(raw)
    else:
        content = content.replace('<article id="n1">', f'<{change}/><article id="n1">', 1)
        path.write_text(content)
    mapping["files"][0].update(bytes=path.stat().st_size, sha256=mobile.digest(path))
    with pytest.raises(ValueError):
        if entry == "delivery":
            mobile.validate_delivery(mapping, grouped.human)
        else:
            mobile.reply_reviews(
                mapping, grouped.human / "review-manifest.json",
                grouped.manifest["decisions_sha256"], "全1枚確認済み\n問題なし",
                directory=None if entry == "reply_default" else grouped.human,
            )


def test_同じ入力から全体のbyteを再現し元画像なしでも返信を照合できる(queue, grouped):
    first = build(queue, grouped)
    first_directory = grouped.human
    grouped.human = first_directory.parent / "human-repeat"
    second = build(queue, grouped)
    assert first == second
    for item in first["files"]:
        assert (first_directory / item["file"]).read_bytes() == (
            grouped.human / item["file"]
        ).read_bytes()
    for source in first_directory.parent.glob("source-*"):
        source.rename(source.with_name("unavailable-" + source.name))
    mobile.validate_delivery(second, grouped.human)
    result = mobile.reply_reviews(
        second, grouped.human / "review-manifest.json", grouped.manifest["decisions_sha256"],
        "全1枚確認済み\n問題なし",
    )
    assert len(result["rows"]) == 2


@pytest.mark.parametrize("change", ["template", "raw", "binary", "markup"])
def test_再生成のテンプレート版と画像SHAを照合する(queue, grouped, change):
    mapping = build(queue, grouped)
    if change == "template":
        mapping["template"] = "unrecognized"
    elif change == "raw":
        mapping["rows"][0]["presentation"]["raw_sha256"] = "0" * 64
    elif change == "markup":
        mapping["rows"][0]["presentation"]["raw"] += '"><template/>'
    else:
        mapping["rows"][0]["presentation"]["masks"][0]["binary_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        mobile.validate_delivery(mapping, grouped.human)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "released", "stale", "expired", "policy"]
)
def test_P6でも未提示保留の差替えや失効を拒否する(queue, grouped, change):
    confirm(queue, grouped)
    manifest = production.read(grouped.human / "review-manifest.json")
    hold = manifest["nonpresented_holds"][0]
    if change == "missing":
        manifest["nonpresented_holds"] = []
    elif change == "duplicate":
        manifest["nonpresented_holds"] *= 2
    elif change in {"released", "stale"}:
        original = grouped.originals[hold["asset_id"]]
        rid = privacy_review.write(
            queue,
            hold["asset_id"],
            original["gate"],
            original["source"]["region_run_id"],
            code_version="synthetic-correction",
            input_run_id=hold["privacy_review_run_id"],
            reviewer="ユーザー",
            real_people="absent",
            hold=change == "stale",
            presented_source_sha256=original["sha"],
            note="合成の追加訂正",
        )
        if change == "released":
            hold["privacy_review_run_id"] = str(rid)
    elif change == "policy":
        original = grouped.originals[hold["asset_id"]]
        rid = privacy_review.write(
            queue,
            hold["asset_id"],
            original["gate"],
            original["source"]["region_run_id"],
            code_version="synthetic-policy-after-hold",
        )
        with Session(queue.engine) as session:
            assert (
                privacy_review.review(session, hold["asset_id"], rid).parameters["verdict"][
                    "decision"
                ]
                == "pending"
            )
        hold["privacy_review_run_id"] = str(rid)
    else:
        from datetime import UTC, datetime, timedelta

        with Session(queue.engine) as session, session.begin():
            row = session.scalar(
                select(Retention).where(Retention.asset_id == UUID(hold["asset_id"]))
            )
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    production.save(grouped.human / "review-manifest.json", manifest)
    with Session(queue.engine) as session, pytest.raises((ValueError, PermissionError)):
        runtime.human_reviews(session, grouped.human.parent, {"human_sampling": grouped.sampling})


def test_同じ番号でも第二項目のC参照を省略して通さない(queue, grouped):
    decisions_path = grouped.execution / "privacy-decisions.json"
    decisions = production.read(decisions_path)
    decisions[1]["selection"]["privacy_review_hash"] = "0" * 64
    production.save(decisions_path, decisions)
    grouped.manifest["decisions_sha256"] = production.segment._hash(decisions_path)
    production.save(grouped.bundle / "manifest.json", grouped.manifest)
    with pytest.raises(ValueError, match="privacy review"):
        build(queue, grouped)


def test_共有番号の項目が離れた順序でも欠落扱いにしない():
    rows = [
        {"number": 1, "asset_id": "a", "presented_source_sha256": "a" * 64},
        {"number": 2, "asset_id": "b", "presented_source_sha256": "b" * 64},
        {"number": 1, "asset_id": "c", "presented_source_sha256": "a" * 64},
    ]
    assert [row["asset_id"] for row in mobile._numbered_rows(rows)[1]] == ["a", "c"]


def test_未提示保留のrun参照欠落はP6で拒否する(queue, grouped):
    confirm(queue, grouped)
    manifest = production.read(grouped.human / "review-manifest.json")
    manifest["nonpresented_holds"][0].pop("privacy_review_run_id")
    production.save(grouped.human / "review-manifest.json", manifest)
    with Session(queue.engine) as session, pytest.raises(ValueError, match="run参照"):
        runtime.human_reviews(session, grouped.human.parent, {"human_sampling": grouped.sampling})


def test_標本項目数を提示枚数として返信すると拒否する(queue, grouped):
    mapping = build(queue, grouped)
    with pytest.raises(ValueError, match="提示件数"):
        mobile.reply_reviews(
            mapping,
            grouped.human / "review-manifest.json",
            grouped.manifest["decisions_sha256"],
            "全2枚確認済み\n問題なし",
        )


def test_未提示項目を返信へ混ぜてもwriterへ渡さない(queue, grouped):
    mapping = build(queue, grouped)
    reply = mobile.reply_reviews(
        mapping,
        grouped.human / "review-manifest.json",
        grouped.manifest["decisions_sha256"],
        "全1枚確認済み\n問題なし",
    )
    reply["rows"].append({**reply["rows"][0], "asset_id": grouped.ids[2]})
    with pytest.raises(ValueError, match="未提示"):
        mobile.apply_privacy_reply(queue, reply)
    with Session(queue.engine) as session:
        assert session.get(ProcessingRun, UUID(grouped.originals[grouped.ids[0]]["run"]))


@pytest.mark.parametrize("side", ["old", "new", "comparison_old"])
def test_未提示保留を旧採用recordsのままでも両統計から除外する(queue, grouped, monkeypatch, side):
    confirm(queue, grouped)
    root = grouped.human.parent
    held = grouped.ids[2]
    filler = [{"asset_id": str(uuid4()), "status": "prep_failed"} for _ in range(7607)]
    if side != "new":
        filler[0] = {
            "asset_id": held,
            "status": "terrain_selected",
            "privacy_review_run_id": grouped.originals[held]["run"],
        }
    baseline = root / "baseline"
    old = {"taxonomy_version": "0.1.0", "assets": filler}
    production.save(baseline / "selection.json", old)
    rows = [{"asset_id": held, "status": "ready", "analysis_domain": "real_terrain"}]
    if side == "old":
        rows += [dict(r) for r in filler[1:]]
    elif side == "new":
        rows += [
            {"asset_id": str(uuid4()), "status": "original_hold" if i < 993 else "prep_failed"}
            for i in range(2599)
        ]
    plan = {
        "version": runtime.VERSION,
        "partitions": [runtime.PARTITION],
        "rows": rows,
        "human_sampling": grouped.sampling,
        "counts": {"original_hold": 993},
    }
    production.save(root / "plan.json", plan)
    production.save(
        root / "execution.json", {"plan_sha256": production.segment._hash(root / "plan.json")}
    )
    production.save(
        root / "ubuntu1/records.json",
        {
            held: {
                "terminal": True,
                "segment_run_id": grouped.originals[held]["source"]["region_run_id"],
                "privacy_review_run_id": grouped.originals[held]["run"],
                "privacy_verdict": {"decision": "accepted"},
            }
        },
    )
    if side == "old":
        gate = root / "gate"
        production.save(gate / "review-freeze.json", {"records": []})
        for name, value in {
            "ROOT": root,
            "OLD": baseline,
            "GATE": gate,
            "REVIEW_SHA256": production.segment._hash(gate / "review-freeze.json"),
        }.items():
            monkeypatch.setattr(statistics, name, value)
        selected, _ = statistics.selection(queue.engine)
    else:
        monkeypatch.setattr(terrain_statistics, "ROOT", root)
        monkeypatch.setattr(terrain_statistics, "OLD", baseline)
        normalized = {**old, "assets": sorted(filler, key=lambda r: r["asset_id"])}
        monkeypatch.setattr(
            terrain_statistics,
            "verify",
            lambda *a: {"selection_hash": terrain_statistics.digest(normalized)},
        )
        legacy = [r["asset_id"] for r in filler[:110]]
        monkeypatch.setattr(
            terrain_statistics,
            "human_holds",
            lambda: {
                "asset_ids": legacy,
                "proof": {"human_runs_written": 0, "missing_references": 110},
            },
        )
        selected, _ = terrain_statistics.selection(queue.engine, old_only=side == "comparison_old")
    assert next(r for r in selected["assets"] if r["asset_id"] == held) == {
        "asset_id": held,
        "status": "privacy_pending",
    }
