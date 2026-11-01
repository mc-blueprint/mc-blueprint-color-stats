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
2. `uv run alembic upgrade head --sql`で0001〜0003のSQLを生成し、空のDBを確認してから
   ubuntu-2で`sudo -u postgres psql -v ON_ERROR_STOP=1 -d colorstats -f <SQL>`を実行する。
   既に適用済みなら再実行せず`alembic_version`を確認する。SQL生成・転送・適用もコマンド記録を残す。
3. ubuntu-1で`bash <版>/ops/deploy/install.sh <版の絶対パス>`を実行する。
   uv 0.13.6、Python 3.12、`uv sync --frozen --no-dev`を使う。
   媒体ルートだけをtoumokorosiへ委譲し、既存ファイルの所有権や内容には触れない。
   サービスはまだ起動しない。
4. 初回だけ`credentials.py`がubuntu-1内でランダムなパスワードとSCRAM-SHA-256検証子を生成する。
   `/var/lib/colorstats/pilot/database.json`（mode 600）を他ホストへ転送・表示しない。
   同ディレクトリの`worker.scram`だけをubuntu-2へ転送し、
   `python3 <版>/ops/deploy/worker_role.py <検証子ファイル>`でロールを作る。
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

### NFSの待機制限（次回配備から）

hard mountはRPCを無期限に再試行するため、次回配備では再生成可能なderivedだけを
`vers=4.2,proto=tcp,rw,soft,timeo=50,retrans=2,nosuid,nodev,_netdev,nofail`にする。
既存のNFSクライアント機能を使い、schedulerのstatと親ワーカーのrenameもI/Oエラーで戻す方式を選んだ。
`timeo=50`は5秒、`retrans=2`は再送回数で、処理全体や停止全体の秒数保証ではない。
softのタイムアウトはEIOを返す一方、データ破損の可能性があるため、DB・raw・正解データには適用しない。
仕様は[nfs(5)](https://man7.org/linux/man-pages/man5/nfs.5.html)を参照。

既存のhard設定は`derived-client.sh`が自動置換せず終了する。再配置の作業枠で解析とschedulerを停止し、
NFS利用プロセスが終了したことを確認して通常のumountを行う。既存fstabのderived行だけを上記オプションへ
更新し、daemon-reload・mount後に`findmnt`でsoft/timeo/retransと共有元を確認する。
強制umountや取得済みデータの削除はしない。

再開前に書込み・rename・読戻しを確認する。障害試験は本番サーバーを止めず、隔離したNFS共有で断線を模擬し、
stat/公開がエラーへ戻ること、停止フラグへの応答、成功runの未確定、リース失効後の回収と復旧後の再開を記録する。
今回の自動テストはEIOと保存先停止の模擬検証までで、NFS断・復帰の実機試験は次回配備時に行う。

2026-11-02の再配置では、3サービスの明示停止・kill後の自動再起動、欠損ファイルがある状態での
scheduler継続を実機確認した。NFSのhard→soft変更は自動権限審査で拒否され、
既存のhard・`_netdev,nofail`を維持している。soft設定の適用と隔離NFSでの断・復帰試験は未実施。
現在は3サービスとも停止フラグを残して停止している。詳細は[最終記録](../../docs/pilot-m1.md)を参照。

## 実行と停止

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

## 次回再配置の確認順序

1. この修正版と#30を含む固定スナップショットを作り、停止を許可された作業枠で旧3サービスの終了を確認する。
2. #30の`ops/storage/`・`ops/backup/`の手順に従って監視設定・サービスを更新する。
   `/etc/colorstats-storage/disks.json`のraw指定・UUID・mountと停止記録を確認する。
   新版collect/prepは異常媒体・欠落・readonly中に取得を止め、処理中は試行数を消費せず保留する。
3. 上記のNFS設定変更と読戻しを完了し、`install.sh <新版> <既存の解析版>`で3サービスを更新する。
   新版キューを使い、prep/colorに`--storage-path ...=/mnt/data/derived`があることを確認する。
   解析ロジックを変更する場合だけ新しい解析版を選ぶ。
4. 停止理由と媒体復旧を確認して対象の停止フラグだけを解除し、1 collect・1解析スロットで再開する。
   journalとレポートで保留中に試行数が増えないこと、復旧後の再取得・解析、障害後の自動再起動を確認する。
   容量欠損記録とM1最終件数・全件解析・実測値を保存する。
