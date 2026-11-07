# 本番全量判定の実行記録

## 最終状態

10,226件すべての処理が終了し、採用5,947・除外1,652・保留2,627件。
未精算・不明要求の再送・旧asset/runの変更はいずれも0。全量終了まで確認した。Closes #117。

最終値は末尾と[集計JSON](production-summary.json)を参照。
以下の途中集計・Refs・残作業の記載は、各時点の経過記録である。

対象は旧7,626件・新2,600件の計10,226 asset。
既存cohortと本番asset集合が一致し、全入力でファイルの存在と取得時SHA-256の一致を確認した。
画像単位の計画、原判定、応答、usage、失敗の詳細はprivateに保存し、本書には集計だけを記載する。

## バックアップとmigration

- ubuntu-2の本番`colorstats` DBを完全なcustom形式の`pg_dump`で保存した。
- 保存先は新設した`/mnt/data/backup-inputs/issue117-20261107T0918Z/`。
  `colorstats.dump`は735,495,658 bytes。
- SHA-256：`6460f4468dbed8e7e54374b2b41e50c92f2d363f044fc54ad93f1de4bed39cc6`。
  checksumファイルの作成後とmigration直前に再検証し、どちらも一致した。
- `pg_restore --list`とDB接続なしの`pg_restore --file=/dev/null`でarchive全体を読み取った。
  DBへの復元は行っていない。
- 既存手順に従って配備版から`alembic upgrade 0008:0009 --sql`を生成し、
  DB所有者postgresの`psql -v ON_ERROR_STOP=1`で適用した。revisionは`0008`→`0009`。
- workerには新しい`api_budget`・`api_call`のSELECT・INSERT・UPDATEだけを追加した。
  `alembic_version`へのUPDATE権限がないことも確認した。

## 配備と実行

- PR #125のmerge commit `92a4921`（#118を含む）をubuntu-1の新しい専用ディレクトリ
  `/opt/colorstats/work/issue117-production-92a4921-20261107T0918Z/`へ展開した。
  既存配備は上書きしていない。
- commit archiveのSHA-256は
  `8b35d255de51964b62d9ddb21db36cff1e1c10698714f139f13cf7b7a1e0c8c7`。
  Python 3.12の既存環境と配備版のPYTHONPATHを使用し、主要3モジュールのhashを照合した。
- 対象source 6,194行のpolicyに今回の外部送信許可を記録した。
  API送信前の既存の権利・保持確認は維持する。
- 本番専用台帳`issue114-image-gate`の上限は50,000,000,000 nano USD（50 USD）。
  5枚smokeの1 USD枠とは別のDB・台帳であり、合算・流用しない。
- `gpt-6-luna`・low・Standard、store=false、toolsなし。画像は1件ずつ、単一スロットで送る。
  countと判定を台帳で予約・精算し、Retry-After、課金不明、連続障害の停止を維持する。
  次の最大予約額を残せない段階で全体を止める。
- 当初の実行unitは`colorstats-i117-production-20261107-r2.service`。
  LoadCredentialでキーを渡し、秘密値は表示・転送していない。Windowsの常駐プロセスはない。
- 最初の投入専用unitはAPI未送信・費用0で正常終了した。
  全件の前処理を待たず、少量ずつ追加投入して直列判定する後継unitが同じ計画・予算を引き継いだ。

## 途中集計

| 項目 | 件数・金額 |
| --- | ---: |
| 投入済みjob | 448 |
| 判定run確定 | 25 |
| 投入済み・未処理 | 423 |
| 投入前の画像読取り失敗 | 1 |
| 未投入 | 9,777 |
| count要求 / 判定要求 | 25 / 25 |
| HTTP 200 / 429 | 50 / 0 |
| 未精算予約 | 0 USD |

25判定を合算した実usageは入力30,905・出力2,503・合計33,408 token。
入力内訳はcache読取り0・cache書込み30,120 token、出力に含まれるreasoningは1,324 token。
料金版は`openai-standard-2026-11-07-v2`。全50要求はsettledで、予算は停止していない。
読取り失敗は`UnidentifiedImageError`で、APIへは送らずprivateに記録した。元入力は変更していない。

## 旧データ照合と残作業

最初の投入専用unit終了時点で、事前に保存した行ごとのhashと再照合した。
旧asset 10,226行・旧processing_run 54,007行の変更・欠落はいずれも0。
API判定開始後を含む最終照合はまだ完了していない。

サービスは全対象の処理終了、停止要求、費用上限への接近、台帳停止、保存先障害で終了する。
終了時に対象・主体・人物・室内・白黒・暗所・建築部位接写の分布、採否・保留理由、
cohort別の件数、費用・usage、応答と費用の監査、旧行hashの最終照合を集計する。
判定分布は全量終了後に評価し、この途中標本を品質合格の根拠にはしない。

private保存先は`/mnt/data/derived/issue117-production-20261107T0918Z/`。
`plan.json`、`service-r2.log`、`progress.json`を進捗に、終了時の`public-summary.json`を最終集計に使う。
画像・応答artifactは既存保持台帳へ登録する。最も早い画像保持期限は2026-12-01 12:27:03 UTC。
停止が必要な場合はubuntu-1で`sudo systemctl kill --kill-whom=main --signal=SIGTERM colorstats-i117-production-20261107-threshold4`
を実行すると、新規取得を止め、通信中の要求の精算・run確定を待って終了する。
課金不明の要求は自動再送しない。

残作業は全量の終了確認、失敗・保留の精査、最終集計と旧データ照合の確認、
本書・公開文面の更新である。完了までは`Closes #117`にしない。

## 4並列への切替（2026-11-07）

ユーザーの「4並列に増やす」という決定に従って変更した。
旧r2 unitの親だけを短時間停止して子の通信・精算を待ち、記録済みのSIGTERMを送って
停止フラグを立てた。09:40:29 UTCに正常終了し、次を確認した。

- 課金不明要求0件、送信中要求0件、未精算予約0、running job 0件。
- 旧asset 10,226行・旧processing_run 54,007行の変更・欠落0。
  新しい画像判定runは130件。応答・usage・精算額・run identityの監査不一致はいずれも0。

送信枠を`COLORSTATS_IMAGE_GATE_CONCURRENCY=4`で指定できる最小変更を
`e8b9c765f7fc51c903d8e1936664eac6b3861d37`にcommitした。既定値は1、指定範囲は1〜4。
予算行のロック内で送信中の本数と全予約・確定費用を検査する仕組みを維持した。
4本同時でもcap境界、二重送信防止、課金不明時の停止、Retry-After、連続429/5xx時の停止を検証した。
全pytestは1,253 passed・1 skipped（外部APIはmock・隔離DB）、ruff・build成功。
私有の運用スクリプトもmockで4 workerの同時動作とSIGTERM後の4件の完了待ちを確認した。

配備先は新設した`/opt/colorstats/work/issue117-production-parallel4-20261107T0950Z/`。
archiveのSHA-256は`b7c80d40fd8ac386768d403a22c10b5fc182499f39da92ddddf2fae903ff3abc`。
archiveと配備ファイルのSHAを再検証した。既存配備は上書きしていない。
classifier・prompt・schema・pricing・固定job payloadは維持し、保存済み応答を再利用する。
運用版commitはprivateの`deployment.json`・`parallel4-start.json`と最終集計に記録する。

新しいunitは`colorstats-i117-production-20261107-p4.service`。
**09:52:53.945923 UTCに4 workerで再開**し、送信上限も4に設定した。
全workerが同じ50 USD台帳を使用し、キーは引き続きLoadCredentialから渡す。
SIGTERMでは新規取得を止め、通信中の要求を精算・run確定してから終了する。
このunitの停止待機上限は300秒。課金不明要求は自動再送しない。

### 再開後の実測

2026-11-07 09:56:15 UTCの読取り専用・repeatable read snapshotで確認した。

| 項目 | 結果 |
| --- | ---: |
| 再開からの測定時間 | 201.292秒 |
| 測定区間の確定run | 185件 |
| スループット | 55.14件/分 |
| 確定run累計 / running job | 315件 / 4件 |
| 観測した最大同時送信 | 4本 |
| 429 / 課金不明 / 再試行要求 | 0 / 0 / 0件 |
| 台帳費用・応答hashの監査不一致 | 0件 |

同じsnapshotの全settled応答について、保存応答のhashと実usageによる費用を台帳と照合し、一致した。
画像として読めず送信しなかった入力は引き続き1件。失敗の詳細はprivateに置く。
残り9,910件を同じ速度で処理できれば、終了見込みは**11月7日13:00 UTCごろ（22:00 JSTごろ）**。
初期区間からの概算であり、入力の大きさ・保持/権利確認・429や障害で変動する。

privateの`parallel4-observed.json`・`parallel4-measurement.json`・`service-p4.log`へ進捗を保存する。
旧停止時の集計は`r2-stop-summary.json`へ保全した。Windowsの常駐プロセスは作っていない。
全量判定・最終照合は継続中であり、公開文面は引き続き`Refs #117`とする。

## 停止調査と再開（2026-11-07）

### 原因

旧p4 unitは11:28:29 UTCに終了した。停止時点は成功5,176・pending 268・failed 3件、
台帳はsettled 10,355・retry 1・unknown 1件だった。
FileNotFoundErrorのパスはunknown要求の保存応答に一致し、元画像の欠損ではなかった。
通信または応答保存の例外で課金・完了が不明になり、共有予算が安全側に停止した後、
終了監査がその存在しない応答ファイルを無条件に読んだため、集計も中断した。
元の実装は例外型・発生段階を記録していなかったため、通信と保存のどちらが失敗したかは特定できない。
費用上限による停止ではなく、課金不明による停止である。

failed 3件のうち1件は課金・完了不明による再送停止、2件は共有予算の停止によるものだった。
3件の元入力は存在し、取得時SHAと一致した。HTTP 520の保存応答はJSONではなく、usageは取得できなかった。
欠損応答が1件あっても残りの監査を続けられるよう、費用区分と固定エラーコードを返す
`production_audit.py`を追加した。未解決予約・上限精算・実usage精算を区別し、欠損を0円扱いにしない。
課金不明時に全体を止める動作は維持する。個別の入力読取り失敗は既存のjob/投入失敗として記録する。
今後は通信・保存の失敗段階と例外型だけを記録し、例外本文・秘密値は保存しない。

修正commitは`eef50e2d4ec4ecf073f1c8246987d6d32fc7570f`。
全pytestは1,260 passed・1 skipped（外部API mock・隔離DB）、ruff・build成功。
欠損応答での監査継続、上限精算後の再送禁止、保存失敗時の秘密値なしの記録を回帰テストした。

### 台帳の照合と停止解除

停止中にprivateへ元の台帳・budget・failed jobの前後を保存し、予算行をロックして処理した。

| 区分 | 件数・金額 |
| --- | ---: |
| 解除前の未精算予約・未処理unknown | 0 / 0 |

上限精算2件は`details.reconciliation.basis=reservation_upper_bound`と根拠・時刻を記録し、
実usageによる費用と分離した。unknownだった要求はstate=stoppedとして、そのjobもfailedのまま保持し、
再送を禁止した。HTTP 520の要求は元のretry状態・Retry-After・最大試行数を維持した。
予算停止に巻き込まれた2 jobだけをpendingへ戻し、既存の試行数・台帳を引き継いだ。
元のfailed理由はprivateの監査記録へ保全した。
上限50 USD・料金版を変更せず、未解決の送信・予約がないことを確認して停止フラグを手動解除した。
APIの追加呼出し・復元・台帳の削除はこの照合では行っていない。

修正後の監査を再開前の実台帳で事前実行し、上限精算2件を含めて不一致0件で完了した。
旧asset 10,226行・旧processing_run 54,007行の変更・欠落も0。

### 巨大画像と再開位置

警告は元画像の復号時のもので、送信する画像は既定の長辺1024以下・RGB PNGに縮小している。
旧p4の警告は延べ34回。画像ごとの画素数はprivateに保全した。
サービスのMemoryPeakは5,215,817,728 bytes（約4.86 GiB）、MemorySwapPeakは0。
停止前後のkernelログでOOM・Killed process・NFS not respondingはいずれも0件だった。
メモリ約16 GiBの環境でメモリ不足を示す事実はなく、この警告を今回の停止原因とは扱わない。
Pillowの安全上限は変更せず、上限を超えた画像1件はDecompressionBombErrorとして投入前に保留した。
ほかにUnidentifiedImageErrorが1件あり、いずれもAPIへ送っていない。

「enqueue 5,400」は進捗ログの区切りで、保存済みmanifestは正確には5,449入力
（job 5,447件・投入前保留2件）だった。job IDは重複せず、本番のjob集合と照合して引き継いだ。
再投入で既存jobを作り直したり、成功run・保存済み応答を破棄したりしていない。

新しい配備先は`/opt/colorstats/work/issue117-production-recovery-20261107T1200Z/`。
archiveのSHA-256は`4cef84b43952e76afb98fad51aa63c0fb06e73a30ddc258a55333d547b2894c6`。
commitと配備ファイル・運用スクリプトのSHAを照合した。既存の配備物は上書きしていない。
新unitは`colorstats-i117-production-20261107-recovery4.service`。
**12:07:09.476595 UTCに4並列で再開**した。共有50 USD台帳・LoadCredential・SIGTERM時のdrainは維持する。
privateの`recovery4-start.json`・`recovery4-observed.json`・`service-recovery4.log`に記録する。

### 復旧後の実測

12:10:12 UTCの読取り専用・repeatable read snapshotで確認した。
保存応答は修正した監査で照合し、上限精算は実usageと分けて集計した。

| 項目 | 結果 |
| --- | ---: |
| 再開からの測定時間 | 183.119秒 |
| 測定区間の確定run / スループット | 145件 / 47.51件/分 |
| 確定run累計 / running job | 5,321件 / 4件 |
| 最大同時送信 / 未処理unknown / 429 | 4 / 0 / 0 |
| HTTP 520累計 | 1件（停止前のもの） |
| 保存応答・費用の監査不一致 | 0件 |

残り4,902件を同じ速度で処理できれば、終了見込みは
**11月7日14:00 UTCごろ（23:00 JSTごろ）**。初期区間からの概算であり、入力差や障害で変動する。
unknownだったjobは再送禁止で保留、投入前に読めなかった2件も保留を継続する。
全量の最終判定分布・失敗/保留内訳・費用・旧データhashの確認は引き続き残っている。
画像単位の証跡と`recovery4-measurement.json`はprivateに保存し、公開文面は`Refs #117`を維持する。


途中の個別精算額・予約額とその差分を復元できる金額はprivateに保全した。
公開費用は以下の全量合計だけに集約する。

## 最終集計（全量処理完了）

- 原因は60秒のHTTP timeout。個別上限精算・再送禁止と、共有の停止閾値へ変更した。
- 修正commitは`341847c6f59e7ab9c923df02f61bc67d3856e159`。全pytest 1,267 passed・1 skipped、ruff・build成功。
- 不明は連続3/累計30、連続429は2、HTTP timeoutは120秒。設定を環境・各要求・開始記録へ保存した。
- 新unitは`colorstats-i117-production-20261107-threshold4`、4並列・同じ50 USD台帳・LoadCredentialを使用した。
- 最終再開：2026-11-07T13:00:18.611530+00:00。全件終了：2026-11-07T14:34:21.859602+00:00。
- 短時間の測定で終了せず、照会とログ購読で正常終了まで監視した。サービスは終了、Windows常駐処理はない。

| 項目 | 件数 |
| --- | ---: |
| 対象 | 10,226 |
| 判定run確定 | 10,221 |
| API失敗による保留 | 2 |
| 投入前保留 | 3 |
| 採用 | 5,947 |
| 除外 | 1,652 |
| 保留合計 | 2,627 |
| pending / running | 0 / 0 |

保留合計には判定runでの保留・API失敗・投入前保留を含める。分類不能を旧承認で採用していない。

| 原判定の採否理由 | 件数 |
| --- | ---: |
| `accepted` | 5,947 |
| `black_and_white` | 579 |
| `dark_or_unknown` | 214 |
| `non_target` | 1,073 |
| `real_people` | 1,897 |
| `subject_conflict` | 8 |
| `subject_unresolved` | 457 |
| `uncertain` | 46 |
| `api_unknown_no_resend` | 2 |
| `DecompressionBombError` | 2 |
| `UnidentifiedImageError` | 1 |

| 原判定の属性 | 内訳 |
| --- | --- |
| `target` | False: 1,581 / True: 8,640 / unavailable: 5 |
| `subject` | building: 5,057 / mixed: 666 / other: 1,156 / terrain: 3,341 / unavailable: 5 / unknown: 1 |
| `real_people` | absent: 8,324 / present: 1,593 / unavailable: 5 / uncertain: 304 |
| `interior` | False: 9,138 / None: 406 / True: 677 / unavailable: 5 |
| `black_and_white` | False: 9,414 / None: 17 / True: 790 / unavailable: 5 |
| `dark` | False: 9,906 / True: 315 / unavailable: 5 |
| `building_detail` | False: 8,333 / True: 1,888 / unavailable: 5 |

各属性は重複する。`unavailable`はAPI失敗・投入前保留・原判定の欠測/不正を含み、各行は10,226件になる。
採否理由はpolicyの優先順位に従うため、属性別の画像件数と採否理由の件数は同じではない。

| 費用・API | 結果 |
| --- | ---: |
| 実usageによる精算 | 1.73258144 USD |
| 予約上限での精算（3件） | 0.003847 USD |
| 計上合計 | 1.73642844 USD |
| 上限 / 未精算予約 | 50 USD / 0 USD |
| 不明要求累計 / 再送 | 2 / 0 |
| HTTP内訳 | 200: 20,444 / 520: 1 / unavailable: 2 |
| 実usage合計 | cache_write_tokens: 8,876,054 / cached_tokens: 2,776,389 / input_tokens: 12,399,861 / output_tokens: 1,041,138 / reasoning_tokens: 559,732 / total_tokens: 13,440,999 |

上限精算は実際の請求額と区別する。不明要求の後続試行がないことと、保存応答・費用の監査不一致0を照合した。
HTTPエラーの過去retry行は履歴として保持し、予約・費用・台帳を削除していない。

| 旧データ | 照合行数 | 変更・欠落 |
| --- | ---: | ---: |
| `asset` | 10,226 | 0 |
| `processing_run` | 54,007 | 0 |

旧行の個別hashと集合hashは前後で一致した。新しい判定runだけを追加し、旧quality・domain・subject・固定統計は変更していない。
画像単位の原判定、保留一覧、usage、台帳の前後はprivateに保持する。Gitには集計のみを追加した。
残るのは公開担当によるpush・PR・mergeであり、本Issueの実装・本番全量処理・最終照合は完了した。

## 本番終了後の再反証修正（2026-11-08）

- `origin/develop`の`d3c742c`を取り込み、Retry-Afterを同じ予算のendpoint・modelごとに共有した。
  期限まで別jobも予約せず延期し、既存の最大3試行・連続429停止・予約上限を維持する。
- 応答のmodel/tierが固定料金の前提と違えば共有予算を直ちに停止する。
  対応料金表がない組合せには既定単価を使わず、予約上限で計上して照合待ちにする。
- 途中の要求別精算額・予約額と画像ごとの画素数をprivateへ移し、費用は全量合計に集約した。
  個別額を含む過去の公開予定commitも、最新develop起点の履歴へ作り直した。
- 修正前に3件の回帰失敗を再現し、修正後の全pytestは1,372 passed・1 skipped。
  外部APIはmock、PostgreSQLは隔離DBを使用し、ruff・buildも成功した。
- 本番の全量処理は上記のとおり完了済み。この修正の再配備・本番DB更新・実API呼出しは行っていない。

Closes #117。
