"""python -m colorstats.queueでワーカーを起動する。"""

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine

from colorstats.queue import Queue
from colorstats.queue.core import STAGES
from colorstats.queue.worker import Worker


def main():
    parser = argparse.ArgumentParser(description="停止ファイルで中断できるstageワーカー")
    parser.add_argument("--handler", action="append", required=True, metavar="STAGE=MODULE")
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--storage-path", action="append", default=[], metavar="STAGE=PATH",
        help="stageが使う保存先root。欠落・readonly中は取得を保留（複数指定可）",
    )
    args = parser.parse_args()
    handlers = {}
    for entry in args.handler:
        stage, separator, module = entry.partition("=")
        if stage not in STAGES or not separator or not module or stage in handlers:
            parser.error("handlerは重複しないSTAGE=MODULEで指定してください")
        handlers[stage] = module
    storage_paths = {}
    for entry in args.storage_path:
        stage, separator, path = entry.partition("=")
        if stage not in handlers or not separator or not path:
            parser.error("storage-pathはhandlerのSTAGE=PATHで指定してください")
        storage_paths.setdefault(stage, []).append(Path(path))
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        Worker(
            Queue(engine), handlers, args.stop_file,
            storage_paths={stage: tuple(paths) for stage, paths in storage_paths.items()},
        ).run(once=args.once)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
