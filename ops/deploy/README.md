# M1パイロットの配備

Issue #27。ubuntu-1で単一のcollectとprep/colorを動かし、ubuntu-2にDBとderivedを置く。
既存のuv.lock、Alembic、層別計画器、Queue/Worker、prep/color、網羅率集計を使用する。
追加のPython依存はない。systemdをプロセス管理に使い、`pilot.py`は既存APIをつなぐ投入・実測だけを担当する。
実行結果と実際の配備版は[実行記録](../../docs/pilot-m1.md)を参照。
停止・再配置・fstab変更は、実施を許可された作業枠で以下の手順に従う。

## 固定版とDB

1. 対象のコード・設定・taxonomy・`uv.lock`・`pyproject.toml`・`alembic.ini`を、
   `/opt/colorstats/releases/<版>/`に展開する。アーカイブのSHA-256と基準commitを記録する。
   未コミット修正を含む場合はcommit版と呼ばずスナップショットとする。
2. 初回は`uv run alembic upgrade head --sql`で0001〜0005のSQLを生成し、空のDBを確認してから
   ubuntu-2で`sudo -u postgres psql -v ON_ERROR_STOP=1 -d colorstats -f <SQL>`を実行する。
   既存DBは`alembic_version`を確認し、例えば0003なら
   `uv run alembic upgrade 0003:head --sql`で未適用分だけを生成する。
   適用後は0005を確認する。0005は既存jobに再取得可能時刻を追加し、既存ジョブはすぐ取得できる。
   ワーカーはmigrationと権限付与の完了後に新版へ切り替える。
   既存の`colorstats_worker`がある場合は、同じDB所有者で
   `sudo -u postgres psql -v ON_ERROR_STOP=1 -1 -d colorstats -f <版>/ops/deploy/worker_grants.sql`
   を実行する。0004の`asset_duplicate`を含む全表へ既存と同じDML権限を付与し、
   `alembic_version`は読取りだけに戻す。今後もmigration後にはこのSQLで権限をそろえる。
   default privilegesは使わない。SQL生成・転送・適用もコマンド記録を残す。
3. ubuntu-1で`bash <版>/ops/deploy/install.sh <版の絶対パス>`を実行する。
   uv 0.13.6、Python 3.12、`uv sync --frozen --no-dev`を使う。
   媒体ルートだけをtoumokorosiへ委譲し、既存ファイルの所有権や内容には触れない。
   サービスはまだ起動しない。
4. 初回だけ`credentials.py`がubuntu-1内でランダムなパスワードとSCRAM-SHA-256検証子を生成する。
   `/var/lib/colorstats/pilot/database.json`（mode 600）を他ホストへ転送・表示しない。
   同ディレクトリの`worker.scram`だけをubuntu-2へ転送し、
   `python3 <版>/ops/deploy/worker_role.py <検証子ファイル>`でロールを作る。
   新設時も同梱の`worker_grants.sql`で同じ権限を付与する。
   既存ロールや認証ファイルは上書きしない。再配備は既存の所有者専用ファイルを利用する。
5. ubuntu-2のpg_hba.confに次の1行を追加し、`SELECT pg_reload_conf()`で反映する。
   `host colorstats colorstats_worker 192.168.1.85/32 scram-sha-256`
   平文パスワードをコマンド引数・SQL・ログへ出さない。
   `launch.py`は所有者専用ファイルから読み、子プロセスの環境だけへ渡す。

## derivedの共有

stageとQueueはローカルの同一ファイルシステム内で一時ファイルと不変出力をrenameする。
共有マウントのない環境では、配備担当の承認を得てから`derived-server.sh`をubuntu-2、
`derived-client.sh`をubuntu-1で実行する。既存のファイル契約・保存パスは変更しない。
NFSのexportはubuntu-1のIPだけ、root_squash・同期書込みとする。
fstabに`_netdev,nofail`付きで登録し、サーバー停止時にもubuntu-1の起動を妨げない。
共有が未整備でもcollect/schedulerは実行できる。schedulerはマウント確認後だけ解析を投入し、
analysisはマウント条件で起動を拒否する。ローカルの空ディレクトリへ代替出力しない。

### NFS断時の待機と復帰

Issue #42でsoft化しない方針を確定した。配備案も現行の
`vers=4.2,proto=tcp,rw,hard,timeo=600,retrans=2,nosuid,nodev,_netdev,nofail`へ揃える。
hardはRPCを再試行し続けるため、`timeo`・`retrans`はI/O全体の待機上限にならない。
`_netdev,nofail`も稼働中I/Oの待機を制限しない。
本番のumount・fstab変更を断試験に使わない。
隔離試験の結果と復旧手順は[共有方式と実機記録](../../docs/storage-sharing.md)を参照する。

2026-11-02の再配置では、3サービスの明示停止・kill後の自動再起動、欠損ファイルがある状態での
scheduler継続を実機確認した。NFSのhard→soft変更は自動権限審査で拒否され、
既存のhard・`_netdev,nofail`を維持している。その後の隔離試験は上記Issue #42の記録を参照する。
現在は3サービスとも停止フラグを残して停止している。詳細は[最終記録](../../docs/pilot-m1.md)を参照。

## 実行と停止

Issue #44では総予算を10,000枚、ソース上限を80%に保ち、Commonsだけで既存画像を含む
8,000枚まで収集する。Openverseは使用しない。層の`images`は画像配分の目標で、
合計10,000枚（835枚×8層、830枚×4層）。層内ソース枠は668枚×8層、664枚×4層で
合計8,000枚になる。作者5%・地域40%・subject最大3枚と0.3%の上限は変更しない。
層内の作者・ソース枠は`images`、未指定の場合は従来の`subjects`を母数とする。
実測占有率と目標を母数にした採用上限は別であり、初期標本の占有率超過も監視する。

subject未同定画像は画像予算・画像目標・作者・ソース・既知地域の枠に数える。
検索は各言語の先頭ページを必ず含め、残りのページを無作為に選ぶ。
Commonsは対応するラスタ画像を`filetype:bitmap`で絞り、実際の検索式をrunへ記録する。
初期監査で絵画の混入を確認したため、タイトルの`canvas`・`painting`も検索から除く。
これは実写真の分類を保証しない。層別件数は検索意図の集計であり、実分類と区別する。
既知の混入は`asset.quality.collection_review`へ要確認理由を記録し、画像予算に含めて保全する。
この絞込みは[CirrusSearchの既存機能](https://www.mediawiki.org/wiki/Help:CirrusSearch#filetype)を使い、
メタデータ取得後のMIME・権利確認も維持する。
計画順は予約を含む画像不足率で決め、`subjects`とsubject網羅率は同定済み件数だけを
数える。画像数をsubject数へ換算しない。空属性の旧prep生成subjectはタイトル一致だけでは
再同定しない。画像目標に達してもsubject同定完了を意味しない。

目標変更時は3サービスを停止して設定・seed・reportを別名で保全する。
旧設定の保留collectがある間は旧targetsを維持し、新コードのcollectだけで消化してから
停止する。保留が0であることをDBで確認後、新targetsを配置し、seedを0へ戻す。
成功・失敗ジョブは初期化しない。解析版は同じなら既存値を維持する。
全8,000枚が収集できない場合は層別ソース枠・作者枠・探索終了などの停止理由を記録し、
集中枠を緩めない。8,000枚到達後もprep/colorの残件処理は継続できる。

以下の予算1,000枚はM1時点の運用記録である。

rawをGPUノードへ渡す配備案は[共有方式と実機記録](../../docs/storage-sharing.md)を参照する。
`raw-replica.py`は監視確認付きのstage、SHA-256確認後のpublish、容量確認、保持削除を行う。
ubuntu-2の`/mnt/data/raw-cache`へ150GB上限で本番配備済み。
手動運用の手順は[raw事前複製の本番運用](#raw事前複製の本番運用)を参照する。

`/var/lib/colorstats/pilot/targets.yaml`は配備時点の収集目標のコピー。
予算1,000、集中枠は既存値のまま。Openverse応答を既存アダプターで確認し、
応答しない場合はCommonsのみで実行して記録する。稼働中にbias設定を書き換えない。
Commonsのみではsource_share=0.8によって800 asset行が上限になる。
層のsubject目標に先に達すれば、その層はそこで止まる。
検索で意図した属性は確定分類と区別し、レポートの不明群も保持する。

```sh
sudo systemctl start colorstats-pilot-collect colorstats-pilot-analysis colorstats-pilot-scheduler
systemctl status colorstats-pilot-collect colorstats-pilot-analysis colorstats-pilot-scheduler
```

collectは全ホストを通して1ワーカーだけにする。analysisはprep/colorを1スロットで処理する。
`pilot.py --run`は60秒ごとに後続stageを投入し、`report.json`を更新する。
collectが空になった時だけseed 0〜19で計画器を呼び、不足層を探索する。
seedの次番号は`seed.json`に保持する。検索対象が少ない場合も20探索で止まり、無制限には増やさない。
既に同じseedで完了したページの継続を調べる場合は既存`bias_cli plan --seed <番号>`を使う。
各stageの設定ハッシュに入力・配備版を含め、再起動で成功/失敗を初期化しない。
解析実装・設定が同じ再配備は`install.sh <新しい版の絶対パス> <既存の解析版>`を使う。
これによりschedulerの`--analysis-version`を固定し、既存の解析ジョブを再生成しない。
colorには成功prepの`run.output_paths`と入力run IDを渡す。

通常停止は`systemctl stop colorstats-pilot-<stage>`。
`stop.py`が生存中のMAINPIDを確認してからフラグを作り、ジョブ返却と終了を待つ。
異常終了後はsystemdがMAINPIDを渡さないため、フラグを作らず`Restart=on-failure`で再起動する。
空のMAINPIDも正常に処理する（[systemdのExecStop仕様](https://www.freedesktop.org/software/systemd/man/255/systemd.service.html#ExecStop=)）。
緊急時は`/var/lib/colorstats/pilot/{collect,analysis,scheduler}.stop`を作る。
停止・プロセス終了を確認してから、再開するstageの専用フラグだけを削除し、サービスをstartする。
killや停電で返却できなければ、10分リース失効後に対応stageが回収する。中断も最大3試行に含まれる。

単発集計は、配備先で次を実行する。停止フラグは解除してから使う。

```sh
.venv/bin/python ops/deploy/launch.py ops/deploy/pilot.py \
  --root /opt/colorstats/releases/<版> --state /var/lib/colorstats/pilot --version <版>
```

容量は成功runが参照するファイルの合計で、失敗・中断後の未参照ファイルは含まない。
`stages.seconds`は成功試行の取得から完了までの合計で、再試行待ちを含む経過時間とは異なる。
原本はcollect、縮小JPEGはprep、色JSONはcolorに分ける。
`database_bytes`はDB全体、`table_bytes`はpublicのテーブル・索引・TOASTの合計。
空の適用直後との差分とasset数から1枚あたりの容量を求める。
rawの件数は検索機会ごとのasset数とユニークSHA-256数を併記する。
未参照ファイルの清掃は本パイロットで行わない。

欠損・I/Oエラーはstageごとの`file_errors`（pathと例外名）に記録し、`capacity_complete=false`にする。
`bytes`は読めた参照ファイルだけの合計、`files`は参照パス数なので、容量不足をゼロ容量と解釈しない。
ファイル集計が失敗してもレポートを保存し、次周期の投入を続ける。
欠損rawはassetのURL・SHA-256とsourceの権利情報を確認して一時パスに再取得し、ハッシュ一致後に参照先を復旧する。
取得不能なら欠損として記録を残す。derivedはraw復旧後、新しい解析版を明示してprep/colorを再投入する。
成功runと既存ジョブを初期化せず、不変参照を上書きしない。旧版だけが参照する欠損は履歴として残す。

## raw事前複製の本番運用

ユーザー判断（2026-11-02、#42）に基づく手動配備。原本の正本はubuntu-1。
両ホストの固定スナップショットは`/opt/colorstats/releases/raw-replica-cd70dda-20261102a/`。
基準`cd70dda`と未コミット修正を含み、既存releaseの差替えやcurrent切替はしていない。
ubuntu-2の同releaseに次の新規`raw-cache.json`を配置した。

```json
{"root":"/mnt/data/raw-cache","max_bytes":150000000000}
```

`staging/<バッチ名>`へ転送し、`batches/<バッチ名>`へ公開する。
150GBは10進byteで、staging・公開済み・付属ファイルを含む論理容量の上限。
追加依存・systemd・exports・fstab設定は不要。パイロットは停止状態を維持する。
以下のコマンドは監査付きSSH、転送は`run_logged.py`経由で実行する。
転送・公開・投入・削除は単一担当が直列に実施し、既存バッチ名を再利用しない。

1. DBを読取り専用取引で参照し、必要なassetだけを選ぶ。`asset.id/sha256/storage_path/license_class`と、
   そのstorage_pathを`output_paths`に含む成功済みcollectのjob/run（finished_atあり、failure_reasonなし）を照合する。
   由来JSONは次の形でcache外の運用記録へ保存する。同じ原本の複数assetも全て記録する。

   ```json
   {"files":[{"asset_id":"<UUID>","source_run_id":"<collect run UUID>",
   "source_stage":"collect","input_run_id":null,"sha256":"<64桁SHA>",
   "source":"/srv/colorstats/raw-orico/<不変パス>.jpg","license_class":"open"}]}
   ```

2. ubuntu-1で既存の配備Pythonと媒体監視実装を使い、新規の転送専用ディレクトリへstageする。
   次は今回確認した配備環境の例。由来JSONのsourceと原本引数を一致させる。

   ```sh
   release=/opt/colorstats/releases/raw-replica-cd70dda-20261102a
   PYTHONDONTWRITEBYTECODE=1 \
   PYTHONPATH=/opt/colorstats/releases/b2a7241-issue37-20261102/src \
   /opt/colorstats/releases/cf166b9-06a615d-issue27-20261102f/.venv/bin/python \
     "$release/raw-replica.py" stage --provenance <由来JSON> \
     --destination <新規転送ディレクトリ> <原本パス>...
   ```

   媒体停止・SHA不一致・由来不一致は投入前の保留とする。不完全なstageは転送しない。
   manifestの各画像には元パス・SHA・byteと`origins`（assetとcollect runの由来）が入る。

3. manifestを含めた転送元ディレクトリの全ファイル容量を求め、ubuntu-2で事前判定する。

   ```sh
   release=/opt/colorstats/releases/raw-replica-cd70dda-20261102a
   python3 "$release/raw-replica.py" capacity --config "$release/raw-cache.json" \
     --incoming-bytes <転送する全byte数>
   ```

   失敗時は転送を保留する。既存のstagingも容量に含むため、再転送時に二重に見積もらない。
   これはfilesystem quota・容量予約ではない。他の転送を並行実行しない。
   成功後、Windows上に画像を保存せず、登録済み接続先間を記録付きSCPで転送する。

   ```sh
   scp -3 -r -o BatchMode=yes -o ConnectTimeout=15 \
     -o ServerAliveInterval=15 -o ServerAliveCountMax=2 \
     toumokorosi@192.168.1.85:<新規転送ディレクトリ> \
     toumokorosi@192.168.1.86:/mnt/data/raw-cache/staging/<新規バッチ名>
   ```

4. ubuntu-2で公開し、cache計上を確認する。

   ```sh
   python3 "$release/raw-replica.py" publish --config "$release/raw-cache.json" \
     --staging /mnt/data/raw-cache/staging/<バッチ名> \
     --destination /mnt/data/raw-cache/batches/<バッチ名>
   python3 "$release/raw-replica.py" capacity --config "$release/raw-cache.json"
   ```

   公開時も全cache容量・SHA・byteを確認し、同一filesystem内のrenameで公開する。
   過容量・破損時はstagingを保全し、公開・投入を保留する。別バッチの自動削除はしない。

5. **本番投入は今回実行していない。** 今後の投入時は、公開manifestをDBと再照合し、
   segmentのasset_idに対応する原本のローカルパスを`payload.input_path`へ渡す。
   `license_class`はassetの値を維持し、`input_run_id`は省略またはnullにする。
   prep以外のrunをprep専用の入力runへ流用しない。
   `payload.raw_origin`に`asset_id/source_run_id/sha256/source/manifest_sha256`を記録してから
   既存`segment.config_hash(payload)`で計算・enqueueする。
   payload全体は既存の成功runの`parameters.payload`へ保存されるため、DB形式変更は不要。
   公開manifestと、バッチに予定した全GPU stage・全job IDの投入計画をcache外へ保全する。
   後続stageを追加した場合も計画を更新し、削除判定から漏らさない。

6. 全GPU stage成功後にだけ削除する。新規投入・読取り開始を止め、投入計画の全jobが
   `succeeded`で成功runを持つことを読取り専用DB照合で確認する。
   実行中・再試行待ち・手動処理を含め公開パスの参照がないことを確認し、完了JSONをcache外に保存する。

   ```json
   {"batch":"<バッチ名>","manifest_sha256":"<公開manifestのSHA>",
   "expected_gpu_jobs":["<投入計画の全job UUID>"],
   "gpu_jobs":[{"job_id":"<同じUUID>","status":"succeeded"}],"references":[]}
   ```

   `expected_gpu_jobs`は保全した投入計画の全件と照合し、成功した一部だけに縮めない。
   `gpu_jobs`は同じ全件の最新状態とし、未成功・件数不足・重複・参照ありではpruneが拒否する。
   参照有無やDB状態をツールが自動取得するわけではなく、運用者の証跡を検証する。
   照合後も削除終了まで新規参照を開始しない。由来manifest・計画・完了JSONはcache外に残す。

   ```sh
   python3 "$release/raw-replica.py" prune --config "$release/raw-cache.json" \
     --destination /mnt/data/raw-cache/batches/<バッチ名> --completion <完了JSON>
   ```

   日数・容量逼迫だけでは未成功・参照中の公開バッチを削除しない。
   `.lock`が残ったときは転送・操作PID・参照停止を確認してから空のlockディレクトリだけを手動解除する。

本番で5枚のSHA・読取り・容量計上・模擬GPU成功による保持削除を確認した。
確認用公開バッチは削除済みで、cache計上は0 byte。証跡はubuntu-2の
`/mnt/data/work/issue-42/production-check-2-proof/`。
配置のSHA・確認結果・監査ログは[本番配置の記録](../../docs/storage-sharing.md#本番配置と確認2026-11-02)を参照する。
本番DBへの書込み、GPU推論、パイロット起動は行っていない。

## 次回再配置の確認順序

1. この修正版と#30を含む固定スナップショットを作り、停止を許可された作業枠で旧3サービスの終了を確認する。
2. #30の`ops/storage/`・`ops/backup/`の手順に従って監視設定・サービスを更新する。
   `/etc/colorstats-storage/disks.json`のraw指定・UUID・mountと停止記録を確認する。
   新版collect/prepは異常媒体・欠落・readonly中に取得を止め、処理中は試行数を消費せず保留する。
3. 現行NFS設定と読戻しを確認し、`install.sh <新版> <既存の解析版>`で3サービスを更新する。
   新版キューを使い、prep/colorに`--storage-path ...=/mnt/data/derived`があることを確認する。
   解析ロジックを変更する場合だけ新しい解析版を選ぶ。
4. 停止理由と媒体復旧を確認して対象の停止フラグだけを解除し、1 collect・1解析スロットで再開する。
   journalとレポートで保留中に試行数が増えないこと、復旧後の再取得・解析、障害後の自動再起動を確認する。
   容量欠損記録とM1最終件数・全件解析・実測値を保存する。
