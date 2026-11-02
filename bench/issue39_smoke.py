"""専用テストDBの一時schemaで常駐ワーカーとopen実画像を確認する。"""

import argparse
import hashlib
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from colorstats.queue import Queue
from colorstats.queue.worker import Worker
from colorstats.schema.models import Asset, ColorObservation, Job, ProcessingRun, Source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    admin = create_engine(os.environ["TEST_DATABASE_URL"])
    schema = "issue39_smoke_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(os.environ["TEST_DATABASE_URL"]).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    engine = create_engine(url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    stop = args.output / ("stop-" + uuid4().hex)
    thread = None
    try:
        command.upgrade(Config("alembic.ini"), "head")
        queue = Queue(engine, lease=timedelta(seconds=1.5))
        renewals = []
        completed = []
        renew, complete = queue.renew, queue.complete

        def observed_renew(claim):
            renew(claim)
            renewals.append(str(claim.id))

        def observed_complete(claim, *values):
            result = complete(claim, *values)
            completed.append((str(claim.id), worker._process.pid))
            return result

        queue.renew, queue.complete = observed_renew, observed_complete
        worker = Worker(queue, {
            "shade": "tests.queue_handler", "prep": "colorstats.analyze.prep",
            "color": "colorstats.analyze.color",
        }, stop, poll_interval=0.02)
        crash = queue.enqueue("shade", None, "e" * 64, {
            "started": str(args.output / "started"), "exit": True,
            "pids": str(args.output / "pids"),
        })
        slow = queue.enqueue("shade", None, "f" * 64, {
            "started": str(args.output / "slow"), "delay": 2,
        })
        thread = threading.Thread(target=worker.run)
        thread.start()

        def finished(job_id):
            deadline = monotonic() + 60
            while monotonic() < deadline:
                with Session(engine) as session:
                    job = session.get(Job, job_id)
                    assert job.status != "failed", job.failure_reason
                    if job.status == "succeeded":
                        run = session.get(ProcessingRun, job.run_id)
                        return job, dict(run.output_paths), str(run.id)
                assert thread.is_alive(), "ワーカーが停止しました"
                sleep(0.05)
            raise TimeoutError(f"job未完了: {job_id}")

        assert finished(crash)[0].attempts == 2
        finished(slow)
        first_pid, second_pid = (args.output / "pids").read_text().splitlines()[-2:]
        assert first_pid != second_pid
        snapshots = {}
        report = []
        for image in args.images:
            with Session(engine) as session, session.begin():
                source = Source(
                    url=image.name, site="issue39-smoke", license="public-domain/CC0",
                    license_class="open", retrieved_at=datetime.now(UTC), policy={},
                )
                session.add(source)
                session.flush()
                asset = Asset(
                    source_id=source.id, url=image.name,
                    sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                    storage_path=str(image), domain="real_building", license_class="open",
                    retrieved_at=datetime.now(UTC), taxonomy_version="0.1.0",
                    scene_attributes={}, quality={},
                )
                session.add(asset)
                session.flush()
                asset_id = asset.id
            prep_paths = []
            target = args.output / (image.stem + ".jpg")
            for repeat in (0, 1):
                job_id = queue.enqueue("prep", asset_id, str(repeat) * 64, {
                    "input_path": str(image), "derived_path": str(target),
                    "license_class": "open", "taxonomy_version": "0.1.0",
                })
                _, paths, run_id = finished(job_id)
                prep_paths.append((Path(paths[str(target)]), run_id))
            assert prep_paths[0][0] != prep_paths[1][0]
            assert prep_paths[0][0].read_bytes() == prep_paths[1][0].read_bytes()
            colors = []
            color_target = args.output / (image.stem + ".json")
            for repeat in (0, 1):
                job_id = queue.enqueue("color", asset_id, str(repeat + 2) * 64, {
                    "input_path": str(prep_paths[0][0]), "input_run_id": prep_paths[0][1],
                    "output_path": str(color_target), "license_class": "open",
                    "taxonomy_version": "0.1.0",
                })
                _, paths, run_id = finished(job_id)
                published = Path(paths[str(color_target)])
                data = json.loads(published.read_text())
                with Session(engine) as session:
                    count = session.scalar(select(func.count()).select_from(ColorObservation)
                                           .where(ColorObservation.processing_run_id == run_id))
                    assert count == len(data["observations"]) > 0
                    assert session.get(Asset, asset_id).phash is not None
                colors.append(published)
            assert colors[0] != colors[1]
            assert colors[0].read_bytes() == colors[1].read_bytes()
            assert not target.exists() and not color_target.exists()
            for path in [item[0] for item in prep_paths] + colors:
                snapshots[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            report.append({"image": image.name, "prep_sha256": snapshots[prep_paths[0][0]],
                           "color_sha256": snapshots[colors[0]]})
        assert renewals
        assert all(pid == int(second_pid) for _, pid in completed)
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                   for path, digest in snapshots.items())
        print(json.dumps({"images": report, "renewals": len(renewals),
                          "successful_jobs": len(completed), "restart": True,
                          "resident_pid": int(second_pid)}, ensure_ascii=False, indent=2))
    finally:
        stop.touch()
        if thread is not None:
            thread.join(timeout=10)
            assert not thread.is_alive()
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()
