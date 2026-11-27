"""必須目視サンプルを単体HTMLにし、番号付きの会話返信を既存取込み形式へ変換する。"""

import argparse
import hashlib
import html
import json
import os
import re
import socket
import tarfile
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

import numpy as np
from bench.issue114.mobile_labels import CODE_NAMES, mask_description
from bench.issue114.privacy import digest, save
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from colorstats import privacy_review, retention
from colorstats.analyze import region_policy as region_policy_contract
from colorstats.api_budget import digest as contract_digest
from colorstats.queue import Queue
from colorstats.review_html import file_uri, jpeg, mask_uri, outline_uri, validate_html
from colorstats.review_html import image_tag as _image
from colorstats.review_html import uri_sha as _uri_sha
from colorstats.schema.models import Asset, ProcessingRun, Region

LIMIT = 12_500_000
FORMAT = "issue114-mobile-v2"
REASONS = {**CODE_NAMES,
           "再提示待ち（自動採用しない）": "人の確認待ち。確認だけで採用に変わることはありません",
           "追加解析後の再提示待ち（統計へ自動採用しない）": "追加の確認作業が済み、人の確認待ち"}
STYLE = """body{margin:0 auto;padding:12px;max-width:800px;font:16px sans-serif;
overflow-wrap:anywhere;box-sizing:border-box}*{box-sizing:border-box}
img{display:block;max-width:100%;height:auto;margin:8px 0}.mask,.outline{image-rendering:pixelated}
article{border-top:2px solid #777;
padding:12px 0}p{line-height:1.6}h2{font-size:1.3rem}figure{margin:0 0 16px}
figcaption{font-weight:bold} .legend{border:1px solid #777;padding:8px} .raw{border:3px solid #222}
.mask{border:3px dashed #176b35}.outline{border:3px dotted #174ea6}
.comparison-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;align-items:start}
.comparison-grid figure{min-width:0;margin:0}.comparison-grid img{width:100%;margin:0}
.comparison-grid figcaption{line-height:1.4;min-height:2.8em}
.photo{background-image:var(--photo);background-size:100% 100%;background-repeat:no-repeat;
background-origin:content-box;background-clip:content-box;border:3px dotted #174ea6}
.photo .outline{border:0}
.mask-comparison{border-top:1px solid #aaa;padding:10px 0}.mask-comparison h3{font-size:1rem}
table{border-collapse:collapse;width:100%;table-layout:fixed}
td,th{border:1px solid #aaa;padding:6px;text-align:left}
th:first-child{width:30%}code{overflow-wrap:anywhere}small{font-size:.75em;font-weight:normal}"""


def explain(value):
    code = str(value)
    text = CODE_NAMES.get(code)
    if text is None and re.search(r"[a-zA-Z]", code):
        text = "この判定の説明はまだありません"
    if text:
        return f'{html.escape(text)} <small><code>{html.escape(code)}</code></small>'
    return html.escape(code)


def mask_section(label, mask, size, *, number, kind, pattern="solid"):
    """同じ座標の写真＋透明な輪郭と二値maskを、縦1列の区画にする。"""
    name, definition = mask_description(label, kind)
    safe_label = html.escape(label)
    category = {"raw": "最初に見つけた部分", "effective": "今回選ばれた部分",
                "exclusion": "使わなかった部分",
                "person": "人のいる場所の確認"}[kind]
    line = {"solid": "つながった線", "dash": "途切れた線", "dot": "点のある線",
            "dashdot": "途切れた線と点"}[pattern]
    outline = _image(outline_uri(mask, size, pattern=pattern, transparent=True),
                     f"番号{number} {name} 写真上の輪郭", "outline")
    binary = _image(mask_uri(mask, size), f"番号{number} {name} 白く示した部分", "mask")
    return f'''<section class="mask-comparison" data-label="{safe_label}" data-kind="{kind}">
<h3>{html.escape(name)} <small><code>{safe_label}</code></small></h3><p>{category}</p>
<p>{html.escape(definition)}</p><div class="comparison-grid">
<figure><figcaption>写真＋輪郭（{line}）</figcaption><div class="photo">{outline}</div></figure>
<figure><figcaption>白い部分が対象</figcaption>{binary}</figure>
</div></section>'''


def _legend(cards):
    entries = sorted(set(re.findall(
        r'<section class="mask-comparison" data-label="([^"]*)" data-kind="([^"]*)"',
        "".join(cards))))
    rows = []
    for label, kind in entries:
        label = html.unescape(label)
        name, definition = mask_description(label, kind)
        rows.append(f'<tr><th>{html.escape(name)}<br><small><code>{html.escape(label)}</code></small></th>'
                    f'<td>{html.escape(definition)}</td></tr>')
    return '<table><caption>示している部分の名前と説明</caption>' + "".join(rows) + '</table>'


def page(cards, first, last, total, groups=None, *, legend=None, view="comparison"):
    counts = groups or {}
    mode = ("もとの写真だけの確認です。自動で調べた結果は載せていません。"
            if view == "raw" else "自動で調べた結果と写真を比較する確認です。")
    return f'''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>#114 写真の確認 {first}–{last}</title><style>{STYLE}</style>
<h1>#114 写真の確認 {first}–{last}／全{total}枚</h1>
<p>{mode}ほかの提示で結果をすでに見た場合、その影響のない確認とは扱いません。</p>
<p>提示{total}枚に対応する標本項目は{counts.get('sample_items', total)}件です。
未提示の保留は{counts.get('nonpresented_holds', 0)}件で、確認済みには含めません。
同じ番号に複数の比較区画がある場合、そのすべてを確認してください。</p>
<p>もとの写真は{counts.get('population', total)}枚です。
確認用に無作為に選んだ写真は{counts.get('random', 0)}枚、
間違いやすい点を確かめるために選んだ写真は{counts.get('challenge', 0)}枚です。
同じ写真は一度だけ数えています。
選び方が違うので、まとめて全体の正しさを判断するための割合は出しません。</p>
<p>すべてのファイルの、すべての番号を確認してください。人の見落とし、白く示した場所の過不足、
写っているものや部位の見分け間違いがあれば、番号と理由をチャットで教えてください。
全件確認後、最初の行に「全{total}枚確認済み」、次の行に「問題なし」と返信してください。
問題がある場合は「問題なし」の代わりに「7: 人の見落とし」のように、1行に1件ずつ書いてください。
途中の確認は完了扱いにしません。別のファイルを作って送る必要はありません。</p>
<p class="legend">比較区画の上は写真と輪郭線、下は同じ場所を白く示した図です。
線の場所以外は写真の色を隠しません。
「最初に見つけた部分」は、周りとの関係を確かめる前の表示です。
「今回選ばれた部分」は、その関係を確かめ、空・人や、別の部位と重なって決められない部分を取り除いた表示です。
壁の中の細かな区別どうしや、木の枝葉と幹は、重なっていてもまとめて使います。
自動の見分け方には間違いがあります。線や白い場所を正解だと思い込まず、写真と比べてください。
木の枝葉と幹、壁の細かな区別まで正しいとは限りません。
確認待ちの写真は、問題なしと答えても自動で採用に変わりません。</p>
{_legend(cards) if legend is None else legend}
{''.join(cards)}</html>'''


def write_pages(cards, output, limit=LIMIT, group_counts=None, *, view="comparison"):
    """UTF-8の実byte数で上限を守り、通し番号を維持して分割する。"""
    groups, current, first = [], [], 1
    legend = _legend(cards)
    sizes = [len(card.encode()) for card in cards]
    total = sum(sizes)
    header = len(page([], 1, len(cards), len(cards), group_counts,
                      legend=legend, view=view).encode())
    if header + total > limit:
        candidates, prefix = [], 0
        for cut, size in enumerate(sizes[:-1], 1):
            prefix += size
            left = prefix + len(page([], 1, cut, len(cards), group_counts,
                                     legend=legend, view=view).encode())
            right = total - prefix + len(page(
                [], cut + 1, len(cards), len(cards), group_counts, legend=legend, view=view,
            ).encode())
            if max(left, right) <= limit:
                candidates.append((abs(left - right), cut))
        if candidates:
            cut = min(candidates)[1]
            groups = [(1, cut, cards[:cut]), (cut + 1, len(cards), cards[cut:])]
    for number, card in enumerate([] if groups else cards, 1):
        if len(page(current + [card], first, number, len(cards), group_counts,
                    legend=legend, view=view).encode()) > limit:
            if not current:
                raise ValueError("1画像分のHTMLが容量上限を超えました")
            groups.append((first, number - 1, current))
            current, first = [], number
        current.append(card)
    if current:
        groups.append((first, len(cards), current))
    files = []
    for part, (first, last, group) in enumerate(groups, 1):
        content = page(group, first, last, len(cards), group_counts,
                       legend=legend, view=view).encode()
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
    run = privacy_review.review(session, asset_id, run_id) if run_id else None
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


def review_partition(manifest):
    """固定標本を提示項目と未提示保留の非交和へ照合し、保留参照を返す。"""
    shown = manifest["required_ids"]
    holds = manifest.get("nonpresented_holds", [])
    held = [row["asset_id"] for row in holds]
    if (len(shown) != len(set(shown)) or len(held) != len(set(held))
            or set(shown) & set(held)):
        raise ValueError("提示と未提示保留の対象に重複があります")
    sampling = manifest.get("sampling")
    if sampling:
        required = sampling["required_ids"]
        if (len(required) != len(set(required))
                or set(required) != set(shown) | set(held)):
            raise ValueError("固定標本と提示・未提示保留の対象が一致しません")
    elif holds:
        raise ValueError("未提示保留には固定標本が必要です")
    return holds


def nonpresented_reviews(session, manifest):
    """未提示項目の現行human holdを検証し、採用しないrun参照だけを返す。"""
    references = {}
    for row in review_partition(manifest):
        if not row.get("privacy_review_run_id"):
            raise ValueError("未提示保留にはrun参照が必要です")
        run = privacy_review.review(session, row["asset_id"], row["privacy_review_run_id"])
        p = run.parameters
        if (p["method"] != "human" or not p["reviewer"] or not p["note"]
                or not p["evidence"]["human_hold"] or p["verdict"]["decision"] != "pending"):
            raise ValueError("未提示項目には現在有効な理由付きhuman holdが必要です")
        references[row["asset_id"]] = str(run.id)
    return references


def _numbered_rows(rows):
    groups, sources, assets = {}, {}, set()
    for row in rows:
        number, aid, sha = row["number"], row["asset_id"], row["presented_source_sha256"]
        if (type(number) is not int or number < 1 or number > len(groups) + 1
                or aid in assets or not isinstance(sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", sha)):
            raise ValueError("番号表の対象・連番・原画像SHAが不正です")
        if (sha in sources and sources[sha] != number
                or number in groups and groups[number][0]["presented_source_sha256"] != sha):
            raise ValueError("番号と原画像SHAの対応が一致しません")
        assets.add(aid)
        sources[sha] = number
        groups.setdefault(number, []).append(row)
    if not groups:
        raise ValueError("提示項目が必要です")
    return groups


class _Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events = []

    def handle_starttag(self, tag, attrs):
        self.events.append(("start", tag, sorted(
            (key, value) for key, value in attrs if key != "data-sample-sha256"
        )))

    def handle_endtag(self, tag):
        self.events.append(("end", tag))

    def handle_data(self, data):
        self.events.append(("text", data))

    def handle_comment(self, data):
        self.events.append(("comment", data))


def _presentation_digest(content):
    parser = _Markup()
    parser.feed(content)
    parser.close()
    return contract_digest(parser.events)


class _PresentedItems(_Markup):
    def __init__(self):
        super().__init__()
        self.number = None
        self.items, self.sources, self.contents = {}, {}, {}
        self.stack = []
        self.sample = None

    def handle_starttag(self, tag, attrs):
        start = len(self.events)
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag == "html" and (self.stack or attrs != {"lang": "ja"}):
            raise ValueError("比較内容の外側が生成時の構造と一致しません")
        if tag == "article":
            if self.number is not None or self.stack != ["html"]:
                raise ValueError("比較内容の番号を別の要素で囲めません")
            self.number = int(attrs["id"][1:])
            if attrs != {"id": f"n{self.number}"}:
                raise ValueError("比較内容の番号に表示属性を追加できません")
            self.items[self.number], self.sources[self.number] = [], []
            self.contents[self.number] = []
        if self.number is not None:
            if token := attrs.get("data-sample-sha256"):
                if tag != "section" or self.stack != ["html", "article"]:
                    raise ValueError("比較内容の項目を別の要素で囲めません")
                self.items[self.number].append(token)
                self.sample = (len(self.stack), start)
            if tag == "img" and "raw" in attrs.get("class", "").split():
                self.sources[self.number].append(attrs["data-sha256"])
        if tag not in {"meta", "img", "br"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("比較内容の要素の対応が一致しません")
        if self.sample is not None and len(self.stack) == self.sample[0]:
            self.contents[self.number].append(contract_digest(self.events[self.sample[1]:]))
            self.sample = None
        if tag == "article":
            if self.sample is not None:
                raise ValueError("提示項目の比較内容が閉じられていません")
            self.number = None


def _private_output(output):
    if output.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("確認用ファイルは公開リポジトリ外のprivate領域へ保存してください")


def build(db, bundle, execution, output, taxonomy, *, host=None, require_contracts=True,
          view="comparison"):
    """保持ロック下で利用可否を確認し、画像入りHTMLと番号表を保持登録する。"""
    _private_output(output)
    if view not in {"raw", "comparison"}:
        raise ValueError("確認方法はrawまたはcomparisonを指定してください")
    manifest = json.loads((bundle / "manifest.json").read_text())
    created = False
    try:
        with Session(db) as session, session.begin():
            retention.lock(session)
            for aid in manifest["required_ids"]:
                retention.assert_usable(session, UUID(aid), images=True)
            nonpresented_reviews(session, manifest)
            output.mkdir(mode=0o700, exist_ok=False)
            created = True
            _build(session, manifest, bundle, execution, output, taxonomy,
                   host or socket.gethostname(), require_contracts, view)
    except BaseException:
        if created:
            for path in output.iterdir():
                path.unlink()
            output.rmdir()
        raise


def _render(session, manifest, bundle, execution, taxonomy, require_contracts, view="comparison"):
    if manifest["decisions_sha256"] != digest(execution / "privacy-decisions.json"):
        raise ValueError("閲覧manifestと自動判定が一致しません")
    decision_rows = json.loads((execution / "privacy-decisions.json").read_text())
    decisions = {row["asset_id"]: row for row in decision_rows}
    if len(decisions) != len(decision_rows):
        raise ValueError("自動判定に重複した項目があります")
    ids = sorted(manifest["required_ids"])
    if len(ids) != len(set(ids)):
        raise ValueError("提示対象に重複したassetがあります")
    regions = {}
    policy_views = {}
    gate_views = {}
    privacy_views = {}
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
            privacy_run = validate_presentation_run(session, UUID(aid), selection)
            privacy_views[aid] = privacy_run.parameters
            evidence = privacy_run.parameters["evidence"]
            if (row["input_sha256"] != evidence["input_sha256"]
                    or row["mask_sha256"] != evidence["person_mask_sha256"]):
                raise ValueError("提示する入力・人物maskとprivacy根拠が一致しません")
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
    ids = sorted(random_ids) + sorted(challenge_ids)
    seen_sources = {}
    for aid in ids:
        row = decisions[aid]
        selection = _selection_for(decisions, aid)
        labels = ["固定無作為群"] if aid in random_ids else ["目的抽出challenge群"]
        display_labels = (["無作為に選んだ写真"] if aid in random_ids
                          else ["間違いやすい点を確かめる写真"])
        if aid in overlap:
            labels.append("無作為群から重複除外")
            display_labels.append("両方の選び方に当てはまるので一度だけ表示")
        raw_path = (Path(session.get(Asset, UUID(aid)).storage_path) if require_contracts
                    else bundle / "images" / f"{aid}-raw.png")
        raw_uri = file_uri(raw_path)
        source_sha256 = _uri_sha(raw_uri)
        first_source = source_sha256 not in seen_sources
        if first_source:
            seen_sources[source_sha256] = (raw_uri, len(seen_sources) + 1)
        elif seen_sources[source_sha256][0] != raw_uri:
            raise ValueError("同一SHAの取得画像byteが一致しません")
        number = seen_sources[source_sha256][1]
        if require_contracts and source_sha256 != gate_views[aid]["source_sha256"]:
            raise ValueError("提示する取得画像と原画像SHAが一致しません")
        if digest(row["input_path"]) != row["input_sha256"] or digest(
                row["mask_path"]) != row["mask_sha256"]:
            raise ValueError("固定した解析画像・人物maskが変わっています")
        decision = "採用" if row["decision"] == "accepted" else "確認待ち"
        subject = {"building": "建物", "terrain": "地形", "mixed": "建物と地形が混じっている",
                   "other": "確認の対象外", "unknown": "不明", None: "まだ決まっていない"}.get(
                       row["subject"], "まだ決まっていない")
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
        gate_decision = gate.get("result") or {}
        gate_state = row.get("gate_state", gate_decision.get("decision", "未記録"))
        gate_reason = gate_decision.get("reason", "未記録")
        privacy = privacy_views.get(aid, {})
        privacy_policy = privacy.get("evidence", {}).get("policy", {})
        privacy_verdict = privacy.get("verdict", {})
        reasons = '・'.join(explain(code) for code in verdict.get('reason_codes') or ['未記録'])
        extras = [f"人物：{explain(people)}",
                  f"対象：{explain(verdict.get('target', '未記録'))}",
                  f"白黒：{explain(verdict.get('black_and_white', '未記録'))}",
                  f"暗所：{explain(verdict.get('dark', '未記録'))}",
                  f"室内：{explain(verdict.get('interior', '未記録'))}",
                  f"上空写真：{explain(verdict.get('aerial_view', '未記録'))}",
                  f"何が中心に写っているか：{explain(verdict.get('subject', '未記録'))}",
                  f"判断の理由：{reasons}"
                  ]
        if privacy:
            extras.append(f"人物の採否：{explain(privacy_verdict['decision'])}／"
                          f"{explain(privacy_verdict['reason'])}。"
                          f"人の確認を含む人物の記録："
                          f"{explain(privacy['evidence']['real_people'])}")
        versions = ["image-review-v1", row.get("region_policy_version"),
                    privacy_policy.get("version")]
        version_text = '／'.join(f'<small><code>{html.escape(v)}</code></small>'
                                for v in versions if v)
        parts = [mask_section("person", person_mask, input_size, number=number, kind="person")]
        effective = policy_views.get(aid)
        if effective:
            for role, mask in sorted(effective["roles"].items()):
                pattern = "dash" if role.startswith("real_terrain/") else "solid"
                parts.append(mask_section(role, mask, input_size, number=number,
                                          kind="effective", pattern=pattern))
            exclusion_styles = {"sky": "dash", "person": "dot", "conflict": "dashdot",
                                "semantic_mismatch": "solid", "void": "dot"}
            for reason, mask in sorted(effective["exclusions"].items()):
                pattern = exclusion_styles.get(reason, "dashdot")
                parts.append(mask_section(reason, mask, input_size, number=number,
                                          kind="exclusion", pattern=pattern))
        else:
            extras.append("周りとの関係を確かめた記録がありません。以下は最初に見つけた場所の表示だけです")
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
            parts.append(mask_section(label, union, input_size, number=number, kind="raw",
                                      pattern='dash' if index % 2 else 'solid'))
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
                     "privacy_review_hash": selection.get("privacy_review_hash"),
                     "privacy_policy_version": privacy_policy.get("version"),
                     "view": view,
                     "black_and_white": verdict.get("black_and_white"),
                     "dark": verdict.get("dark"),
                     "region_policy_version": row.get("region_policy_version"),
                     "region_policy_hash": row.get("region_policy_hash")})
        rows[-1]["presented_source_sha256"] = source_sha256
        card = f'''<article id="n{number}" style="--photo:url('{prepared_uri}')"
data-photo-sha256="{_uri_sha(prepared_uri)}"><h2>番号 {number}：{'・'.join(display_labels)}</h2>
<p>これまでの判断：{decision}／{html.escape(REASONS.get(row['reason'], str(row['reason'])))}。
写真全体を見た判断：{explain(gate_state)}／{explain(gate_reason)}。
人と判定された広さは写真の {row['person_ratio']:.4%}（人として示す広さ {row['mask_ratio']:.4%}）、
中心に写っているもの：{subject}。</p>
<p>{'／'.join(extras)}</p>
<p>判定の版：{version_text}</p>
<details><summary>もとの写真を開く（自動で調べる前の写真）</summary>
<figure><figcaption>もとの写真</figcaption>
{_image(raw_uri, f'番号{number} もとの写真', 'raw')}</figure></details>
<p>以下は自動で調べた写真です。上下で同じ場所を比べられます。</p>
{''.join(parts)}</article>'''
        if view == "raw":
            card = (f'<article id="n{number}"><h2>番号 {number}：'
                         f'{"・".join(display_labels)}</h2><figure><figcaption>もとの写真</figcaption>'
                         f'{_image(raw_uri, f"番号{number} もとの写真", "raw")}</figure></article>')

        if not first_source:
            pattern = r"<figure>.*?</figure>" if view == "raw" else r"<details>.*?</details>"
            card = re.sub(pattern, "", card, flags=re.S)
        card = card.replace(f'<article id="n{number}"', '<section', 1)
        card = card.replace("</article>", "</section>")
        card = f'<section>{card}</section>'
        rows[-1]["presentation_sha256"] = _presentation_digest(card)
        token = contract_digest(rows[-1])
        card = card.replace('<section>', f'<section data-sample-sha256="{token}">', 1)
        if first_source:
            cards.append(f'<article id="n{number}">{card}</article>')
        else:
            cards[number - 1] = (cards[number - 1].removesuffix("</article>")
                                 + '<p>同じ原画像に対応する別の確認項目です。</p>'
                                 + card + "</article>")
    random_numbers = {row["number"] for row in rows if row["asset_id"] in random_ids}
    groups.update(random=len(random_numbers), challenge=len(cards) - len(random_numbers),
                  sample_items=len(rows),
                  nonpresented_holds=len(manifest.get("nonpresented_holds", [])))
    return cards, rows, groups


def _build(session, manifest, bundle, execution, output, taxonomy, host, require_contracts, view):
    cards, rows, groups = _render(session, manifest, bundle, execution, taxonomy, require_contracts,
                                view)
    files = write_pages(cards, output, group_counts=groups, view=view)
    for item in files:
        validate_html((output / item["file"]).read_text(encoding="utf-8"),
                      range(item["first"], item["last"] + 1), limit=LIMIT, style=STYLE)
    save(output / "number-map.json", {
        "format": FORMAT, "review_manifest_sha256": digest(bundle / "manifest.json"),
        "decisions_sha256": manifest["decisions_sha256"], "groups": groups,
        "rows": rows, "files": files,
    })
    for item in files:
        for row in rows:
            if not item["first"] <= row["number"] <= item["last"]:
                continue
            retention.register_file(session, UUID(row["asset_id"]), host,
                                    output / item["file"], "image_bundle")
    for row in rows:
        aid = row["asset_id"]
        retention.register_file(session, UUID(aid), host,
                                output / "number-map.json", "image_bundle")
    print(json.dumps({"total": len(cards), "sample_items": len(rows), "files": files},
                     ensure_ascii=False))


def validate_delivery(mapping, directory):
    """固定番号表と送付HTMLの実byte・SHA・連番・埋込画像を照合する。"""
    if mapping["format"] != FORMAT:
        raise ValueError("提示番号表を現行形式で再生成してください")
    groups = _numbered_rows(mapping["rows"])
    expected = 1
    for item in mapping["files"]:
        if (not re.fullmatch(r"review-[0-9]+\.html", item["file"])
                or item["first"] != expected or item["last"] < expected
                or item["last"] > len(groups)):
            raise ValueError("提示HTMLのファイル名・番号範囲が一致しません")
        raw = (directory / item["file"]).read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("提示HTMLのbyte数・SHAが一致しません")
        validate_html(raw.decode("utf-8"), range(item["first"], item["last"] + 1),
                      limit=LIMIT, style=STYLE)
        presented = _PresentedItems()
        presented.feed(raw.decode("utf-8"))
        presented.close()
        for number in range(item["first"], item["last"] + 1):
            rows = groups[number]
            if (presented.items[number] != [contract_digest(row) for row in rows]
                    or presented.sources[number] != [rows[0]["presented_source_sha256"]]):
                raise ValueError("提示HTMLと番号表の原画像・項目区画が一致しません")
            if presented.contents[number] != [row["presentation_sha256"] for row in rows]:
                raise ValueError("提示HTMLと番号表の比較内容SHAが一致しません")
        expected = item["last"] + 1
    if expected != len(groups) + 1 or not mapping["files"]:
        raise ValueError("提示HTMLの全番号が揃っていません")


def share(db, source, output, *, host=None):
    """新しい私有HTMLコピー・番号表・送付tarを、既存保持台帳へ登録する。

    tarに入れるのはHTMLだけ。画像のいずれかが失効したら共有束全体が削除対象になる。
    出力は未使用のリポジトリ外ディレクトリ。失敗時は今回の新規出力だけを取り除く。
    """
    _private_output(output)
    mapping = json.loads((source / "number-map.json").read_text(encoding="utf-8"))
    created = False
    try:
        with Session(db) as session, session.begin():
            retention.lock(session)
            for row in mapping["rows"]:
                retention.assert_usable(session, UUID(row["asset_id"]), images=True)
            validate_delivery(mapping, source)
            output.mkdir(mode=0o700, exist_ok=False)
            created = True
            save(output / "number-map.json", mapping)
            for item in mapping["files"]:
                path = output / item["file"]
                with path.open("xb") as stream:
                    stream.write((source / item["file"]).read_bytes())
                path.chmod(0o600)
            validate_delivery(mapping, output)
            archive = output / "review.tar"
            with tarfile.open(archive, "x") as stream:
                for item in mapping["files"]:
                    stream.add(output / item["file"], arcname=item["file"], recursive=False)
            archive.chmod(0o600)
            for row in mapping["rows"]:
                aid = UUID(row["asset_id"])
                paths = [output / "number-map.json", archive]
                paths.extend(output / item["file"] for item in mapping["files"]
                             if item["first"] <= row["number"] <= item["last"])
                for path in paths:
                    retention.register_file(session, aid, host or socket.gethostname(),
                                            path, "image_bundle")
    except BaseException:
        if created:
            for path in output.iterdir():
                path.unlink()
            output.rmdir()
        raise
    return mapping


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


def reply_reviews(mapping, manifest, decisions_sha256, reply, *, directory=None):
    """定型テキストだけを解析して変換する。辞書入力・未確認・参照変更はValueError。"""
    if (mapping["format"] != FORMAT
            or mapping["decisions_sha256"] != decisions_sha256
            or mapping["review_manifest_sha256"] != digest(manifest)):
        raise ValueError("番号表と固定した閲覧対象が一致しません")
    review = json.loads(manifest.read_text())
    if directory is not None:
        validate_delivery(mapping, directory)
    holds = review_partition(review)
    required = set(review["required_ids"])
    rows = mapping["rows"]
    groups = _numbered_rows(rows)
    if ([row["asset_id"] for row in rows] != (
                sorted(set(review.get("random_ids", [])))
                + sorted(required - set(review.get("random_ids", []))))):
        raise ValueError("番号表の対象・連番が一致しません")
    originals = {row["asset_id"]: row for row in review["rows"]}
    if len(originals) != len(review["rows"]) or set(originals) != required:
        raise ValueError("閲覧原本の提示項目に重複・欠落・余分があります")
    for row in rows:
        if any(row[key] != value for key, value in originals[row["asset_id"]].items()):
            raise ValueError("番号表の自動判定が閲覧原本と一致しません")
    reply = parse_chat_reply(reply, len(groups))
    problems = {problem["number"]: problem["reason"] for problem in reply["problems"]}
    return {"reviewer": "ユーザー", "confirm_no_errors": not problems,
            "nonpresented_holds": holds,
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
    shown = [row["asset_id"] for row in rows]
    held = {row["asset_id"] for row in data.get("nonpresented_holds", [])}
    if len(shown) != len(set(shown)) or set(shown) & held:
        raise ValueError("返信の提示項目に重複または未提示項目があります")
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
    parser.add_argument("action", choices=("build", "reply", "share"))
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--view", choices=("raw", "comparison"), default="comparison")
    parser.add_argument("--host", help="保持台帳へ登録する生成先host（省略時は実行host）")
    args = parser.parse_args()
    if args.action != "share" and args.execution is None:
        parser.error("build/replyには--executionが必要です")
    _private_output(args.output)
    os.umask(0o077)
    if args.action == "reply":
        data = reply_reviews(json.loads(args.mapping.read_text()),
                             args.execution / "review-manifest.json",
                             digest(args.execution / "privacy-decisions.json"),
                             args.input.read_text(encoding="utf-8"), directory=args.mapping.parent)
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
        if args.action == "share":
            if args.bundle is None:
                parser.error("shareには生成済み提示物の--bundleが必要です")
            share(db, args.bundle, args.output, host=args.host)
        else:
            build(db, args.bundle, args.execution, args.output, args.taxonomy, host=args.host,
                  view=args.view)
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
