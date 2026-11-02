"""選択したrawを検証付きで複製する配備案。自動起動・DB更新は行わない。

stageはubuntu-1で媒体監視と原本SHA-256を確認し、転送専用ディレクトリを作る。
publishは転送後のディレクトリを検証し、対象ノードのキャッシュへ原子的に公開する。
呼出しは監査付きSSHで行い、転送自体もrun_logged.pyで記録する。
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
from pathlib import Path

from colorstats.queue.storage import storage_available

RAW_ROOTS = (Path("/srv/colorstats/raw-orico"), Path("/srv/colorstats/raw-suneast"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage(destination, sources):
    if socket.gethostname() != "ubuntu-1":
        raise ValueError("stageはubuntu-1で実行してください")
    if not storage_available("prep"):
        raise RuntimeError("raw媒体が停止中です。複製を保留してください")
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for source in sources:
        source = source.resolve(strict=True)
        if not any(source.is_relative_to(root) for root in RAW_ROOTS):
            raise ValueError("raw媒体以外は転送できません")
        sha256 = digest(source)
        if source.stem != sha256:
            raise ValueError("原本の名前とSHA-256が一致しません")
        name = sha256 + source.suffix
        target = destination / name
        shutil.copyfile(source, target)
        if digest(target) != sha256 or not storage_available("prep"):
            raise RuntimeError("複製中に媒体停止または内容不一致を検知しました")
        records.append({"source": str(source), "name": name, "sha256": sha256,
                        "bytes": target.stat().st_size})
    (destination / "manifest.json").write_text(
        json.dumps({"files": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def publish(staging, destination):
    records = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))["files"]
    if destination.exists():
        raise FileExistsError("公開先には新しいバッチ名を指定してください")
    # renameまで不完全なバッチを利用者へ渡さない。
    for record in records:
        name = record["name"]
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("不正な原本名です")
        source = staging / name
        if source.is_symlink() or digest(source) != record["sha256"]:
            raise ValueError("転送した原本のSHA-256が一致しません")
        if source.stat().st_size != record["bytes"]:
            raise ValueError("転送した原本の容量が一致しません")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staging, destination)
    print(json.dumps({"root": str(destination), "files": len(records)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--destination", type=Path, required=True)
    stage_parser.add_argument("sources", type=Path, nargs="+")
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--staging", type=Path, required=True)
    publish_parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "stage":
        stage(args.destination, args.sources)
    else:
        publish(args.staging, args.destination)


if __name__ == "__main__":
    main()
