"""設定されたホストとパスへ論理保存先を解決する。"""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml


@dataclass(frozen=True)
class Location:
    host: str
    path: PurePosixPath | PureWindowsPath

    def local_path(self, host: str) -> Path:
        """対象ホスト上でのみローカルパス化する。転送やマウントは行わない。"""
        if self.host != host:
            raise ValueError(f"保存先ホストは{self.host}です")
        return Path(self.path)


class Storage:
    def __init__(self, config: Path):
        self.roots = yaml.safe_load(config.read_text(encoding="utf-8"))["storage"]

    def resolve(self, logical_path: str) -> Location:
        """raw/<sha先頭2桁>/<sha>.<拡張子>または他の論理名/相対パスを解決する。

        rawはSHA-256の整数値 mod 設定配列長で媒体を選ぶ。設定順・媒体数の変更は
        再配置を伴う。UUID/serialの検証・リモート転送は呼出し元の責務。
        """
        parts = logical_path.split("/")
        if len(parts) < 2 or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in parts):
            raise ValueError("論理パスは論理名から始まる相対パスが必要です")
        root = self.roots[parts[0]]
        if parts[0] == "raw":
            match = re.fullmatch(r"raw/([0-9a-f]{2})/([0-9a-f]{64})\.([a-z0-9]+)", logical_path)
            if match is None or match[1] != match[2][:2]:
                raise ValueError("rawパスはSHA-256の内容アドレスが必要です")
            root = root[int(match[2], 16) % len(root)]
        path_type = PureWindowsPath if root["host"] == "windows" else PurePosixPath
        return Location(root["host"], path_type(root["path"]).joinpath(*parts[1:]))


def temporary_path(target: Path, token: str) -> Path:
    """確定先と同じディレクトリに試行専用ファイルを作る。失敗時の清掃は呼出し元。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.{token}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    return Path(name)
