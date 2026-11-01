# ストレージ監視

`monitor.py` は UUID ごとにSMARTのCRC・代替セクタ・温度を前回値と比較し、journal cursorからkernelログの増分を読み、BadCRC・I/O error・リンクresetを探します。SMART値の増加、60°C以上で異常、raw媒体のシリアル不一致、kernel異常を検出すると記録し、該当するraw mountだけをreadonlyへremountします。初回はSMART基準値を保存し、kernelログは現在のbootから読みます。状態は `/var/lib/colorstats-storage/state.json` と `/var/lib/colorstats-storage/kernel.cursor`、異常記録は `/var/log/colorstats-storage/events.jsonl` です。

## ホスト別ディスク設定

`disks/ubuntu-0.json`、`disks/ubuntu-1.json`、`disks/ubuntu-2.json` は各ホストで照合した全ディスクのUUID・serialを記録します。設定を更新するときは `lsblk -o NAME,FSTYPE,UUID,SERIAL,MOUNTPOINTS` と `smartctl -i /dev/<device>` の両方で対応を確認し、`/dev`名からserialやUUIDを推測しないでください。設定中のUUIDは `/dev/disk/by-uuid/` からSMARTを読むために使います。

- ubuntu-0: OSディスク、WD 750GB、ext4のST3500×2。STはIssue #23で消去承認後にフォーマットし、新UUIDへ更新しました。`previous_uuids` はバックアップ判定が旧UUIDの異常履歴を引き継ぐための対応です。バックアップHDDはすべて `raw: false` で、この監視によるreadonly化は行いません。`ops/backup/` の転送処理が監視状態と異常記録を読み、該当媒体への転送を停止します。媒体のmount・書込み・フォーマットはこの監視設定では行いません。
- ubuntu-1: ORICO、TOSHIBA、CSSD、SUNEAST。ORICOとSUNEASTだけ `raw: true` でmount先を指定します。
- ubuntu-2: OSディスクとNVMeデータディスク。どちらも `raw: false` です。

## 配置と有効化

各Ubuntuで `smartctl` がなければ `smartmontools` を導入します。ubuntu-0でaptが既存パッケージの構成不良により失敗した場合は、状態を変更せず報告してください。`monitor.py` を `/usr/local/lib/colorstats-storage/monitor.py`、service/timerを `/etc/systemd/system/` にroot所有で配置し、対象ホストのJSONを `/etc/colorstats-storage/disks.json` に置きます。systemd serviceはrootで実行します。

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now colorstats-storage.timer
sudo systemctl start colorstats-storage.service
systemctl list-timers colorstats-storage.timer --no-pager
systemctl show colorstats-storage.service -p Result -p ExecMainStatus
```

`/var/lib/colorstats-storage/state.json` に全UUIDのSMART値が記録され、`/var/lib/colorstats-storage/kernel.cursor` にkernel journalの読取位置が保存され、serviceの `Result=success`、timerが `active` であることを確認します。初回は起動時点からkernelログを読み、SMARTは比較元がないため異常判定せず基準値を記録します。

## readonly動作の安全な確認

実媒体に異常を発生させず確認するには、一時的な `journalctl` wrapperから `I/O error, dev <対象partition>` を監視へ渡します。`<対象partition>` はUUID symlinkの実体名（例: `sda2`）と完全一致させます。テスト用wrapperをPATHの先頭に置いてrootで `monitor.py` を一度実行し、該当raw mountの `findmnt -no SOURCE,OPTIONS --target <mount>` が `ro`、他のraw mountが `rw` であることを確認します。確認後は `mount -o remount,rw <mount>` で元に戻し、一時wrapperを削除してください。イベントログに対象UUIDの `kernel` と `remounted_readonly` が残ることも確認します。

readonlyからの通常復帰は自動化せず、原因確認後に手動で行います。再起動後はrawのUUID mount、`colorstats-storage.timer` のactive状態、直近のservice結果を確認してください。

異常判定はPython標準ライブラリのみで実装しています。監視は `smartctl` と `journalctl` を利用します。

## 作業確認記録

- 2026-11-01: ubuntu-0・ubuntu-1に続き、ubuntu-2も増分カーソル対応版へ更新しました。`colorstats-storage.service` を手動起動し、`Result=success`・`ExecMainStatus=0`、timerの `active`、`/var/lib/colorstats-storage/kernel.cursor`（122 bytes）とSMART状態ファイルの作成を確認しました。OSディスクUUID `1b655df6-20ea-4fb5-944d-0518d96aef98` は `/dev/sda2` の980Plus SSD、serial `20ZYB12143975`、NVMeデータディスクUUID `f153f9af-eb33-48ee-8567-a088b5036076` は `/dev/nvme0n1p1`、serial `2440009301477` と一致しました。記録された温度はそれぞれ40°C・41°Cで、SMART CRC・代替セクタ値はいずれも0でした。

- 2026-11-01: ubuntu-1の再起動後（起動時刻 `2026-11-01 10:21:44 UTC`）に確認しました。`/etc/fstab` のORICO (`138e6f52-15ae-4b26-b370-bd6f1a586e7e`) とSUNEAST (`0b0662f1-5ad5-4131-a758-e78d3abb6d6c`) のUUID行は有効で、どちらも `ext4 defaults,nofail 0 2` でした。`findmnt --verify` は両UUIDを実デバイスへ解決し、mount先も存在することを確認しました。`/srv/colorstats/raw-orico` は `/dev/sda2`、`/srv/colorstats/raw-suneast` は `/dev/sdd2` から各UUIDが一致して自動マウントされ、両方 `rw` です。`colorstats-storage.timer` は `active`、直近serviceは `Result=success`・`ExecMainStatus=0` でした。
- 前回bootの `journalctl -b -1 -p err` にはORICO/SUNEASTのmount失敗はありませんでした。記録されたのはVMX/SGXがBIOSで無効というkernel通知と、`pam_lastlog.so` が見つからないlogin警告です。どのように復旧されたかは確認できていません。
- 起動を止めない `nofail` は両行に設定済みです。`x-systemd.device-timeout` は設定されていません（追加は提案のみで、今回変更していません）。
