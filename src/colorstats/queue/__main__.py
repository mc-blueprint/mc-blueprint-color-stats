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
    args = parser.parse_args()
    handlers = {}
    for entry in args.handler:
        stage, separator, module = entry.partition("=")
        if stage not in STAGES or not separator or not module or stage in handlers:
            parser.error("handlerは重複しないSTAGE=MODULEで指定してください")
        handlers[stage] = module
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        Worker(Queue(engine), handlers, args.stop_file).run(once=args.once)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
