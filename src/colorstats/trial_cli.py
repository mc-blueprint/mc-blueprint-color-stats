"""VLM試行の私有入力・結果・比較ページをローカルで準備するCLI。"""

import argparse
import io
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image
from sqlalchemy import create_engine

from colorstats.api_budget import digest
from colorstats.trial_inputs import (
    SEED,
    SPLITS,
    add_files,
    load_manifest,
    prepare,
    read_candidates,
    recheck,
    select_candidates,
    sha,
    stamp,
    write_private,
)
from colorstats.trial_pages import build_pages
from colorstats.trial_results import CONFIG_FIELDS, accept_results


def synthetic_inputs(result_root):
    """取得・送信・DB・GPUなしで、#141形式の合成30件の入力束を保存する。"""
    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="colorstats-trial-") as directory:
        sources = Path(directory)
        scenes = [
            scene
            for strata in SPLITS.values()
            for scene, count in strata.items()
            for _ in range(count)
        ]
        candidates = []
        for n, scene in enumerate(scenes):
            image = sources / f"source-{n}.png"
            Image.new("RGB", (64, 48), (n * 7, 60, 120)).save(image)
            candidates.append(
                {
                    "asset_id": str(uuid4()),
                    "subject_group": str(uuid4()),
                    "source_sha256": sha(image.read_bytes()),
                    "phash": sha(f"candidate-{n}".encode())[:16],
                    "path": str(image),
                    "scene": scene,
                    "people": "absent",
                    "scene_ref": "synthetic",
                    "person_ref": "synthetic",
                    "expires_at": (now + timedelta(days=3)).isoformat(),
                }
            )
        legacy = {
            "version": "delivery-v3",
            "presentation_sha256": sha(b"synthetic-presentation"),
            "images": [
                {
                    "asset_id": str(uuid4()),
                    "source_sha256": sha(f"old-{n}".encode()),
                    "phash": sha(f"old-phash-{n}".encode())[:16],
                }
                for n in range(108)
            ],
        }
        selected = select_candidates(candidates, legacy, now=now)
        manifest = prepare(selected, result_root, now=now, synthetic=True)
    return manifest


def demo(result_root):
    """取得・送信・DB・GPUなしで合成30件とダミー150結果を保存する。"""
    manifest = synthetic_inputs(result_root)
    now = stamp(manifest["created_at"])
    root = Path(result_root)
    (root / "masks").mkdir(mode=0o700)
    configurations = {}
    for config, precision in zip(
        "ABCDE", ["BF16", "BF16", "AWQ4", "BF16", "FP32+BF16-autocast"], strict=True
    ):
        row = {key: sha((config + key).encode()) for key in CONFIG_FIELDS}
        for key in ("model_revision", "segmenter_revision"):
            row[key] = row[key][:40]
        if config in "ABC":
            row["segmenter_revision"] = sha(b"synthetic-segmenter")[:40]
            row["segmenter_sha256"] = sha(b"synthetic-segmenter-weights")
        row["precision"] = precision
        configurations[config] = row
    active_attempts = {
        image["trial_id"]: dict.fromkeys("ABCDE", "synthetic") for image in manifest["images"]
    }
    expiry = min((image["local_expires_at"] for image in manifest["images"]), key=stamp)
    results = []
    for image in manifest["images"]:
        width, height = image["input"]["size"]
        mask = np.zeros((height, width), dtype="uint8")
        mask[height // 3 :, width // 4 : width * 3 // 4] = 255
        file = f"masks/{image['trial_id']}.png"
        stream = io.BytesIO()
        Image.fromarray(mask).save(stream, format="PNG")
        content = stream.getvalue()
        record = {"file": file, "sha256": sha(content)}
        add_files(root, [{**record, "expires_at": expiry}])
        write_private(root / file, content)
        for config in "ABCDE":
            results.append(
                {
                    "version": "trial-output-v1",
                    "trial_id": image["trial_id"],
                    "configuration_id": config,
                    "configuration_sha256": digest(configurations[config]),
                    "input_sha256": image["input"]["sha256"],
                    "size": [width, height],
                    "attempt": "synthetic",
                    "status": "success",
                    "scene": "unsupported" if config == "E" else image["scene"],
                    "regions": [{"part": "wall", "box": [0.25, 0.25, 0.75, 1], "mask": record}],
                    "elapsed_seconds": 0,
                    "peak_vram_mib": 0,
                    "expense_ref": "not_billed",
                }
            )
    accept_results(root, configurations, results, active_attempts=active_attempts, now=now)
    return build_pages(root, now=now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare")
    create.add_argument("--reviews", type=Path, required=True)
    create.add_argument("--legacy", type=Path, required=True)
    render = sub.add_parser("render")
    render.add_argument("--configurations", type=Path, required=True)
    render.add_argument("--results", type=Path, required=True)
    render.add_argument("--active-attempts", type=Path, required=True)
    for name in ("recheck", "demo"):
        sub.add_parser(name)
    for command in sub.choices.values():
        command.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "demo":
        result = demo(args.result_root)
    elif args.command == "render":
        if not load_manifest(args.result_root)["synthetic"]:
            engine = create_engine(os.environ["DATABASE_URL"])
            try:
                recheck(engine, args.result_root)
            finally:
                engine.dispose()
        accept_results(
            args.result_root,
            json.loads(args.configurations.read_text(encoding="utf-8")),
            json.loads(args.results.read_text(encoding="utf-8")),
            active_attempts=json.loads(args.active_attempts.read_text(encoding="utf-8")),
        )
        result = build_pages(args.result_root)
    else:
        engine = create_engine(os.environ["DATABASE_URL"])
        try:
            if args.command == "recheck":
                result = {
                    "usable_until": recheck(engine, args.result_root).isoformat(),
                    "external_authorized": False,
                }
            else:
                candidates, pairs = read_candidates(
                    engine, json.loads(args.reviews.read_text(encoding="utf-8"))
                )
                selected = select_candidates(
                    candidates, json.loads(args.legacy.read_text(encoding="utf-8")), pairs
                )
                manifest = prepare(selected, args.result_root)
                result = {
                    "selected": len(manifest["images"]),
                    "seed": SEED,
                    "external_authorized": False,
                }
        finally:
            engine.dispose()
    print(
        json.dumps(
            {"files": len(result["files"])} if "files" in result else result, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
