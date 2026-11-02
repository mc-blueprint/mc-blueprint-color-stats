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
from contextlib import contextmanager
from pathlib import Path

RAW_ROOTS = (Path("/srv/colorstats/raw-orico"), Path("/srv/colorstats/raw-suneast"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage(destination, sources, provenance):
    from colorstats.queue.storage import storage_available

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
        origins = [row for row in provenance["files"] if row["source"] == str(source)]
        if not origins or any(
            row["sha256"] != sha256 or not row["asset_id"] or not row["source_run_id"]
            or row["source_stage"] != "collect" or row["input_run_id"] is not None
            for row in origins
        ):
            raise ValueError("原本とasset・collect runの由来記録が一致しません")
        name = sha256 + source.suffix
        target = destination / name
        shutil.copyfile(source, target)
        if digest(target) != sha256 or not storage_available("prep"):
            raise RuntimeError("複製中に媒体停止または内容不一致を検知しました")
        records.append({"source": str(source), "name": name, "sha256": sha256,
                        "bytes": target.stat().st_size, "origins": origins})
    (destination / "manifest.json").write_text(
        json.dumps({"files": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def usage(root):
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def capacity(config, incoming_bytes=0):
    root = Path(config["root"]).resolve(strict=True)
    with cache_lock(root):
        used = usage(root)
        if incoming_bytes < 0 or used + incoming_bytes > config["max_bytes"]:
            raise ValueError("cacheの容量上限を超えています。転送を保留してください")
        print(json.dumps({"cache_bytes": used, "incoming_bytes": incoming_bytes,
                          "max_bytes": config["max_bytes"]}))


@contextmanager
def cache_lock(root):
    lock = root / ".lock"
    lock.mkdir()
    try:
        yield
    finally:
        lock.rmdir()


def batch_path(root, destination):
    if destination.is_symlink() or destination.resolve().parent != root / "batches":
        raise ValueError("公開先はcacheのbatches直下に指定してください")


def publish(staging, destination, config):
    """同一cache内のstagingを検証し、全ファイルの合計が上限以下なら公開する。"""
    root = Path(config["root"]).resolve(strict=True)
    batch_path(root, destination)
    if staging.is_symlink() or staging.resolve().parent != root / "staging":
        raise ValueError("転送先はcacheのstaging直下に指定してください")
    with cache_lock(root):
        if usage(root) > config["max_bytes"]:
            raise ValueError("cacheの容量上限を超えています。投入を保留してください")
        _publish(staging, destination)
        print(json.dumps({"cache_bytes": usage(root), "max_bytes": config["max_bytes"]}))


def _publish(staging, destination):
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


def prune(destination, completion, config):
    """運用者の完了証跡に基づき、全GPUジョブ成功・参照なしのバッチだけ削除する。

    completionの契約とDB照合・新規参照停止の手順はops/deploy/README.md参照。
    DBへ接続せず、不一致・未成功・参照ありではValueErrorとして保持する。
    """
    root = Path(config["root"]).resolve(strict=True)
    batch_path(root, destination)
    with cache_lock(root):
        expected = completion["expected_gpu_jobs"]
        jobs = completion["gpu_jobs"]
        ids = [job["job_id"] for job in jobs]
        if (
            completion["batch"] != destination.name
            or completion["manifest_sha256"] != digest(destination / "manifest.json")
            or not expected or len(set(expected)) != len(expected)
            or len(set(ids)) != len(ids) or set(expected) != set(ids)
            or any(job["status"] != "succeeded" for job in jobs)
            or completion["references"] != []
        ):
            raise ValueError("全GPU stageの成功と参照解除を確認できないため保持します")
        shutil.rmtree(destination)
        print(json.dumps({"deleted": str(destination), "cache_bytes": usage(root)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--destination", type=Path, required=True)
    stage_parser.add_argument("--provenance", type=Path, required=True)
    stage_parser.add_argument("sources", type=Path, nargs="+")
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--staging", type=Path, required=True)
    publish_parser.add_argument("--destination", type=Path, required=True)
    publish_parser.add_argument("--config", type=Path, required=True)
    prune_parser = commands.add_parser("prune")
    prune_parser.add_argument("--destination", type=Path, required=True)
    prune_parser.add_argument("--completion", type=Path, required=True)
    prune_parser.add_argument("--config", type=Path, required=True)
    capacity_parser = commands.add_parser("capacity")
    capacity_parser.add_argument("--config", type=Path, required=True)
    capacity_parser.add_argument("--incoming-bytes", type=int, default=0)
    args = parser.parse_args()
    if args.command == "stage":
        stage(args.destination, args.sources,
              json.loads(args.provenance.read_text(encoding="utf-8")))
    elif args.command == "publish":
        publish(args.staging, args.destination,
                json.loads(args.config.read_text(encoding="utf-8")))
    elif args.command == "prune":
        prune(args.destination, json.loads(args.completion.read_text(encoding="utf-8")),
              json.loads(args.config.read_text(encoding="utf-8")))
    else:
        capacity(json.loads(args.config.read_text(encoding="utf-8")), args.incoming_bytes)


if __name__ == "__main__":
    main()
