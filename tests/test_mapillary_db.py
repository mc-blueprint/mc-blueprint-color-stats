import hashlib
import io
import os
from dataclasses import asdict
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.collect import stage
from colorstats.queue import RunInfo
from colorstats.schema.models import Asset, Retention
from tests.test_collect import payload_for
from tests.test_mapillary import client, item, request, setup  # noqa: F401
from tests.test_queue import database, queue  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="隔離PostgreSQL")


def test_解析専用登録とrollback再投入重複期限停止を共通stageで検証する(
    setup, queue, tmp_path, monkeypatch,  # noqa: F811
):
    payload, _ = payload_for(tmp_path)
    payload.update(policy=setup, request=asdict(request()))
    content = io.BytesIO()
    Image.new("RGB", (32, 24), "blue").save(content, "JPEG")
    adapter, calls = client(setup, [{"data": [item()]}, content.getvalue()])
    monkeypatch.setattr(stage, "MapillaryAdapter", lambda policy: adapter)
    digest = hashlib.sha256(b"mapillary-fixture").hexdigest()
    queue.enqueue("collect", None, digest, payload)
    claim = queue.claim(["collect"])
    url = queue.engine.url.render_as_string(hide_password=False)
    prepared = stage.prepare(claim, database_url=url)
    assert len(prepared.data["records"]) == 1
    record = prepared.data["records"][0]
    assert record["received"] == {"width": 32, "height": 24, "mime": "image/jpeg"}
    info = RunInfo("analysis_only", "test", "0.1.0", "windows", {"effective": {}})

    def fail(session, run):
        run.output_paths = {record["target"]: record["target"]}
        stage.register(session, run, prepared.data)
        raise RuntimeError("rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        queue.complete(claim, info, fail, [])
    with Session(queue.engine) as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 0
        assert session.scalar(select(func.count()).select_from(Retention)) == 0
    queue.complete(claim, prepared.info,
                   lambda session, run: stage.register(session, run, prepared.data), prepared.files)
    with Session(queue.engine) as session, session.begin():
        asset = session.scalars(select(Asset)).one()
        assert asset.license_class == "analysis_only" and asset.subject_id is None
        assert asset.quality["metadata"]["native_id"] == "123"
        assert stage.existing_rendition(session, record["candidate"]).id == asset.id
        assert "secret" not in str(asset.quality)
        entry = session.scalars(select(Retention).where(Retention.asset_id == asset.id)).one()
        with pytest.raises(PermissionError):
            retention.assert_usable(session, asset.id, images=True,
                                    now=entry.expires_at + timedelta(seconds=1))
        retention.stop(session, provider="mapillary", native_id="123", reason="deletion_request",
                       request_url="https://github.com/mc-blueprint/mc-blueprint-color-stats/issues/94")
    with Session(queue.engine) as session:
        with pytest.raises(PermissionError):
            retention.check_acquisition(session, "mapillary", record["candidate"]["source_url"],
                                        record["candidate"]["original_url"])
    assert len(calls) == 2
