"""生存中のMAINPIDへの停止要求だけをフラグにし、キュー返却を待つ。"""

import os
import sys
from pathlib import Path
from time import monotonic, sleep


def stop(flag: Path, pid: str | None = None) -> None:
    # systemdは主プロセスが終了済みならMAINPIDを渡さない。
    if not pid:
        return
    process_id = int(pid)
    if process_id <= 0:
        raise ValueError("MAINPIDは正のPIDが必要です")
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return
    flag.touch()
    deadline = monotonic() + 10
    while monotonic() < deadline:
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            break
        sleep(0.2)


if __name__ == "__main__":
    stop(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None)
