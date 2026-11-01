"""ubuntu-1内に接続設定を作り、転送可能なSCRAM検証子だけを別ファイルへ保存する。"""

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path


def create(directory: Path) -> None:
    """新規配備専用。既存の認証情報は上書きせず、平文はこのホスト内だけに置く。"""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    password = secrets.token_urlsafe(48)
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
    client = hmac.digest(salted, b"Client Key", "sha256")
    stored = hashlib.sha256(client).digest()
    server = hmac.digest(salted, b"Server Key", "sha256")
    def encoded(value):
        return base64.b64encode(value).decode("ascii")

    verifier = f"SCRAM-SHA-256$4096:{encoded(salt)}${encoded(stored)}:{encoded(server)}"
    values = {
        "database.json": json.dumps({
            "url": f"postgresql+psycopg://colorstats_worker:{password}@192.168.1.86/colorstats"
        }) + "\n",
        "worker.scram": verifier + "\n",
    }
    for name, value in values.items():
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(value)


if __name__ == "__main__":
    import sys

    create(Path(sys.argv[1]))
