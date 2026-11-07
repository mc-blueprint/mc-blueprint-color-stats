"""了承済みの固定OneFormer 8ファイルを取得し、全SHAを照合する。"""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

REPOSITORY = "shi-labs/oneformer_ade20k_swin_large"
REVISION = "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads((Path(__file__).resolve().parents[2]
                           / "src/colorstats/analyze/oneformer-files.json").read_text())
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, sha in expected.items():
        target = args.directory / name
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".part")
            request = urllib.request.Request(
                f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}",
                headers={"User-Agent": "colorstats-issue118"},
            )
            with (urllib.request.urlopen(request, timeout=120) as source,
                  temporary.open("wb") as out):
                while chunk := source.read(1024 * 1024):
                    out.write(chunk)
            if digest(temporary) != sha:
                raise ValueError(f"取得ファイルのSHA不一致: {name}")
            temporary.replace(target)
        if digest(target) != sha:
            raise ValueError(f"配置済みファイルのSHA不一致: {name}")
        print(json.dumps({"file": name, "bytes": target.stat().st_size, "sha256": sha}), flush=True)
    provenance = {"repository": REPOSITORY, "revision": REVISION,
                  "license": "MIT", "files": expected}
    (args.directory / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"verified_files": len(expected), "verified_bytes": sum(
        (args.directory / name).stat().st_size for name in expected)}), flush=True)


if __name__ == "__main__":
    main()
