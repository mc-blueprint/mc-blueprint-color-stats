"""1件の実取得をローカル一時rawへ保存し、APIレスポンスをテスト用に記録する。"""

import argparse
import hashlib
import io
import json
import tempfile
from pathlib import Path
from urllib.request import urlopen

from colorstats.collect import SearchRequest
from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.policy import load_policy
from colorstats.collect.stage import MIME_EXTENSIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-fixture", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    policy = load_policy(root / "configs/source_policy.yaml", "wikimedia_commons")
    responses = []

    def record(request, **kwargs):
        response = urlopen(request, **kwargs)
        if request.full_url.startswith("https://commons.wikimedia.org/w/api.php?"):
            with response:
                data = response.read()
                responses.append(json.loads(data))
                recorded = io.BytesIO(data)
                recorded.headers = response.headers
                return recorded
        return response

    adapter = CommonsAdapter(policy, opener=record)
    try:
        result = adapter.search(
            SearchRequest(
                "wikimedia_commons",
                'intitle:"Himeji Castle" filetype:bitmap',
                limit=1,
            )
        )
        candidate = result.candidates[0]
        with tempfile.TemporaryDirectory(prefix="colorstats-collect-") as directory:
            temporary = Path(directory) / "original"
            adapter.download(candidate, temporary)
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            extension = MIME_EXTENSIONS[candidate.mime]
            target = Path(directory) / "raw" / digest[:2] / (digest + "." + extension)
            target.parent.mkdir(parents=True)
            temporary.replace(target)
            print(
                json.dumps(
                    {
                        "source_url": candidate.source_url,
                        "author": candidate.author,
                        "license": candidate.license,
                        "width": candidate.width,
                        "height": candidate.height,
                        "sha256": digest,
                        "bytes": target.stat().st_size,
                        "raw": str(target),
                        "temporary_cleanup": True,
                    },
                    ensure_ascii=False,
                )
            )
        if args.record_fixture:
            fixture = root / "tests/fixtures/commons.json"
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(
                json.dumps(responses, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    finally:
        adapter.finish()


if __name__ == "__main__":
    main()
