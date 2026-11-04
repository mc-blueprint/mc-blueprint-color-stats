# Issue #77 第1段階の検証記録

2026-11-03、起点 `2ea1ea5`、ブランチ `feature/issue-77`。本番の実収集・書込み・公開は未実施。

- Windows Python 3.12、全pytest：366 passed / 166 skipped。DBと明示指定GPU等をスキップ。
- Ubuntu Python 3.12、専用PostgreSQL 16.15の全pytest：531 passed / 1 skipped（GPU）。
- 反証修正を含む収集関連テスト：185 passed。
- ruff check .、sdist/wheelビルド、git diff --check：成功。
- 通信は既存fixture／モックのみ。GPU・本番DB・#66のサービスは使っていない。
- 専用DBは `/mnt/data/work/issue-77/pgdata`、Unix socket、port 5577、listen_addresses空。
  テストごとに新規の空DBを作り、さらに既存fixtureが固有schemaを作成・削除する。
  実行後に専用PostgreSQLの停止を確認済み。検証artifactとDBデータは保全する。

反証範囲：URL予約競合・失効と再試行、同一URL再発見、別URLの既存SHA、同バッチSHA、
SAとCC0の候補順、API/HTTP要求分母、timeoutを含む再成功、byte、層満了前の検索停止、
API上限後の無通信、カテゴリ内候補とAPI継続、旧bias稼働時の拒否、source_policy変更拒否、
既存作者・ライセンス完全照合の回帰、確定subjectを名前一致だけで数えないこと。

本番残存確認（09:19 UTC、postgres peer、REPEATABLE READ / READ ONLY）：
pending/running collect 0件、finished_atがNULLのbias/measurement run 0件。削除は行っていない。
反証修正時に本番DBへの接続は行っていない。第2段階の開始直前に再確認する。

主な監査ログ（`%USERPROFILE%/.codex/logs/commands/`）：

- 本番読取り：`20261103T091912Z-3efb9c3f65bd4458a5c709cb51f3741a.jsonl`
- 隔離DB全体：`20261103T095812Z-e312385b87f445f695b8113e89e44386.jsonl`
- 収集関連185件：`20261103T095640Z-d3bda69366244df4bc3f415220d5118b.jsonl`
- 最終ruff：`20261103T095947Z-e7f164a0e9ba40b9b81036ff0c00f5c5.jsonl`
- 最終ビルド：`20261103T095946Z-bd4e4e8181744fc1bbc8bf8107167fc2.jsonl`

残りは#66完了後の実収集と#72による根拠付き同定、その後の歩留まり報告。
Openverseの`by`は測定時に照合済みの選択値・版から正規化し、SA等の除外を維持する。
stats/・analyze/・queue/およびdocs/collection-bias.mdは変更していない。
新規の外部技術・DBスキーマ・保存形式移行はない。メインへ渡す新しい契約は、
測定設定・試行run台帳・observerイベントと根拠付きsubjectだけを数える分母（docs/collect.md）である。

反証F1〜F5は修正・回帰済み。既定urllibのHTTPHandlerをモックし外部接続を禁止して、
リダイレクト先での枠・待機・UA・応答byteを確認した。BY/BY-SAの実アダプターfixture、
原本取得途中の上限停止、照合途中の除外と継続位置、取得timeout時の履歴保存、
異なる出典からの同じ原本URL再発見を隔離DBで再現した。
懸念C1は供給元固定枠を実装し、Commons枠満了後もOpenverseが要求できる反例で検証した。
C2は1万Asset行と適格SHAの上限・層別外挿式・成立条件をplan.mdへ記載した。
