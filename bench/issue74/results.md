# Issue #74 第1段階の検証記録

2026-11-03。基準origin/developは133b2691c16103057b42dc8713a0f7c824daa89f。
ブランチfeature/issue-74、担当worktreeは
H:/mc-blueprint/worktrees/colorstats-74/mc-blueprint-color-stats。
commit・push・PR作成と公開文面の作成は行っていない。

## 実装と境界

既存SQLAlchemy/psycopgで1つのREPEATABLE READ / READ ONLY取引を開き、
必要列を256件ずつ取得する。DuckDBの組込みParquetを使い、Arrow/pandasや
PostgreSQL拡張の自動取得を追加しない。新規DBテーブル・Enum・移行はない。
DuckDBは1.4.3固定。既存lockの更新はこの依存の追加分だけ。
Python 3.12.15/Windowsのuv sync --lockedとUbuntu 24.04のcp312 wheelで確認した。
一次情報: [PyPI配布メタデータ](https://pypi.org/pypi/duckdb/1.4.3/json)、
[MITライセンス](https://duckdb.org/faq)。
lockにはcp312-win_amd64とcp312-manylinux_2_26_x86_64のwheelとhashがある。

契約とCLIの詳細は[schema追記案](schema-section.md)を参照する。
docs/schema.mdは#79との競合を避けて未変更。
#66の「和集合統計は後続snapshotで生成」と#81の固定評価に接続し、
wall/treeの和集合主色を既存colorの画素抽出で生成する。
重なりの二重計上や建築ラベルの支持の地形への転用を防ぐ。
生成時だけ画像・マスクを読み、生成後はDBと画像なしで値を使える。
主統計のsubject・属性・n_effの選択とQueue.completeによる登録は#75の責務。

## 最終検証

- ruff check .: 成功。
- uv lock --check: 成功。uv build: sdist・wheelとも成功。
- Windows/Python 3.12.15全件pytest: 360 passed, 147 skipped、53.43秒。
  DB未指定によるDB関連と既存GPU条件付きテストをスキップした。
  colourの任意Matplotlib未導入の警告が1件ある。
- Ubuntu/PostgreSQL 16.15全件pytest: 506 passed, 1 skipped、83.01秒。
  スキップは既存の公式重み・CUDA等の明示指定を要するGPUテスト。
- #74の22テストはすべて成功。
  SA/NC/ND、評価専用重み、由来欠損、複数出典、SHA代表、成功run混在、
  別asset・失敗run・入力循環・設定不一致、subject/属性/候補の固定、
  並行更新下の一貫読取り、出力失敗・上書き拒否、manifest/Parquet改変拒否を確認。
- 品質資料のCRLF/LF差を吸収し、内容改変は拒否する。
  和集合は重複画素を一度だけ使い、画像削除後もsnapshotを検証できる。
- 検証runnerは__main__ガードと子プロセス用PYTHONPATHを指定する。
  test_schemaは空DB必須のため、最終実行は新規の専用DBを使用した。

## fixtureの数値

9 asset、SHA異なり7。権利適格4、必要解析・domain確認後3、SHA代表2。
全出典9行を保持。個別観測24行中の入口・品質適格は2行、
関係8行中の適格は0行。観測クラスタ行数と画像数は異なる。
除外理由は複数該当を許し、合計を除外asset数として扱わない。
別fixtureでは確定subjectと候補根拠、権利制約のある推定入力runを検査した。

OS間照合は[roundtrip.py](roundtrip.py)を使用した。
実DB fixtureの7 Parquet・94行をLinux→Windows→Linuxで全列値照合し、
各方向の読書きとmanifest/ファイルhashの検証が成功。
各再出力はmanifest込み32,851バイト。
Windows 0.422秒、Ubuntu 0.168秒（小fixtureであり全量性能の外挿値ではない）。

- 元fixture: 2997372687636635630e8fcb17ad0a285e91cfc7330de43598877acedd0d8fbb
- Windows再出力: 5b7e8328250724cf49a4f63e779937586e19f5e3600cabad07a62f1ceb7b3392
- Linux再出力: 9236301c978cfc25f47a8615931b312e791fb8b89518d4cb6f0d90fffe62dd5e

OS間照合後の変更は件数区分の分離とドメイン別ゲート等。
OS間照合fixtureのParquet形式は変えていない。

## 実行領域と残り作業

ローカルvenv・転送用アーカイブ・OS間fixtureは指定scratchpadのvenv-74、
i74-*.py/アーカイブ、i74-linux-fixture、i74-windows-roundtrip2に保全する。
Ubuntuは/mnt/data/work/issue-74にコード・依存・fixture・ログを保全する。
専用PostgreSQL 16は同領域のpgdata、専用socket、ポート5574で隔離した。
本番DBの変更、#66全量ジョブの停止、ubuntu-1 pilot再開は行っていない。

第2段階は#66全量完了と#79 merge後に実データsnapshotを生成する。
本番DBへの任意dry-runも今回は未実施。
実データの権利適格数・確定subject支持・全量の速度/容量は未計測で、
fixtureの結果をM3全体の支持条件達成とは扱わない。
schema節の統合、公開文面の作成、公開は第2段階に残る。

## 2026-11-05 第2段階の完了

上記の残り作業は当時の状態。全量snapshot生成・schema統合・公開準備は
[全量検証記録](full-results.md)で完了し、件数・hashは[全量監査JSON](full-summary.json)へ記録した。
push・PRは今回の指示により未実施。
