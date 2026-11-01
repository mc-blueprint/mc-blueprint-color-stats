"""所有者専用の設定から接続URLを読み、引数・journalへ出さずプロセスを起動する。"""

import json
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    os.environ["DATABASE_URL"] = json.loads(
        Path("/var/lib/colorstats/pilot/database.json").read_text()
    )["url"]
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
