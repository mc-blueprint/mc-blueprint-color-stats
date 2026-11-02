"""ゲートのない公式SAM 2・Grounding DINO重みだけを取得する。"""

import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

from colorstats.analyze.segment_models import REPOSITORIES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    for name in ("sam2", "dino"):
        repository = REPOSITORIES[name]
        info = HfApi(token=False).model_info(repository)
        if info.gated:
            raise RuntimeError(f"{repository}はゲート付きのため取得しません")
        directory = args.models / name
        snapshot_download(
            repository, revision=info.sha, token=False, local_dir=directory,
            allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model", "LICENSE*", "README.md"],
        )
        provenance = {"repository": repository, "revision": info.sha, "license_class": "open"}
        (directory / "source.json").write_text(json.dumps(provenance) + "\n", encoding="utf-8")
        print(json.dumps(provenance))


if __name__ == "__main__":
    main()
