"""既存の所有者専用設定で本番DBを読取り、性能と層別候補を標準出力へ返す。

ubuntu-1へのファイル作成・DB更新は行わない。失敗時は認証情報を含み得る
例外本文やtracebackを出さず、例外型だけを報告する。
"""

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text


def main():
    url = json.loads(Path('/var/lib/colorstats/pilot/database.json').read_text())['url']
    engine = create_engine(url, echo=False, hide_parameters=True)
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        connection.execute(text("SET LOCAL statement_timeout = '30s'"))
        snapshot_at = connection.scalar(text('SELECT transaction_timestamp()')).isoformat()
        assets = [dict(row) for row in connection.execute(text('''
            WITH origins AS MATERIALIZED (
                SELECT DISTINCT ON (p.value) p.value AS source, r.id AS run_id
                FROM processing_run r CROSS JOIN LATERAL jsonb_each_text(r.output_paths) p
                WHERE r.stage='collect' AND r.finished_at IS NOT NULL
                      AND r.failure_reason IS NULL
                ORDER BY p.value, r.finished_at DESC
            )
            SELECT a.id::text AS asset_id, a.sha256, a.storage_path AS source,
                   a.license_class, a.taxonomy_version, a.domain, a.retrieved_at,
                   a.search_parameters->'collection_bias' AS bias,
                   c.run_id::text AS source_run_id
            FROM asset a
            LEFT JOIN origins c ON c.source=a.storage_path
            ORDER BY a.id
        ''')).mappings()]
        runs = [dict(row) for row in connection.execute(text('''
            SELECT j.asset_id::text AS asset_id, j.stage, j.attempts,
                   r.id::text AS run_id, r.started_at, r.finished_at, r.code_version,
                   r.output_paths,
                   EXTRACT(EPOCH FROM r.finished_at-r.started_at)::float AS seconds
            FROM job j JOIN processing_run r ON r.id=j.run_id
            WHERE j.stage IN ('prep', 'color') AND j.status='succeeded'
                  AND r.finished_at IS NOT NULL AND r.failure_reason IS NULL
            ORDER BY j.stage, j.asset_id
        ''')).mappings()]
        statuses = [dict(row) for row in connection.execute(text('''
            SELECT stage, status, count(*) AS items FROM job
            WHERE stage IN ('prep','color') GROUP BY stage,status ORDER BY stage,status
        ''')).mappings()]
    engine.dispose()
    # collection_biasを持つ画像を#44の層別収集コホートとして固定する。
    cohort = {row['asset_id'] for row in assets if row['bias']}
    summaries = []
    for stage in ('prep', 'color'):
        rows = [row for row in runs if row['stage'] == stage and row['asset_id'] in cohort]
        paths = sorted({p for row in rows for p in row['output_paths'].values()})
        existing = [Path(p) for p in paths if Path(p).is_file()]
        seconds = sum(row['seconds'] for row in rows)
        output_bytes = sum(p.stat().st_size for p in existing)
        first = min((row['started_at'] for row in rows), default=None)
        last = max((row['finished_at'] for row in rows), default=None)
        summaries.append({
            'stage': stage, 'successful_runs': len(rows),
            'unique_assets': len({row['asset_id'] for row in rows}),
            'summed_run_seconds': seconds,
            'items_per_active_second': len(rows) / seconds if seconds else None,
            'first_started_at': first, 'last_finished_at': last,
            'span_seconds': (last-first).total_seconds() if rows else None,
            'output_files': len(existing), 'missing_output_files': len(paths)-len(existing),
            'output_bytes': output_bytes,
            'bytes_per_run': output_bytes / len(rows) if rows else None,
            'attempts': dict(Counter(row['attempts'] for row in rows)),
            'code_versions': dict(Counter(row['code_version'] for row in rows)),
        })
    candidates = []
    for row in assets:
        if row['asset_id'] not in cohort or not row['source_run_id']:
            continue
        bias = row.pop('bias')
        row.update(stratum=bias.get('stratum'), source_stage='collect', input_run_id=None)
        candidates.append(row)
    print(json.dumps({
        'captured_at': datetime.now(UTC).isoformat(), 'snapshot_at': snapshot_at,
        'all_assets': len(assets), 'cohort_assets': len(cohort),
        'cohort_definition': 'asset.search_parameters.collection_biasが存在する層別収集画像',
        'job_statuses_all_assets': statuses, 'stages': summaries, 'candidates': candidates,
    }, default=str, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error_type': type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
