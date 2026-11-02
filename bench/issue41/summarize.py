"""完了済みの公開評価とモデル判定を集計し、JSONと要約表を保存する。"""

import csv
import hashlib
import json
from pathlib import Path

from colorstats.judgment_inputs import summarize_judgments, validate_judgment


def summarize_results(root):
    data = root.parent.parent / "data/issue41"
    judgments_root = root / "judgments"
    sources = {}

    def read(path):
        sources[str(path.relative_to(root.parent.parent)).replace("\\", "/")] = (
            hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest())
        return json.loads(path.read_text(encoding="utf-8"))

    schema = read(root / "judgment.schema.json")
    selection_path = data / "gold100/selection.csv"
    sources["data/issue41/gold100/selection.csv"] = hashlib.sha256(
        selection_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    with selection_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selection = {r["asset_id"]: r for r in rows}
    inputs, judgments, executions = {}, {}, []
    for index in range(1, 11):
        directory = data / f"judge/batch-{index:02d}"
        batch_input = read(directory / "input.json")
        result = read(judgments_root / f"batch-{index:02d}.json")
        validate_judgment(result, batch_input, schema)
        if result["repeat_of"] is not None:
            raise ValueError("初回判定のrepeat_ofはnullが必要です")
        for image in result["images"]:
            if image["asset_id"] in judgments:
                raise ValueError("バッチ間でasset_idが重複しています")
            judgments[image["asset_id"]] = image
        inputs.update({i["asset_id"]: i for i in batch_input["images"]})
        executions.append({k: result[k]
                           for k in ("batch_id", "model", "execution_id", "repeat_of")})
    if len(selection) != len(rows) or selection.keys() != judgments.keys():
        raise ValueError("selectionと判定の画像が一致しません")
    for aid, image in inputs.items():
        if any(image[k] != selection[aid][k] for k in
               ("building_id", "building_evidence", "title", "source_url")):
            raise ValueError("selectionと判定入力の同定候補が一致しません")
    repeat_input = read(data / "judge/repeat/input.json")
    repeat = read(judgments_root / "repeat.json")
    validate_judgment(repeat, repeat_input, schema)
    repeated = {i["asset_id"]: i for i in repeat["images"]}
    plan = read(data / "judge/repeat-plan.json")
    if set(repeated) != set(plan["images"]) or len(repeated) != len(rows[::10]):
        raise ValueError("二重判定の画像が事前計画と一致しません")
    if set(repeated) != {r["asset_id"] for r in rows[::10]}:
        raise ValueError("二重判定の画像がselectionの固定抽出と一致しません")
    for image in repeat_input["images"]:
        if image != inputs[image["asset_id"]]:
            raise ValueError("二重判定の入力が初回入力と一致しません")
    if repeat["repeat_of"] is None or repeat["execution_id"] in {
            e["execution_id"] for e in executions}:
        raise ValueError("二重判定には別実行とrepeat_ofが必要です")
    executions.append({k: repeat[k] for k in ("batch_id", "model", "execution_id", "repeat_of")})
    summary, identity = summarize_judgments(inputs, judgments, repeated, selection)
    summary.update({"sources_sha256": sources, "executions": executions,
                    "definitions": {
                        "verdict": "各draft_idを1件とする領域加重集計。重複マスクも別候補。",
                        "missed_major_parts": "同一画像の同一labelは1件。"
                                              "主要部位の見落とし報告数。",
                        "repeat": "verdictは完全一致領域数/比較領域数。画像別も同式。"
                                  "見落としはlabel集合、building_nameはnullを含む完全一致。",
                    }})
    identity["executions"] = executions[:-1]
    # 同定結果は判定時の保存先を出典とする既存形式を維持する。
    identity["sources_sha256"] = {
        (f"data/issue41/judge/{Path(path).stem}/judgment.json"
         if path.startswith("bench/issue41/judgments/") else path): value
        for path, value in sources.items()}
    (judgments_root / "building-identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "judgment-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def judgment_tables(summary, identity_path="judgments/building-identity.json"):
    lines = ["## 自前100枚のモデル判定（フェーズB・C）", "",
             "初回100枚を集計し、二重判定10枚は一致率だけに使用する。人手正解ではない。", "",
             "| 層 | 画像 | 領域 | correct | wrong_label | spill | not_present |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, values in [("全体", {"images": len(summary["images"]), **summary["overall"]}),
                         *summary["domains"].items()]:
        rates = " | ".join(f"{values['counts'][v]} ({values['rates'][v]:.2%})"
                           for v in values["rates"])
        lines.append(f"| {name} | {values['images']} | {values['regions']} | {rates} |")
    lines += ["", "| ラベル | 領域 | correct | wrong_label | spill | not_present | "
              "見落とし画像数 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for label in sorted(summary["labels"].keys() | summary["missed_major_parts"].keys()):
        values = summary["labels"].get(label)
        rates = (" | ".join(f"{values['counts'][v]} ({values['rates'][v]:.2%})"
                            for v in values["rates"]) if values else "— | — | — | —")
        lines.append(f"| {label} | {values['regions'] if values else 0} | {rates} | "
                     f"{summary['missed_major_parts'].get(label, 0)} |")
    lines += ["", "領域数を分母とする。面積加重・画像平均ではなく、同一マスクの候補も別に数える。",
              "見落としは画像内のlabelを集合化した件数で、部位の総数や再現率ではない。", "",
              "### 二重判定", "", "| 指標 | 一致 / 比較数 | 一致率 |",
              "| --- | ---: | ---: |"]
    for key in ("verdict", "missed_major_parts", "building_name"):
        value = summary["repeat"][key]
        lines.append(f"| {key} | {value['matches']} / {value['total']} | {value['rate']:.2%} |")
    lines += ["", "| asset_id | verdict一致 / 領域数 | 一致率 | 見落としlabel集合一致 | 名称一致 |",
              "| --- | ---: | ---: | --- | --- |"]
    for aid, value in summary["repeat"]["images"].items():
        score = value["verdict"]
        rate = "—" if score["rate"] is None else f"{score['rate']:.2%}"
        lines.append(f"| {aid} | {score['matches']} / {score['total']} | {rate} | "
                     f"{value['missed_major_parts_equal']} | {value['building_name_equal']} |")
    identity = summary["identity"]
    lines += ["", "### 同一建築の同定", "",
              f"名称あり{identity['named_images']}枚、名称{identity['distinct_names']}種。"
              f"複数画像の同名群は{len(identity['repeated_groups'])}群。", "",
              "| building_name | 枚数 | asset_id |", "| --- | ---: | --- |"]
    for group in identity["repeated_groups"]:
        lines.append(f"| {group['building_name']} | {len(group['asset_ids'])} | "
                     f"{', '.join(group['asset_ids'])} |")
    lines += ["", f"既存building_idとの群構成比較: `{identity['comparison_counts']}`。",
              "名称の意味的一致は自動判定しない。matchは同名群と既存ID群のasset集合一致、",
              "not_groupedは両方が単独、unresolvedは既存候補あり・名称null。",
              "全100枚の名称・判定根拠・既存候補・群比較は",
              f"[保存版]({identity_path})に保存し、#46へ引き継ぐ。", "",
              "| 既存の複数画像候補 | 枚数 | 群比較（画像数） |",
              "| --- | ---: | --- |"]
    for group in identity["candidate_groups"]:
        lines.append(f"| {group['building_id']} | {len(group['asset_ids'])} | "
                     f"{group['comparisons']} |")
    lines += ["", "未同定を不一致や同定成功に数えない。", "",
              "### 限界", "",
              "モデル判定であり人手正解ではない。二重判定は同一モデル内の再現性だけを示し、",
              "正確さや独立した判定者間の一致を保証しない。名称null同士も一致に含む。",
              "初回の根拠を採用し、再判定による多数決・修正は行わない。",
              "同名群は判定者の記録をまとめたもので、同名だけで同一建築が証明されるわけではない。",
              "固定10枚の再判定であり、無作為標本ではない。画像・領域の相関と重複候補があるため、",
              "全体correct率を新規画像の精度や画素IoUとして解釈しない。", ""]
    return lines


def main():
    root = Path(__file__).resolve().parent
    mapping_hash = hashlib.sha256(
        (root / "label-map.yaml").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    reports = {}
    manifests = {}
    for dataset in ("cmp", "ade"):
        report = json.loads((root / f"{dataset}-report.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / f"{dataset}-dataset-manifest.json").read_text(
            encoding="utf-8"))
        if (not report["complete"] or report["completed"] != manifest["selected_count"]
                or report["settings"]["mapping_sha256"] != mapping_hash):
            raise ValueError("評価が未完了、またはmanifest・対応表と一致しません")
        reports[dataset], manifests[dataset] = report, manifest
    lines = [
        "# Issue #41 評価・モデル判定の実測結果", "",
        "対象はsam2-dinoのみ。人手修正は行わず、公開正解の画素評価とモデル判定を分ける。",
        "条件・限界・再実行は[評価手順](../../docs/evaluation.md)参照。", "",
        "## 取得データ", "", "保存先: ubuntu-2 `/mnt/data/work/issue-41/public/`。",
        "画像・正解PNG・予測マスクはGitに含めない。", "",
        "| ZIP | 画像数 | 取得日時（UTC） | SHA-256 |",
        "| --- | ---: | --- | --- |",
    ]
    for manifest in manifests.values():
        for archive in manifest["archives"]:
            lines.append(f"| {archive['filename']} | {archive['image_count']} | "
                         f"{archive['retrieved_at_utc']} | `{archive['sha256']}` |")
    lines += ["", "ADEはvalidation 2,000枚の元解像度マスクから617枚を固定条件で選定。",
              "選定画像一覧・評価外クラスは各dataset-manifest.json、実行設定は各report.json。", ""]
    for dataset, report in reports.items():
        coverage = report["coverage"]
        lines += [f"## {dataset.upper()}（{report['completed']}枚）", "",
                  f"対応領域: {coverage['valid_pixels']:,}/{coverage['total_pixels']:,}画素 "
                  f"({coverage['valid_pixels'] / coverage['total_pixels']:.2%})。"
                  f"評価可能画素0の画像: {len(coverage['zero_valid_images'])}枚。", "",
                  "| ラベル | IoU | 適合率 | 再現率 | 正解画素数 |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for label, values in report["labels"].items():
            metrics = ["—" if values[k] is None else f"{values[k]:.4f}"
                       for k in ("iou", "precision", "recall")]
            lines.append(f"| {label} | {' | '.join(metrics)} | {values['tp'] + values['fn']:,} |")
        supported = [v["iou"] for v in report["labels"].values()
                     if v["tp"] + v["fn"] > 0]
        lines += ["", f"正解が存在するラベルの単純平均IoU: {sum(supported)/len(supported):.4f}。",
                  "指標は対応する正解領域内だけの集計。評価外領域へのはみ出しは罰しない。", ""]
    judge = json.loads((root / "judge-input-summary.json").read_text(encoding="utf-8"))
    lines += ["## 判定用入力", "",
              "Git保存版の判定結果は`judgments/batch-01.json`〜`batch-10.json`と",
              "`judgments/repeat.json`。集計の再生成には、別途保管した",
              "`data/issue41`の入力・selection・repeat-planも必要。",
              "入力全100枚・2,934領域を照合済み。",
              "各バッチは一覧JPEG10枚とJSON・schema・プロンプト・同定候補・語彙。", "",
              "| バッチ | 領域数 | 画像容量（MiB） | 概算入力トークン（画像＋文書） |",
              "| --- | ---: | ---: | ---: |"]
    for batch in judge["batches"]:
        tokens = batch["estimated_image_tokens"] + batch["estimated_text_tokens"]
        lines.append(f"| {batch['batch_id']} | {batch['regions']} | "
                     f"{batch['image_bytes']/1024**2:.2f} | {tokens:,} |")
    lines += ["", judge["token_estimate"], ""]
    summary = summarize_results(root)
    tables = judgment_tables(summary)
    lines += tables
    (root / "results.md").write_text("\n".join(lines), encoding="utf-8")
    document = root.parent.parent / "docs/evaluation.md"
    text = document.read_text(encoding="utf-8")
    marker = "\n## 自前100枚のモデル判定（フェーズB・C）\n"
    text = text.split(marker)[0].rstrip() + "\n\n" + "\n".join(
        judgment_tables(summary, "../bench/issue41/judgments/building-identity.json"))
    document.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
