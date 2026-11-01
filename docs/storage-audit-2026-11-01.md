# ストレージ調査結果・更新版（初回2026年10月31日／最終更新2026年11月1日JST）

## 最新の結論

**11月1日、ORICOを別ポート・別データケーブルで再接続し、直接読み取り3項目と、許可されたext4ジャーナル回復後の書込み3項目がすべて成功した。通信異常・PHY/CRC増加はなく、終了後のFSもclean・needs_recoveryなし・Journal start=0。10月31日のSUNEAST両ケーブル変更後full試験、TOSHIBA再接続後full試験も成功している。**

- 最新インベントリーはORICO・TOSHIBA・OS用CSSD・SUNEASTの4台。ORICO（TM40BNK57PJCFY2MF32P）は再接続済みで、native SATAのata1として確認した。
- 過去にはORICO不在・別ポート・NCQ無効でも通信異常が発生した。ORICO単独、個別ポート単独、NCQ固有の原因とは断定できない。
- SUNEASTはデータと電源、ORICOはポートとデータケーブルをそれぞれ同時に変更しており、個別の寄与は未分離。ORICOの電源変更は言及されていない。短時間・限定範囲の成功であり、原因部品・恒久的解決・全領域健全性は未確定。
- この更新版は保存済み証跡だけで作成。追加接続・測定は行わず、元の報告書も変更していない。

## 最新の性能と健康情報

全時刻はJST。SUNEAST/TOSHIBAは2026年10月31日、ORICOは11月1日の結果。数値は「読み／書き」、MB/sは10進、ランダムはIOPS。

| 対象・測定結果の時刻 | seq 1MiB QD1 MB/s | rand 4KiB QD1 IOPS | rand 4KiB QD32 IOPS |
| --- | ---: | ---: | ---: |
| SUNEAST・10/31 23:36:30〜23:37:11 | 474.69 / 411.71† | 25,768.6 / 31,063.4† | 94,671.0 / 31,126.1† |
| TOSHIBA・10/31 23:46:02〜23:47:10 | 446.83 / 97.68† | 20,660.8 / 18,280.6† | 94,228.6 / 17,215.7† |
| ORICO・11/1 読09:43／書09:50 | 479.14 / 390.74 | 18,068.9 / 20,628.3 | 86,773.9 / 75,786.1 |

† **印付きwrite値だけがNTFS(ntfs-3g)上の専用ファイルによるFS参考値であり、物理書込み性能は未確定。** ORICOのwriteは回復済みext4上の専用ファイル測定で、NTFSの†には該当しない。readは未マウントのブロックデバイスを直接readonly測定。

SUNEAST fullはTOSHIBA再接続前に実施した。TOSHIBA試験中のOS/SUNEASTはSMART・ログ観察のみで、3台同時負荷や再接続後SUNEASTのfull再試験はしていない。

ORICOのreadは11/1 09:43にFS回復前、writeは09:47の回復・読み取り専用全検査後の09:50:01〜09:50:22に実施した。別工程の結果を併記しており、read/writeや4台へ一斉負荷をかけた結果ではない。

| 確認項目 | SUNEAST full前後 | TOSHIBA full前後 |
| --- | --- | --- |
| SMART総合 | PASSED→PASSED | PASSED→PASSED |
| 温度 | 40→45℃ | 35→38℃ |
| PHY ICRC / data R_ERR | 0→0 / 0→0 | 0→0 / 0→0 |
| PHY COMRESET | 4→4 | 4→4 |
| 属性199 CRC | 0→0 | 未提供（0と解釈しない） |
| リンク | 6Gbps維持 | 6Gbps維持 |
| 測定中新BadCRC/EIO/reset | 0 | 0 |
| QD32実効分布（fio） | read/writeとも99.99% | read/writeとも99.99% |

TOSHIBAはqueue_depth32→32を記録。OS用CSSD/SUNEASTも観察前後のPHY値は不変。CSSDのCRC累積62,697は増加なし、SUNEASTのCRCは0のまま。

ORICOはread/writeともSMART前後PASSED、PHY ICRC/R_ERR=0のまま、COMRESET=3のまま、属性199 CRC=0のまま。温度はread37→41℃、write37→43℃、6Gbps・queue_depth32維持、新BadCRC/EIO/reset=0。最新write後もFSはclean・needs_recoveryなし・Journal start=0。

### 最新構成（11月1日・ORICO回復後の書込み試験時）

| 媒体 | 固定識別シリアル | 最新の/dev名・接続 |
| --- | --- | --- |
| ORICO（2.5インチSATA SSD） | TM40BNK57PJCFY2MF32P | /dev/sda・ata1 |
| TOSHIBA THNSNA240GESK | 96CB411HKK7U | /dev/sdb・ata2 |
| OS CSSD-S6O240NCG1Q | 2G3620019305 | /dev/sdc・ata3 |
| SUNEAST SE900 SSD 1024GB | 30084394891 | /dev/sdd・ata4 |

SUNEAST性能の測定時は/dev/sdb・ata4、TOSHIBA性能の測定時は/dev/sda・ata2だった。/dev名は再起動・追加接続で変化するため、測定時の構成と上表を混同せずシリアルで識別する。

## 経緯と比較（10月31日〜11月1日、過去の異常を含む）

| 段階・JST | 観測・判断 |
| --- | --- |
| 初回・19時台 | SUNEAST ata6は試験完了。ORICO ata5はfio以前の起動時からCRC/復号異常。原因部品未特定 |
| SSD側データコネクターのみ交換・21:12起動 | SUNEASTがata5で起動時BadCRC/READ EIO。ORICOも移動先ata6の21:20 readonly中に異常。単一媒体/ポートへの断定不可 |
| ORICO除去後・22:37〜22:41確認 | SUNEAST ata5の起動異常は継続。CSSD/TOSHIBAの当時の試験は成功。旧報告書の冒頭結論はこの過去段階 |
| SUNEAST詳細調査・22:53 | 直近3起動でNCQ read計21コマンド失敗、複数サイズ/LBAでSError0x280100。runtime PMはon/active |
| OS＋SUNEASTの2台・23:04確認 | TOSHIBA/ORICO不在でもata5にNCQ失敗7件、READ EIO5件、reset4回。台数削減だけでは解消せず |
| ポート変更・23:08確認 | ata4・6Gbpsで起動時/無負荷異常なし。性能健全性は未検証とした |
| ata4負荷・23:10 | 最初の1MiB read中にBadCRC/reset2回。352.97MB/sで1GiB完了したが正常性能とは認めず後続中止 |
| NCQ比較・23:20 | 同一128KiB条件でon側は14秒異常なし。off側の通常READ DMA(c8)でもCRC/復号異常。NCQ固有説は支持されず |
| データ＋電源変更後・23:31 | 128KiB QD1 readonly14秒337.97MB/s、異常なし。前回on側も無エラーだったため、この段階だけでは変更効果未確定 |
| 同構成full・23:36〜23:37 | SUNEAST全項目成功、PHY/CRC増加なし |
| TOSHIBA再接続・10/31 23:46〜23:47 | TOSHIBA full成功、OS/SUNEASTを含む試験中新規kernel異常なし |
| ORICO別ポート・別データケーブル再接続・11/1 09:37 | ata1・6Gbps、2.5インチSATA SSDとして再識別。29秒128KiB QD1 readonlyは355.44MB/s、新規異常なし |
| ORICO read3・11/1 09:43 | seq/rand read全て成功。当時はneeds_recovery・Journal start8が残り、writeを保留した |
| ORICO回復・write・11/1 09:47〜09:50 | e2fsck -p rc0でjournal回復、-f -n Pass1〜5 rc0。clean・needs_recovery消失・Journal start0確認後にwrite3項目成功。終了後も正常 |

ユーザー情報として、ケーブルと両ポートは直前まで正常使用していた。最初はSSD側コネクターのみ交換し、その後は同じデータケーブル・電源のままポートだけ変更、後にデータと電源の両方を変更した。この情報とログを両方残し、原因部品は断定しない。

NCQ off試験はエラー後の出力回収がタイムアウトし、正確なfio終了時刻は未記録。23:20:58にqueue_depth32復元、23:21:53に試験fio残存0・state runningを確認。最新full試験では設定変更なし。

## 初回の全体調査（3ホスト・9媒体）

以下は初回構成・初回測定値（おおむね19:48〜19:59 JST）。ubuntu-0/2は後続段階では再測定していない。ubuntu-0のOS用sdaは当初対象外。/dev名は当時のものであり、現在のubuntu-1構成とは区別する。

| ホスト・当時の媒体 | 容量GiB・種別 | 型番 | seq R/W MB/s | rand QD1 R/W IOPS | rand QD32 R/W IOPS |
| --- | --- | --- | ---: | ---: | ---: |
| ubuntu-0 sdb | 698.6 HDD | WDC WD7500BPVT-26HXZT3 | 75.53 / 97.44 | 113.6 / 218.7 | 272.1 / 221.6 |
| ubuntu-0 sdc | 465.8 HDD | ST3500630NS IBM | 80.09 / 75.66† | 150.6 / 10,946.4† | 267.0 / 7,398.7† |
| ubuntu-0 sdd | 465.8 HDD | ST3500630NS IBM | 高温保留 | 高温保留 | 高温保留 |
| ubuntu-1 sda | 223.6 SATA SSD | CSSD-S6O240NCG1Q | 445.72 / 309.17 | 7,852.1 / 15,802.3 | 74,010.2 / 58,449.1 |
| ubuntu-1 sdb | 223.6 SATA SSD | TOSHIBA THNSNA240GESK | 451.15 / 96.34† | 21,222.8 / 9,341.6† | 85,948.9 / 8,862.2† |
| ubuntu-1 sdc→sde | 953.9 SATA SSD | ORICO | EIO中止 | 未測定 | 未測定 |
| ubuntu-1 sdd | 953.9 SATA SSD | SUNEAST SE900 SSD 1024GB | 474.48 / 412.50† | 21,720.4 / 29,667.7† | 92,827.2 / 30,800.6† |
| ubuntu-2 sda | 238.5 SATA SSD | 980Plus SATA3-256GB | 275.39 / 378.48 | 6,870.2 / 20,443.3 | 21,269.3 / 66,114.5 |
| ubuntu-2 nvme0n1 | 953.9 NVMe SSD | BIWIN NV3500 1TB | 1,662.14 / 1,757.35 | 13,359.7 / 67,562.9 | 130,096.3 / 199,957.3 |

初回の†もNTFS write参考値。NTFS readはキャッシュによる見かけ値を除き、後から実施した未マウント・readonlyブロックreadの値を採用した。

| 初回媒体 | 健康情報の要点 |
| --- | --- |
| ubuntu-0 sdb | PASSED、1,635h、36℃、代替/保留/訂正不能/CRC=0 |
| ubuntu-0 sdc | PASSED、74,688h、52→53℃、代替/保留/訂正不能=0、CRC累積1で増加なし |
| ubuntu-0 sdd | PASSED、73,998h、58℃で負荷保留、代替/保留/訂正不能=0、CRC累積1、過去の閾値超過履歴あり |
| ubuntu-1 CSSD | PASSED、2,964h、温度表示不整合、測定後44℃、CRC累積62,697は増加なし |
| ubuntu-1 TOSHIBA | PASSED、8,351h、36→37℃、代替等の標準属性は未提供 |
| ubuntu-1 ORICO | PASSEDでも実I/O異常、0hと報告、35→36℃。属性199=0でもPHY/カーネルに通信異常 |
| ubuntu-1 SUNEAST | 初回PASSED、31h、48℃。当初ata6では試験完了、その後の構成で異常確認 |
| ubuntu-2 SATA SSD | PASSED、7,449h、40℃、代替/保留/訂正不能/CRC=0、ATAエラー履歴あり |
| ubuntu-2 NVMe | PASSED、1h、41℃、消耗0%、予備領域100%、媒体エラー0、エラーログ0、Unsafe Shutdowns=7 |

SSDのベンダ依存指標を寿命残量へ独自換算しない。初回CSSD id177 Wear_Leveling_Countはnormalized100/raw57、ATA Endurance Indicator raw5。TOSHIBAはATA Endurance Indicator raw12。ORICOはid177 normalized100/raw0。SUNEAST id233 Media_Wearout_Indicatorはnormalized100/raw0。ubuntu-2 SATA SSD id177はnormalized100/raw5037903で消耗%は不明。これらをNVMeのPercentage Usedと混同しない。


## 条件・限界

- full試験はfio3.36/direct=1/libaio/1job、seq1MiB QD1、rand4KiB QD1/QD32、各runtime30秒またはio_size1GiBの早い方。同期・I/O回復でコマンド全体は30秒を超え得る。
- 最新readは未マウントblock・offset1GiB/範囲1GiBをreadonly測定。NTFS writeはntfs-3g.probe成功後norecover一時mount。ORICO ext4 writeは許可済み回復・読み取り専用全検査・clean/Journal start0確認後だけ実施。いずれも固有名・排他1GiBfile、空き3GiB以上・全初期化成功・終了時fsyncを確認した。
- 全NTFS writeはキャッシュ/ドライバを含むFS参考値。HDDで高IOPSが出ても物理ランダムwriteとはみなさない。fioによるブロックデバイスへの直接writeなし。ORICOの許可済みFS回復は別工程のe2fsck -pによる操作。
- kernel全行を1秒程度監視し、継続taskfile行も保存。異常時は後続中止。128KiB比較はruntime14秒/timeout15秒要求だが、kernel回復・プロセス回収を含む15秒以内終了の保証ではない。
- SMART PASSED/属性199=0だけで通信正常を保証しない。起動前履歴・測定中新規増加を区別し、電源断等でリセットされるPHY値を単純比較しない。短時間・限定領域の成功は全領域/長期/持続性能の保証ではない。

## 片付け・未解決事項・環境への影響

- 最新SUNEAST/TOSHIBA/ORICOの試験ファイルは作成inode照合後に削除exists=false、自分のmountだけ解除rc0/still_mounted=false、空directory削除、fio残存0、done.cleanup_failed=false。既存OS mountは維持し、旧ファイルの意図的な探索・削除はしていない。
- ORICOは再接続済み。過去のext4 journal abort/lost async page write等に対し、11/1に許可済みe2fsck -pでジャーナル回復しrc0。さらに-f -nの読み取り専用全検査がPass1〜5すべてrc0。回復後・書込み試験後ともclean・needs_recoveryなし・Journal start0を確認し、FS回復は完了。手動修復・再起動・formatは行っていない。
- 旧残留可能ファイルはORICOのUUID138e6f52-15ae-4b26-b370-bd6f1a586e7e内 `/codex-storage-bench-cc68441c6a9948f5b71267a91ebe3b7d.fio`（1GiB）。今回の許可は新規試験ファイルの削除だけで、旧ファイルを意図的に探索・削除していない。回復後の存在有無は個別未確認であり、残留可能性は未解決。
- ubuntu-0 sddは初回58℃で負荷保留のまま。ubuntu-0/2は後続段階では再検査していない。
- 初回のツール導入時、ubuntu-0のfio導入は成功したが、既存NVIDIA関連3パッケージの未構成処理がobjtool/module.lds欠落で失敗しapt終了100。範囲外のドライバ修復は未実施。
- 未解決は原因部品、SUNEASTのデータ/電源およびORICOのポート/データケーブルの個別寄与、長期再発有無、ORICO旧ファイルの有無。ORICOのFS回復自体は完了として区別する。今後比較する場合は現構成を記録して1要因ずつ扱う。本更新では追加検査なし。

## 証跡

保存済みファイルへの絶対パス。各記録の媒体・日時・条件を参照する。

- [ORICO再接続後29秒確認](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/orico-reconnected-20261101-1793493428-report.txt)
- [ORICO直接read3報告](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/orico-full-20261101-1793493756-report.txt)
- [ORICO直接read3 raw](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/orico-full-20261101-1793493756-read.jsonl)
- [ORICO回復・write報告](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/orico-recovery-write-20261101-1793494026-report.txt)
- [ORICO回復・読み取り専用検証raw](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/orico-recovery-write-20261101-1793494026-recovery.jsonl)
- [ORICO最終write・cleanup raw](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/orico-recovery-write-20261101-1793494026-write-final.jsonl)
- [元の報告書](H:/データ収集/ストレージ調査結果_2026-10-31.md)
- [SUNEAST最新full報告](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-cables-full-1793457348-report.txt)
- [SUNEAST最新full raw](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-cables-full-1793457348-raw.jsonl)
- [TOSHIBA最新full報告](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/toshiba-reinserted-full-1793457898-report.txt)
- [TOSHIBA最新full raw](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/toshiba-reinserted-full-1793457898-raw.jsonl)
- [SUNEAST詳細](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-detail.txt)
- [OS＋SUNEAST構成](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/os-suneast-only-1793455454-report.txt)
- [ポート変更直後](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-port-change-1793455698-report.txt)
- [ata4負荷再発](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-ata4-benchmark-1793455834-report.txt)
- [NCQ比較](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-ncq-compare-1793456394-report.txt)
- [NCQ比較raw](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-ncq-compare-1793456394-raw.jsonl)
- [停止/復元確認](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-ncq-compare-1793456394-stop-verification.jsonl)
- [両ケーブル変更後短時間確認](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/suneast-cables-changed-1793457012-report.txt)
- [初回9媒体集計](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/summary.json)
- [初回原因調査](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/orico-cause.txt)
- [SSD側コネクター交換後](C:/Users/ryuma/.codex/visualizations/2026/10/31/01a19175-1040-71e0-b3d7-214207fda3ba/storage-audit/retest-20261031-1793449109-report.txt)

元資料の一般的な定義出典：[Linux libATA](https://www.kernel.org/doc/html/latest/driver-api/libata.html#ata-bus-error)、[Linux v6.8 SError](https://github.com/torvalds/linux/blob/v6.8/include/linux/ata.h)。更新のための追加web検索はなし。
