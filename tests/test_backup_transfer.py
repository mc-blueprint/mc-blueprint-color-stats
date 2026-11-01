"""実際の送信shellを偽のSSH・DBコマンドと組み合わせて確認する。"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Linuxのbashで実行する")
class BackupTransferTests(unittest.TestCase):
    def run_backup(self, bad_hosts, destinations=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = {
                "psql": "echo postgres",
                "pg_dump": 'file=${@: -1:1}; touch "${file#--file=}"',
                "pg_restore": ":",
                "ssh": '''[[ "$1" == -n ]] || cat >/dev/null
host=${@: -2:1}
case "$BAD_HOSTS" in *"$host"*) echo 'temperature=61C'; exit 1;; esac
case "$host" in a@host) echo uuid=aaa;; b@host) echo uuid=bbb;; c@host) echo uuid=ccc;; esac''',
                "rsync": 'echo "${@: -1:1}" >> "$TRANSFER_LOG"',
            }
            for name, body in commands.items():
                executable = root / name
                executable.write_text("#!/bin/bash\n" + body + "\n")
                executable.chmod(0o755)
            (root / "destinations").write_text(
                destinations or "a@host:.\nb@host:.\nc@host:.\n"
            )
            (root / "ground-truth").mkdir()
            (root / "aggregates").mkdir()
            (root / "backup.conf").write_text(
                f"DESTINATIONS_FILE={root}/destinations\nDATA_ROOT={root}\n"
            )
            source = Path(__file__).resolve().parents[1] / "ops/backup/colorstats-backup.sh"
            script = source.read_text().replace(
                "source /etc/colorstats/backup.conf", f"source {root}/backup.conf"
            ).replace("dump_dir=/var/lib/colorstats-backup", f"dump_dir={root}/dumps")
            (root / "backup.sh").write_text(script)
            log = root / "transfers"
            result = subprocess.run(
                ["bash", str(root / "backup.sh")],
                env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                     "BAD_HOSTS": bad_hosts, "TRANSFER_LOG": str(log)},
                capture_output=True,
                text=True,
            )
            return result, log.read_text() if log.exists() else ""

    def test_abnormal_medium_is_excluded_and_two_media_receive_backup(self):
        result, transfers = self.run_backup("c@host")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("a@host", transfers)
        self.assertIn("b@host", transfers)
        self.assertNotIn("c@host", transfers)
        self.assertIn("excluded destination=c@host:. reason=temperature=61C", result.stdout)
        self.assertIn("backup result: transferred=2", result.stdout)

    def test_fewer_than_two_healthy_media_fails_before_transfer(self):
        result, transfers = self.run_backup("b@host c@host")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(transfers, "")
        self.assertIn("fewer than 2 healthy media", result.stderr)

    def test_duplicate_medium_does_not_satisfy_two_media_requirement(self):
        result, transfers = self.run_backup("", "a@host:.\na@host:.\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(transfers, "")

    def test_no_healthy_media_fails_with_a_reason(self):
        result, transfers = self.run_backup("a@host b@host c@host")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(transfers, "")
        self.assertIn("fewer than 2 healthy media", result.stderr)


if __name__ == "__main__":
    unittest.main()
