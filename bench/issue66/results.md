# Issue #66 部位全量解析の実行記録

2026-11-03。起点 `133b2691c16103057b42dc8713a0f7c824daa89f`（#81 merge後）。
worktree: `H:/mc-blueprint/worktrees/colorstats-66/mc-blueprint-color-stats`、
branch: `feature/issue-66`。commit・push・PR作成は未実施。
全量完了・集計後に公開準備を行う。Issue全体の完成とはまだ扱わない。

## 実装と契約

既存SQLAlchemy・PostgreSQL Queue/Worker、stageのprepare/register、
#47のSamplerを再利用し、依存・テーブル・保存形式を増やしていない。

- `ops/deploy/m3_analysis.py`のfreeze/run/reportで、固定コホートと再集計を管理する。
- 成功prepのDB参照から既存derivedの不変出力を解決し、入力画像SHA-256を固定。
  raw-cacheを複製せず、registerのパス・asset・成功run照合を維持する。
- `Queue.claim(..., job_ids=...)`を追加。省略時は従来どおり。
  本バッチのジョブだけを取得し、旧失敗版・他タスクのpendingを消費しない。
- 既存Workerの同じ計算子を再利用し、実ファイルhashが同じSAM 2/DINOを常駐。
  既存の256 prepareごとの子交代・停止・リース失効・3試行打切りを維持する。
- 成功runの登録は既存Queue.completeの所有権付き取引。
  再起動時は同じmanifest・payloadから既存Jobを解決し、成功済みを二重登録しない。
- shade noneと部位colorには同じprep・segmentの参照と入力hashを渡す。
  hash不一致は計算前に拒否し、segment由来との不一致は登録取引を戻す。
- 既存全体color7,603件を本バッチの成功に含めない。
  関係は領域UUID順のco_occurs、差はB−A、面積比はB/A。
- 採用設定は `configs/segment_stats.yaml`、sam2-dino / threshold 0.35 /
  text_threshold 0.25 / shade none。入力hashに加えてコード・設定hashを固定。
  支持の正本は[ #81 結果](../issue81/results.md)。
  個別door以外の子ラベルを支持済みと解釈しない。
  wall/treeを採用する後続snapshot/統計は同じassetの構成マスク和集合から直接求める。
  今回の既存Region・子観測を独立した支持標本として加算しない。

本番接続は既存postgres peer認証。専用の`/mnt/data/work/issue-66/peer.py`から
rootで実行し、DB接続時だけpostgresの実効UIDへ落として接続、直後に戻す。
認証ファイル・URL・トークンを転送・出力せず、DBロール・認証設定は変更していない。
source/prep/subjectの既存値と#79のコード・関連付けは変更しない。

## 固定入力と版

全asset **7,607件**、SHA異なり **3,575**。prep成功 **7,603件**、失敗 **4件**。
失敗理由は巨大画像のDecompressionBombError 2件、SVGのUnidentifiedImageError 1件、
math domain error 1件。既存prepの失敗・試行数は変更せず、回復・解析成功に数えない。

修正版の本番rootは `/mnt/data/work/issue-66/production-v2`。
manifest SHA-256:
`85ce77ea471236ad882ea77403f206302e794733f0c59dc2fad16fb9f647a047`。
manifestには全件のasset/SHA・prep状態/理由、成功prep run/パス/hash、
採用設定とコード各ファイルhashを保存する。

初回版 `/mnt/data/work/issue-66/production` は停止・保全。
色処理の先行importが作るMatplotlib仮モジュールにより、
Transformersが `matplotlib.__spec__ is not set` で失敗した。
stageの失敗として6ジョブ・18試行、停止時pending 1ジョブ、
失敗試行55.752秒、全経過66.416秒、成功run 0件。
`failed-import-report.json`とattemptsを保全し、成功版の速度へ混ぜない。
起動時の色処理importを遅延させて修正し、回帰テストを追加した。
旧ジョブのresetや失敗の成功への書換えは行っていない。
旧版pending 1件も本バッチの取得対象外として保全する。後日、対象を限定しない
汎用segment Workerを起動する際は、この旧版ジョブを含めない運用判断が必要。

## 検証

- Windows専用Python 3.12 venv、uv.lock準拠。
  最終全pytest: **354 passed, 139 skipped**（37.84秒）。
  import修正後の関連回帰: **5 passed, 2 skipped**（6.03秒）。
- Ubuntu / Python 3.12.3 / 専用PostgreSQL 16：
  修正後全pytest **491 passed, 1 skipped**（74.74秒）。
  追加した登録hash不一致のrollbackを含む関連テスト **8 passed**（2.10秒）。
  専用クラスタは終了後停止し、データとログを保全。
- ruff check、sdist/wheelビルド成功。
  既存ColourUsageWarning（任意Matplotlibなし）を成功扱いの根拠にはしていない。
- skipはWindowsのDB/Linux要件と既存GPU DB統合テスト。
  実CUDAと本番DBの接続は下記の20件サンプルで別途確認する。
- 他ジョブ非取得、入力差替え拒否、登録失敗rollback、再開時の成功run不変、
  再試行と失敗時間の区別、モデル内容変更時の再ロードを検証した。


## 20件の実接続と全量起動

修正版の20件はsegment/shade/colorとも20成功・失敗0・再試行0。
全経過 **254.471秒**、**0.078595 asset/秒**。
成功run時間はsegment **160.011秒**、shade **16.774秒**、color **44.089秒**。
588領域、shade観測588件、部位色観測2,940件、共起9,792件を登録した。
出力668 artifact / **12,094,679 byte**。prep画像入力は各stage **1,403,174 byte**。

GPU平均 **23.894%**、VRAM最大 **3,435MiB**（1秒間隔254サンプル）。
プロセス論理read **50,150,612,971 byte**、write **15,548,364 byte**、
物理read **917,504 byte**、write **14,757,888 byte**。
重みの繰返しhashを含むため、prep画像の入力byteと論理readを混同しない。

DB全体差 **8,200,192 byte**、表/TOAST差 **5,554,176 byte**、
索引差 **2,646,016 byte**、WAL差 **16,649,832 byte**。
詳細な表/索引別差と計測条件は[sample-summary.json](sample-summary.json)。
並行#79のCPU作業があったため、専有時の速度・DB増分とは断定しない。

由来・権利・件数・関係のDB値/符号・入力hashの照合違反0件。
reportを2回実行し、全計測値と全668 artifact hashが一致した。
独立SQLで全7,607 assetの集合・SHA不一致0件と、
全量再開時に先行20件のrun IDがすべて不変であることを確認した。

全量は **2026-11-03 03:42:15 UTC（12:42:15 JST）** に
`colorstats-issue66-full.service`（invocation
`44541b4ec72d40ba9fc855eba271fa6c`）として起動した。
直前のGPUは0%・17MiB、計算アプリなし、空き **936,622,387,200 byte**。
#79のCPU処理も同じディスクで動くため、全量計測にも並行書込みの注記を付ける。

03:44:53 UTC時点でfullはactive/running、color成功28件、segment成功29件、
shade成功28件＋実行中1件。失敗は0件。先行20件の次のassetも実登録している。

20件サンプルを単純外挿すると全7,603件は **約26.87時間**。
画像の検出数・関係数、モデル再ロード、DB増量・並行作業で変わる参考値であり、
全量実測ではない。全量終了後に実測で更新する。

## 計測の意味

`*-before.json` / `*-after.json`にDB全体byte、表/TOAST・索引別byte、
挿入/更新/削除カウンタとWAL LSNを保存する。
reportが各セッションの差とWAL差を再計算する。
#79等の並行書込みを含み得るので、本バッチ専有のDB/WAL増分とは断定しない。

`attempts.jsonl`は試行開始/終了をfsyncし、理由・経過秒・親/計算子PIDごとの
/proc I/Oカウンタを保持する。成功run時間、失敗試行時間、再試行を分けて集計する。
`process_io_bytes`のrchar/wcharは論理I/O、read_bytes/write_bytesは物理I/O。
キャッシュ済み読取りではread_bytes=0となる。重み・再hash・maskのI/Oも含む。
強制終了した子の最終未採取区間は含まない。
stageの`input_bytes`はprep画像の論理byteだけ、output_bytesは成功artifactのbyte。
DB I/OはDB/WAL差で別に扱い、プロセスI/Oへ混ぜない。

`*-telemetry.jsonl`に1秒間隔のGPU利用率・VRAMを保存する。
reportは成功runとProcessingRunInput、入力hash、登録ライセンス、
region/部位観測/関係件数とDBの関係値・符号、全出力artifact hashを照合する。
新規出力JSONで結果を保全し、以前の集計は上書きしない。

## 全量の運用

全量ユニット名: `colorstats-issue66-full.service`。
stdout/stderr: `/mnt/data/work/issue-66/full.log`。
入力・試行・計測: `/mnt/data/work/issue-66/production-v2/`。
コード: `/mnt/data/work/issue-66/code`、Python: `/mnt/data/work/issue-40/venv/bin/python`。
ubuntu-1のpilotは再開しない。再開中のコード・設定・manifestは変更しない。

進捗（ubuntu-2で実行。Windowsからは登録済み`scripts/ssh.py`を使用）:

```sh
systemctl show colorstats-issue66-full.service -p ActiveState -p SubState -p ExecMainStatus
tail -20 /mnt/data/work/issue-66/full.log
sudo -u postgres psql -d colorstats -X -P pager=off -c "
SELECT stage,status,count(*),sum(attempts) AS attempts
FROM job
WHERE payload->>'batch'='85ce77ea471236ad882ea77403f206302e794733f0c59dc2fad16fb9f647a047'
GROUP BY stage,status ORDER BY stage,status;"
```

停止:

```sh
sudo systemctl stop colorstats-issue66-full.service
```

SIGTERMでrootの`stop`を作成し、既存Workerで進行試行を中断・記録する。
OS強制停止ではリース期限（10分）後に再取得し、3試行上限を維持する。
一時ユニットはOS再起動で消えるため、再開は同じコード・rootを指定して次を実行する。
停止理由とGPU・ディスクの利用状況を確認し、停止ユニットの`stop`だけを取り除く。
初回起動と同じコマンドで、新しい成功出力を二重登録せず未完了から続行する。

```sh
sudo rm -- /mnt/data/work/issue-66/production-v2/stop  # 存在し、停止理由を確認した場合だけ
sudo systemd-run --unit=colorstats-issue66-full --collect \
  --property=Restart=on-failure --property=RestartSec=60 \
  --property=WorkingDirectory=/mnt/data/work/issue-66/code \
  --property=StandardOutput=append:/mnt/data/work/issue-66/full.log \
  --property=StandardError=append:/mnt/data/work/issue-66/full.log \
  --setenv=PYTHONPATH=src:. \
  /mnt/data/work/issue-40/venv/bin/python /mnt/data/work/issue-66/peer.py \
  run --root /mnt/data/work/issue-66/production-v2
```

## 2026-11-04 全量終了後の実測と完成条件

解析サービスは `inactive/dead`, `Result=success`, `ExecMainStatus=0` で終了し、再起動・再実行はしていない。`full.log` の最終行は processed=7,603、elapsed_seconds=91,593.747372466（25時間26分33.747秒）。manifest `85ce77...a047` の7,607件すべてを確認し、prep成功7,603件、prep失敗4件である。失敗4件は DecompressionBombError 2件、SVGのUnidentifiedImageError 1件、math domain error 1件。失敗を回復扱いにしていない。

| stage | job結果 | 試行 / 再試行 | 成功run秒 | input byte | 成功artifact byte | DB登録数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| segment | 成功3,890 / 失敗3,713 | 15,117 / 7,514 | 29,773.106164 | 233,438,578 | 593,523,845 | region 111,471 |
| shade | 成功3,890 / 失敗0 | 3,890 / 0 | 4,864.253923 | 233,438,578 | 324,277,308 | part observation 111,471 |
| color | 成功3,890 / 失敗0 | 3,890 / 0 | 11,511.873235 | 233,438,578 | 1,421,858,002 | part observation 557,355; relation 1,726,948 |

segment失敗3,713件の最終理由はすべて `RuntimeError: ValueError: matplotlib.__spec__ is not set`。各失敗は再試行3回を含み、全attempt 22,897件はstarted/finishedが各22,897件、未終了attempt 0件、input rejection 0件。成功処理の出力artifactは全件SHA-256を照合し、成功runと入力・asset・license・region・観測・relation登録の違反は0件。登録relationとJSON、relation符号の照合違反も0件。完了したassetは3,890件、未完了は3,713件（prep失敗4件は別途除外）で、全量成功条件には未達。

全run経過時間の合計は91,848.624秒（既存20件sampleを含む）。attempt記録上の成功46,476.386秒、失敗33,663.469秒。全量run単体の経過91,593.747秒に対するcolor完了数は0.04247 asset/秒。試行時間の合計とwall timeは並列処理・待機等を含むため一致しない。

最終reportは `final-20261104T0520Z.json` と `final-20261104T060000Z.json` の2回を実行し、ファイルSHA-256は双方 `76f7d507e0d736c86742130b50deb6edd7ff473ca8d5619cbfca31a238a97a77` で一致。いずれも `violations=[]`、`completed_assets=3890`、`pending_assets=3713`。DB照会はreportのREPEATABLE READ / READ ONLY transactionを用い、明示SQLも `BEGIN READ ONLY` から `ROLLBACK` で実行した。DB全体差分は +1,437,843,456 byte、WAL差分は +11,380,229,680 byte。表・索引個別差分はJSONの `db_deltas.tables` / `db_deltas.indexes` に保存。いずれも同時期の #79 等の書込みを含み、#66単独の容量とは断定しない。

telemetryは91,832サンプル、GPU平均13.0868%、最大VRAM 6,539 MiB。process I/O集計（20件のsampleと全量runを含む）は rchar 57,542,367,156,781、wchar 5,899,129,098、read_bytes 41,304,064、write_bytes 5,658,419,200 byte。サービス終了後はGPU 0%、17 MiB使用、対象filesystem空き928,434,073,600 byte。全量run単体の経過時間はログの91,593.747秒であり、reportの91,848.624秒は既存20件sample 254.471秒との合算。

Issue #66 完成条件判定:

- [x] 7,607件のprep成功/失敗状態と失敗理由を保持。prep成功7,603件を対象に処理ジョブが作成され、prep失敗4件は除外。
- [ ] 7,603件すべてで segment→shade→color と部位色・関係の登録を完了。実績は3,890件、segment失敗3,713件。
- [x] 採用設定（sam2-dino、threshold 0.35、shade none）をmanifestに固定。
- [x] 成功run、入力由来・hash、artifact hash、DB登録件数の照合を実施。report違反0件。
- [x] 実行時間、stage成功run時間、失敗/再試行、GPU/VRAM、process I/O、DB表/索引差分、WAL差分を記録。DB/WAL差分は同時書込みを含む。
- [ ] 全量完了。失敗原因 `matplotlib.__spec__ is not set` の解消後に、未完了3,713件を含めた再実行・集計が必要。今回の指示に従い、サービスを再起動・再実行していない。

公開準備・残作業: 全量未完了のためIssue完了とは扱わない。失敗理由の修正と対象3,713件の安全な再処理、最終集計を行った後に公開準備文面を確定する。

## 2026-11-04 segment失敗原因と修正・再処理

`attempts.jsonl`にはPython tracebackは保存されず失敗理由文字列のみだった。systemd journalにもtracebackはなかったため、同じubuntu-2 venv・実行コードでstage import順を単独再現した。初期worker PID 121264は `segment→shade→color` の順に20件を成功。worker PID 128256は256 prepare後の再起動直後、04:01:51 UTCにshade、04:01:54にcolorを成功した後、04:01:56のsegmentから同一PIDで失敗し、3回のattemptすべて同じ理由になった。同じ「shade/colorから始まるworkerで後続segmentが失敗」「segmentから始まるworkerは成功」の交互パターンが後続PIDにも記録されている。

再現時のtracebackは `transformers/utils/import_utils.py` の `_is_package_available("matplotlib")` から `importlib.util.find_spec("matplotlib")` に入り、`ValueError: matplotlib.__spec__ is not set` を送出した。直前の `colorstats.colors` import後に `sys.modules["matplotlib"]` は `unittest.mock.MagicMock`、`__spec__` はNoneだった。colour-scienceの `colour.plotting` はMatplotlibがない場合、`MagicMock`をmatplotlibおよびoptional plotting module名で `sys.modules` に登録する。worker再起動境界が3 stage単位に揃わずshadeから始まると、color importがTransformers初回importより先になり、次assetのsegmentが壊れたglobal module entryを検査する。これが成功workerとの差と失敗再現の根拠。

修正は [colors.py](../../src/colorstats/colors.py) で、`colour` import後に `__spec__` がない `matplotlib` entryだけを `sys.modules` から除去する。Transformers側はmatplotlib未導入を通常どおり検出できる。 [test_color.py](../../tests/test_color.py) に別processでの回帰テストを追加。ubuntu-2の実venvでも修正後にcolor→Transformers model classの順でimportし、成功、`find_spec` はNoneを確認した。

修正検証: ruff成功、Windows pytest **431 passed / 153 skipped**、wheel build成功（SHA-256 `89d88d450a5a5ffbe8ea556c8740eeb93bbb8ae5c34ae4d0b60b0022bab0e84a`）、隔離PostgreSQL 16 pytest **493 passed / 1 skipped**（84.64秒）。Matplotlib未導入のcolour-science warningは継続するが、import失敗は再現しなかった。

再処理manifestは既存reportのfailed segment asset IDだけを使って `/mnt/data/work/issue-66/retry-3713/` に作成した。manifest SHA-256 `bab6f3c0971026d03767a656c9ac2b8fb2385f47be3a4fa5a3eb8a3986fab59e`、対象3,713件、prep失敗4件・以前の成功3,890件は含まない。別batchとして既存runを再利用・上書きせず、新規jobで再処理する。

最初の20件はsegment/shade/color各20件成功、attempt 20件ずつ、再試行0、report violations 0、経過293.457秒。DBのREAD ONLY集計でも新batchは3stage各20 succeeded。既存batchはsegment/shade/color各3,890 succeeded、segment failed 3,713のまま維持されている。20件の実測から残り3,693件は約15時間（概算14–16時間）。全量unitの起動・進捗・停止手順はこのrunの開始後に追記する。

## 全量完了後

1. full.logの終了、ユニットの終了状態とDBのpending/running/failedを確認する。
   7,603成功を推測しない。失敗・入力拒否があれば理由と未開始後段を照合する。
2. コードディレクトリで次を実行する（日時を含む新規出力名を使う）。

```sh
cd /mnt/data/work/issue-66/code
sudo env PYTHONPATH=src:. /mnt/data/work/issue-40/venv/bin/python \
  /mnt/data/work/issue-66/peer.py report \
  --root /mnt/data/work/issue-66/production-v2 \
  --output /mnt/data/work/issue-66/production-v2/final-YYYYMMDDTHHMMSS.json
```

3. violations=0、prep失敗4件保持、completed_assets/pending_assets、
   各stageの成功/失敗と試行数、入出力byte、GPU・VRAM、DB表/索引/WAL差を確認する。
   同じコマンドを別の新規出力名で再集計し、DB状態不変なら計測集計とhashが一致することを照合。
4. 全量の実測でdocs/m2-report.md §5・§6の速度・容量試算を更新する。
   stage成功run時間と全経過・失敗/再試行を併記し、並行DB書込みの影響を明記する。
5. 本結果の全量状態と未支持を更新し、#74/#75へrun・artifact・採用設定を引き継ぐ。
   その後にコミット文・PRタイトル/本文（Closes #66）を準備する。
   今回の作業ではcommit・push・PRと公開用文面を作らない。

## 2026-11-04 segment失敗原因の修正と再処理

- 実環境で再現した根本原因は `colour.plotting` の optional Matplotlib fallback が `sys.modules` に `matplotlib` の `MagicMock`（`__spec__ is None`）を残すこと。worker recycle後に色処理を先にimportしたPIDは、`shade → color → segment` の順で次のsegmentが初めてTransformersをimportし、`importlib.util.find_spec("matplotlib")` が `ValueError: matplotlib.__spec__ is not set` を送出した。成功PID 121264はsegmentから始まる20件が成功。失敗PID 128256は04:01:51 UTC shade、04:01:54 color成功後、04:01:56 segmentが失敗し、同様の順序差は後続PIDにも現れた。attempt/journalにtracebackが残らなかったため、ubuntu-2実venvで同じimport順を再現して特定した。
- `src/colorstats/colors.py` は `colour` import後、`__spec__` のない `matplotlib` entryだけを `sys.modules` から除去し、Transformersがoptional package不在を通常どおり検出するよう修正。`tests/test_color.py` に別processでの回帰テストを追加。ubuntu-2実venvでも色処理→Transformers import成功と `find_spec` がNoneになることを確認。
- 検証：ruff成功、Windows pytest 431 passed / 153 skipped、隔離PostgreSQL 16 pytest 493 passed / 1 skipped（84.64秒）。wheel build成功（109,496 byte、SHA-256 `89d88d450a5a5ffbe8ea556c8740eeb93bbb8ae5c34ae4d0b60b0022bab0e84a`）。`python -m build` はbuild frontend未導入で実行失敗し、`pip wheel . --no-deps` でwheel生成を確認した。Matplotlib未導入に関するcolour-science warningは残るが、対象import失敗は再現しなかった。
- 失敗segmentだけのmanifestは `/mnt/data/work/issue-66/retry-3713/`、3,713件、SHA-256 `bab6f3c0971026d03767a656c9ac2b8fb2385f47be3a4fa5a3eb8a3986fab59e`。prep失敗4件と以前の成功3,890件は対象外。別batchであり旧run・データを上書きしない。先行20件はsegment/shade/color各20成功、attempt各20、再試行0、report violations 0、293.457秒。READ ONLY DB照合でも元batchの3stage各3,890成功とsegment failed 3,713は維持。
- 残りを `colorstats-issue66-retry.service`（InvocationID `2c58c5336dfc407ebc1574665cdba4ca`）で2026-11-04 06:25 UTCに起動。対象コホート3,713件中、先行20件成功済み、残り3,693件。起動初期確認はactive/running、ログ `/mnt/data/work/issue-66/retry-3713.log`。起動後の先頭6件は先行成功の冪等再利用で約9秒。先行20件の実測からの概算は約15時間（14～16時間、初期化・キャッシュ・共有負荷で変動）。
- 進捗：`systemctl show colorstats-issue66-retry.service -p ActiveState -p SubState -p Result -p ExecMainStatus --no-pager`、`tail -n 20 /mnt/data/work/issue-66/retry-3713.log`。停止：`sudo systemctl stop colorstats-issue66-retry.service`。完了後は上記「全量完了後」の手順をretry rootに適用し、READ ONLY DB集計・report整合・telemetry/GPU/I/O・WAL/table/index差分を記録する。再起動・再実行しない。
- 完成条件：原因修正と回帰確認は達成。失敗segment 3,713件の再処理は開始済みで未完了のため、全7,603件のsegment→shade→color完了条件は未達。prep失敗4件は失敗理由を維持し、回復扱いにしない。

## 2026-11-04 複数ホストworker参加可否

- 現在の `peer.py run` はmanifestを1件ずつ走査し、各stageで `Queue.claim((stage,), job_ids=(job_id,))` としてそのassetのjobだけを取得する。DBの `SKIP LOCKED` はclaim内で使うが、現runnerはqueue全体のconsumerではない。同じrootは `runner.lock` で排他し、payloadにはroot内output pathが含まれるため、同一manifest/rootを複数hostから同時起動する方式は使えない。安全な分割には現runをstage境界で正常停止し、DBの成功状態を読み取り専用で確定して、重複しないsubset manifest/rootを作り、各hostの接続・入力・出力・重みを事前確認する必要がある。
- ubuntu-2では既存 `colorstats-issue66-retry.service` を継続。2026-11-04 10:45 UTCの確認でactive/running、manifest processed=1,184、elapsed=15,585.4秒、GPU RTX 4070・VRAM 3,441 MiB。3,713件のmanifest行中、先行20件は成功済み。これまでの速度から残り約2,529行を約9時間15分と見積もり、完了見込みは約20:10 UTC（11/05 05:10 JST）。共有負荷と失敗・再試行で変動する。
- ubuntu-1はRTX 4060・driver 595.99・CUDA対応torch 2.11.0+cu128が既存gpucheck venvで動く。ただしそのvenvにはNumPyがなく、既存アプリvenvにはtorchがない。Issue #66用work rootはなく、`/mnt/data/derived` のNFS mountだけが確認できる。ホスト上の既存DB URLを表示せずREAD ONLY疎通を試したが、アプリvenvで成功を確認できなかった。検索した既存環境からSAM2/DINO重みも確認できず、処理用環境として参加させる条件を満たさない。pilot serviceは再開していない。
- Windowsメイン機のRTX 4070 SUPER・driver 617.42は認識され、WSL2 Ubuntu-24.04からもGPUが見える。Windowsの既存venvにはtorchがなく、WSL2からはworktreeは見えるが `/mnt/data/derived` と再処理rootがなく、worker用DB認証経路・モデル重みも確認できない。追加workerは起動していない。
- よって現時点の安全な参加hostはubuntu-2のみ。別hostへ分担するには、各hostから秘密を移さずDBへ接続する既存認証/peer経路と、モデル重み・固定derived入力・個別output rootの到達性を整える必要がある。OS設定・driver・systemd以外のシステム設定や認証情報の移送は行っていない。
- 状態確認：`systemctl show colorstats-issue66-retry.service -p ActiveState -p SubState -p Result -p ExecMainStatus --no-pager` と `tail -n 20 /mnt/data/work/issue-66/retry-3713.log`。停止は `sudo systemctl stop colorstats-issue66-retry.service`。今回、稼働中unitは停止・再起動せず、既存成功run/データへの変更もない。


## 2026-11-04 Ubuntu-1参加・分担worker開始

前節は開始前の評価時点の記録である。今回、Ubuntu-1の実行環境を整備し、Ubuntu-1/2の別root・別manifestで再処理を開始した。旧 `colorstats-issue66-retry.service` は境界停止済みで再起動していない。停止時点で旧retry rootの完了1,357件、未処理2,356件（境界でsegment pendingの1件を含む）を確認した。過去の成功3,890件とprep失敗4件は対象外。旧rootと成功記録は保持する。

### 実行環境・参加可否

- Ubuntu-1: RTX 4060/driver 595.99/CUDA対応torch 2.11.0。`/opt/colorstats/work/issue66-20261104` にコードとvenvを用意し、lockに従い `uv sync --frozen --no-dev --extra gpu` を実施。モデル49ファイル（808 MiB）を共有元からローカルへコピーし、全ファイルSHA-256一致を確認した。入力prepは共有 `/mnt/data/derived` から読み、成果物も同じ共有領域へ保存する。DB認証は既存のowner-only `/var/lib/colorstats/pilot/database.json` を `ops.deploy.launch` 経由で再利用し、秘密を移送・表示していない。既存pilot unitは起動していない。
- Windows/WSL2: RTX 4070 SUPERがWSL2から見えることは確認した。一方、WSL2には `/mnt/data/derived` のマウントがなく、現在のNFS exportはWSL2から利用できず、worker用のDB認証経路もない。入力成果物の複製や秘密の転送で補わず、Windows workerは起動しない。参加には共有ストレージ経路と秘密を移さないDB接続経路の整備が必要。
- Ubuntu-1の初回unitはjournaldの代わりにNFS上のログファイルを開こうとして `209/STDOUT` で失敗した。asset claim前に失敗したことをjournalで確認し、NFSログを使わないjournald出力のunitへ切り替えた。

### 分割・実行状態

旧retry manifest 3,713件のうち、旧rootで完了した1,357件を除き、境界の未完了1件と後続2,356件から、3件のUbuntu-1 smoke対象を除いた2,353件を再分割した。Ubuntu-1 941件、Ubuntu-2 1,412件でasset IDは互いに重複しない。両manifestのimplementation設定は元と一致し、全入力ファイル存在を確認した。smoke対象は別rootで既に完了しており、full manifestには含めていない。

| Worker | 件数 | manifest SHA-256 | Smoke report |
| --- | ---: | --- | --- |
| Ubuntu-1 | 941 | `69a23e08968e32f2d9714ed3efea45a9b3070a67566f2352560470eaf108be8f` | completed 3 / pending 938 / violations 0 |
| Ubuntu-2 | 1,412 | `3153bc517764615b72e59d864880ed6f5c7b20bf8cde321d2da4241758f30fb5` | completed 3 / pending 1,409 / violations 0 |

Smoke資産はUbuntu-1で `5f6b89cc-6ca8-4d45-ac3c-cf5b8cb65ea9`, `5f6bc038-1ba9-4164-8465-fa3841505d4b`, `5f8c04a2-1512-4174-9614-74d14d7d012e` を処理した（旧境界asset `5f68c2d7-6cbc-4c24-a65d-f678509a5972` はfull manifestへ）。Ubuntu-2ではfull manifest先頭3件を処理した。各host reportのviolationsは空。実行開始はUbuntu-1 2026-11-04 11:36 UTC、Ubuntu-2 11:39 UTC。

Unitは `colorstats-issue66-u1.service`（Ubuntu-1）と `colorstats-issue66-u2.service`（Ubuntu-2）。開始確認時点で両方active/running。Ubuntu-2開始前のGPUは17 MiB、0%。Ubuntu-1は開始前10 MiB、0%。各rootは `/mnt/data/derived/issue66-workers-20261104/ubuntu1-full-20261104` と `ubuntu2-full-20261104`。ログはjournaldに記録する。進捗確認は `sudo journalctl -u <unit> -n 30 --no-pager` と、各hostのrunnerで一意な新規 `report --root <root> --output <新規report.json>` を実行する。Ubuntu-1は `/opt/colorstats/work/issue66-20261104/.venv/bin/python ops/deploy/launch.py -m ops.deploy.m3_analysis report ...`、Ubuntu-2は `sudo env PYTHONPATH=src:. /mnt/data/work/issue-40/venv/bin/python /mnt/data/work/issue-66/peer.py report ...` を使う。停止は各hostで `sudo systemctl stop <unit>`。stage境界を待って正常停止し、旧unitは再開しない。

### 今後の分担手順と完了後集計

1. `ops/deploy/README.md` と `docs/storage-sharing.md` を確認し、各hostのCUDA/依存、model SHA-256、prep入力のread、共有出力のwrite、DB認証経路を起動前に検証する。Ubuntu-1ではlockからvenvを構築し、Ubuntu-2のmodel file hash一覧とコピー後をSHA-256で照合する。秘密をホスト間転送しない。
2. 稼働中workerをstage境界で正常停止し、完了後reportを別名出力する。READ ONLY transactionで対象batchの成功・pending・failed、run/attemptを照会し、成功済みIDを再処理対象から除外する。元manifestとimplementation設定を検査し、残りIDを重複しないsubset manifest/rootへ分割する。入力path存在、subset間のID非重複、成功済みIDとの非重複、implementation一致を起動前にassertする。各rootに同一manifestを複数hostから渡さない。
3. 各hostで独立rootのrunnerをjournald付きsystemd transient unitとして起動し、数件処理後にreport violations=0を確認して継続する。GPUが他作業で使用中なら起動しない。Ubuntu-1は `launch.py` の既存認証、Ubuntu-2は `peer.py` の既存peer認証を使う。
4. 終了後に全subsetのreportと元batchをREAD ONLYで照合し、成功・失敗・除外理由、attempt/retry、run時間、stage時間、出力hash/bytes、DB表/index差、WAL、I/O byte、経過時間とGPU利用を集計する。重複asset、report違反、未処理assetが残る場合は完了扱いにしない。Issue完成条件と公開文面はこの集計結果を反映してから更新する。

開始時の処理速度（Ubuntu-1 smoke 3件、Ubuntu-2 full 3件と既存Ubuntu-2計測）による暫定見込みは約5〜6時間、2026-11-04 17:00 UTC前後。初期化、失敗・再試行、GPU競合で変動するため、進捗から再計算する。全量完了は未確認。


2026-11-04 11:42 UTCの追跡確認ではUbuntu-1が18/941件、Ubuntu-2が12/1,412件を処理中で、両unitともactive/running。最新journalに連続したprocessed記録があり、異常終了は確認していない。この時点の速度からの完了見込みは概ね16:45〜17:00 UTC（11/05 01:45〜02:00 JST）。途中経過であり完了・最終reportは未確認。


## 2026-11-05 分担再処理・全量集計の最終結果

### 完成条件と件数の照合

| 範囲 | 対象/成功 | 失敗・未処理 | 判定 |
| --- | ---: | ---: | --- |
| 収集asset / prep | 7,607 / 成功7,603 | prep失敗4 | 達成。理由はDecompressionBombError 2、UnidentifiedImageError 1、math domain error 1を維持 |
| segment（prep成功分） | 7,603 | 0 | 達成 |
| shade（prep成功分） | 7,603 | 0 | 達成 |
| 部位color・共起 | 7,601 | color失敗2 | 件数・理由を記録。全件成功という意味での完了は未達 |
| 全stage成功 | 7,601 / 7,603 | 2 | 部位観測・関係・由来・権利のreport違反0 |

元のproduction-v2 reportはsegment成功3,890・失敗3,713。失敗segment cohortの3,713件は、旧retry root完了1,357件、Ubuntu-1 smoke 3件、Ubuntu-1 full 941件、Ubuntu-2 full 1,412件で全件を照合した（1,357 + 3 + 941 + 1,412 = 3,713）。前回の未説明差3件はsmoke専用rootに分けた3件であり、欠落ではない。full subset合計2,353件にsmoke 3件を加えた2,356件は旧retry root停止時の未完了2,356件と一致する。旧retry rootのpending 2,356は旧batch内の未claim記録として残るが、対象は新規batch manifestで再処理済みである。旧rootは書き換えていない。

再処理後もcolor失敗したassetは `c854f77f-007d-40d4-b375-d5325c43ed62` と `d1a9c1b3-27d3-4b62-8a0d-2d4629dc5179`。両者は同一prep画像SHA-256 `95c401846fe6d58fb7683b4d54b8080fda157f47d377e4e9ff4dab13c8f2f1d7` を持つ。各assetの61部位中1部位でmask面積4,410画素に対し、alpha・黒・白の除外後の有効色画素が0だった。color抽出はこの条件をValueErrorとして扱う仕様であり、各jobは同一理由で3 attempt後にfailed。入力画像全体には139,680/196,608画素の有効色があり、asset全体の入力破損ではない。成功した再実行で解消する種類ではないため再実行せず、失敗理由を保持する。

5つのreport（production-v2、retry-3713、Ubuntu-1 full/smoke、Ubuntu-2 full）は各々DBのREPEATABLE READ READ ONLY transactionで生成。各reportの `violations=[]`、`unclosed_attempts=0`。全stageの成功ID集合をbatch間でunionして7,603件と照合し、segment/shade各7,603、color 7,601、全3stage成功7,601となった。処理中attemptは残っていない。run/artifact hash、部位観測件数、関係件数と符号、run由来・license照合も違反0。

report JSONは次に保持されている。`/mnt/data/work/issue-66/production-v2/final-report-20261105.json`、`/mnt/data/work/issue-66/retry-3713/final-report-20261105.json`、共有領域 `/mnt/data/derived/issue66-workers-20261104/{ubuntu1-final-report.json,ubuntu1-smoke-final-report.json,ubuntu2-final-report.json}`。全量reportは診断・計測用で、DB更新は行っていない。

### 実測時間・容量

| batch / host | elapsed秒 | 完了/manifest | GPU平均 | VRAM最大MiB | process rchar/wchar byte | process read_bytes/write_bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| production-v2 | 91,848.624 | 3,890/7,607 | 13.087% | 6,539 | 32,008,162,460,135 / 3,009,237,957 | 20,193,280 / 2,979,356,672 |
| 旧retry root | 18,136.512 | 1,357/3,713 | 23.049% | 5,891 | 3,417,702,011,052 / 1,005,782,565 | 2,981,888 / 960,761,856 |
| Ubuntu-1 full | 17,561.481 | 941/941 | 33.698% | 5,358 | 2,391,844,984,831 / 721,715,581 | 187,023,360 / 744,640,512 |
| Ubuntu-1 smoke | 78.199 | 3/3 | 21.077% | 3,042 | 6,960,874,252 / 8,284,739 | 218,738,688 / 8,728,576 |
| Ubuntu-2 full | 18,913.036 | 1,410/1,412 | 23.263% | 6,567 | 3,588,930,101,659 / 1,078,990,351 | 679,936 / 1,017,516,032 |

Ubuntu-1 unitは2026-11-04 11:36:38〜16:29:21 UTC、Result=success/exit 0、CPU time 5h30m11.616s。Ubuntu-2は11:39:32〜16:54:46 UTC、Result=success/exit 0、CPU time 8h06m10.482s。2 host full unit期間のうち最大側は5h15m14s。単独処理の完了数はUbuntu-1 941、Ubuntu-2 1,410（color失敗2を除く）。

成功runの累積stage時間はsegment 62,349.181秒、shade 9,582.486秒、color 22,546.377秒（合計94,478.044秒）。成功artifact出力byteはsegment 1,146,051,363、shade 632,633,337、color 2,766,263,507、合計4,544,948,207 byte。color失敗attempt時間は旧retry root 5.440秒、Ubuntu-2 full 7.991秒。Ubuntu-2 fullは1,412 segment + 1,412 shade + 1,416 color attempt = 4,240開始・終了、colorの2 jobが各3 attempts（追加retry計4回）。

DB snapshotのdatabase byte差/WAL byte差は、production-v2が2回分 `(1,437,843,456 / 11,380,229,680; 8,200,192 / 16,649,832)`、旧retry rootが2回分 `(7,684,096 / 88,996,832; 478,183,424 / 5,274,295,760)`、Ubuntu-1 full `(830,365,696 / 8,338,453,728)`、smoke `(1,073,152 / 15,517,688)`、Ubuntu-2 full `(867,909,632 / 8,783,235,904)`。table/indexごとの差は各report JSON内に記録した。これらのsnapshotは `includes_concurrent_writes=true` で、特にUbuntu-1/2 fullは同時実行中のDB書込みを含むため合算値をIssue増分容量とは扱わない。process I/Oのrchar/wcharとread_bytes/write_bytesは別指標である。

### 終了状態と検証

- `colorstats-issue66-u1.service`: inactive/dead, Result=success, ExecMainCode=0, ExecMainStatus=0。journal末尾はprocessed=941とDeactivated successfully。
- `colorstats-issue66-u2.service`: inactive/dead, Result=success, ExecMainCode=0, ExecMainStatus=0。journal末尾はprocessed=1,412とDeactivated successfully。
- Ubuntu-1 pilotは未起動。unit再起動・再実行なし。4 prep失敗と2 color失敗を成功・回復として数えていない。
- ruff: `All checks passed!`。pytest: **434 passed, 153 skipped**。Matplotlibあり・なしの関連テスト各1 passed。package build: wheel生成成功。

保存済みattempt snapshotを再集計し、process I/O表を訂正した。旧処理はPIDごとの最大値を足していたため、親が終了子のI/Oを取り込んだ後にも子の値を重複計上していた。各snapshotで親と稼働中の子を合算し、合計の最大値から初回値を引いた。attempt記録から再計算でき、元のrun/artifact/attempt記録は保持した。
