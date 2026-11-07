"""必須目視サンプルを単体HTMLにし、番号付きの会話返信を既存取込み形式へ変換する。"""

import argparse
import base64
import hashlib
import html
import io
import json
import os
import re
import socket
from pathlib import Path
from uuid import UUID

import numpy as np
from bench.issue114.privacy import digest, save
from PIL import Image, ImageFilter
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import privacy_review, retention
from colorstats.analyze import region_policy as region_policy_contract
from colorstats.api_budget import digest as contract_digest
from colorstats.queue import Queue
from colorstats.schema.models import ProcessingRun, Region

LIMIT = 25_000_000
REASONS = {"person_not_detected": "人物検出なし", "person_masked": "人物maskあり",
           "subject_ambiguous": "主体混在", "subject_unresolved": "主体不明",
           "person_over_limit": "人物面積超過"}
STYLE = """body{margin:0 auto;padding:12px;max-width:800px;font:16px sans-serif;
overflow-wrap:anywhere;box-sizing:border-box}*{box-sizing:border-box}
img{display:block;max-width:100%;height:auto;margin:8px 0}.mask,.outline{image-rendering:pixelated}
article{border-top:2px solid #777;
padding:12px 0}p{line-height:1.6}h2{font-size:1.3rem}figure{margin:0 0 16px}
figcaption{font-weight:bold} .legend{border:1px solid #777;padding:8px} .raw{border:3px solid #222}
.mask{border:3px dashed #176b35}.outline{border:3px dotted #174ea6}"""


def jpeg(image):
    """長辺800px以内のJPEGをdata URI用に符号化する。"""
    image = image.convert("RGB")
    image.thumbnail((800, 800), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode()


def mask_uri(mask, size):
    """座標を維持した単独maskのdata URIを返す。"""
    values = np.asarray(mask)
    if values.shape != (size[1], size[0]) or not np.isin(values, [False, True, 0, 255]).all():
        raise ValueError("maskの座標・二値値が不正です")
    image = Image.fromarray((values != 0).astype("uint8") * 255, mode="L")
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def outline_uri(mask, size, *, pattern="solid"):
    """元座標の輪郭を別画像にし、役割ごとの線種で区別する。"""
    values = np.asarray(mask) != 0
    if values.shape != (size[1], size[0]):
        raise ValueError("輪郭maskの寸法が一致しません")
    source = Image.fromarray(values.astype("uint8") * 255, mode="L")
    outer = np.asarray(source.filter(ImageFilter.MaxFilter(3))) != 0
    edge = outer & ~values
    if pattern == "dash":
        edge[1::4] = False
        edge[3::4] = False
    elif pattern == "dot":
        edge[::3, ::3] = False
    elif pattern == "dashdot":
        edge[1::4] = False
        edge[3::4, ::3] = False
    elif pattern != "solid":
        raise ValueError("未対応の輪郭線種です")
    result = Image.fromarray(np.where(edge, 0, 255).astype("uint8"), mode="L")
    stream = io.BytesIO()
    result.save(stream, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def page(cards, first, last, total, groups=None):
    counts = groups or {}
    return f'''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>#114 目視確認 {first}–{last}</title><style>{STYLE}</style>
<h1>#114 目視確認 {first}–{last}／全{total}枚</h1>
<p>対象母数：{counts.get('population', total)}枚。固定無作為群：{counts.get('random', 0)}枚、
目的抽出challenge群：{counts.get('challenge', 0)}枚（重複除外済み）。
群を混ぜて率を計算しません。</p>
<p>全ファイルの全番号を確認してください。人物の見落とし、maskの不足、
主体・有効領域・自動判定の誤りがあれば、
チャットへ「問題あり：番号と理由」を返信してください。
全件確認後は「全{total}枚確認済み。問題なし」または
「全{total}枚確認済み。問題あり：7 人物の見落とし、…」と返信します。
途中の確認は完了扱いにしません。JSONの保存・送付は不要です。</p>
<p class="legend">凡例：原画像は実線枠、mask単独表示は破線枠、輪郭は点線枠。
mask画像は原画像と同じ座標で表示し、写真へ色を重ねません。
raw候補とregion-policy-v1の有効maskは明確に区別します。
予測を表示した画像の確認は盲検ではありません。保留は確認後も自動採用されません。</p>
{''.join(cards)}</html>'''


def write_pages(cards, output, limit=LIMIT, group_counts=None):
    """UTF-8の実byte数で上限を守り、通し番号を維持して分割する。"""
    groups, current, first = [], [], 1
    sizes = [len(card.encode()) for card in cards]
    total = sum(sizes)
    if len(page([], 1, len(cards), len(cards), group_counts).encode()) + total > limit:
        candidates, prefix = [], 0
        for cut, size in enumerate(sizes[:-1], 1):
            prefix += size
            left = prefix + len(page([], 1, cut, len(cards), group_counts).encode())
            right = total - prefix + len(page(
                [], cut + 1, len(cards), len(cards), group_counts,
            ).encode())
            if max(left, right) <= limit:
                candidates.append((abs(left - right), cut))
        if candidates:
            cut = min(candidates)[1]
            groups = [(1, cut, cards[:cut]), (cut + 1, len(cards), cards[cut:])]
    for number, card in enumerate([] if groups else cards, 1):
        if len(page(current + [card], first, number, len(cards), group_counts).encode()) > limit:
            if not current:
                raise ValueError("1画像分のHTMLが容量上限を超えました")
            groups.append((first, number - 1, current))
            current, first = [], number
        current.append(card)
    if current:
        groups.append((first, len(cards), current))
    files = []
    for part, (first, last, group) in enumerate(groups, 1):
        content = page(group, first, last, len(cards), group_counts).encode()
        if len(content) > limit:
            raise ValueError("HTMLが容量上限を超えました")
        path = output / f"review-{part:02}.html"
        with path.open("xb") as stream:
            stream.write(content)
        path.chmod(0o600)
        files.append({"file": path.name, "bytes": len(content), "first": first, "last": last,
                      "sha256": digest(path)})
    return files


def _review_references(selection, gate, region_run_id, people):
    return {
        "image_gate_run_id": gate.get("run_id") or selection.get("image_gate_run_id"),
        "region_policy_run_id": region_run_id,
        "privacy_review_run_id": selection.get("privacy_review_run_id"),
        "presented_source_sha256": gate.get("source_sha256"),
        "confirmed_real_people": people,
    }


def _selection_for(decisions, asset_id):
    row = decisions[asset_id]
    return row.get("selection", row)


def validate_presentation_run(session, asset_id, selection):
    """閲覧対象のprivacy run/hashとA/B参照を照合する。保留verdictも提示可能。"""
    run_id = selection.get("privacy_review_run_id")
    run = session.get(ProcessingRun, UUID(run_id)) if run_id else None
    parameters = run.parameters if run else {}
    evidence = parameters.get("evidence", {})
    if (run is None or run.stage != "review" or not run.finished_at
            or run.failure_reason is not None or parameters.get("kind") != "privacy_review"
            or evidence.get("asset_id") != str(asset_id)
            or evidence.get("image_gate_run_id") != selection.get("image_gate_run_id")
            or evidence.get("region_policy_run_id") != selection.get("region_policy_run_id")
            or selection.get("privacy_review_hash") != contract_digest(parameters)):
        raise ValueError("提示するprivacy review run/hashの参照が一致しません")
    return run


def build(db, bundle, execution, output, taxonomy, *, host=None, require_contracts=True):
    """保持ロック下で利用可否を確認し、画像入りHTMLと番号表を保持登録する。"""
    manifest = json.loads((bundle / "manifest.json").read_text())
    created = False
    try:
        with Session(db) as session, session.begin():
            retention.lock(session)
            for aid in manifest["required_ids"]:
                retention.assert_usable(session, UUID(aid), images=True)
            output.mkdir(mode=0o700, exist_ok=False)
            created = True
            _build(session, manifest, bundle, execution, output, taxonomy,
                   host or socket.gethostname(), require_contracts)
    except BaseException:
        if created:
            for path in output.iterdir():
                path.unlink()
            output.rmdir()
        raise


def _build(session, manifest, bundle, execution, output, taxonomy, host, require_contracts):
    if manifest["decisions_sha256"] != digest(execution / "privacy-decisions.json"):
        raise ValueError("閲覧manifestと自動判定が一致しません")
    decisions = {row["asset_id"]: row for row in json.loads(
        (execution / "privacy-decisions.json").read_text())}
    ids = sorted(manifest["required_ids"])
    if len(ids) != len(set(ids)):
        raise ValueError("提示対象に重複したassetがあります")
    regions = {}
    policy_views = {}
    gate_views = {}
    region_run_ids = {}
    for aid in ids:
        row = decisions[aid]
        selection = _selection_for(decisions, aid)
        gate_run_id = row.get("image_gate_run_id") or selection.get("image_gate_run_id")
        if require_contracts and (selection.get("contract") != "image-review-v1"
                                  or not gate_run_id):
            raise ValueError("image-review-v1の判定参照が必要です")
        if gate_run_id:
            run = session.get(ProcessingRun, UUID(gate_run_id))
            if (run is None or run.stage != "review" or not run.finished_at
                    or run.parameters.get("kind") != "image_gate"
                    or run.parameters.get("asset_id") != aid):
                raise ValueError("固定したimage-review-v1 runを読み取れません")
            result_path = Path(run.parameters["result_path"])
            if digest(result_path) != run.parameters["result_sha256"]:
                raise ValueError("image-review-v1の判定artifact SHAが一致しません")
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            gate_views[aid] = {"result": run.parameters.get("verdict"),
                               "observation": saved.get("result"),
                               "identity": run.parameters.get("identity"),
                               "identity_hash": run.parameters.get("identity_hash"),
                               "run_id": str(run.id),
                               "source_sha256": run.parameters.get("source_sha256")}
            if (selection.get("contract") == "image-review-v1"
                    and (selection.get("image_gate_hash") != contract_digest(run.parameters)
                         or selection.get("image_gate_input_sha256")
                         != run.parameters["identity"]["input_sha256"])):
                raise ValueError("image-review-v1の参照hashまたは入力が一致しません")
        region_run_id = (row.get("region_policy_run_id")
                         or selection.get("region_policy_run_id") or row.get("region_run_id"))
        if not region_run_id:
            if require_contracts:
                raise ValueError("region-policy-v1のrun参照が必要です")
            continue
        region_run_ids[aid] = region_run_id
        run = session.get(ProcessingRun, UUID(region_run_id))
        policy = region_policy_contract.reference(run) if run else None
        if policy is None:
            if require_contracts:
                raise ValueError("region-policy-v1の有効maskが必要です")
            continue
        if (selection.get("contract") == "image-review-v1"
                and (selection.get("region_policy_run_id") != str(run.id)
                     or selection.get("region_policy_hash") != contract_digest(policy))):
            raise ValueError("image-review-v1とregion-policy-v1の参照が一致しません")
        if require_contracts:
            validate_presentation_run(session, UUID(aid), selection)
        payload = {"region_policy": policy, "region_run_id": str(run.id),
                   "input_path": row["input_path"], "input_sha256": row["input_sha256"]}
        role_masks = region_policy_contract.load_masks(payload)
        exclusions = {}
        for reason, record in policy["exclusions"].items():
            with Image.open(record["path"]) as image:
                exclusions[reason] = np.asarray(image.convert("L")) != 0
        policy_views[aid] = {"version": policy["version"], "hash": policy["policy_hash"],
                             "roles": role_masks, "exclusions": exclusions}
        row["region_policy_version"] = policy["version"]
        row["region_policy_hash"] = policy["policy_hash"]
    for region in session.scalars(select(Region).where(
        Region.processing_run_id.in_([UUID(region_run_ids[aid]) for aid in region_run_ids]),
    )):
        if region.mask_path:
            regions.setdefault(str(region.asset_id), []).append((region.label, region.mask_path))
    cards, rows = [], []
    random_ids, boundary_ids = set(manifest["random_ids"]), set(manifest["boundary_ids"])
    if (not random_ids <= set(ids) or not boundary_ids <= set(ids)
            or type(manifest.get("population", len(ids))) is not int
            or manifest.get("population", len(ids)) < len(ids)):
        raise ValueError("標本群または母数が固定対象と一致しません")
    overlap = random_ids & boundary_ids
    challenge_ids = set(ids) - random_ids
    groups = {"population": manifest.get("population", len(ids)),
              "random": len(random_ids), "challenge": len(challenge_ids)}
    for number, aid in enumerate(ids, 1):
        row = decisions[aid]
        selection = _selection_for(decisions, aid)
        labels = ["固定無作為群"] if aid in random_ids else ["目的抽出challenge群"]
        if aid in overlap:
            labels.append("無作為群から重複除外")
        with Image.open(bundle / "images" / f"{aid}-raw.png") as raw:
            raw_uri = jpeg(raw)
        if digest(row["input_path"]) != row["input_sha256"] or digest(
                row["mask_path"]) != row["mask_sha256"]:
            raise ValueError("固定した解析画像・人物maskが変わっています")
        decision = "採用" if row["decision"] == "accepted" else "目視待ち"
        subject = {"building": "建物", "terrain": "地形", "mixed": "混在",
                   "other": "対象外", "unknown": "不明", None: "未確定"}.get(
                       row["subject"], "未確定")
        with Image.open(row["input_path"]) as prepared:
            input_size = prepared.size
            prepared_uri = jpeg(prepared)
        with Image.open(row["mask_path"]) as person_image:
            if person_image.size != input_size:
                raise ValueError("人物maskと解析画像の座標が一致しません")
            person_mask = np.asarray(person_image.convert("L")) != 0
        gate = gate_views.get(aid, {})
        verdict = row.get("image_gate_verdict") or gate.get("observation") or {}
        people = verdict.get("real_people", row.get("real_people", "未記録"))
        details = {"accepted": "採用", "rejected": "除外", "pending": "保留"}
        gate_decision = gate.get("result") or {}
        gate_state = details.get(row.get("gate_state", gate_decision.get("decision", "")), "未記録")
        gate_reason = gate_decision.get("reason", "未記録")
        identity = gate.get("identity") or {}
        image_review_version = identity.get(
            "policy_version", row.get("image_review_version", "未記録"),
        )
        extras = [f"人物：{html.escape(str(people))}",
                  f"対象：{html.escape(str(verdict.get('target', '未記録')))}",
                  f"白黒：{html.escape(str(verdict.get('black_and_white', '未記録')))}",
                  f"暗所：{html.escape(str(verdict.get('dark', '未記録')))}",
                  f"室内：{html.escape(str(verdict.get('interior', '未記録')))}",
                  f"混在：{html.escape(str(verdict.get('subject', '未記録')))}",
                  f"理由code：{html.escape('・'.join(verdict.get('reason_codes') or ['未記録']))}",
                  f"image-review：{html.escape(str(image_review_version))}",
                  f"schema：{html.escape(str(identity.get('schema_version', '未記録')))}",
                  f"領域policy：{html.escape(str(row.get('region_policy_version', 'raw候補のみ')))}"
                  ]
        parts = [f'''<figure><figcaption>人物mask単独表示（実線輪郭）</figcaption>
<img class="mask" alt="番号{number} 人物mask"
src="{mask_uri(person_mask, input_size)}"></figure>
<figure><figcaption>人物mask輪郭</figcaption>
<img class="outline" alt="番号{number} 人物mask輪郭"
src="{outline_uri(person_mask, input_size)}"></figure>''']
        effective = policy_views.get(aid)
        if effective:
            extras.append(f"region-policy hash：{effective['hash']}")
            for role, mask in sorted(effective["roles"].items()):
                pattern = "dash" if role.startswith("real_terrain/") else "solid"
                parts.append(f'''<figure><figcaption>有効領域単独mask：{html.escape(role)}</figcaption>
<img class="mask" alt="番号{number} {html.escape(role)} 有効mask"
src="{mask_uri(mask, input_size)}"></figure>
<figure><figcaption>有効領域輪郭：{html.escape(role)}</figcaption>
<img class="outline" alt="番号{number} {html.escape(role)} 輪郭"
src="{outline_uri(mask, input_size, pattern=pattern)}"></figure>''')
            exclusion_styles = {"sky": "dash", "person": "dot", "conflict": "dashdot",
                                "semantic_mismatch": "solid", "void": "dot"}
            exclusion_labels = {"sky": "空", "person": "人物", "conflict": "競合void",
                                "semantic_mismatch": "semantic不一致", "void": "void全域"}
            for reason, mask in sorted(effective["exclusions"].items()):
                label = exclusion_labels.get(reason, reason)
                pattern = exclusion_styles.get(reason, "dashdot")
                parts.append(f'''<figure><figcaption>除外mask単独：{html.escape(label)}</figcaption>
<img class="mask" alt="番号{number} {html.escape(reason)} 除外mask"
src="{mask_uri(mask, input_size)}"></figure>
<figure><figcaption>除外mask輪郭：{html.escape(label)}（{pattern}）</figcaption>
<img class="outline" alt="番号{number} {html.escape(reason)} 輪郭"
src="{outline_uri(mask, input_size, pattern=pattern)}"></figure>''')
        else:
            extras.append("region-policy：未記録。以下はraw候補で、有効maskとして判定できません")
        for index, label in enumerate(sorted({label for label, _ in regions.get(aid, [])})
                                      if not effective else []):
            union = np.zeros((input_size[1], input_size[0]), dtype=bool)
            for region_label, path in regions[aid]:
                if region_label == label:
                    with Image.open(path) as image:
                        values = np.asarray(image.convert("L")) != 0
                    if values.shape != union.shape:
                        raise ValueError("部位maskと原画像の座標が一致しません")
                    union |= values
            style = "mask" if index % 2 == 0 else "outline"
            parts.append(f'''<figure><figcaption>raw候補：{html.escape(label)} mask単独</figcaption>
<img class="{style}" alt="番号{number} {html.escape(label)} mask"
src="{mask_uri(union, input_size)}"></figure>
<figure><figcaption>raw候補：{html.escape(label)} 輪郭</figcaption>
<img class="outline" alt="番号{number} {html.escape(label)} 輪郭"
src="{outline_uri(union, input_size, pattern='dash' if index % 2 else 'solid')}"></figure>''')
        cards.append(f'''<article id="n{number}"><h2>番号 {number}：{'・'.join(labels)}</h2>
<p>既存判定：{decision}／{html.escape(REASONS.get(row['reason'], str(row['reason'])))}。
画像ゲート：{gate_state}／{html.escape(str(gate_reason))}。
人物率 {row['person_ratio']:.4%}（膨張後 {row['mask_ratio']:.4%}）、subject：{subject}。</p>
<p>{'／'.join(extras)}</p>
<figure><figcaption>取得画像</figcaption>
<img class="raw" alt="番号{number} 取得画像" src="{raw_uri}" loading="lazy"></figure>
<figure><figcaption>解析画像（maskと同一座標）</figcaption>
<img class="raw" alt="番号{number} 解析画像" src="{prepared_uri}" loading="lazy"></figure>
{''.join(parts)}</article>''')
        rows.append({"number": number, "asset_id": aid, "groups": labels,
                     "input_sha256": row["input_sha256"],
                     **{key: row[key] for key in ("decision", "subject", "reason",
                                                "person_ratio", "mask_ratio")},
                     "image_review_version": row.get("image_review_version"),
                     "image_gate_identity_hash": gate.get("identity_hash"),
                     **_review_references(selection, gate, region_run_ids.get(aid), people),
                     "image_gate_decision": gate_decision.get("decision"),
                     "image_gate_reason": gate_reason,
                     "image_gate_subject": verdict.get("subject"),
                     "real_people": people,
                     "black_and_white": verdict.get("black_and_white"),
                     "dark": verdict.get("dark"),
                     "region_policy_version": row.get("region_policy_version"),
                     "region_policy_hash": row.get("region_policy_hash")})
    files = write_pages(cards, output, group_counts=groups)
    if len(files) != 1:
        raise ValueError("目視確認は容量25 MB以下の単一HTMLにしてください")
    save(output / "number-map.json", {
        "format": "issue114-mobile-v1", "review_manifest_sha256": digest(bundle / "manifest.json"),
        "decisions_sha256": manifest["decisions_sha256"], "groups": groups,
        "rows": rows, "files": files,
    })
    for item in files:
        for row in rows[item["first"] - 1:item["last"]]:
            retention.register_file(session, UUID(row["asset_id"]), host,
                                    output / item["file"], "image_bundle")
    for aid in ids:
        retention.register_file(session, UUID(aid), host,
                                output / "number-map.json", "image_bundle")
    print(json.dumps({"total": len(rows), "files": files}, ensure_ascii=False))


def parse_chat_reply(text, total):
    """担当が確認した定型テキストを読む。理由は分割・解釈せず行単位で保持する。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("全件確認済みの肯定形返信が必要です")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = re.fullmatch(r"全([0-9０-９]+)枚確認済み。?", lines[0])
    if not header or int(header.group(1)) != total:
        raise ValueError("提示件数と一致する全件確認済みの肯定形が必要です")
    if lines[1:] == ["問題なし"]:
        return {"all_reviewed": True, "reply_text": text, "problems": []}
    if len(lines) < 2:
        raise ValueError("問題なし、または1行1件の番号: 理由が必要です")
    problems = []
    for line in lines[1:]:
        found = re.fullmatch(r"([0-9０-９]+)[：:]\s*(\S.*)", line)
        if not found or not 1 <= int(found.group(1)) <= total:
            raise ValueError("問題番号ごとに理由を記載してください")
        number = int(found.group(1))
        if any(problem["number"] == number for problem in problems):
            raise ValueError("問題番号が重複しています")
        problems.append({"number": number, "reason": found.group(2)})
    return {"all_reviewed": True, "reply_text": text, "problems": problems}


def reply_reviews(mapping, manifest, decisions_sha256, reply):
    """定型テキストだけを解析して変換する。辞書入力・未確認・参照変更はValueError。"""
    if (mapping["format"] != "issue114-mobile-v1"
            or mapping["decisions_sha256"] != decisions_sha256
            or mapping["review_manifest_sha256"] != digest(manifest)):
        raise ValueError("番号表と固定した閲覧対象が一致しません")
    review = json.loads(manifest.read_text())
    required = set(review["required_ids"])
    rows = mapping["rows"]
    if ([row["number"] for row in rows] != list(range(1, len(rows) + 1))
            or [row["asset_id"] for row in rows] != sorted(required)):
        raise ValueError("番号表の対象・連番が一致しません")
    originals = {row["asset_id"]: row for row in review["rows"]}
    for row in rows:
        if any(row[key] != value for key, value in originals[row["asset_id"]].items()):
            raise ValueError("番号表の自動判定が閲覧原本と一致しません")
    reply = parse_chat_reply(reply, len(rows))
    problems = {problem["number"]: problem["reason"] for problem in reply["problems"]}
    return {"reviewer": "ユーザー", "confirm_no_errors": not problems,
            "decisions_sha256": decisions_sha256, "chat_reply": reply["reply_text"].strip(),
            "number_map_sha256": hashlib.sha256(
                json.dumps(mapping, sort_keys=True).encode()).hexdigest(),
            "rows": [{"asset_id": row["asset_id"],
                      "decision": "pending" if row["number"] in problems else "same",
                      "subject": row["subject"], "error_found": row["number"] in problems,
                      "note": problems.get(row["number"], "会話で提示画像の確認済み・問題なし"),
                      **{key: row.get(key) for key in (
                          "image_gate_run_id", "region_policy_run_id", "privacy_review_run_id",
                          "presented_source_sha256", "confirmed_real_people",
                      )}}
                     for row in rows]}


def apply_privacy_reply(queue, data):
    """提示の確認を記録する。問題なしでも既存の人物訂正・保留は解除しない。"""
    rows = data["rows"]
    for row in rows:
        if not row.get("privacy_review_run_id") or not row.get("presented_source_sha256"):
            raise ValueError("提示したprivacy review runと原画像SHAが必要です")
        if not row["error_found"] and (
                not row.get("image_gate_run_id") or not row.get("region_policy_run_id")):
            raise ValueError("問題なしの画像にはA/B runが必要です")

    for row in rows:
        if row["error_found"]:
            run_id = privacy_review.record_hold(
                queue, row["asset_id"], row["privacy_review_run_id"],
                code_version="issue120-chat-review-v1", reviewer=data["reviewer"],
                presented_source_sha256=row["presented_source_sha256"], note=row["note"],
            )
        else:
            with queue._transaction() as session:
                original = session.get(ProcessingRun, UUID(row["privacy_review_run_id"]))
                if original is None:
                    raise ValueError("提示したprivacy review runがありません")
                evidence = original.parameters["evidence"]
            run_id = privacy_review.write(
                queue, row["asset_id"], row["image_gate_run_id"],
                row["region_policy_run_id"], code_version="issue120-chat-review-v1",
                input_run_id=row["privacy_review_run_id"], reviewer=data["reviewer"],
                real_people=evidence["real_people"], hold=evidence["human_hold"],
                presented_source_sha256=row["presented_source_sha256"], note=row["note"],
            )
        row["recorded_privacy_review_run_id"] = str(run_id)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "reply"))
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--host", help="保持台帳へ登録する生成先host（省略時は実行host）")
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "reply":
        data = reply_reviews(json.loads(args.mapping.read_text()),
                             args.execution / "review-manifest.json",
                             digest(args.execution / "privacy-decisions.json"),
                             args.input.read_text(encoding="utf-8"))
        if not args.apply:
            save(args.output, data)
            print("番号返信を変換しました。DB接続・書込みなし。")
            return
        from bench.issue105.production import engine

        db = engine(False)
        try:
            apply_privacy_reply(Queue(db), data)
            save(args.output, data)
        finally:
            db.dispose()
        print("番号返信をprivacy review runへ記録しました。")
        return

    from bench.issue105.production import engine

    db = engine(False)
    try:
        build(db, args.bundle, args.execution, args.output, args.taxonomy, host=args.host)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
