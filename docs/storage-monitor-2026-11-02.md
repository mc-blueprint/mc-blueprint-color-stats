# ストレージ監視・保持処理の修正確認（Issue #30）

## 配置と実機確認

ubuntu-0・ubuntu-1・ubuntu-2の `/usr/local/lib/colorstats-storage/monitor.py` を更新し、
各 `colorstats-storage.service` は `Result=success`・`ExecMainStatus=0`、timerはactive。
UUID欠落・SMART取得失敗は媒体ごとのerrorとイベントになり、後続媒体の確認を継続する。

ubuntu-1のORICOについて、実際のUUID/serial対応に加え、親ディスクとsysfsからの照合名が
`sda2`・`sda`・`ata1` であることを読み取りで確認した。隔離した一時tmpfsにディスク形式と
ATA形式の異常を注入し、実際のro remount・blockedファイル・kernel/remounted_readonly記録と、
対照tmpfsのrw維持を確認した。tmpfsにはUUIDがないため、その対応とSMARTサンプルだけを注入した。
実媒体の障害発生・媒体フォーマット・本番rawのreadonly化は行っていない。

パイロットは停止・再起動していない。collect/analysis/schedulerのPIDはそれぞれ
`11450` / `11451` / `11452` を維持し、全てactive。ORICO/SUNEASTのrawもrwを維持した。

ubuntu-0ではhealth.pyと `/usr/local/sbin/colorstats-backup-retention`、保持serviceを更新して
daemon-reloadした。保持timerはactive。healthの実ユーザー実行、bash構文、systemd起動先を確認した。
実バックアップの削除を避けるため保持serviceは手動起動していない。異常・未mount媒体に削除を
渡さないことはLinux上で本物の保持shellと隔離したコマンドfixtureを組み合わせて検証した。

NVMeは `smartctl -a` が未対応のself-test log取得で終了値4になることを実機で確認した。
最終版は必要な `-i -H -A` だけを取得し、ubuntu-2の両媒体はsmart_exit=0。
初期配置のNVMe誤検出1件は `events.jsonl` から `issue30-initial-probe.jsonl` へ退避した。
ST500aの初回記録も一旦退避したが、実在するSMART履歴異常と確認できたため保持ログへ戻した。
既存の異常履歴は除去していない。

## 温度由来の除外と日次バックアップの復旧

初期判定ではST500a・ST500bのSMART終了値32（bit5）を恒久的な媒体異常として扱い、
健全な保存先がWDだけになっていた。両STの `In_the_past` は属性190
`Airflow_Temperature_Cel` だけで、現在41°C・43°C、CRCはともに1で増分なし、
代替セクタ・保留セクタは0と実機で確認した。

オーケストレータの判断に従い、温度は60°C以上で停止・55°C未満で復帰する
`temperature_blocked` として保存する。SMART bit4〜5は該当属性も保存し、温度だけの
しきい値履歴では恒久除外しない。bit3の健康異常、温度以外のしきい値異常、CRC・
代替セクタ・保留セクタの増分、kernel異常は従来どおり手動解除まで履歴で除外する。
旧 `smart_increase` は前後のカウンタに増加がない温度超過だけを区別し、混在・判別不能な
履歴は除外を維持する。既存のPython標準機能とsmartctlの属性表を再利用し、依存追加はない。
SMART終了ビットの仕様は [smartctlのマニュアル](https://manpages.ubuntu.com/manpages/noble/man8/smartctl.8.html)
を確認した。

ubuntu-0の属性情報がない旧 `smart_health` 記録14行は、対象UUID・CRC・セクタ数・温度・
終了値を照合し、元の理由を `original_reason` に残して `temperature_history` に分類した。
元ログは `/var/log/colorstats-storage/issue30-before-temperature-20261101T153321Z.jsonl` と
`issue30-before-temperature-20261101T153431Z.jsonl` に保存（root専用）。
最初の更新では旧監視と競合し2行が追加されたため、監視timer・監視serviceだけを一時停止して
その2行も再分類し、監視serviceの実行とtimerの再開を確認した。他の異常履歴は除去していない。

最終版の監視を3ホスト、healthをubuntu-0へ配置し、監視serviceの成功・timerのactiveを確認。
ubuntu-1のパイロットPIDは11450・11451・11452を維持し、rawは両方rw。
新版キューは稼働中パイロットへ反映していない。

ubuntu-2で日次バックアップserviceを手動実行し、`Result=success`・`ExecMainStatus=0`、
`healthy=3 excluded=0`・`transferred=3` を確認した。UTCでは日曜2026-11-01のため、
WD・ST500a・ST500bの `daily/` と `weekly/` の両方に転送された。
各媒体・periodで以下の本体と送信元サイドカーを照合し、3媒体間・送信元の一致も確認した。

| 成果物 | SHA-256 |
| --- | --- |
| `colorstats-2026-11-01.dump` | `90bac851bd5caeca5b85a3e82b6f6df3602a64e5041e2ff746d2543c7c903c67` |
| `postgres-2026-11-01.dump` | `4be4b3f8657250a1d800ba7f9e64755869ce00bb2689ca3b8c017d4a3e912b52` |
| `ground-truth-2026-11-01.tar.gz` | `2e1157bfd802a5087b4f324a7b6f8d962eb2560267125fdf96b85b2162610df8` |
| `aggregates-2026-11-01.tar.gz` | `7aebe1d13653c7736964be311bf7d676534db125dae2c20321ffe581e8176433` |

今回の手動実行中だけruntime drop-inで `KEEP_LOCAL_BACKUP=1` を設定し、送信元の生成物も
削除せず保全した。終了後に今回のdrop-inだけを除去してdaemon-reload済み。
保持serviceの手動起動・バックアップ削除・フォーマット・再起動・netplan/fstab変更は行っていない。

## 共有契約と残りの反映

Queue.deferは所有権を確認してpendingへ返し、今回の試行数を戻す。DBスキーマ変更はない。
collect/prepはローカル監視のrawを自動確認する。derived等は新しい `--storage-path STAGE=PATH`
で該当stageごとに指定する。詳細は [queue.md](queue.md)。

稼働中の#27パイロットは既にimportした旧キュー実装のままで、新しい取得停止契約は未反映。
停止禁止に従い、サービス・稼働release・`ops/deploy/` は変更していない。
#27の担当が次の承認された配置時にこのキュー変更を取り込み、実際のNFS derivedパスを
prep/colorのstorage-pathへ指定する必要がある。監視の配置完了と、旧プロセスへの反映は区別する。

別ホスト復元は [復元試験記録](restore-test-2026-11-02.md) を参照。
commit・push・PR作成は依頼の禁止に従って未実施。

## ローカル検証と反証

前任時点ではWSL Ubuntu-24.04・Python 3.12・専用PostgreSQL 16で全208テスト成功（skipなし）、
`ruff check .` 成功、sdistとwheelのビルド成功。任意依存Matplotlib未導入の既存警告が1件。
初回は201テスト成功。最終再実行時に前回のschemaテストが残した `alembic_version` で
空DB前提が1件失敗したため、実行ごとに新規一時DBを作る検証スクリプトへ直し、208件成功した。
プロジェクトの既存schemaテスト自体は変更していない。

重点反証では、取得前・取得後・計算中・完了前・ファイル公開時の停止経路、旧トークンの拒否、
子のEROFS伝播、SMARTログ履歴と取得失敗の区別、UUID取り違え時のremount防止、
インストール手順とservice起動先の一致、#27の変更範囲との非競合を確認した。
最終検証ログは `20261101T152251Z-3d9cc69ef9074b9c95e465e64f138424.jsonl`。

温度の追加修正後は、一時環境が消失していたため同じWSL環境を再作成した。
新規一時DBで全216テスト成功（skipなし、既存のMatplotlib未導入警告1件）。
ruffの行長1件を修正し、旧イベント判定のガード追加後に関連8テスト・ruff・sdist/wheelビルド成功。
60→59→55→54→59→60°Cの状態遷移、温度とセクタ増分の混在、SMART bit3の維持、
温度以外のbit5、旧UUIDの温度履歴、保持と転送で共有するhealth判定を反証した。
共有契約の変更は監視状態の `pending`・`failed_attributes`・`temperature_blocked` と
温度イベントの区別。DB・バックアップ本体の形式変更はない。

## 監査ログ

`%USERPROFILE%/.codex/logs/commands/` 配下:

- ubuntu-1一時tmpfs試験: `20261101T151338Z-05192ad00e724c23b809455df0165bcc.jsonl`
- ORICOの対応確認: `20261101T151854Z-0ae581f0506b4eb19e34f9ab2f138e04.jsonl`
- ST500aの実データ: `20261101T151853Z-803746e878f14727a07da92be5ee7e58.jsonl`
- 最終配置: `20261101T152304Z-41e8bc614be94f4b84d90cd61bf64f75.jsonl`（ubuntu-0）、
  `20261101T152306Z-c9dc8822a1ce4594a1171c1eea6fc191.jsonl`（ubuntu-1）、
  `20261101T152306Z-778ae832dcc74bc29e5cd0f40383057d.jsonl`（ubuntu-2）。
- 温度修正後の全216テスト: `20261101T153152Z-cffbb4dc7900407887c656be3aec87c9.jsonl`。
- 最終の関連8テスト・ruff・build: `20261101T153300Z-ba088fb14a424079abc7e8462474a5d5.jsonl`。
- 温度履歴の確認: `20261101T152913Z-c0ab5bda891345279f72e848c552d5c6.jsonl`。
- 最終温度判定の配置: `20261101T153431Z-562c0cc9091e4cc0aaad290c98e88fb8.jsonl`（ubuntu-0）、
  `20261101T153454Z-2d562df5c76044639209ca46780167dd.jsonl`（ubuntu-1）、
  `20261101T153458Z-1ea79e977022448aa4b1c7c384d0555a.jsonl`（ubuntu-2）。
- 日次バックアップ実行: `20261101T153537Z-ad7f476bc1844836963574698fc21cde.jsonl`。
- 3媒体・日次/週次のSHA-256照合: `20261101T153548Z-ea690147b63d47bc969e7c3b5cb95649.jsonl`。
