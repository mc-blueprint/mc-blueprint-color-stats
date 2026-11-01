# PostgreSQL復元試験（2026-11-01）

- 保存先：ubuntu-0 WD750GB `/srv/colorstats/backup-wd750/daily/`
- 復元先：ubuntu-2 PostgreSQL 16 の一時DB `colorstats_restore_check`（ubuntu-1にはPostgreSQLクライアント／サーバーがなかったため、別DBで実施）
- 手順：空の `colorstats` DBに試験テーブルと3行を作成し、日次 `pg_dump -Fc` を生成・転送。別DBへ `pg_restore --exit-on-error --no-owner` で復元して件数と行データ指紋を比較。
- 結果：元・復元後とも3行、指紋は `9c0e35cfa6c9b504ce3fc47ab51b5792` で一致。
- 復元に使った試験ダンプSHA-256：`6263408011c277f0ad723932327abfa1cf4087077294997e20ef805290047230`。転送直後にWD上の同一ダンプと一致確認済み。
- 終了後に一時DB、試験テーブル、ubuntu-2上の一時ダンプを削除。
- 試験テーブル削除後に日次serviceを再実行し、WDの日次・週次を更新。その時点のSHA-256は `colorstats`: `17dcaedaa8ec1d350eca8650dc42f2e7290212ad4461bc7704c602c68453e93f`、`postgres`: `2f16495f2103ea743db7890fb5793ed68cead0b678bafb68373092a697c7f7b7`。

## 再起動後の起動失敗と復旧確認

- ユーザーによるubuntu-2の再起動日時は2026-11-01 10:11:30 UTC。10:11:38 UTCのPostgreSQLログに `could not bind IPv4 address "192.168.1.86": Cannot assign requested address` と `FATAL: could not create any TCP/IP sockets` があり、LAN IPv4未割当による起動失敗を確認した。
- 変更前の設定は `listen_addresses = '"192.168.1.86"'`。余分な引用符も除き、`pg_conftool 16 main set listen_addresses '*'` を適用。10:43:35 UTCに `postgresql@16-main.service` を起動し、activeになった。今回の失敗原因は未割当の特定IPへのbindであり、全インターフェース待受によってその依存を除去した。
- `SHOW data_directory` は `/mnt/data/postgres`、`SHOW listen_addresses` は `*`、`SHOW password_encryption` は `scram-sha-256`。`/mnt/data` はNVMeのext4マウントであることを確認。
- localhost・`127.0.0.1`・`::1`・`192.168.1.86` 宛てにロール・DB `colorstats` で認証付き接続成功。`pg_hba_file_rules` に構文エラーはなく、TCP許可はlocalhostとLAN内の `colorstats` DB・ロールに限定されている。
- ubuntu-1（`192.168.1.85`）から `192.168.1.86:5432` へのLAN TCP接続成功。ubuntu-1にはpsql・libpq・Python PostgreSQLドライバがなく、認証付きSQL確認は未完了。ubuntu-2の既存クライアントを一時利用し、認証値をSSH経由で検証プロセスのメモリだけに渡す案は、自動承認審査で秘密情報のホスト間移送に明示承認がないとして拒否された。認証値の移送は実行されておらず、ユーザー承認待ち。
- 自動起動設定は `postgresql.service`: enabled、`postgresql@16-main.service`: enabled-runtime、クラスタの `start.conf`: auto。クラスタはPostgreSQLの起動生成規則により有効化されている。ホストの追加再起動は行わず、次回ブートの実動確認は未実施。
- ubuntu-2の `colorstats-backup.timer` とubuntu-0の `colorstats-backup-retention.timer` はともにactive・enabled。
- 10:43:37–10:43:38 UTCに `colorstats-backup.service` を手動実行し、`Result=success`・`ExecMainStatus=0`。ubuntu-0のWD750GB（UUID `3f9a319f-394c-4cca-805d-fc88d782d644`）への転送を確認した。
- WDの `daily/` と `weekly/` の2026-11-01分はともに更新され、ダンプ本体と `.sha256` が一致。最新SHA-256は `colorstats`: `1eab419b8493dd28078e2f5440ef80424fb6f2108ecdcde433e5b1498ceec4bd`（896 bytes）、`postgres`: `96fe69450a60493afccb355eaf24522c02c83108caf9cac614e19b6e12e6dd30`（1097 bytes）。
- Windowsの指定uv・Python 3.12.15で `uv run pytest`: 6件成功、`uv run ruff check .`: 成功。
- 主バックアップ媒体はWD 1台。ST3500 2台は未使用・未変更で、既存データの確認と利用可否のユーザー判断待ち。媒体冗長化は未達。
