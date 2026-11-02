"""Issue47: 固定した収集画像でDBを使わず常駐stage性能を測る。

既存prepareの出力だけを専用rootへ確定する。segmentのモデル生成だけを
計測内で一度にまとめ、本番のWorker・モデル実装は変更しない。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, UUID, uuid5


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Sampler:
    def __init__(self, path):
        self.path = path
        self.samples = []
        self.error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        try:
            self._sample()
        except Exception as error:
            self.error = error

    def _sample(self):
        with self.path.open('x', encoding='utf-8') as stream:
            while not self.stop.is_set():
                start = time.monotonic()
                status = Path('/proc/self/status').read_text()
                rss = next(int(line.split()[1]) * 1024 for line in status.splitlines()
                           if line.startswith('VmRSS:'))
                result = subprocess.run([
                    'nvidia-smi', '--query-gpu=utilization.gpu,memory.used',
                    '--format=csv,noheader,nounits',
                ], capture_output=True, text=True, check=True)
                utilization, memory = map(int, result.stdout.strip().split(','))
                row = {'at': datetime.now(UTC).isoformat(), 'rss_bytes': rss,
                       'gpu_utilization_percent': utilization, 'gpu_memory_mib': memory}
                self.samples.append(row)
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                self.stop.wait(max(0, 1 - (time.monotonic()-start)))

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        if self.error is not None:
            raise self.error

    def summary(self):
        return {
            'sample_interval_seconds': 1, 'samples': len(self.samples),
            'max_rss_bytes': max((row['rss_bytes'] for row in self.samples), default=None),
            'gpu_utilization_mean_percent': (
                sum(row['gpu_utilization_percent'] for row in self.samples) / len(self.samples)
                if self.samples else None),
            'gpu_utilization_max_percent': max(
                (row['gpu_utilization_percent'] for row in self.samples), default=None),
            'gpu_memory_max_mib': max(
                (row['gpu_memory_mib'] for row in self.samples), default=None),
        }


def claim(stage, row, payload, config_hash):
    from colorstats.queue.core import Claim

    identifier = uuid5(NAMESPACE_URL, f'issue47/{stage}/{row["asset_id"]}')
    return Claim(id=identifier, token=identifier, stage=stage, asset_id=UUID(row['asset_id']),
                 config_hash=config_hash, payload=payload, attempt=1, started_at=datetime.now(UTC))


def publish(prepared):
    total = 0
    for temporary, target in prepared.files:
        if target.exists():
            raise FileExistsError(target)
        total += temporary.stat().st_size
        temporary.replace(target)
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--deadline', required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_relative_to(Path('/mnt/data/work/issue-47')):
        raise ValueError('評価専用のissue-47配下だけを使用してください')
    deadline = datetime.fromisoformat(args.deadline)
    selected = json.loads((root / 'selection.json').read_text())
    rows = selected['files']
    initialization_started = time.perf_counter()
    import torch

    from colorstats.analyze import color, prep, segment, segment_models, shade

    imports_seconds = time.perf_counter() - initialization_started
    torch.manual_seed(0)
    paths = {name: str(args.models / name) for name in ('sam2', 'dino')}
    prompts = selected['prompts']
    result = {
        'node': socket.gethostname(), 'platform': platform.platform(),
        'started_at': datetime.now(UTC).isoformat(), 'selected': len(rows),
        'selection_sha256': segment._hash(root / 'selection.json'),
        'raw_manifest_sha256': segment._hash(root / 'raw-cache/batches/sample/manifest.json'),
        'imports_seconds': imports_seconds, 'torch_version': torch.__version__,
        'benchmark_sha256': segment._hash(Path(__file__)),
        'implementation_sha256': {
            name: segment._hash(Path(module.__file__)) for name, module in (
                ('prep', prep), ('segment', segment), ('segment_models', segment_models),
                ('shade', shade), ('color', color),
            )
        },
        'cuda_version': torch.version.cuda, 'gpu': torch.cuda.get_device_name(),
        'prompts': prompts, 'threshold': 0.35, 'text_threshold': 0.25,
        'batch_size': 1, 'box_batch_size': 1, 'precision': 'bfloat16',
        'database': '未使用。prepareと専用出力へのrenameのみ',
        'timing': '設定ハッシュ生成・prepare・ファイル確定を含む。DB・転送・待機は含まない',
        'stages': [],
    }
    region_inputs = {}
    runner = None
    for stage in ('prep', 'segment', 'shade-none', 'shade-gray-world', 'color-parts'):
        if datetime.now(UTC) >= deadline:
            result['stopped_before'] = stage
            break
        output = root / 'outputs' / stage
        output.mkdir(parents=True, exist_ok=False)
        if stage == 'segment':
            torch.cuda.reset_peak_memory_stats()
            with Sampler(root / 'model-init-telemetry.jsonl') as monitor:
                start = time.perf_counter()
                runner = segment_models._sam2(paths)
                torch.cuda.synchronize()
                result['model_initialization'] = {
                    'seconds': time.perf_counter()-start,
                    'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                    'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
                }
            result['model_initialization'].update(monitor.summary())

        def resident_predict(
            image, method, model_paths, image_prompts, threshold, text_threshold, runner=runner,
        ):
            started = time.perf_counter()
            with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
                predictions = runner(image, image_prompts, threshold, text_threshold)
            torch.cuda.synchronize()
            return predictions, {
                'load_seconds': 0, 'inference_seconds': time.perf_counter()-started,
            }

        stage_rows = []
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        with Sampler(root / f'{stage}-telemetry.jsonl') as monitor, patch(
            'colorstats.analyze.segment.predict', resident_predict,
        ):
            for row in rows:
                if datetime.now(UTC) >= deadline:
                    break
                asset_id = row['asset_id']
                base = {
                    'license_class': row['license_class'],
                    'taxonomy_version': row['taxonomy_version'],
                }
                item_start = time.perf_counter()
                try:
                    if stage == 'prep':
                        payload = {**base, 'input_path': str(
                            root / 'raw-cache/batches/sample' / row['name']),
                            'derived_path': str(output / f'{asset_id}.jpg')}
                        prepared = prep.prepare(claim(
                            stage, row, payload, segment._digest(payload)))
                    else:
                        payload = {**base,
                                   'input_path': str(root / 'outputs/prep' / f'{asset_id}.jpg'),
                                   'input_run_id': None,
                                   'output_path': str(output / f'{asset_id}.json')}
                        if stage == 'segment':
                            payload.update(method='sam2-dino', model_paths=paths, prompts=prompts,
                                           threshold=0.35, text_threshold=0.25)
                            prepared = segment.prepare(claim(
                                stage, row, payload, segment.config_hash(payload)))
                        else:
                            payload.update(
                                regions=region_inputs[asset_id],
                                region_run_id=str(uuid5(
                                    NAMESPACE_URL, f'issue47/segment/{asset_id}')),
                            )
                            handler = color if stage == 'color-parts' else shade
                            if stage != 'color-parts':
                                payload['method'] = stage.removeprefix('shade-')
                            prepared = handler.prepare(claim(
                                'color' if stage == 'color-parts' else 'shade', row, payload,
                                handler.config_hash(payload)))
                    output_bytes = publish(prepared)
                    record = {'asset_id': asset_id, 'success': True, 'output_bytes': output_bytes,
                              'seconds': time.perf_counter()-item_start}
                    if stage == 'segment':
                        data = prepared.data
                        if 'models' not in result:
                            result['models'] = prepared.info.parameters['models']
                        region_inputs[asset_id] = sorted([
                            {'region_id': str(uuid5(NAMESPACE_URL, f'issue47/{asset_id}/{i}')),
                             'mask_path': part['mask_path'], 'label_source': 'model',
                             'size': [data['metrics']['width'], data['metrics']['height']]}
                            for i, part in enumerate(data['regions'])
                        ], key=lambda part: part['region_id'])
                        record['regions'] = len(data['regions'])
                        record['inference_seconds'] = data['metrics']['inference_seconds']
                    if stage == 'color-parts':
                        record['relations'] = len(prepared.data['relations'])
                        record['regions'] = len(prepared.data['regions'])
                except Exception as error:
                    record = {'asset_id': asset_id, 'success': False,
                              'error_type': type(error).__name__, 'error': str(error),
                              'seconds': time.perf_counter()-item_start}
                stage_rows.append(record)
                if len(stage_rows) % 10 == 0:
                    save(root / f'{stage}-items.json', stage_rows)
                    print(stage, len(stage_rows), '/', len(rows), flush=True)
        elapsed = time.perf_counter()-started
        successful = [row for row in stage_rows if row['success']]
        total = sum(row['output_bytes'] for row in successful)
        summary = {
            'stage': stage, 'attempted': len(stage_rows), 'successful': len(successful),
            'failed': len(stage_rows)-len(successful), 'elapsed_seconds': elapsed,
            'items_per_second': len(successful)/elapsed,
            'output_bytes': total, 'bytes_per_item': total/len(successful) if successful else None,
            'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
            'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
            **monitor.summary(),
        }
        if stage == 'segment':
            summary['inference_seconds'] = sum(row['inference_seconds'] for row in successful)
            summary['regions'] = sum(row['regions'] for row in successful)
            save(root / 'region-inputs.json', region_inputs)
        if stage == 'color-parts':
            summary['relations'] = sum(row['relations'] for row in successful)
        result['stages'].append(summary)
        save(root / f'{stage}-items.json', stage_rows)
        save(root / 'ubuntu2-results.json', result)
        print(json.dumps(summary), flush=True)
    result['finished_at'] = datetime.now(UTC).isoformat()
    result['complete'] = len(result['stages']) == 5 and all(
        stage['successful'] == len(rows) for stage in result['stages'])
    save(root / 'ubuntu2-results.json', result)


if __name__ == '__main__':
    # 認証設定も本番DBも使わないことを起動時に固定する。
    for name in ('DATABASE_URL', 'TEST_DATABASE_URL'):
        os.environ.pop(name, None)
    main()
