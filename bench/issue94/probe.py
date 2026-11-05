"""30 API要求・15画像以内の事前予算。秘密値を表示しない公開API経路の確認。"""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from colorstats.collect import SearchRequest
from colorstats.collect.mapillary import MapillaryAdapter
from colorstats.collect.policy import load_policy

root = Path("/mnt/data/work/issue-94")
budget = root / "budget.json"
if not budget.exists():
    budget.write_text(json.dumps({"api_requests": 30, "images": 15,
                                  "purpose": "固定少量の動作確認。本収集なし"}))
policy = load_policy(Path("configs/source_policy.yaml"), "mapillary")
for url in ["https://graph.mapillary.com/robots.txt"]:
    try:
        with urlopen(Request(url, headers={"User-Agent": policy["user_agent"]}), timeout=60) as r:
            robots = r.read().decode()
            print("robots", r.status, robots[:2000])
            if "Disallow: /" in robots:
                raise SystemExit("robotsの許可を確認できないため停止")
    except HTTPError as e:
        code = e.code
        e.close()
        raise SystemExit(f"robots未確認のため停止: HTTP {code}") from None
adapter = MapillaryAdapter(policy)
counts = {}


def observe(event, value=1):
    if event in ("api_request", "request", "bytes", "responses"):
        counts[event] = counts.get(event, 0) + value


adapter.observer = observe
try:
    result = adapter.search(SearchRequest("mapillary", "kyoto-street-buildings", limit=2))
    print("result", json.dumps({"next_offset": result.next_offset, "candidates": [
        {"reason": c.exclusion_reason, "metadata_keys": list(c.metadata),
         "media_host": __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(
             c.download_url).hostname} for c in result.candidates]}))
except Exception as e:
    print("probe-error", type(e).__name__, str(e))
finally:
    adapter.finish()
    print("counts", json.dumps(counts))
