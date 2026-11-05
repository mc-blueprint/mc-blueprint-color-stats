"""担当コードだけを新規の隔離ディレクトリへ転送し、登録済みSSHラッパーで実行する。"""

import base64
import io
import subprocess
import sys
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
    for directory in ("src", "configs", "taxonomy", "bench/issue94"):
        for path in (root / directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.add(path, arcname=str(path.relative_to(root)).replace("\\", "/"))
    for name in ("alembic.ini", "tests/__init__.py", "tests/conftest.py", "tests/test_queue.py",
                 "tests/test_collect.py", "tests/test_mapillary.py", "tests/test_mapillary_db.py",
                 "tests/fixtures/commons.json", "tests/fixtures/mapillary.json"):
        archive.add(root / name, arcname=name)
destination = "/mnt/data/work/issue-94/code-" + sys.argv[1]
def run(command):
    subprocess.run([
        sys.executable, "H:/MCBlueprintColorStats/scripts/ssh.py", "--host", "ubuntu-1",
        "--directory", "/mnt/data", "--command", command,
    ], check=True)


run("umask 077; mkdir -p /mnt/data/work/issue-94; " + f"mkdir {destination}")
encoded = base64.b64encode(buffer.getvalue()).decode()
for index, start in enumerate(range(0, len(encoded), 12000)):
    run(f"umask 077; echo {encoded[start:start + 12000]} > {destination}/part-{index:04d}")
run(f"cat {destination}/part-* | base64 -d | tar xz -C {destination} && "
    f"cd {destination} && " + sys.argv[2])
