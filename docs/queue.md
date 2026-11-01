# ジョブとワーカーの契約

Issue #6。PostgreSQL 16、Python 3.12、既存のSQLAlchemy 2・psycopg・PyYAMLを使う。
新規依存・本番への適用はない。revision `0002` を `0001` の後に追加する。

## Procrastinateの調査と選定

2026-11-01に公式stableドキュメントと公式リポジトリのmainを確認した。

| 要件 | 調査結果 |
| --- | --- |
| キュー分割 | taskのqueueとworkerのqueuesで指定できる |
| 再試行 | retryは再試行回数。初回込み3試行なら2を指定する |
| リース・停止検知 | worker heartbeatとstalled jobの検出・手動再投入がある。各ジョブの期限と試行所有権を検査する仕組みとは異なる |
| SKIP LOCKED | fetch関数が `FOR UPDATE OF jobs SKIP LOCKED` を使う |
| Windows・WSL2 | Windowsは公式に動作確認あり、signalには制限。WSL2もLinux上でpsycopgから到達可能なPostgreSQLを使う構成と推定できるが、Procrastinate自体のWSL2実行は未検証 |
| DB取引の共有 | 外部接続での投入・取消・状態取得は可能。調査したfinish関数はjob IDと状態で更新し、試行トークンを条件にしない |

第一候補として適合性を調べたが、今回の採用は見送る。問題はキュー分割や接続性ではなく、
リース失効後の旧試行が採用済み出力・結果登録・完了を変更することを防ぐ境界にある。
Procrastinateを使っても別の所有権付きjob行が必要になり、二つのキュー状態と再試行回数を
同期することになる。今回はこの不足に対する一つのjob行と短いSQLAlchemy取引に限定する。
取得・再試行はこの所有権の状態遷移として扱い、汎用スケジューラ・独自接続プール・通知機構は
追加しない。SQLロック・一意制約・取引は既存PostgreSQL/SQLAlchemy、プロセス管理とrenameは
Python標準機能を使う。

ProcrastinateはMIT、Python 3.10以上で、公式リポジトリには更新が続いている。
Python 3.12・SQLAlchemy 2との互換性やライセンスが不採用の理由ではない。
採用すると別途スキーマとworker heartbeat・stalled再投入の運用が必要になる。

一次情報:

- [workerとキュー](https://procrastinate.readthedocs.io/en/stable/howto/basics/worker.html)
- [再試行](https://procrastinate.readthedocs.io/en/stable/howto/advanced/retry.html)
- [停止検知と再投入](https://github.com/procrastinate-org/procrastinate/blob/main/docs/howto/production/retry_stalled_jobs.md)
- [取得・完了関数と一意制約](https://github.com/procrastinate-org/procrastinate/blob/main/procrastinate/sql/schema.sql)
- [外部接続](https://procrastinate.readthedocs.io/en/stable/howto/production/external_connection.html)
- [Windows](https://procrastinate.readthedocs.io/en/stable/howto/basics/windows.html)
- [依存と対応Python](https://github.com/procrastinate-org/procrastinate/blob/main/pyproject.toml)
- [ライセンス](https://github.com/procrastinate-org/procrastinate/blob/main/LICENSE.md)

## 実行単位と状態

`job` のキーは `(stage, asset_id, stage_config_hash)`。
`UNIQUE NULLS NOT DISTINCT` によりNULLのassetも重複しない。
stageはcollect・prep・segment・shade・color・review・aggregate。
assetが未確定のcollect、全体集計のaggregateではassetをNULLにし、
対象のソースページ・検索条件・統計バージョンなども含めて設定ハッシュを作る。
同じ設定で別対象を処理するときは対象もハッシュに含める。
ハッシュの正規化・生成は各stageの責務。

`Queue.enqueue(stage, asset_id, config_hash, payload)` は同じキーのIDを返す。
既存payloadと異なる投入はValueError。成功・failedを再投入で初期化しない。
payloadはJSON辞書で、秘密情報を保存しない。
結果の再計算は設定・コード版を含む新しいハッシュを使う。

`Queue.claim(stages)` はpendingまたは期限切れrunningをSKIP LOCKEDで取得し、
新しいUUIDトークンを払い出す。DB時計を基準に10分のリースを設定する。
取得時に試行数を増やす。通常失敗、計算プロセス異常終了、停止フラグによる中断、
リース期限切れは1失敗と数え、3試行で理由付きfailedとなる。
期限切れは次の対応stageのclaimで回収するため、そのstageのワーカーが最低1台必要。
通常失敗の直後はpendingへ戻り、追加の待機・バックオフは設けない。
pendingは`available_at`がDB時計の現在時刻以下の場合だけ取得する。

`Queue.renew(claim)` と `fail(claim, reason)` はトークンと期限を検査し、
権利を失った試行にはLeaseLostを返す。リースはworkerが期間の約1/3ごとに更新する。
Jobのfailure_reasonは直近の失敗理由を保持し、後の成功時も履歴として残る。
成功runのfailure_reasonはNULL。失敗試行にはprocessing_runや解析結果を作らない。
例外文は保存されるため、stageの例外にも認証情報を含めない。

### 保存先の異常による保留（Issue #30）

Linuxのcollect/prepワーカーは `/etc/colorstats-storage/disks.json` のraw媒体を
取得前・計算中・完了前に確認する。UUIDデバイスの欠落、mountの欠落・取り違え、
readonly、`/var/lib/colorstats-storage/blocked/<UUID>` の存在時は該当stageを取得しない。
他のstageは取得を続ける。監視設定がない開発環境ではrawの自動確認は行わない。

raw以外の保存先は、ワーカー起動時に `--storage-path STAGE=/絶対パス` を繰り返して
入出力rootを指定する。欠落したディレクトリ・readonlyを同じ間隔で確認する。
Pythonからは `Worker(..., storage_paths={"prep": (Path("/srv/colorstats/derived"),)})` を使う。
例えばNFSのderivedを使うprep/colorには両stageを指定する。パスは各ホストで到達できる
既存rootを指定し、共有mount自体の状態は配置側でも監視する。

取得済みの計算中に異常を検出すると子プロセスを終了して `Queue.defer(claim, reason)` で
pendingへ戻し、今回の試行数を1減らす。EROFS・ENODEV・ESTALE・EIOは子のerrnoを親へ伝え、
監視記録の作成より先に書込みが失敗した場合も保留する。完了ファイル公開時の同じ例外も対象。
deferは既存のトークンと期限を検査し、旧試行はLeaseLostとなる。
Issue #35のrevision `0005`でjobに`available_at`（タイムゾーン付き・非NULL）を追加する。
新規・既存ジョブの初期値はDBの現在時刻。deferはこれをDB時計の30秒後に設定する。
待機中のpendingはclaimから除外し、作成日時が後のprep/colorなどを取得できるようにする。
保存先を復旧してもこの待機は短縮しない。異常が続く場合も各保留後に30秒待ち、試行数は消費しない。
既存のPostgreSQL日時列とSQLAlchemyの取得条件で対応し、依存追加や別のスケジューラは使わない。
通常失敗・手動stop-file・リース切れの既存契約は維持する。DBへ返せなかった場合はリース切れで
回収されるため、その場合まで試行数を返したことにはならない。

監視の停止記録は自動解除しない。原因確認、UUID/mount照合、手動rw復旧と監視再実行を行い、
管理者が対象UUIDのblockedファイルを除去すると、稼働中の対応ワーカーが取得を再開する。
監視状態には取得失敗時の `error` とSMARTの `smart_exit` が加わる。旧形式の正常値も読める。
配置済みの監視だけでは既に起動中の旧ワーカーコードは変わらないため、新版ワーカーの配置・起動を
別途そろえる。#27の稼働中パイロットをこの作業で停止・再起動してはならない。

## 結果確定の境界

`Queue.complete(claim, info, register, files)` の順序:

1. 短い読取り取引で成功済みなら既存run IDを返し、他試行のトークンを拒否する。
2. DB取引の外で、出力名と同じ親ディレクトリに `.output-<試行トークン>-<UUID>` を新規作成する。
   一時ファイルをその中の出力名へ `Path.replace` する。公開ごとに新しいディレクトリを作り、再利用しない。
3. job行をロックし、現在のトークン・期限を検査する。
4. processing_runを作り、`output_paths` に出力名→実際の不変パスの辞書を保存する。
   `register(session, run)` で結果を登録する。
5. runの終了日時、jobのrun_idとsucceededを同じ取引でcommitする。

成功したrunはjobと1対1。再試行で作った未commitのrunはロールバックされる。
runの開始日時は成功した試行の取得時刻。必要な入力runの由来はregisterが
processing_run_inputへ保存する。モデル・重み・ライセンスなどはRunInfoで渡す。
registerは与えられたSessionだけを使い、commit、外部送信、ファイル操作を行わない。
ファイル参照列へは `run.output_paths[str(target)]` を登録する。`target` 自体には書き込まない。
後続処理も成功runの参照を使用する。公開したファイルは呼出し元も変更しない。

公開前の確認後に旧試行が停止しても、その再開は固有パスだけに書き込み、
新試行が採用したファイルを上書きできない。参照の採用とregisterは行ロックで直列化する。
最終取引の所有権確認後に接続を失った試行はcommitできない。
registerは短く保ち、時間のかかる計算や画像書込みは取引前に終える。

ファイルとDBは分散取引にしない。rename後の停止・DB失敗・複数ファイルの途中失敗は
未参照ファイルを残しうる。DB成功が正本で、存在だけで成功判定しない。
再試行も別の不変パスを作る。一時ファイルと出力名は同じ親・同じファイルシステムに置く。
清掃は運用側が該当stageの全ワーカーを停止し、停止した旧プロセスも終了した後に行う。
全成功runのoutput_pathsと結果列が参照するファイルを保持し、未参照の専用ディレクトリと
一時ファイルだけを削除する。稼働中の一括削除や経過時間だけによる削除は行わない。

全Queue取引に `statement_timeout` と `idle_in_transaction_session_timeout` を
`set_config(..., true)` で取引単位に設定する。既定はそれぞれ5秒、`Queue(timeout=秒数)` で変更可能。
SQL・ロック待ちは前者、取引中に親が停止した場合は後者で取引を中断し、行ロックを解放する。
タイムアウトは取引全体の実行時間上限ではない。registerはDB登録だけに限定する。
取引が失敗した場合は結果も参照もrollbackされ、対応stageのワーカーがリース期限後のclaimで回収する。
DB再起動も同じ回収手順を使う。プールは切断された接続を破棄する。
詳細は[PostgreSQL 16の接続設定](https://www.postgresql.org/docs/16/runtime-config-client.html)を参照。

## stageの接続と起動

stageモジュールは次の二つを実装する。

- `prepare(claim) -> Prepared`: 子プロセスで計算。一時ファイルだけを書き、DBや確定先を変更しない。
- `register(session, run, data)`: 親プロセスの完了取引内でDB結果を登録する。

PreparedはRunInfo、pickle可能な小さいdata、`[(temporary_path, target_path)]` を保持する。

例外として#9の専用ハンドラー`colorstats.collect.bias`だけは、取得前の集中枠を
複数ワーカー間で確保するためprepareから専用予約テーブルへ書き込む。
予約はjobのリーストークンと結び付け、失敗・トークン変更・期限切れ後は次の採否/計画で回収する。
完了中のjobは行ロックで回収から除外し、成功時は結果登録と同じ取引で予約を確定する。
通信・確定ファイルへの書込みはこの例外に含めない。詳細は[偏り制御](collection-bias.md)を参照。

target_pathは出力の識別名で、実際の保存先はregister時のrun.output_pathsから取得する。
画像本体・モデルはpipeへ流さず、ファイル参照を返す。
モデル初期化もprepare側で行う。並列数はワーカープロセス数で調整する。
実際のstage処理は後続Issueで追加する。

```sh
uv run alembic upgrade head
# DATABASE_URLは認証情報をログへ残さない方法で環境へ渡す
uv run python -m colorstats.queue --handler prep=colorstats.analyze.prep --stop-file /tmp/prep.stop
```

上のprepモジュール名は後続実装の接続例で、現時点では同梱していない。
`--handler` は繰り返し指定可能。`--once` は最大1件処理して終了する。
Windowsでも同じCLIを使える。stop-fileを作ると新規取得を止め、計算子プロセスを終了し、
その終了後に、有効なリースのジョブを理由付きpending（3試行目ならfailed）へ戻す。
フラグは自動削除しない。再開時は運用側が削除する。
フラグ確認は通常0.2秒ごと。検知時はDB応答を待たず計算子をterminateし、
1秒で終了しなければkillして最大1秒待つ。DB返却はdaemonスレッドで開始し、親は最大2秒だけ待つ。
返却失敗・応答停止では終了を優先し、リース失効後に他ワーカーが回収する。
残った返却スレッドが遅れて応答を受けても所有権検査により新試行を変更しない。
最終取引中は短いDB登録の終了または取引タイムアウトで確定し、計算子は終了処理する。
強制終了・ノード断もリース切れ後に引き継ぐ。接続・通信断の時間はDB側タイムアウトとは別なので、
接続URLにconnect_timeout、運用環境にTCPの通信断検知も設定する。
WSL2では到達可能なDBのIP・DNS名を使い、接続タイムアウトを設定する。
本番DBの準備と接続設定は#4で管理する。

## 論理保存先

`Storage(Path("configs/storage.yaml")).resolve(logical_path)` はLocation(host, path)を返す。
#3の `storage.raw` 配列とderived/models/work/backupのhost/path辞書をそのまま読む。
rawのUUID・serialは保持された設定の運用メタデータであり、ここでは媒体確認やmountをしない。

`raw/<sha256先頭2桁>/<sha256>.<ext>` はSHA-256の整数値 mod raw配列長で振り分ける。
設定配列の順序や媒体数を変えると既存rawの解決先も変わるため、再配置・参照確認が必要。
resolveが返す出力名は設定rootの直下の `<先頭2桁>/<sha256>.<ext>`。
Queue.complete経由の実ファイルはその親に作る
固有ディレクトリ内に置く。asset.storage_pathなどへは採用されたrun.output_pathsの値を保存する。
WindowsのworkはPureWindowsPath、それ以外はPurePosixPath。
`location.local_path(host)` はhost一致時だけローカルPathを返す。
リモート転送・共有マウントは行わず、データへ到達できるノードにワーカーを配置する。
`temporary_path(target, str(claim.token))` で試行固有の一時ファイルを作れる。

## 検証

CIの `TEST_DATABASE_URL` を使う `tests/test_queue.py` は、ランダム名の専用schemaに
Alembic headを適用し、終了時にそのschemaだけを削除する。
リース切れ・旧試行の拒否、並行再投入、3失敗、DBロールバック後の再試行、SKIP LOCKED、
停止フラグによる計算中断と別ワーカーの成功、同時完了、計算中のリース更新を確認する。
公開直前に停止した旧試行の再開、取引アイドル・SQL待機の上限後のロック解放と引継ぎ、
DB返却が停止しても計算子を先に終了して親が上限内に戻ることも確認する。
既存のschemaテストで0002を含む適用・巻戻し・再適用・metadata差分なしも確認する。
保存先は#3の形式をfixtureにして、Windows/Linuxパスとraw振り分けを単体テストする。
