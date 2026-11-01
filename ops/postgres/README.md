# PostgreSQL 16（ubuntu-2）

## 構成

- Ubuntu 24.04標準のPostgreSQL 16を使用する。
- クラスタのデータディレクトリは `/mnt/data/postgres`。
- 待受は全インターフェース（`listen_addresses = '*'`）とし、TCP接続元は `pg_hba.conf` でlocalhostとLAN内 `192.168.1.0/24` に限定し、SCRAM-SHA-256で認証する。LANからはDB・ロールとも `colorstats` の接続だけを許可する。
- ローカル管理はOSの `postgres` ユーザーによるpeer認証を使う。

## 初期構築

初期生成されたクラスタを停止し、既存データを保持したまま指定領域へ複製してからデータディレクトリを切り替える。元のディレクトリは切替確認まで残す。

```sh
sudo systemctl stop postgresql
sudo install -d -o postgres -g postgres -m 700 /mnt/data/postgres
sudo rsync -aHAX --numeric-ids /var/lib/postgresql/16/main/ /mnt/data/postgres/
sudo pg_conftool 16 main set data_directory /mnt/data/postgres
sudo systemctl start postgresql
```

リポジトリの運用設定を適用するときは `sudo bash ops/postgres/configure.sh` を実行する。アプリ用パスワードは `/var/lib/postgresql/colorstats-password`、接続確認用 `.pgpass` は `/var/lib/postgresql/.pgpass` にpostgres所有・mode 600で保存される。値を端末出力やログに表示しない。

`/etc/postgresql/16/main/postgresql.conf` の `listen_addresses` を `'*'` にし、`pg_hba.conf` に次の規則を追加する。既定のlocalhost向けSCRAM認証規則は保持する。

```text
host colorstats colorstats 192.168.1.0/24 scram-sha-256
```

`sudo pg_conftool 16 main set listen_addresses '*'` で設定する。シェルの引用符は値に含めず、PostgreSQL設定用の引用符は `pg_conftool` に任せる。全インターフェースで待ち受けることで、起動時にLANのIPv4がまだ割り当てられていなくても起動できる。接続許可は待受アドレスではなく上記の認証規則で制御し、LAN外や他のDB・ロール向けの許可規則は追加しない。

この方式は既存のPostgreSQLと `pg_conftool` だけで対応でき、追加依存やネットワーク待機用のsystemd設定は不要。[PostgreSQL 16の公式仕様](https://www.postgresql.org/docs/16/runtime-config-connection.html)では `*` は利用可能な全インターフェースを表し、少なくとも1つのTCP/IPアドレスで待ち受けられれば起動する。

`password_encryption` は `scram-sha-256` にする。アプリ用ロールとDB `colorstats` を作成し、認証秘密はホスト上のmode 600ファイルだけに保存する。リポジトリやコマンド引数へ秘密を書かない。接続元は `configs/postgres.env.example` を基に値を設定する。

## 動作確認

```sh
sudo -u postgres psql -Atqc 'show data_directory; show listen_addresses;'
pg_isready -h 192.168.1.86
```

接続元から `psql` を使い、認証を伴う接続と `select version()` を確認する。パスワードは対話入力か権限を絞った `PGPASSFILE` から渡す。

## 復元試験

復元先ホストにPostgreSQL 16クライアント・サーバーを用意し、空の検証DBへカスタム形式ダンプを復元する。

```sh
createdb colorstats_restore_check
pg_restore --exit-on-error --no-owner --dbname=colorstats_restore_check /path/to/colorstats.dump
psql --dbname=colorstats_restore_check --command='select count(*) from information_schema.tables where table_schema = '\''public'\'';'
```

復元元と試験日時、ダンプのSHA-256、コマンド終了コード、復元後の確認結果を運用記録に残す。実データが未作成の段階では、Issue完了時に一時DB・テーブルを作り、ダンプ・復元を通しで検証する。
