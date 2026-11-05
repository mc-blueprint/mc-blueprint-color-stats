# Issue #91 検証・比較記録

実行日：2026-11-05 UTC。基準commit：`0bfee8194c76d5465d3424b0ade7690daeee2ff9`。
実行先はubuntu-1だけ。本番DBへ接続せず、新規の一時PostgreSQL 16と
`/mnt/data/derived/issue91-20261105T143000Z/`だけを使用した。
pilotサービスはinactiveのまま維持し、各比較workerと一時PostgreSQLは終了済み。

## 完成条件

| 条件 | 結果 |
| --- | --- |
| provider別claim・二重起動の通信禁止 | 達成。SQLで限定し、providerリースと既存running jobを確認する。独立process・失効旧ownerを検証。 |
| 実hostの合算レート・同時数・帯域 | 達成。共通DBのhost/rate_group行で送信・read前に予約。Wikimediaは同時2・20Mbps/10秒窓。 |
| 集中枠・通信枠・原本URL予約の競合と失敗 | 達成。既存CollectionReservation・SKIP LOCKED・試行所有権・台帳復元を継続利用。 |
| 強制終了・期限切れ・DB障害時の制限維持と二重確定禁止 | 達成。送信前・応答後DB障害、process kill、lease喪失、未完了byte保持と旧試行の確定拒否を検証。 |
| ubuntu-1の2ソース並行と直列比較 | 部分達成。wall-time/DB/byteを記録し並行jobは両方成功したが、直列Openverseが504で同一応答の比較ではない。 |
| 保存契約未確定の別host無効化 | 達成。新provider workerはubuntu-1以外をclaim前に拒否し、jobの保存先hostも照合。 |

未達の比較条件があるため公開文面は`Refs #91`とする。

## 事前予算と消費

Commonsの全試行合計をAPI20・画像20以内とし、最終比較は既消費API6・画像3を差し引き、
各モードAPI7・非API7を上限として実行した。最終比較の実消費は各API2・画像1、
全試行累計API10・画像5。Openverseは登録値を扱わずanonymousのまま、
全試行合計5 API要求（5/hour・100/dayの範囲）。元ページ通信は別に計数する。
予算は各保存先の`budget.json`へ通信前に保存した。UAと取得許可条件は変更していない。

予備試行`issue91-20261105T141000Z`のOpenverse 1要求が504で中断し、
`issue91-20261105T142000Z`の2要求も504だった。この過程で、JSONBのキー順によって
親ドメインのpage設定がAPI/mediaより先に選ばれる既存不具合を発見した。
最長suffixを優先して修正し、DB往復の回帰テストを追加した。
予備試行の誤分類カウンターはAPI消費の根拠にせず、実際のendpointへの要求数で算入した。
予備試行を最終比較へ混ぜず、ログと取得済み画像は保存している。

## 最終比較

入力は両モードともCommons/Openverseの`Himeji Castle`、各検索limit=1。
各モードのDBとrawを分離し、初期状態を空にして直列→並行の順で実行した。

| 指標 | 直列 | provider別2worker |
| --- | ---: | ---: |
| wall-time | 17.027秒 | 15.952秒 |
| HTTP本文受信byte合計 | 338,663 | 883,584 |
| prepare内SQL実行時間合計 | 0.182283秒 | 0.276646秒 |
| prepare内SQL文数 | 469 | 1,018 |
| DB commit増分 | 78 | 174 |
| DB rollback増分 | 6 | 9 |
| DB block read/hit増分 | 25 / 5,226 | 25 / 8,447 |
| Commons API / 画像要求 | 2 / 1 | 2 / 1 |
| Openverse API / 元ページ要求 | 1 / 0 | 1 / 1 |
| collect job結果 | Commons成功・Openverse失敗 | 両provider成功 |

SQL時間は各prepare processのSQLAlchemy実行イベントで測り、commitや通信時間を含まない。
DB増分は`pg_stat_database`の取得時点の値で、統計反映には遅延がある。
受信byteはAPI・画像・元ページ・失敗応答を含む本文量であり、保存画像量とは異なる。
並行側Openverseは元ページとの作者・ライセンス完全照合に通らず、画像取得を行わず正常終了した。

時間差は1.075秒（6.3%）だが、直列側のOpenverseはHTTP504、並行側は検索・元ページ取得に
成功しており、**同一応答・同一仕事量の比較ではない**。並行収集の高速化率とは解釈しない。
詳細は保存先の`serial/report.json`・`parallel/report.json`とprovider別イベントにある。

継続指示に対する追加比較は未実行。2026-11-05 14:35 UTC時点で、本タスクだけで
直近1時間に匿名API5要求を消費済みであり、2要求を追加できない。
全5要求が時間窓外になる15:18 UTC以降に、他の収集の消費も確認して再判定する。
枠の迂回・認証切替・別IP利用・同条件の連続再試行は行わない。

## 運用と残作業

[#114向け運用手順](../../ops/collect/provider-workers.md)にmigration0008、最小権限、
provider別起動、raw媒体監視、停止・所有権・未完了通信の復旧判断を記載した。
未完了通信は失効後もhostを止め、不明なRetry-Afterを自動解除しない。
API/byte台帳を消去せず、旧接続の終了と待機期限を確認してから運用担当が対象tokenを復旧する。
残作業は匿名枠回復後の同一応答条件での再比較と、その結果に基づく完成判定。

## 最終差分の検証

- WSLは`C:\Windows\System32\wsl.exe -d Ubuntu-24.04`を明示し、ext4の一時コピーと隔離PostgreSQL16で実行。
- 全pytest：1043 passed、1 skipped。skipは公式重み・CUDA・一時テストDBの明示指定が必要な既存GPUテスト。
- ruff check、Python3.12のsdist/wheel build、git diff --checkが成功。
- 独立process・provider二重起動・process強制終了・lease失効・送信前/応答後DB障害・fake clock/stream共有窓を検証。
- 応答後DB障害の回帰では、host予約を保持しつつプロセス内semaphoreを解放することを確認。

最終コマンド記録：`%USERPROFILE%\.codex\logs\commands\20261105T145206Z-6b7caf6244264458890d87c4261d580e.jsonl`。
