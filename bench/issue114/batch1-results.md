# Issue #114 第2段階・バッチ1

2026-11-07の追加決定による自動人物判定・採用分解析・目視用HTMLの現在値は
[自動判定の実行記録](privacy-results.md)を参照する。以下の全件目視待ちは過去の停止記録である。

2026-11-06のユーザー決定：source_shareは設定総枠の固定上限を維持し、Commonsを先に収集する。
Openverse登録値は未配置のため起動しない。全30,000枚の実現やソース多様性の達成とは扱わない。
第1段階commitは`225306c`。本書は同一ownerのバッチ1実行記録で、push・PRは行わない。

## バックアップとmigration

- ubuntu-2完全pg_dump（custom形式）：
  `/mnt/data/work/issue-114/batch1-20261106/backup-before-0008/colorstats.dump`。
- 585,244,032 byte、SHA-256：
  `7eb2215c0ec334e11402230947c0115275efce2ed0dc834a825073f4daf6eb6b`。
- 新規ディレクトリへ作成し、SHA再検証・pg_restore目録・全SQLストリーム読取りが成功。
  復元・旧データ上書き・削除は行っていない。
- 既存Alembicのoffline生成SQLにより0007→0008を適用。前後revisionはバックアップと同じ領域へ保存。
  collection_limitについてcolorstats_workerへSELECT/INSERT/UPDATEだけを追加した。
- 本番準備前は既存7,626 asset、collect pending/running=0。
  古いsegment pending 2件は今回の対象外で、変更せず保持する。

## 事前予算と実装

| バッチ共通上限 | 値 |
|---|---:|
| 新規画像の取得試行 | 3,000枚 |
| API送信予約 | 10,000要求 |
| HTTP本文のread予約 | 15,000,000,000 byte |
| HTTP 429 / 5xxの連続停止 | 3応答 |

`collection_limit`の`batch:issue114-batch1`で、層・measurement・再起動をまたいで予算を共有する。
APIは送信直前、byteはread直前、画像はbias採用予約時に消費し、失敗・EOF・中断分も払い戻さない。
byte予約は実受信より保守的で、HTTPヘッダー・TLS・TCPの通信量を示す値ではない。
challengeは初回で停止し、429/503のRetry-Afterも共有台帳へ先に保存する。
予算停止後の別workerも新規送信を拒否する。元の10秒byte窓・provider leaseは維持する。

収集はubuntu-1のみ、新規のバッチunitがCommons専用Queue workerを子processとして起動する。
旧pilotは起動しない。両raw媒体を指定し、#109の縮小既定、同時2・1秒間隔・25 MB/10秒、
Commons API同時1と現行source policyを守る。
#105の優先度1→2→3ごとに別measurementで計画し、バッチ共通予算は同じIDを使う。
本収集のmeasurementだけ後続検索ページも有効にし、各優先度seed 0〜19の有限計画を消化する。
予算到達・challenge・連続HTTP失敗では停止し、未実施jobは削除せず保全する。
有限計画の消化は公開サイト全体の画像在庫枯渇を意味しない。

新規asset ID一覧を固定し、新しいprep出力先へだけ投入する。
prepの`preserve_other_assets`指定で、他assetのsubject・候補を書き換えない。
`m3_analysis freeze --asset-ids <JSON>`で新規cohortを固定でき、未指定時は#66の7,607件検査を維持する。
新規cohortはubuntu-1/2へ非重複manifest・別rootで2:3を目安に分割する。
prep入力hash・モデル・実装hashを照合し、segment→shade→colorは#66の常駐GPU runnerを再利用する。
旧asset・旧runの行hashを実行前後で照合し、旧snapshot・旧reportは変更しない。

## 状態

WSL Ubuntu-24.04 / Python 3.12 / 隔離PostgreSQL16の全pytestは
**1,059 passed / 1 skipped（実GPU）、217.96秒**。ruffとsdist/wheel buildも成功した。
ログは`20261106T011454Z-8c2acfc418114ed08dc3d25c644dfe01.jsonl`、
検証artifactは`/tmp/colorstats-issue114-CWcWVN/`。検証DBとrunnerの終了を確認済み。
重点回帰121件も成功。新規cohort、本文read前の上限、独立接続のbyte競合、再起動維持、
HTTP連続失敗/challenge、旧asset保護、計測付きページ継続を検証した。

予算制御・cohort対応の実装・検証まで完了。収集・解析・新統計比較は順次実施し、結果を追記する。

## 初回起動の停止と再開準備

初回unitは`colorstats-issue114-batch1-collect`（01:20:46〜01:23:10 UTC）。
HTTPは200だったが、画像取得前の`retention_stop`照合でworkerのSELECT不足が判明し、
停止ファイルでworker/prepareを終了した。新規assetは0、消費済み予約API68・byte11,993,088を保持した。
既存worker_grants.sqlの全表権限再適用は自動承認審査が拒否したため、
`GRANT SELECT ON retention_stop TO colorstats_worker`だけを適用・確認した。

最終試行の要求2・応答2、最終status200、連続失敗0、旧service/子process終了と稼働collectなしを確認。
期限切れのCommons通信token `53b22668-d5fd-40af-b355-f17ad283f7e0`だけを#91手順で復旧した。
slots以外の台帳hashは前後とも`5cd616d56e938a69c1155f3d7006beb4`で、API/byte/停止期限は保持した。
画像・API・byteの予算は増やしていない。

運転スクリプトに`--resume`を追加し、旧の終了結果・stopファイルを別attemptへ移して保全する。
同じ予算・policy・基準hashを再利用し、未実施jobだけを進める。回帰2件・ruff・build成功。
再開時も収集handlerの固定版`49f4282`と既存jobを維持し、失敗jobをpendingへ戻さない。

保持の直接依存表についても権限を読み取り確認し、不足する`retention`・`retention_file`の
SELECT/INSERTだけを追加した。全表権限の付与・DDL権限・superuser化は行っていない。

## 解析・統計の運転準備

`analysis.sh`は収集終了・prep完了を待って、両hostの既存モデル49ファイルのSHA一致、
GPU未使用、入力非重複を確認し、各3枚smoke→report整合照合→全量を実行する。
Hugging Face/Transformersはオフライン指定とし、既存ローカル重み以外を取得しない。
`statistics.py`は#105訂正v2のselectionを保持して新規cohortだけを追加し、
snapshot→固定計算→rule_stat登録→全行照合→reportと新旧比較を行う。
全体DB内訳とsnapshotコホート（既存の対象外19枚を除く）を区別し、Commonsへの偏りを記載する。
旧asset・runの行hashが異なれば統計更新を拒否する。

これらと再開回帰を含む最終WSL全pytestは**1,062 passed / 1 skipped、212.28秒**。
ruff・sdist/wheel build・analysis.shのbash構文確認が成功。
ログ`20261106T013350Z-e4e5e9b3745345b9a0e1920af0ee08dc.jsonl`、
artifact `/tmp/colorstats-issue114-TQ0sA1/`。検証DBの停止確認済み。

## バッチ1の収集確定結果

2026-11-06 16:31 UTCまでに `batch_api_requests_limit` で自動終了し、worker exit=0。
新規asset 2,600枚、DB全体10,226枚。追加分・DB全体ともCommonsのみで、
Openverse匿名・登録は0枚。実際のソース構成はCommons 100%で、多様性の改善は未達。
source_shareは総枠30,000枚に対する固定上限24,000枚であり、実構成比による停止ではない。
優先度1のseed 0〜19の実行中にAPI上限へ到達し、優先度2・3には進んでいない。

| 指標 | 実績 |
|---|---:|
| 候補の遭遇回数 | 8,379 |
| 照合済み候補の遭遇回数 | 7,415 |
| 取得 / 登録 / D15適格新規SHA | 各2,600 |
| API要求 / HTTP要求・応答 | 10,000 / 各12,600 |
| HTTP本文の実読取量 | 1,086,697,405 byte |
| うち画像本文 | 1,028,068,465 byte |
| 返却しない本文read予約量 | 7,459,897,344 byte |
| timeout / duplicate SHA | 各0 |

本文予約量と実転送量を区別する。read前の固定chunk予約・EOF分も返却しないため差がある。
本文実読取量にはHTTPヘッダー・TLS・TCPを含めない。APIは検索・メタデータ要求であり、
画像GET 2,600要求を含むHTTP全体の要求数は12,600。画像・API・byteの追加予算は与えていない。

| 層 | 候補 | 照合 | 取得 | D15適格新規SHA |
|---|---:|---:|---:|---:|
| chinese-house | 1,039 | 859 | 370 | 370 |
| desert-summer-day | 1,070 | 953 | 326 | 326 |
| forest-autumn-day | 918 | 835 | 215 | 215 |
| islamic-temple | 720 | 637 | 170 | 170 |
| japanese-castle | 890 | 793 | 369 | 369 |
| japanese-temple | 1,438 | 1,241 | 568 | 568 |
| mountains-summer-day | 763 | 738 | 193 | 193 |
| plains-summer-day | 767 | 714 | 169 | 169 |
| snowy-winter-day | 774 | 645 | 220 | 220 |

候補・照合は全試行の遭遇回数で、distinct画像数ではない。取得→適格新規SHAは100%、
候補→適格新規SHAは約31.03%。個別URL・画像メタデータを除いた集計は
`batch1-collection.json` に固定した。

初回停止の試行 `d8d843f3-9006-4b22-b632-f0ca0a7c7fc5` は履歴上runningのまま残る。
開始01:22:58 UTC、API2・本文4,057 byte・取得0で、対応jobは再試行2でsucceeded。
これは稼働中workerではなく初回停止の履歴であり、台帳を書き換えず保全した。
収集jobはsucceeded 1,636 / failed 2、pending・runningは0。
この未終結履歴の通信も上記実績へ含めており、再開時の返却・過少計上はない。

途中照合（13:05 UTC）では旧asset 7,626行・旧processing_run 42,314行のhash変更0。
収集完了後、新規2,600枚だけを対象にprepサービスの実行開始を確認した。

## 解析の停止と未完了条件（2026-11-07）

再開照会でprep 2,600 succeeded、segment 2,600 succeeded、shade 2,600 failed、color 0を確認した。
全shade失敗理由は `PermissionError: 人物・要配慮情報の内部確認が必要です`。
`retention.check_privacy`はRetention登録のある新規収集画像に対して内部確認を要求するが、
新規2,600枚の `quality.privacy_review` 記録は0件だった。
旧コホートのRetention未登録画像にはこの確認を要求しない実装であり、旧版での成功を新規分へ適用できない。
`retention.review_privacy` の契約は原画像・縮小画像双方の内部目視、building/terrain主体の確認、
必要時の人物除外maskとSHA固定である。確認を偽装した一括承認・ゲート解除は行っていない。

| host | 担当 | segment成功 | shade失敗 | shade試行 | color完了 | region |
|---|---:|---:|---:|---:|---:|---:|
| ubuntu-1 | 1,040 | 1,040 | 1,040 | 3,120 | 0 | 27,938 |
| ubuntu-2 | 1,560 | 1,560 | 1,560 | 4,680 | 0 | 41,727 |

両hostとも由来・artifact照合violations=0、未終結GPU試行=0。
GPU利用率の平均はubuntu-1 49.73% / ubuntu-2 39.52%、最大GPUメモリ6,106 / 5,429 MiB。
既存モデルを使ったGPU segmentの実行は確認済み。解析全体の完了数は両hostとも0。
個別asset情報を除いた検証結果は `batch1-analysis.json`。

smokeがsegment成功だけを検査し、reportの `completed_assets=0` を見逃して全量へ進んだ。
全量後にもshade・colorの完了検査が不足していたためdoneファイルが生成され、statsが起動した。
今回この不足を修正し、smokeの3件・全量の担当件数について三段階完了とpending件数を検査する。
statistics単独起動でも、出力ディレクトリ作成・DB接続前に同じ完了検査を行う。
失敗を再現する回帰テストを追加した。旧doneファイル・失敗job・全試行履歴は保全する。

2026-11-06 22:48 UTC、依存する今回のstatsサービスを停止し、MainPID=0 / inactiveを確認。
新規aggregate jobは0件で、rule_statの新規登録はない。新snapshot manifest・新report・比較JSONも未生成。
途中の `/mnt/data/derived/stats/issue114-batch1-20261106` は3エントリを持つ部分出力として保全した。
同じディレクトリでの再実行・上書き・削除は行わない。バックアップからの復元も行っていない。
解析後の旧asset 7,626行・旧processing_run 42,314行のhash変更は0、revisionは0008。

### 再開条件と残作業

1. 内部確認者が原画像と縮小画像を確認し、人物・要配慮主体は不採用とする。
   建物・地形を主体とする採用画像には確認者・主体・必要な人物除外maskを既存APIで記録する。
2. 確認済みmaskのpath・hashをshade/color入力へ固定する。現在の#66 runnerはperson_maskを渡さないため、
   maskが必要な画像をそのまま再実行できない。共有payloadへの対応を含む残作業として主担当へ返す。
3. max_attemptsに達した失敗jobと既存segment成果物を保全し、確認済みcohortの新しい実行枠を固定する。
   同一manifestをrunし直すだけではfailed jobを再試行できない。job状態や予算を独断でリセットしない。
4. 両hostでshade・colorまで3件smokeを検証後、確認済みの全件を処理する。
   不採用・保留画像を分母から黙って除かず、件数・理由を記録する。
5. 全件の完了検査後、新しい別ディレクトリでsnapshot・rule_stat・reportを作成し、
   #105訂正v2と適格画像・SHA代表・subject・n_eff・補正率・情報なし・supported・条件4を比較する。
   追加分とDB全体のCommons 100%という偏りも記載する。

#105訂正v2の基準は適格画像7,601、SHA代表3,570、確認済みsubject154、supported 0、条件4=true。
building/wallはsubject121・n_eff 27.048480793731592・補正率1.0・情報なし0、
terrain/treeはsubject15・n_eff 10.956521739130437・補正率0.5333333333333333・情報なし0.4666666666666667。
新しい統計が未生成のため、これらの新旧増減は未検証であり改善したとは報告しない。
全30,000枚・ソース多様性・新統計の完成条件は未達のため、公開用文面は `Refs #114` とする。

完了判定修正後のWSL全pytestは **1,068 passed / 1 skipped、214.59秒**、既存warning 4件。
ruff・sdist/wheel build・修正後analysis.shのbash構文確認は成功。
ログ `20261106T225152Z-56fa0410967049a7b9eecd1b08ba21f6.jsonl`、
artifact `/tmp/colorstats-issue114-JMHQbN/`。隔離PostgreSQL停止・検証process終了を確認した。
pytestのskipは実GPU条件付きテストで、今回の実GPU segment成功・shade失敗とは別に記録する。

22:58 UTCの最終照会で、今回のcollect/resume・gpu1・gpu2・stats全unitのMainPID=0を確認した。
初回collectのfailed履歴は残すが稼働processはない。Windows側の常駐監視processも残していない。
完了判定修正は担当worktreeで検証・commitし、実行済み配備コードは履歴として変更していない。
再開時は修正commitを新しく配備する。旧doneファイルを根拠に旧stats unitを再起動しない。
