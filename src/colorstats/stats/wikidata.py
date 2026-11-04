"""Commonsの保存済みカテゴリから、座標を持つ固有対象のカタログを作る。"""

import copy
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode

from colorstats.collect.commons import ENDPOINT, CommonsAdapter
from colorstats.stats.subjects import digest, normalize

WIKIDATA = "https://www.wikidata.org/w/api.php"
ROOTS = {
    "real_building": {"Q41176", "Q811979"},
    "real_terrain": {
        "Q8502", "Q23397", "Q22698", "Q4022", "Q23442", "Q4421", "Q8514",
        "Q46831", "Q54050", "Q35509",
    },
}
EXCLUDED = {"Q56061", "Q486972", "Q82794", "Q32880", "Q16889133", "Q4167836", "Q13406463"}
COARSE = {"Q34442", "Q79007", "Q1497364", "Q1497375", "Q98116669", "Q23413"}
SITE_TYPES = {"Q5393308", "Q845945"}
BUILDINGS = {"Q41176", "Q1497364", "Q1497375", "Q98116669", "Q23413"}
ELEMENTS = {"Q391414"}


def values(entity, prop):
    """廃止ランク・値なしを除いた主張値を返す。"""
    return [
        claim["mainsnak"]["datavalue"]["value"]
        for claim in entity.get("claims", {}).get(prop, [])
        if claim.get("rank") != "deprecated"
        and claim.get("mainsnak", {}).get("snaktype") == "value"
    ]


def references(entity, prop):
    return {value["id"] for value in values(entity, prop)}


class WikidataCatalog:
    """直列取得したAPI応答を要求hash別に保存し、同じ要求では通信しない。

    cacheは実行間で保持するディレクトリ。API不通・不正応答は例外を伝播し、
    部分カタログで推定を続行しない。offlineでは不足キャッシュも失敗とする。
    """

    def __init__(self, policy, cache, *, client=None, offline=False):
        self.client = client or CommonsAdapter(policy)
        self.cache = Path(cache)
        self.offline = offline
        self.requests = {}

    def query(self, endpoint, **parameters):
        parameters = {
            "format": "json", "maxlag": self.client.policy["maxlag"], **parameters,
        }
        key = digest({"endpoint": endpoint, "parameters": parameters})
        path = self.cache / (key + ".json")
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            if self.offline:
                raise FileNotFoundError("取得結果がキャッシュにありません")
            data = self.client._get(endpoint + "?" + urlencode(parameters))
            if "error" in data or not ("query" in data or "entities" in data):
                raise ValueError("API応答に必要な結果がありません")
            self.cache.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True)
        if "error" in data or not ("query" in data or "entities" in data):
            raise ValueError("保存API応答が不正です")
        self.requests[key] = digest(data)
        return data

    def entities(self, ids):
        result = {}
        ids = sorted(set(ids))
        for start in range(0, len(ids), 50):
            data = self.query(
                WIKIDATA, action="wbgetentities", ids="|".join(ids[start:start + 50]),
                props="claims|labels|aliases|info", languages="en|ja|fr|de|es",
            )
            requested = ids[start:start + 50]
            if set(requested) - data["entities"].keys() or any(
                "missing" in data["entities"][qid] for qid in requested
            ):
                raise ValueError("要求したWikidata項目の応答が欠損しています")
            result.update(data["entities"])
        return result

    def attribute_claims(self, ids):
        """#79と同じキャッシュ要求から地域・年代用の4属性とrevisionだけを返す。"""
        return {
            qid: {
                "revision": entity.get("lastrevid"),
                "claims": {p: entity.get("claims", {}).get(p, [])
                           for p in ("P17", "P131", "P625", "P571")},
            }
            for qid, entity in self.entities(ids).items()
        }

    def build(self, categories, rules):
        """rulesのコピーへ固有対象を追加し、取得根拠を含めて返す。DBは変更しない。"""
        categories = set(categories) | {
            c for target in rules["subjects"] for c in target["categories"]
        }
        titles = sorted({
            "Category:" + c.removeprefix("Category:") for c in categories
        })
        links = defaultdict(set)
        for start in range(0, len(titles), 50):
            data = self.query(
                ENDPOINT, action="query", formatversion=2, prop="pageprops",
                ppprop="wikibase_item", redirects=1, titles="|".join(titles[start:start + 50]),
            )
            pages = {p["title"]: p for p in data["query"]["pages"]}
            redirects = {
                r["from"]: r["to"]
                for kind in ("normalized", "redirects") for r in data["query"].get(kind, [])
            }
            for title in titles[start:start + 50]:
                resolved, seen = title, set()
                while resolved in redirects and resolved not in seen:
                    seen.add(resolved)
                    resolved = redirects[resolved]
                if resolved not in pages:
                    raise ValueError("要求したCommonsカテゴリの応答が欠損しています")
                item = pages[resolved].get("pageprops", {}).get("wikibase_item")
                if item:
                    links[normalize(title).removeprefix("category:")].add(item)
        manual_ids = {t["wikidata_id"] for t in rules["subjects"] if t.get("wikidata_id")}
        entities = self.entities({qid for ids in links.values() for qid in ids} | manual_ids)
        topics = set()
        for entity in entities.values():
            topics.update(references(entity, "P301"))
        entities.update(self.entities(topics - entities.keys()))
        resolved = defaultdict(set)
        for category, ids in links.items():
            for qid in ids:
                entity = entities[qid]
                topic_ids = references(entity, "P301")
                if topic_ids:
                    for topic in topic_ids:
                        # カテゴリ項目の主題を対象とする。P910の逆リンクも根拠へ残す。
                        resolved[category].add(topic)
                else:
                    resolved[category].add(qid)
        categories_by_item = defaultdict(set)
        for category, ids in links.items():
            for qid in ids:
                categories_by_item[qid].add(category)
        saved_categories = {normalize(c).removeprefix("category:") for c in categories}
        for qid, entity in entities.items():
            if "Q4167836" in references(entity, "P31"):
                continue
            for category in values(entity, "P373"):
                category = normalize(category).removeprefix("category:")
                if category in saved_categories:
                    resolved[category].add(qid)
            for category_id in references(entity, "P910"):
                for category in categories_by_item.get(category_id, []):
                    resolved[category].add(qid)
        for ids in resolved.values():
            ids.difference_update({
                qid for qid in ids if "Q4167836" in references(entities[qid], "P31")
            })
        targets = {qid for ids in resolved.values() for qid in ids} | manual_ids
        def load_classes(pending):
            expanded = set()
            while pending:
                entities.update(self.entities(pending - entities.keys()))
                expanded.update(pending)
                pending = {
                    parent for qid in pending for parent in references(entities[qid], "P279")
                } - expanded

        load_classes({parent for qid in targets for parent in references(entities[qid], "P31")})

        def ancestors(qid, relation="P31"):
            found, pending = set(), set(references(entities[qid], relation))
            while pending:
                item = pending.pop()
                if item in found:
                    continue
                found.add(item)
                pending.update(references(entities[item], "P279") - found)
            return found

        identity_targets = {
            qid for qid in targets
            if any(ancestors(qid) & roots for roots in ROOTS.values())
            and not ancestors(qid) & EXCLUDED
        }
        building_targets = {
            qid for qid in identity_targets if ancestors(qid) & ROOTS["real_building"]
        }
        parts = {part for qid in building_targets for part in references(entities[qid], "P527")}
        entities.update(self.entities(parts - entities.keys()))
        load_classes(
            {parent for qid in parts for parent in references(entities[qid], "P31")}
            | {cls for qid in building_targets for cls in references(entities[qid], "P2670")}
        )
        part_classes = {qid: ancestors(qid) for qid in parts}

        eligible = {}
        for qid in sorted(targets):
            entity = entities[qid]
            classes = ancestors(qid)
            domains = [d for d, roots in ROOTS.items() if roots & classes]
            points = [
                p for p in values(entity, "P625")
                if p.get("globe") == "http://www.wikidata.org/entity/Q2"
                and p.get("latitude") is not None and p.get("longitude") is not None
            ]
            if len(domains) != 1 or classes & EXCLUDED or len(points) != 1:
                continue
            names = {
                v["value"] for v in entity.get("labels", {}).values()
            } | {
                alias["value"]
                for aliases in entity.get("aliases", {}).values() for alias in aliases
            }
            if not names or any(normalize(n).startswith("category:") for n in names):
                continue
            building_parts = sorted(
                part for part in references(entity, "P527")
                if part_classes.get(part, set()) & BUILDINGS
                and not part_classes[part] & ELEMENTS
            )
            part_types = references(entity, "P2670") if domains[0] == "real_building" else set()
            part_type_classes = [{cls} | ancestors(cls, "P279") for cls in part_types]
            has_building_types = any(
                classes & BUILDINGS and not classes & ELEMENTS for classes in part_type_classes
            )
            coarse = bool(
                domains[0] == "real_building"
                and (classes & COARSE or references(entity, "P31") & SITE_TYPES
                     or building_parts or has_building_types)
            )
            eligible[qid] = {
                "domain": domains[0], "candidate_only": coarse,
                "granularity": {
                    "state": "coarse" if coarse else "single",
                    "classes": sorted(classes & COARSE),
                    "site_types": sorted(references(entity, "P31") & SITE_TYPES),
                    "building_parts": building_parts, "part_types": sorted(part_types),
                }, "name": entity.get("labels", {}).get("en", {}).get(
                    "value", sorted(names)[0],
                ), "aliases": sorted(names), "coordinates": [
                    points[0]["latitude"], points[0]["longitude"],
                ], "classes": sorted(classes), "revision": entity.get("lastrevid"),
            }

        result = copy.deepcopy(rules)
        result["ambiguous_categories"] = {
            category: sorted(ids & identity_targets)
            for category, ids in sorted(resolved.items()) if len(ids & identity_targets) > 1
        }
        bindings = {}
        for target in result["subjects"]:
            if target.get("wikidata_id"):
                qid = target["wikidata_id"]
                if qid not in eligible or eligible[qid]["domain"] != target["domain"]:
                    raise ValueError("手作業対象のWikidata IDが対象条件を満たしません")
                ids = {qid}
            else:
                ids = {
                    qid for category in target["categories"]
                    for qid in resolved.get(normalize(category), set())
                    if qid in eligible and eligible[qid]["domain"] == target["domain"]
                }
            if len(ids) > 1:
                raise ValueError("手作業対象のカテゴリが異なるWikidata対象を指しています")
            if ids:
                qid = next(iter(ids))
                if qid in bindings:
                    raise ValueError("複数の手作業対象が同じWikidata対象を指しています")
                target["wikidata_id"] = qid
                target["candidate_only"] = eligible[qid]["candidate_only"]
                target["granularity"] = eligible[qid]["granularity"]
                bindings[qid] = target
        for qid, item in eligible.items():
            categories = sorted(c for c, ids in resolved.items() if ids == {qid})
            if not categories:
                continue
            target = bindings.get(qid)
            if target is None:
                target = {
                    "key": "wikidata:" + qid, "name": item["name"], "domain": item["domain"],
                    "aliases": [], "categories": [], "attributes": {},
                }
                result["subjects"].append(target)
            target.update({
                "wikidata_id": qid, "coordinates": item["coordinates"],
                "automatic_categories": categories, "candidate_only": item["candidate_only"],
                "granularity": item["granularity"],
            })
            target["categories"] = sorted(set(target["categories"]) | set(categories))
            target["aliases"] = sorted(set(target["aliases"]) | set(item["aliases"]))
        result["wikidata"] = {
            "requests": dict(sorted(self.requests.items())),
            "entities": {qid: item for qid, item in eligible.items()},
            "category_items": {c: sorted(ids) for c, ids in sorted(resolved.items())},
            "user_agent": self.client.policy["user_agent"],
        }
        return result
