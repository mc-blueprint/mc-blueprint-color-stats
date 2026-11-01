# ストレージ監視

`monitor.py` は UUID ごとにSMARTのCRC・代替セクタ・保留セクタ・温度を前回値と比較し、journal cursorからkernelログの増分を読み、BadCRC・I/O error・リンクresetを探します。カウンタの増加、温度の停止状態、raw媒体のシリアル不一致、kernel異常を検出すると記録し、該当するraw mountだけをreadonlyへremountします。初回も温度と健康状態は判定し、カウンタだけ基準値を保存します。状態は `/var/lib/colorstats-storage/state.json` と `/var/lib/colorstats-storage/kernel.cursor`、異常記録は `/var/log/colorstats-storage/events.jsonl` です。

UUIDのpartitionから `lsblk` で親ディスク、sysfsでATAポートを解決し、serialをSMARTで照合します。ORICOなら `sda2`・`sda`・`ata1` が照合名です。SMARTは `smartctl -i -H -A` のみ取得し、NVMeの未対応自己試験ログなどは要求しません。終了ビット0〜2は取得失敗、3は健康異常、4〜5は属性別のしきい値異常として扱い、6〜7のログ履歴だけでは媒体の健康異常としません。4〜5が温度属性だけの場合は恒久的な健康異常にしません。終了値と該当属性は `smart_exit`・`failed_attributes` に保存します。UUID欠落・SMART取得や解析失敗・journal取得失敗も媒体ごとの異常とし、後続媒体の監視を続けます。

温度は60°C以上で `temperature_blocked` を立て、55°C未満で解除します。バックアップの転送・保持はこの状態に従い自動復帰し、温度履歴だけでは恒久除外しません。CRC・代替セクタ・保留セクタの増分、I/Oエラー、SMART健康ビット等は媒体異常として履歴を残し、手動解除まで除外します。rawのreadonly・blocked解除は従来どおり手動です。

rawの異常時はremountより先に `/var/lib/colorstats-storage/blocked/<UUID>` を作り、mount失敗・取り違えでも取得を止めます。readonly化はmountのUUIDが一致する場合だけ行い、失敗も記録します。ワーカーとの契約と復帰手順は [queue.md](../../docs/queue.md) を参照してください。監視・healthはPython標準ライブラリと既存のLinuxツールを再利用し、依存は増やしていません。

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

`/var/lib/colorstats-storage/state.json` に全UUIDのSMART値または取得失敗の `error` が記録され、`/var/lib/colorstats-storage/kernel.cursor` にkernel journalの読取位置が保存され、serviceの `Result=success`、timerが `active` であることを確認します。serviceの成功は全媒体が健全という意味ではありません。異常は状態・イベントとblockedファイルも確認します。

## readonly動作の安全な確認

稼働中のrawでは試験しません。隔離した一時tmpfsまたは一時ループデバイスを使い、CONFIG・STATE・LOG・BLOCKEDも一時ディレクトリへ分けます。ディスクとATAの異常ログをそれぞれ注入し、対象mountがro、対照mountがrw、対象UUIDのblockedファイルとkernel/remounted_readonlyイベントが作られることを確認します。tmpfsにはUUIDがないため、UUID照合だけは試験内で注入し、その制約を記録します。実媒体のUUID・serial・親ディスク・ATA対応は読み取りだけで別途確認します。復旧後のキュー取得は一時DBと同じ隔離mountで確認します。

readonlyからの通常復帰は自動化せず、原因確認後に手動で行います。再起動後はrawのUUID mount、`colorstats-storage.timer` のactive状態、直近のservice結果を確認してください。

異常判定はPython標準ライブラリのみで実装しています。監視は `smartctl` と `journalctl` を利用します。

## 作業確認記録

- 2026-11-01: ubuntu-0・ubuntu-1に続き、ubuntu-2も増分カーソル対応版へ更新しました。`colorstats-storage.service` を手動起動し、`Result=success`・`ExecMainStatus=0`、timerの `active`、`/var/lib/colorstats-storage/kernel.cursor`（122 bytes）とSMART状態ファイルの作成を確認しました。OSディスクUUID `1b655df6-20ea-4fb5-944d-0518d96aef98` は `/dev/sda2` の980Plus SSD、serial `20ZYB12143975`、NVMeデータディスクUUID `f153f9af-eb33-48ee-8567-a088b5036076` は `/dev/nvme0n1p1`、serial `2440009301477` と一致しました。記録された温度はそれぞれ40°C・41°Cで、SMART CRC・代替セクタ値はいずれも0でした。

- 2026-11-01: ubuntu-1の再起動後（起動時刻 `2026-11-01 10:21:44 UTC`）に確認しました。`/etc/fstab` のORICO (`138e6f52-15ae-4b26-b370-bd6f1a586e7e`) とSUNEAST (`0b0662f1-5ad5-4131-a758-e78d3abb6d6c`) のUUID行は有効で、どちらも `ext4 defaults,nofail 0 2` でした。`findmnt --verify` は両UUIDを実デバイスへ解決し、mount先も存在することを確認しました。`/srv/colorstats/raw-orico` は `/dev/sda2`、`/srv/colorstats/raw-suneast` は `/dev/sdd2` から各UUIDが一致して自動マウントされ、両方 `rw` です。`colorstats-storage.timer` は `active`、直近serviceは `Result=success`・`ExecMainStatus=0` でした。
- 前回bootの `journalctl -b -1 -p err` にはORICO/SUNEASTのmount失敗はありませんでした。記録されたのはVMX/SGXがBIOSで無効というkernel通知と、`pam_lastlog.so` が見つからないlogin警告です。どのように復旧されたかは確認できていません。
- 起動を止めない `nofail` は両行に設定済みです。`x-systemd.device-timeout` は設定されていません（追加は提案のみで、今回変更していません）。
