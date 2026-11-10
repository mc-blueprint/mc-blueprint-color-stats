"""旧artifactを読むroot集計でも、新規ディレクトリだけを許可された匿名UIDで作る。"""

import os
from contextlib import contextmanager
from pathlib import Path

from bench.issue114.production import ROOT


@contextmanager
def anonymous_directories():
    mkdir = os.mkdir

    def create(path, mode=0o777, *, dir_fd=None):
        if dir_fd is not None or not Path(path).resolve().is_relative_to(ROOT):
            raise PermissionError("集計の新規ディレクトリは#114専用領域内に限定します")
        uid, gid = os.geteuid(), os.getegid()
        os.setegid(65534)
        os.seteuid(65534)
        try:
            mkdir(path, mode & 0o700)
        finally:
            os.seteuid(uid)
            os.setegid(gid)

    os.mkdir = create
    try:
        yield
    finally:
        os.mkdir = mkdir
