# Issue #88 実装・検証・公開準備

worktree：H:/mc-blueprint/worktrees/colorstats-88/mc-blueprint-color-stats
branch：feature/issue-88。ownerは本complex_workerセッション。再委譲なし。
引継ぎ済み起点：ed8bc430f0f5709c38578728bb3db7f189ab8490（#87・#99を含む）。
primary、並行担当のcollect/http.py・measurement.py・source_policy.yamlとそのdocsは未編集。
ユーザー指示に従いcommitまで。push・PR・merge・Issue close・実機変更は行わない。

## 完成条件

1. 内部限定：画像一時ファイルと確定ファイル0600、確定ディレクトリと内部snapshot0700。CVAT出力も非公開化。
2. 期限・停止：原画像期限と数値統計利用を分離し、受付・根拠失効後は取得直前／処理開始・更新・確定／stats・pack採用時に停止。
3. 削除監査：raw/derived/mask/CVAT/replica/cache/backupを依存台帳で管理し、参照解除・物理削除・失敗を区別。
4. 復元：DB backupと別保管する停止台帳を先に適用。古いDBに出典がなくても将来の再取得を拒否。
5. 誤削除防止：新規分だけ登録。既存asset・領域・runと共有パスを保護。原画像URL/native IDの受付は別画像を停止しない。旧snapshotは不変。
6. M4契約：public-statistics.schema.jsonとvalidate_public、混入拒否fixture。実ビルダーと必要帰属schemaはM4へ引継ぎ。
7. 公表：READMEからdocs/retention.mdへ案内し、目的・保持期間・GitHub Issue窓口と受付手順を記載。

## 共有契約

- source_policyへの追加キーは不要。既存retention.raw_days/rejected_days/deletion_request_days/backup_daysを短い方優先で再利用。
- 後続収集はstage.prepareのdatabase_urlまたは既存DATABASE_URLを必須とする。標準Workerとbias経路は対応済み。
- native IDはquality.metadata.native_id。source URL受付は出典全体、それ以外は該当画像だけ停止。不採用は現在の対象画像だけ。
- 新規画像のcolor/shade前にretention.review_privacyで確認する。人物maskは同寸PNGとSHAを固定し、payload.person_maskへ渡す。
- 新たなCVAT/cache/replica/backup作成処理はlock(88,1)内でregister_fileを呼ぶ。hostは清掃先と合わせる。
- 台帳登録済みassetの派生出力予定パスは物理公開前に別取引で確定する。登録・公開途中の障害でも再開・清掃可能。新規原本のDB確定失敗時は当該出力を清掃する。
- M4はvalidate_public(payload, session=..., selection=...)を同じ公開取引内で使用する。provider ID allowlistはwikimedia_commons/openverse/loc/mapillary。
- 0007適用、内部OS/CVAT認可、全hostのcleanupとbackup依存登録、復元前の台帳適用は運用導入時に必要。本番適用は本依頼の対象外。

## 最終検証

- WSL Ubuntu-24.04、Python 3.12.3、PostgreSQL 16.15を同一環境で実行。
- 全pytest：820 passed / 1 skipped。skipは明示重み・CUDAが必要な既存GPUテストのみ。
- 時間依存テストの断続失敗なし。単独再実行による救済なし。
- ruff check .、sdist/wheel build、git diff --check成功。
- 中間で検出したワーカープロトコル、ロック順、照会増加、台帳fixtureの隔離、空DB再作成を修正済み。
- 実サイト収集、本番DB書込み、既存永続データ削除、pilot再開、サービス設定変更なし。
- 再現：bench/issue88/verify.sh。タスク専用DBを毎回作り、終了時に専用PostgreSQLを停止する。
- 実行venv（読取り利用）：/tmp/colorstats-issue87/scratchpad/integrated-venv。
- ビルド依存：/tmp/colorstats-issue88/builddeps（hatchling 1.33.0をpip --targetで隔離導入）。
- コードコピー・結果XML・ビルド成果物：/tmp/colorstats-issue88/code、results.xml、dist/。
- 外部公開文面：指定scratchpadのi88-commit.txt・i88-pr-title.txt・i88-pr-body.md（UTF-8 BOMなし）。

## 変更ファイル

- `README.md`
- `bench/issue88/handoff.md`
- `bench/issue88/verify.sh`
- `docs/pack-contract.md`
- `docs/retention.md`
- `docs/schema.md`
- `src/colorstats/analyze/color.py`
- `src/colorstats/analyze/prep.py`
- `src/colorstats/analyze/shade.py`
- `src/colorstats/collect/bias.py`
- `src/colorstats/collect/stage.py`
- `src/colorstats/cvat.py`
- `src/colorstats/pack_boundary.py`
- `src/colorstats/public-statistics.schema.json`
- `src/colorstats/queue/core.py`
- `src/colorstats/queue/worker.py`
- `src/colorstats/retention.py`
- `src/colorstats/retention_cli.py`
- `src/colorstats/schema/migrations/versions/0007_retention.py`
- `src/colorstats/schema/models.py`
- `src/colorstats/stats/aggregate.py`
- `src/colorstats/stats/licenses.py`
- `src/colorstats/stats/snapshot.py`
- `src/colorstats/store/__init__.py`
- `tests/test_analysis_rights_db.py`
- `tests/test_retention.py`
- `tests/test_schema.py`
- `tests/test_stats_aggregate.py`
