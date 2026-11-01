# ubuntu-0への日次バックアップ

## 保存領域

主保存先はWD750GB ext4（UUID `3f9a319f-394c-4cca-805d-fc88d782d644`）を `/srv/colorstats/backup-wd750` にUUID指定でマウントする。ST3500 2台は既存NTFSデータの確認と利用判断が済むまで変更しない。保存先はリストとして設定し、追加媒体が利用可能になった後に追記できる。追加媒体が未設定の間は冗長性要件未達として扱う。

## 世代

- `colorstats-backup.service` が毎日、全接続可能な非template DBを `pg_dump -Fc` でDBごとに取得し、`pg_restore --list` とSHA-256を確認してから保存先リストの各宛先へ転送する。
- DBごとに日次7世代、週次4世代を `daily/` と `weekly/` に分けて保持する。日曜は週次ディレクトリにもコピーし、ubuntu-0の `colorstats-backup-retention.timer` が日次でPython標準ライブラリの保持処理を実行する。
- 保存先リストは `/etc/colorstats/backup-destinations` に1行1宛先（`user@host:path`）で置く。WDの初期宛先は `colorstats-backup@192.168.1.46:.`。SSH鍵の強制コマンドで転送ルートを `/srv/colorstats/backup-wd750` に固定する。追加先はユーザー判断後に適切な転送ルートを設定して行を追加する。
- バックアップ転送用SSH鍵はubuntu-2上のPostgreSQL実行ユーザーだけが読める権限で保管する。ubuntu-0の専用アカウントは `rrsync -wo` 強制コマンドでWDバックアップ領域への受信だけを許可する。
- rsync/sshは既存コマンドを利用する。追加パッケージが必要な場合は導入前に報告する。

systemd timerは毎日実行し、失敗はsystemd journalで確認する。媒体のSMART監視はIssue #3の担当範囲。

## 復元試験

少なくとも月次でubuntu-1またはWSLの隔離した検証DBに最新ダンプを復元する。復元結果と日時、対象世代、ハッシュ、終了コードを記録する。Issue #4の完了時は一時データベースを用いた初回復元を実施し、その結果をPRに記載する。
