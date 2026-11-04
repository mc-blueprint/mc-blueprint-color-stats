# Issue #99 本番件数

- 確認日：2026-11-05
- 接続先：ubuntu-2、本番 PostgreSQL `colorstats`
- 手順：登録済みSSHスクリプト経由で `BEGIN READ ONLY`、集計SELECT、`ROLLBACK` を実行。
- 条件：`asset.subject_id` があり、収集由来の `search_parameters.collection_bias` があり、`quality.subject_inference` が未記録のasset。
- 結果：該当asset 0件、subject 0件。
- 書込み・修正：なし。

```sql
SELECT count(DISTINCT a.id) AS assets, count(DISTINCT a.subject_id) AS subjects
FROM asset a JOIN subject s ON s.id = a.subject_id
WHERE a.search_parameters ? 'collection_bias'
  AND COALESCE(a.quality, '{}'::jsonb)->'subject_inference' IS NULL;
```

この条件は旧収集処理で名称一致により割り当てられたsubjectを対象とする。今回の実行結果は0件。
