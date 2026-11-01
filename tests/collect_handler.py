"""実通信なしでcollect stageのspawn境界を検証するハンドラー。"""

import io
import json
from pathlib import Path
from unittest.mock import patch

from colorstats.collect import stage
from colorstats.collect.commons import CommonsAdapter
from colorstats.collect.stage import register  # noqa: F401


def prepare(claim):
    path = Path(__file__).parent / "fixtures/commons.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    responses = iter([json.dumps(record).encode() for record in records] + [b"original"])

    def opener(request, **kwargs):
        response = io.BytesIO(next(responses))
        response.headers = {}
        return response

    adapter = CommonsAdapter(claim.payload["policy"], opener=opener, wait=lambda _: None)
    with patch.object(stage, "CommonsAdapter", return_value=adapter):
        return stage.prepare(claim)
