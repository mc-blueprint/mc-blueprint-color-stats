"""ubuntu-1を読取り専用のまま転送した原本を、#42の検証・公開関数へ渡す。"""

import argparse
import json
import runpy
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_relative_to(Path('/mnt/data/work/issue-47')):
        raise ValueError('Issue47の評価専用領域を指定してください')
    selection = json.loads((root / 'selection.json').read_text())
    replica = runpy.run_path(str(root / 'ops/deploy/raw-replica.py'))
    staging = root / 'raw-cache/staging/sample'
    by_name = {}
    for row in selection['files']:
        source = staging / row['name']
        digest = replica['digest'](source)
        if digest != row['sha256'] or source.stem != digest:
            raise ValueError('DB・原本名・転送済み画像のSHA-256が一致しません')
        origin = {key: row[key] for key in (
            'asset_id', 'source_run_id', 'source_stage', 'input_run_id',
            'sha256', 'source', 'license_class',
        )}
        record = by_name.setdefault(source.name, {
            'source': row['source'], 'name': source.name, 'sha256': digest,
            'bytes': source.stat().st_size, 'origins': [],
        })
        record['origins'].append(origin)
    manifest = {'files': list(by_name.values())}
    (staging / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    config = {'root': str(root / 'raw-cache'), 'max_bytes': 150_000_000_000}
    replica['capacity'](config)
    replica['publish'](staging, root / 'raw-cache/batches/sample', config)
    (root / 'cache-proof.json').write_text(json.dumps({
        'files': len(by_name), 'assets': len(selection['files']),
        'raw_bytes': sum(row['bytes'] for row in by_name.values()),
        'manifest_sha256': replica['digest'](root / 'raw-cache/batches/sample/manifest.json'),
        'max_bytes': config['max_bytes'],
        'verification': 'DBのSHA・原本名・転送後SHA・#42 publishによる再検証',
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
