# ubuntu-0 ストレージ調査（2026-11-16）

## 現在の構成

ubuntu-0の読み取り確認とSMART短時間自己診断による。増設HDD・SSDはまだマウントも監視登録もされておらず、バックアップの実際の宛先は既存の3台のまま。

| serial | 機種・用途 | 健康状態・所見 |
|---|---|---|
| 2137E5D1DC79 | Crucial MX500 500GB SSD（OS） | PASSED、538h、寿命消費0% |
| WD-WX81A82T3509 | WD Scorpio Blue 750GB（現行主バックアップ） | PASSED、2,009h、異常なし。バックアップ使用量7.9GB |
| 9QG4GD0M | ST3500630NS（現行バックアップ） | PASSED、約75,000h、Airflow温度の過去閾値超過、UDMA CRC累積1。直近の短時間自己診断はhost resetで中断。使用量7.9GB |
| 9QG4B26Z | ST3500630NS（現行バックアップ） | PASSED、約74,300h、Airflow温度の過去閾値超過、UDMA CRC累積1。使用量7.9GB |

## 増設ディスク

6台の短時間自己診断はすべてエラーなし。起動後のkernelログにI/O・SATA通信エラーなし。ファイルシステムは未作成または旧NTFSのままで、未マウント・監視対象外。

| serial | 機種 | 所見 |
|---|---|---|
| CT22060000480 | PS4-240GB、SATA SSD 240GB | 2,270h、PASSED、代替0。属性181の生値は大きいが属性175（チップ単位）は0 |
| 30084020558 | SUNEAST SE900 512GB、SATA SSD | 7,192h、PASSED、予備ブロック残あり、過去最高75℃ |
| WD-WCAV9P368289 | WD5000AVDS（AV-GP）、HDD 500GB | 17,085h、PASSED、電源投入33,785回 |
| 5VM9VQAP | ST3500418AS、HDD 500GB | 8,929h、PASSED。Command_Timeout累計23（7.5秒超3件） |
| JP2940HD0NRRHC | Hitachi HDS721010CLA332、HDD 1TB | 5,862h、PASSED。Raw_Read_Error_Rate正規化値93（閾値16） |
| 13NUP23PS | TOSHIBA DT01ACA100、HDD 1TB | 41,758h、PASSED |

予定していた3TB HDDは未検出。SATAはIntel、JMicron JMB58x、ASMedia×2で、増設HDD4台はJMicron側。

## 選定順と割り当て

ユーザー判断により、HDDは保管用としてすべて利用可能。バックアップ媒体は「書き込みが多いと問題が発生する可能性が高いもの」から選び、書き込み量の多い用途に比較的健全なHDDを残す。

| 順位 | ディスク | 割り当て |
|---:|---|---|
| 1 | ST3500630NS（9QG4GD0M） | バックアップ |
| 2 | ST3500630NS（9QG4B26Z） | バックアップ |
| 3 | ST3500418AS（5VM9VQAP） | バックアップ |
| 4 | TOSHIBA DT01ACA100（41,758h） | 保管用 |
| 5 | Hitachi HDS721010CLA332（読み取りエラー値の低下） | 保管用 |
| 6 | WD5000AVDS（AV-GP、連続書き込み向け機種） | 保管用 |
| 7 | WD7500BPVT（2,009h、異常なし） | 保管用。現行主バックアップから外す |

これは書き込み負荷時の問題発生リスクに基づく選定順であり、SMARTのPASSEDだけで故障しないことを保証するものではない。移行後もバックアップは現行と同じ3台構成とする。

## 未実施事項

ST3500418ASの初期化・マウント・監視登録・転送先切替、およびWD750のバックアップ解除は本Issueの対象外で、別Issueで扱う。移行完了までは現行構成と設定を維持する。
