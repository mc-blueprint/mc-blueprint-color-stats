# ubuntu-0への日次バックアップ

## 保存領域

主保存先はWD750GB ext4（UUID `3f9a319f-394c-4cca-805d-fc88d782d644`）を `/srv/colorstats/backup-wd750` にUUID指定でマウントする。2026-11-01のユーザー承認に従ってST3500×2をext4化し、以下を追加した。全媒体を `defaults,nofail` で永続マウントする。

| serial | マウント先 | UUID |
| --- | --- | --- |
| 9QG4GD0M | `/srv/colorstats/backup-st500a` | `71cefe86-d90a-4caa-be51-54cc5f8d6ebc` |
| 9QG4B26Z | `/srv/colorstats/backup-st500b` | `e53f78c3-2918-4a64-bc50-807a38249da1` |

`configs/storage.yaml` の `backup.host/path` は主保存先のまま維持し、`replicas` に同じホストの追加媒体を記録する。論理パスresolverは主保存先を返し、複製転送はバックアップ処理が担当する。

## 世代

- `colorstats-backup.service` が毎日、全接続可能な非template DBを `pg_dump -Fc` でDBごとに取得し、`pg_restore --list` とSHA-256を確認してから保存先リストの各宛先へ転送する。
- `/etc/colorstats/backup.conf` の `DATA_ROOT=/mnt/data/backup-inputs` 以下の `ground-truth/`（正解データ）と `aggregates/`（集計結果）を、日付付きtar.gzとSHA-256にして同じ宛先へ送る。生成元からここへ確定済みのデータを投入し、バックアップ中は変更しない。ディレクトリ欠落・読取失敗時はserviceを失敗させ、欠落を成功扱いしない。初回確認時は両ディレクトリが空で、実データは未投入。
- DB・アーカイブごとに、各媒体で日次7世代、週次4世代を `daily/` と `weekly/` に分けて保持する。日曜は週次ディレクトリにもコピーし、ubuntu-0の `colorstats-backup-retention.timer` が日次でPython標準ライブラリの保持処理を実行する。各媒体・各periodの処理直前に転送と同じhealth判定とmountのUUID照合を行う。異常・監視不明・未マウントの媒体には保持処理を起動せず、他媒体は続ける。
- 保存先リストは `/etc/colorstats/backup-destinations` に1行1宛先（`user@host:path`）で置く。`destinations.example` の3行を配置する。WDは既存の `colorstats-backup`、STは `colorstats-backup-st500a`・`colorstats-backup-st500b` を使い、同じ公開鍵に媒体別の強制コマンドを設定する。
- バックアップ転送用SSH鍵はubuntu-2上のPostgreSQL実行ユーザーだけが読める権限で保管する。ubuntu-0は `rrsync -wo` で受信領域を限定する。3媒体共通の `receive-st500.sh` はマウント・UUID・監視状態を検証し、欠落・取り違え・異常時は書き込まず失敗する。転送開始後に1宛先で失敗するとserviceも失敗し、後続宛先は未転送となるため、復旧後に再実行する。
- rsync/sshは既存コマンドを利用する。追加パッケージが必要な場合は導入前に報告する。

systemd timerは毎日実行する。送信側は転送直前に各受信アカウントへSSHの `health` コマンドを送り、`health.py` が既存監視の `/var/lib/colorstats-storage/state.json` と `/var/log/colorstats-storage/events.jsonl` を確認する。温度は60°C以上で転送・保持から除外し、監視で55°C未満を確認したら自動復帰する（`temperature_blocked` に状態を保存）。温度だけの過去履歴では恒久除外しない。CRC・代替セクタ・保留セクタの増分、kernel異常、温度以外のSMART健康異常は履歴で除外する。監視状態の欠落・不正・15分以上の更新停止も除外し、異常記録ファイルがまだない初回は最新SMART値で判定する。受信時にも同じ判定を行う。既存SSHとPython標準ライブラリを利用し、依存は追加しない。

除外理由は送信serviceのjournalに `excluded destination=... reason=...` と記録し、転送完了時は `backup result: transferred=...` を残す。同じUUIDを重複して数えず、健全な保存先が2台未満なら転送せずserviceを失敗させる。外部通知の仕組みは未実装で、systemdの失敗状態とjournalで代える。`systemctl --failed` と `journalctl -u colorstats-backup.service` で確認する。STは約7.4万時間稼働しており、単独保存先にはしない。

媒体異常イベントによる除外は原因確認・手動解除まで維持する。フォーマット前の異常も、監視JSONの `previous_uuids` で同じserialの旧UUIDに対応付ける。旧 `smart_increase` のうち、前後のCRC・セクタ数に増加がなく温度だけが60°C以上の記録は温度履歴と判別する。属性情報のない旧 `smart_health` は自動解除せず、管理者がSMARTと照合し温度だけと確認できた行を、元の理由を残して `temperature_history` に分類する。媒体異常の復帰時はtimerを停止し、配線・SMART等を点検し、イベントログを退避して対象UUID（旧UUIDを含む）の解決済み行だけを管理者が除去する。他媒体の記録は保持する。監視serviceを再実行し、2台以上の健全性とハッシュ一致を確認してtimerを再開する。

## 追加媒体の配置

`setup-st500.sh` は上表のフォーマット済みUUID・serialを検証し、マウントと専用受信アカウントを設定する。再実行してもフォーマットしない。事前にubuntu-0の `/tmp/` に `health.py` と `receive-st500.sh` を転送し、`setup-health-ubuntu0.sh` を実行する。判定を `/usr/local/lib/colorstats-backup/health.py`、受信ガードを `/usr/local/sbin/colorstats-receive-st500` にroot所有で配置し、既存WDアカウントの強制コマンドにも適用する。初期配置では `install-ubuntu0.sh` の前に同じファイルを配置する。STの設定は既存WD受信用の公開鍵を内部で複製し、秘密鍵を移動・表示しない。`colorstats-backup` グループでSTの世代保持を許可する。

ubuntu-0へ更新した監視JSON、`backup_retention.py`、保持serviceを既存の配置先へ設置する。`retention.sh` はroot所有・755で `/usr/local/sbin/colorstats-backup-retention` に配置し、health.pyも先に配置する。初期配置・保持更新スクリプトへは `/tmp/retention.sh` と `/tmp/colorstats-backup-retention.service` を渡す。`systemctl daemon-reload` 後に監視・保持serviceを起動する。削除禁止の確認では保持serviceは起動せず、隔離fixtureで書込み先を検証する。ubuntu-2は `update-ubuntu2.sh` で `colorstats-backup.sh` と宛先リストを更新し、`DATA_ROOT` とその2ディレクトリをpostgres所有・700で準備する。初期配置の `install-ubuntu2.sh` と更新スクリプトは `/tmp/destinations.example` も入力に使う。

手動検証はubuntu-2で `sudo systemctl start colorstats-backup.service` を実行し、ubuntu-0の転送された健全な各媒体の `daily/`（日曜は `weekly/` も）のダンプとアーカイブのSHA-256が一致すること、監視・保持serviceの `Result=success` を確認する。サイドカーは送信元の絶対パスを記録するため、受信先ではファイル本体のハッシュ値とサイドカー先頭の値を比較する。

## 復元試験

少なくとも月次でubuntu-1またはWSLの隔離した検証DBに最新ダンプを復元する。復元結果と日時、対象世代、ハッシュ、終了コードを記録する。Issue #4の完了時は一時データベースを用いた初回復元を実施し、その結果をPRに記載する。
