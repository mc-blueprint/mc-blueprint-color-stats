"""取得済み画像の層別網羅率。予約を実績には含めない。"""

import math
from collections import Counter

from sqlalchemy import select

from colorstats.schema.models import Asset, Source, Subject


def subject_attributes(subject: Subject) -> dict:
    return {
        **subject.scene_attributes,
        "domain": subject.domain,
        "region": subject.location,
        "era": subject.era,
    }


def matches(attributes: dict, layer: dict) -> bool:
    return all(attributes.get(key) == value for key, value in layer["attributes"].items())


def images(session) -> list[dict]:
    """既存collectも集計する。ソースは検索provider、未記録の画像だけ出典siteを使う。"""
    rows = session.execute(
        select(Asset, Source, Subject)
        .join(Source, Source.id == Asset.source_id)
        .outerjoin(Subject, Subject.id == Asset.subject_id)
    )
    return [
        {
            "subject_id": asset.subject_id,
            "author": (asset.quality.get("author", source.author) or "").strip().casefold(),
            "source": asset.search_provider or source.site,
            "region": (
                asset.search_parameters["collection_bias"]["region"]
                if "collection_bias" in (asset.search_parameters or {})
                else subject.location if subject else None
            ),
            "attributes": {
                **(
                    asset.search_parameters["collection_bias"]["intended_attributes"]
                    if "collection_bias" in (asset.search_parameters or {})
                    else subject_attributes(subject) if subject else {}
                ),
                **asset.scene_attributes,
            },
        }
        for asset, source, subject in rows
    ]


def coverage(session, config: dict) -> dict:
    """件数・実測作者占有率・Shannonエントロピー（bit）を返す。空の層も出力する。"""
    collected = images(session)
    layers = []
    assigned = 0
    for layer in config["strata"]:
        rows = [row for row in collected if matches(row["attributes"], layer)]
        assigned += len(rows)
        authors = Counter(row["author"] for row in rows if row["author"])
        count = len(rows)
        shares = [value / count for value in authors.values()]
        unknown = count - sum(authors.values())
        if unknown:
            shares.append(unknown / count)
        subjects = len({row["subject_id"] for row in rows if row["subject_id"]})
        unknown_subjects = sum(row["subject_id"] is None for row in rows)
        unknown_regions = sum(not row["region"] for row in rows)
        top_share = max(authors.values(), default=0) / count if count else 0
        layers.append(
            {
                "stratum": layer["id"],
                "attributes": layer["attributes"],
                "images": count,
                "subjects": subjects,
                "target_subjects": layer["subjects"],
                "coverage": subjects / layer["subjects"],
                "deficit": max(0, layer["subjects"] - subjects),
                "authors": len(authors),
                "unknown_author_images": unknown,
                "unknown_author_share": unknown / count if count else 0,
                "unknown_region_images": unknown_regions,
                "unknown_region_share": unknown_regions / count if count else 0,
                "unknown_subject_images": unknown_subjects,
                "unknown_subject_share": unknown_subjects / count if count else 0,
                "sources": len({row["source"] for row in rows}),
                "top_author_share": top_share,
                "author_entropy_bits": -sum(p * math.log2(p) for p in shares),
                "concentrated": top_share > config["limits"]["author_share"],
            }
        )
    return {
        "images": len(collected),
        "unassigned_images": len(collected) - assigned,
        "strata": layers,
    }
