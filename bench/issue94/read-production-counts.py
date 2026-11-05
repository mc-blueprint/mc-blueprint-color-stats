"""本番ジョブをREAD ONLYで集計する。接続情報と個別payloadは表示しない。"""

import json
from pathlib import Path

from sqlalchemy import create_engine, text

url = json.loads(Path("/var/lib/colorstats/pilot/database.json").read_text())["url"]
engine = create_engine(url, echo=False, hide_parameters=True)
try:
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        readonly = connection.exec_driver_sql("SHOW transaction_read_only").scalar_one()
        rows = connection.execute(text("""
            SELECT payload->'request'->>'provider' AS provider, status, count(*)
            FROM job
            WHERE stage = 'collect'
              AND payload->'policy'->>'enabled' = 'true'
              AND (payload->'request'->>'provider' = 'mapillary'
                   OR (payload->'request'->>'provider' = 'openverse'
                       AND (payload->'policy'->'hosts' ? 'mapillary.com'
                            OR payload->'policy'->'hosts' ? 'images.mapillary.com'
                            OR payload->'policy'->'hosts' ? 'fbcdn.net')))
            GROUP BY provider, status ORDER BY provider, status
        """)).all()
        result = {"transaction_read_only": readonly, "counts": [
            {"provider": row[0], "status": row[1], "count": row[2]} for row in rows]}
        print(json.dumps(result))
except Exception as error:
    print("READ ONLY確認失敗: " + type(error).__name__)
    raise SystemExit(1) from None
finally:
    engine.dispose()
