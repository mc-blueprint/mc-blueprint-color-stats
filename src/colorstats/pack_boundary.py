"""M4公開schemaが確定するまでの配布allowlistと拒否回帰の受け口。"""

import json
import math
import uuid
from importlib.resources import files

from jsonschema import Draft202012Validator

from colorstats.retention import check_selection, lock
from colorstats.schema.models import Asset, Source

SCHEMA = json.loads(files("colorstats").joinpath("public-statistics.schema.json").read_text())


def validate_public(payload, *, session, selection):
    """数値集計だけを受ける。内部索引を現行DBで確認してから公開する。

    payloadは配布候補、selectionは配布しない内部snapshot入力索引。
    呼出し元は同じ取引中に公開を確定する。未知キー・自由文・画像はValueError。
    必須帰属がある場合はM4の別schema確定まで公開を保留する。
    """
    errors = list(Draft202012Validator(SCHEMA).iter_errors(payload))
    if errors or any(not math.isfinite(v) for row in payload["statistics"]
                     for v in [*row["oklab"], row["ratio"]]):
        raise ValueError("配布allowlist外の内容です")
    lock(session)
    check_selection(session, selection)
    for item in selection["assets"]:
        asset = session.get(Asset, uuid.UUID(item["asset_id"]))
        source = session.get(Source, asset.source_id)
        if source.policy.get("attribution_required"):
            raise ValueError("必要帰属のM4 schemaが未確定のため公開を保留します")
