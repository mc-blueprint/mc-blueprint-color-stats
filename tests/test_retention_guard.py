import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "posix", reason="Linuxのbashで実行する")
def test_excluded_and_missing_media_receive_no_retention_writes(tmp_path):
    log = tmp_path / "writes"
    runner = tmp_path / "python"
    runner.write_text('''#!/bin/bash
if [[ "$1" == */health.py ]]; then
    [[ "$2" != e53f78c3-2918-4a64-bc50-807a38249da1 ]]
else
    echo "$*" >> "$WRITE_LOG"
fi
''')
    runner.chmod(0o755)
    findmnt = tmp_path / "findmnt"
    findmnt.write_text('''#!/bin/bash
case "${@: -1}" in
    */backup-wd750) echo 3f9a319f-394c-4cca-805d-fc88d782d644;;
    *) exit 1;;
esac
''')
    findmnt.chmod(0o755)
    source = Path(__file__).resolve().parents[1] / "ops/backup/retention.sh"
    script = source.read_text().replace("/usr/bin/python3", str(runner))
    result = subprocess.run(["bash", "-c", script], env={
        **os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "WRITE_LOG": str(log)
    }, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    writes = log.read_text().splitlines()
    assert len(writes) == 2
    assert all("backup-wd750" in line for line in writes)
    assert "--generations 7" in writes[0] and "--generations 4" in writes[1]
