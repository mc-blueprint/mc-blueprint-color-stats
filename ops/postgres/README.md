# PostgreSQL 16（ubuntu-1）

## 構成

- Ubuntu公式aptのPostgreSQL 16を使い、data directoryを`/mnt/data/postgres`に置く。
- `listen_addresses`は`localhost`。`pg_hba.conf`はloopbackのSCRAM認証を許可し、LANから直接接続させない。
- ubuntu-1上のアプリは`127.0.0.1:5432`へ接続する。別ホストから管理・利用する場合はSSHトンネルを使う。
- OSの`postgres`ユーザーによるpeer認証をローカル管理に使う。

## 初期構築

初期生成されたクラスタを停止し、既存データを保持したままNVMe上へ複製してdata directoryを切り替える。切替確認まで元のディレクトリを残す。

```sh
sudo systemctl stop postgresql
sudo install -d -o postgres -g postgres -m 700 /mnt/data/postgres
sudo rsync -aHAX --numeric-ids /var/lib/postgresql/16/main/ /mnt/data/postgres/
sudo pg_conftool 16 main set data_directory /mnt/data/postgres
sudo pg_conftool 16 main set listen_addresses localhost
sudo systemctl start postgresql
```

新規環境へのアプリ用ロール・DB初期設定は`sudo bash ops/postgres/configure.sh`で行う。既存の認証ファイルは上書きせず、秘密を端末やログに表示しない。接続元設定例は`configs/postgres.env.example`を使う。

## 接続確認

```sh
sudo -u postgres psql -Atqc 'show data_directory; show listen_addresses;'
pg_isready -h 127.0.0.1
```

リモート端末からは、SSH接続先をubuntu-1にして次のトンネルを開く。クライアント設定は`PGHOST=127.0.0.1`、`PGPORT=15432`とする。

```sh
ssh -N -L 15432:127.0.0.1:5432 <ubuntu-1のSSH接続先>
```

## 復元試験

ubuntu-1またはWSLの隔離した検証DBへ最新ダンプを復元する。

```sh
createdb colorstats_restore_check
pg_restore --exit-on-error --no-owner --dbname=colorstats_restore_check /path/to/colorstats.dump
psql --dbname=colorstats_restore_check --command='select count(*) from information_schema.tables where table_schema = '\''public'\'';'
```

復元元、試験日時、ダンプのSHA-256、終了コード、復元後の確認結果を運用記録に残す。
