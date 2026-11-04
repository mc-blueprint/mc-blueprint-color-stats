"""保持台帳の管理入口。DB URLは既存のDATABASE_URLだけから受け取る。"""

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from colorstats import retention
from colorstats.schema.models import Retention, RetentionFile
from colorstats.store import temporary_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stop = commands.add_parser("stop")
    target = stop.add_mutually_exclusive_group(required=True)
    target.add_argument("--source-url")
    target.add_argument("--url")
    target.add_argument("--native-id")
    stop.add_argument("--provider")
    stop.add_argument("--request-url", required=True)
    stop.add_argument("--ledger", type=Path, required=True)
    stop.add_argument("--reason", default="deletion_request",
                      choices=("deletion_request", "rights_revoked", "rejected"))
    clean = commands.add_parser("cleanup")
    clean.add_argument("--host", required=True)
    commands.add_parser("audit")
    export = commands.add_parser("export-stops")
    export.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore-stops")
    restore.add_argument("--input", type=Path, required=True)
    rebuild = commands.add_parser("rebuild-selection")
    rebuild.add_argument("--input", type=Path, required=True)
    rebuild.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with Session(engine) as session, session.begin():
            if args.command == "stop":
                retention.stop(session, source_url=args.source_url, url=args.url,
                               provider=args.provider, native_id=args.native_id,
                               request_url=args.request_url, reason=args.reason)
                temporary = temporary_path(args.ledger, "deletion-ledger")
                try:
                    with temporary.open("w", encoding="utf-8") as stream:
                        json.dump(retention.export_tombstones(session), stream, ensure_ascii=False)
                        stream.flush()
                        os.fsync(stream.fileno())
                    temporary.replace(args.ledger)
                finally:
                    temporary.unlink(missing_ok=True)
            elif args.command == "cleanup":
                retention.cleanup(session, host=args.host)
            elif args.command == "export-stops":
                with args.output.open("x", encoding="utf-8") as stream:
                    args.output.chmod(0o600)
                    json.dump(retention.export_tombstones(session), stream, ensure_ascii=False)
            elif args.command == "restore-stops":
                retention.apply_tombstones(
                    session, json.loads(args.input.read_text(encoding="utf-8")),
                )
            elif args.command == "rebuild-selection":
                selection = retention.rebuild_selection(
                    session, json.loads(args.input.read_text(encoding="utf-8")),
                )
                with args.output.open("x", encoding="utf-8") as stream:
                    args.output.chmod(0o600)
                    json.dump(selection, stream, ensure_ascii=False)
            else:
                for table in (Retention, RetentionFile):
                    for row in session.scalars(select(table)):
                        print(json.dumps({c.name: getattr(row, c.name)
                                          for c in table.__table__.columns}, default=str))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
