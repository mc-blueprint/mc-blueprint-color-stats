"""固定コホートの区分を再評価する。元ライセンス・出典・解析runは変更しない。"""

from collections import Counter
from copy import deepcopy
from urllib.parse import urlsplit

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from colorstats.rights import analysis_review_reasons
from colorstats.schema.models import Asset, Source
from colorstats.stats.licenses import exclusion_reasons
from colorstats.stats.snapshot import canonical, digest

RIGHTS_KEYS = (
    "rights_basis", "rights_review", "attribution_required", "access_scope",
    "image_redistribution", "retention",
)


def assessment(asset, source, policy):
    """元表記の完全一致と確認根拠で区分を判定し、追記予定値と除外理由を返す。

    引数はDB列名をキーとする辞書。既存値と異なる確認情報は上書きしない。
    Openverseは元Commonsの照合済みmetadataを要求する。通信は行わない。
    """
    quality = deepcopy(asset["quality"])
    origin = deepcopy(source["policy"])
    reasons = []
    name = quality.get("license", "")
    if "nc" in name.lower().split("-"):
        reasons.append("noncommercial")
    elif name not in policy.get("license_rules", {}).get("analysis_only", []):
        reasons.append("unknown_license")
    if name != source["license"]:
        reasons.append("license_missing_or_mismatch")
    if asset["search_provider"] != source["site"]:
        reasons.append("missing_provenance")
    if source["site"] == "openverse":
        metadata = quality.get("metadata", {})
        if not (metadata.get("source_verified")
                and urlsplit(source["url"]).hostname == "commons.wikimedia.org"):
            reasons.append("unverified_origin")
    elif source["site"] != "wikimedia_commons":
        reasons.append("unverified_origin")
    reasons.extend(analysis_review_reasons(policy))
    if any(p.get("use_stopped") or p.get("deletion_requested") for p in (
        origin, quality.get("rights", {}),
    )):
        reasons.append("rights_use_stopped")
    additions = {
        "rights": {key: policy.get(key) for key in RIGHTS_KEYS},
        "provider": asset["search_provider"], "original_id": source["url"],
        "retrieved_at": asset["retrieved_at"].isoformat(),
    }
    if any(key in quality and quality[key] != value for key, value in additions.items()):
        reasons.append("rights_policy_mismatch")
    if any(key in origin and origin[key] != policy.get(key) for key in RIGHTS_KEYS):
        reasons.append("rights_policy_mismatch")
    if asset["license_class"] not in {"open", "analysis_only"} or source[
        "license_class"
    ] not in {"open", "analysis_only"}:
        reasons.append("restricted_source")
    quality.update(additions)
    origin.update({key: policy.get(key) for key in RIGHTS_KEYS})
    revised_asset = asset | {"license_class": "analysis_only", "quality": quality}
    revised_source = source | {"license_class": "analysis_only", "policy": origin}
    reasons.extend(exclusion_reasons(revised_asset, revised_source, []))
    return revised_asset, revised_source, sorted(set(reasons))


def execute(engine, asset_ids, policies, *, apply=False, expected_hash=None):
    """区分件数・除外理由と計画hashを返す。既定はREPEATABLE READ/READ ONLY。

    apply=Trueは保存済みdry-runのexpected_hashを必須とし、全対象をロックして
    1取引で区分列と未設定の確認フィールドだけを追記する。既存qualityを保持し、
    retention台帳・保存期限を追加しない。再実行時は変更0件になる。
    計画不一致・コホート欠落はValueError。DB例外は呼出し元へ返す。
    """
    if apply and not expected_hash:
        raise ValueError("保存済みdry-runのhashが必要です")
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" + (
            "" if apply else ", READ ONLY"
        )))
        query = select(Asset).where(Asset.id.in_(asset_ids)).order_by(Asset.id)
        assets = session.scalars(query.with_for_update() if apply else query).all()
        if len(assets) != len(asset_ids) or {row.id for row in assets} != set(asset_ids):
            raise ValueError("固定コホートに欠落または重複があります")
        query = select(Source).where(
            Source.id.in_({a.source_id for a in assets}),
        ).order_by(Source.id)
        sources = {row.id: row for row in session.scalars(
            query.with_for_update() if apply else query,
        )}
        before, after, exclusions = Counter(), Counter(), Counter()
        changes, evidence = [], []
        for row in assets:
            source = sources[row.source_id]
            asset = {column.name: getattr(row, column.name) for column in Asset.__table__.columns}
            origin = {col.name: getattr(source, col.name) for col in Source.__table__.columns}
            before[row.license_class] += 1
            policy = policies.get(source.site, {})
            # 既存open経路は再判定対象に含めない。
            chosen = row.quality.get("license", "")
            open_names = {"pd", "pdm", "cc0"} | {
                f"cc-by-{version}" for version in ("1.0", "2.0", "2.5", "3.0", "4.0")
            }
            if chosen in open_names:
                after[row.license_class] += 1
                continue
            revised, revised_source, reasons = assessment(asset, origin, policy)
            exclusions.update(reasons)
            category = row.license_class if reasons else "analysis_only"
            after[category] += 1
            evidence.append({
                "asset_id": str(row.id), "original_hash": digest(asset | {
                    "license_class": None,
                    "quality": {k: v for k, v in asset["quality"].items()
                                if k not in {"rights", "provider", "original_id", "retrieved_at"}},
                }),
                "source_hash": digest(origin | {
                    "license_class": None,
                    "policy": {k: v for k, v in origin["policy"].items() if k not in RIGHTS_KEYS},
                }), "category": category, "reasons": reasons,
                "quality": revised["quality"], "policy": revised_source["policy"],
            })
            if not reasons and (row.license_class != category or row.quality != revised["quality"]
                                or source.license_class != category
                                or source.policy != revised_source["policy"]):
                changes.append((row, source, revised, revised_source))
        plan_hash = digest(evidence)
        if apply and plan_hash != expected_hash:
            raise ValueError("dry-run以後に入力または計画が変わりました")
        if apply:
            for row, source, revised, revised_source in changes:
                row.license_class = source.license_class = "analysis_only"
                row.quality = revised["quality"]
                source.policy = revised_source["policy"]
        return {
            "total": len(assets), "before": dict(before), "after": dict(after),
            "exclusions": dict(exclusions), "changes": len(changes),
            "plan_hash": plan_hash, "applied": apply,
            "evidence_hash": digest(canonical(evidence)),
        }
