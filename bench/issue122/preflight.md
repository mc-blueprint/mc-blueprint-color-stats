# #122 本番準備・実行・保全の記録

2026-11-09、本番DB接続先をubuntu-2に訂正した引継ぎに基づき、完全バックアップを取得した。
担当ブランチはfeature/issue-122、起点はf160796a84789b6a6071b2603839e13b7ba3bb0c。

最終状態は、両GPU全量・全件監査・地形限定snapshot/統計/旧版比較・保全照合まで完了。
supported 0・条件4 failedのためM4採用は保留し、人確認等の未達条件は[result.md](result.md)へ記載した。
以下は初回停止から再開・終結までの時系列記録である。

## 完了した確認

- 保存先はubuntu-2の`/mnt/data/work/issue-122/backup-20261109T0049Z/`。
- `before.dump`はpg_dumpのcustom形式によるDB全体のバックアップ。776,185,462 bytes。
- SHA-256は`eb7558b9a5399e6a61ed1640e5a99138fa09f1d665da0a6d1545d195f3af7c5b`。保存済みchecksumによる再照合成功。
- `pg_restore --list`成功。TOCは`before.dump.list`に保存し、164行。
- DB revisionは取得前・取得後ともに`0009`。migrationは未実行。
- 保存ディレクトリは700、dump・TOC・checksum・revision記録は600。
- バックアップと権限確認は2026-11-09 00:50〜00:51 UTCに完了。

## 初回停止の確認（配置により解消）

ubuntu-1の既存`/opt/colorstats/work/issue129-v2-r8-20261108/`と担当ブランチには、
改行を正規化しても解析コードのhash差がある。既存配置を本タスクの同一実装として使用できる状態は未確認。

| ファイル | 既存配置のLF正規化SHA-256 | 担当ブランチのLF正規化SHA-256 |
| --- | --- | --- |
| `src/colorstats/analyze/region_policy.py` | `9dc847bc7ac5a21452af6479053e099c4b5e5f82c30814d6baf695ce37764e1c` | `11ae495905505228ee3f8442b06a20d1dc09e142d78dbd23d2a5e4b69c78a244` |
| `src/colorstats/analyze/segment.py` | `092c750abfc54c4de797cb851ddafe881c6b2da05c3035a4435061586cd11a75` | `b0e3ae6a2ff1cc50409d10d472487b84e2e90e802f662b6389c3288f53436f05` |
| `src/colorstats/analyze/color.py` | `26c1f4c175af5ec9817d7c32b6d7264ca84bce1904f433397cccb529abf9d9ce` | `edfa6e90cabbbdce7edd7c5a8ef31fec626f008ef5fa1c9ee38a572a624890cd` |
| `ops/deploy/m3_analysis.py` | `359202a29688ce3fbf895e08208d94d3c0cd697ca329df9aabb06cd8d588e953` | `2768e09c611b61d462a7f7cc6ca44476e391e6e56362c206ae9e28beb6fa290a` |

担当ブランチには建物改善の別methodも追加されている。ファイルhashの不一致だけから、
地形methodの品質変化や#121の不合格を断定しない。固定契約との照合と本タスク用実行版の確定が必要。

## 初回停止時点の残り作業（後続で実行済み）

実行版の確定と配置、旧データの不変照合、両GPU各3件smoke、本番B/C全量、
地形側の新snapshot・rule_stat・report、旧#105 v2比較、WSL隔離DB込み全検証、公開文面の準備。
WindowsからUbuntuへの転送は、後述のユーザー許可の対象・経路・配置先に従う。

## 転送と実行版の固定

2026-11-09のユーザーによるLAN転送許可に基づき、Git管理下のコード・設定・共通契約を転送した。
画像・個別判定・秘密は含めず、既存配置と分離したディレクトリへ保存した。

- 最初の`baseline-r1.tar`はSHA-256 `3552fdeff339f5fd41766bb22eb4c378abcc23a823c85e1937796a1712444bd5`。
  改行のLF変換によりclass-infoのbyte hashとpolicy hashが#121固定値から変わったため、解析には使用していない。
- 修正版`execution-r2.tar`はSHA-256 `8b0946dd848ff221892d746b9482b2423dc9df6a62f35338ea3de32fe7e37200`。
  Git管理下のworktreeのbyte列を保持し、両ホストでarchiveのSHA一致を確認した。
- ubuntu-1の配置は`/opt/colorstats/work/issue122-20261109/execution-r2/`。
- ubuntu-2の配置は`/mnt/data/work/issue-122/code-20261109/execution-r2/`。
- 両ホストでDINO/SAM2/OneFormerの全固定ファイル、parent table、policyを#121と照合して一致した。
  policy hashは`3dad77aa16f42d620dc85cdf2e81586288db93c67154c86a39c68fb1774e65ba`。
- 本番promptは#121が地形評価に使った#73 ADEの固定prompt集合、閾値は0.35/0.25。
  建物改善の別methodは選択していない。

## 初回smokeの停止（後述の再開で解消）

私有計画は`/mnt/data/derived/issue122-20261109/plan.json`に保持する。
旧7,607件は重複なし、#129の旧7,626件の部分集合であり、新2,600件との交差は0。

| 状態 | 件数 |
| --- | ---: |
| v2採用・prep成功による解析候補 | 3,912 |
| v2保留 | 2,495 |
| v2除外 | 1,196 |
| 既存prep失敗 | 4 |
| 固定分母 | 7,607 |

候補はubuntu-1へ1,564件、ubuntu-2へ2,348件に重複なく分割した。
この候補数を地形統計の適格数・成功数とは扱わない。

各3件のsmokeを開始したが、次の予期しないファイルアクセス失敗により全量へ進んでいない。

- ubuntu-1は、DBに記録された既存prep画像の読取りがPermissionErrorとなり、job作成前に停止した。
- ubuntu-2は、segment 1件が成功した後、人物reviewが原画像を再検証する段階で、
  DBの`storage_path`が指す`/srv/colorstats/raw-orico/`配下の画像が存在せずFileNotFoundErrorとなった。
- 新規jobはsegment成功1件だけ。人物review・shade・colorの完了は0件。
  3件smoke成功・全量成功を報告できる状態ではない。
- unitは`colorstats-i122-u1-smoke-r2.service`と`colorstats-i122-u2-smoke-r2.service`。
  両方の停止を確認した。最終状態はfailed、ExecMainStatus=1。GPU計算プロセスは両ホストで0件。
- 既存データのアクセス権・配置・サービスを変更していない。pilotの再起動、有料API、復元も行っていない。

担当分すべての原画像・prepの読取りとSHAをjob作成前に確認するガードをworktreeへ追加した。
このガードはsmokeで使ったexecution-r2には含まれない。再開時は固定実行版と計画の扱いを再確認する。
両ホストの原画像・prep・maskへの到達性と権限を満たす構成が再開の前提となる。

## 停止後の保全照合

| 表 | 処理前の行数 | 変更・欠落 |
| --- | ---: | ---: |
| asset | 10,226 | 0 |
| subject | 919 | 0 |
| subject_candidate | 3,595 | 0 |
| source | 6,194 | 0 |
| processing_run | 75,323 | 0 |
| rule_stat | 2,845 | 0 |

新2,600件を含む全asset行の不変を確認した。既存の人物保留993件も変更していない。
DB revisionは停止後も0009。旧snapshotはcanonical manifest hashと全ParquetファイルのSHAを照合した。
GPU環境にduckdbがないため、Parquetの行数再読取りは行っていない。

- M3のsnapshot IDは`3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702`。
- #104のsnapshot IDは`e60bc14c7076a405b75333d1a0b280d9b088534796bdc4fedec0fbdebe414471`。
- #105 v2のsnapshot IDは`a8384373192d930df952190433d5d346393549b87c941ef157ea93380c714864`。

新しいsnapshot・rule_stat・reportと旧#105 v2比較は未生成。建物側は未集計。
既存snapshot・alias・配色パックへは反映していない。

## worktreeの検証と引継ぎ

- WSL Ubuntu-24.04/root・隔離PostgreSQL16で全pytestは1,423 passed・1 skipped。
  検証時間311.01秒、ruff・sdist/wheel build成功。隔離DBは正常停止した。
- 追加の原画像/prep欠落の回帰テストは2 passed。追加テストと専用コードのruffも成功。
  この2件は上記の全pytest実行がコードを退避した後に追加したため、別実行として記録する。
- skipは公式重み・CUDA・専用テストDBの明示指定を要する既存領域GPUテスト。
  今回の本番smoke失敗をこのskipやpytest成功で補完したとは扱わない。
- 検証出力はWSLの`/var/tmp/colorstats-issue122-l3b7iN/`。
- `git grep -i`で今回の公開準備差分を検査し、Windows/Macユーザー名の一致0。
- commit文・PRタイトル・本文を準備した。Issue完成条件が残るため本文はRefs #122。
  commit・push・PR作成は未実行。

再開後は固定計画・実行版・担当範囲を照合し、両ホストの全担当入力の到達性を確認してから
各3件smoke、本番全量、地形限定の品質採用処理と統計生成、旧#105 v2比較へ進む。
smoke失敗時の計画・成功segment・バックアップ・旧版は保持する。

## 2026-11-09 再開時の構成と実行版

ユーザーの「転送に許可を求めないで」に基づき、登録済みUbuntu間のLAN転送を実施した。
既存NFSのroot-squashにより、ubuntu-1のrootは匿名UIDとなり、UID 1000・mode 700の旧prepを読めなかった。
原画像の正本はubuntu-1のローカル媒体にあり、ubuntu-2にはDB記録の絶対パスが存在しなかった。

既存`raw-replica.py`のstageを再利用し、成功collectの出力パス・媒体監視・SHAを照合して
旧候補3,912件の原画像を#122専用領域へ複製した。旧prepも3,912件分を複製し、保持台帳へ登録した。
原画像・prep全件のコピーSHAと保持条件を再確認した。

- 専用コピーは`/mnt/data/derived/issue122-20261109/media-r3/root/`。
- 一時unit内だけで、その下の`srv/colorstats`を`/srv/colorstats`へ、
  `mnt/data/derived/pilot-m1`を`/mnt/data/derived/pilot-m1`へ読取り専用bindする。
- 元の媒体・画像・prepの所有者とmode、共有設定、OSユーザー・グループは変更していない。
  新規の専用コピー領域だけを既存NFS匿名UID 65534に揃えた。
- コピーの保持台帳上の物理hostはubuntu-2。コピー・元データは削除していない。
- 後続の照合・統計生成でも同じ一時unitの読取り専用bindが必要となる。

全3,912件の旧prepは`max_size`と`phash_distance`だけを保存し、`input_sha256`を保存していなかった。
既知の旧設定に限り原画像からJPEGを再生成し、固定prep出力SHAとの完全一致を検証する処理を追加した。
原画像パス・取得画像SHA・新maskの照合を継続し、旧run・旧パラメータは書き換えていない。

再開版archiveは`execution-r5.tar`、SHA-256
`0ce9495e8355a9b63f75f927a87a710df2cdefaa9b690e068222129b4345c0b9`。両ホストで一致を確認した。
配置は各ホストの既述の専用転送先下の`execution-r5/`。

| 固定対象 | SHA-256 |
| --- | --- |
| 計画全体 | `475fc50acdbcbf564691c94166539a0193fc65a338f2f5fc2812cd07b281a77c` |
| 再開実装の全体hash | `9b2de6d2f29364091442e51546738b74067222a6127f57233fc8f38b200b277b` |
| #129 v2の計画全体 | `0b3f3eda9df068b02ee0b1f9be46634daa53230b0a1666daf20cd9e06abf5429` |

再開実装の固定は`execution-r5.json`に保存した。旧`plan.json`と以前の実行版は保持した。
計画固定時刻は2026-11-09 01:04:55 UTC。

両ホストの再開smokeは各3件が終結し、有効role/person maskと成功shade/colorの入力hashを照合した。
各hostともsegment成功3、人物reviewの採用2・保留1、shade/color成功各2、失敗・未終結0。
人物の画像根拠と画素根拠の不一致は保留した。

全量unitは2026-11-09 01:55 UTCに開始した。

- ubuntu-1は`colorstats-i122-u1-full-r5.service`、InvocationID `7c0c15cf6b0749e1b59b23781c5db270`。
- ubuntu-2は`colorstats-i122-u2-full-r5.service`、InvocationID `866ccefb4ec9456eb14958b4e73c873d`。
- 各rootの`progress.json`と`records.json`を保全する。監視はunit状態・件数を3分間隔で確認する。
- 2026-11-09 02:23 UTC時点でubuntu-1は68/1,564件、ubuntu-2は92/2,348件が終結し、両unitはactive。
  この時点では全量未完了であり、統計・旧版比較は未生成。

実際の新segment各3件のモデル・policy・promptを地形品質の固定契約と照合して一致した。
新しい地形3件からsnapshotを作るdry-runも成功した。追加API要求は行っていない。
現行worktreeの統計側には、水・tree親群に限る採用、欠測色の除外、人物承認失効の登録時再確認を実装した。
この統計側の追加差分はGPU全量の固定実行版とは分けて検証し、統計生成前に別archiveへ固定する。

統計側は`statistics-r6.tar`へ固定し、両ホストでSHA-256
`38f4a96476555a94d3a08c20bf6c8190537c138e78be75c4aea356dd767647a9`の一致を確認した。
実際の地形3件を使ったsnapshot→aggregate→reportの接続検証も成功した。
これは診断専用の私有artifactで、DBへの統計登録は0件。
水・tree親群だけの18統計行を生成でき、欠測色を除いた有効groupは3件だった。
本番の固定7,607件の訂正版snapshotとは区別する。

統計側の現行差分の全検証はWSL Ubuntu-24.04/root・隔離PostgreSQL16で
**1,439 passed・1 skipped**（312.97秒）、ruff・sdist/wheel build成功。
隔離DBは正常停止した。検証出力は`/var/tmp/colorstats-issue122-G7tCBX/`。
skipは既述の明示GPU環境を要する既存テストであり、本番runの成否とは別に記録する。

## 全量終結と実行版の内訳

2026-11-09 13:25 UTCまでに両ホストの全量unitが正常終了した。
両unitの`Result=success`・`ExecMainStatus=0`・inactiveと、GPU子プロセスの終了を確認した。
本番DBは引き続きrevision `0009`。完全バックアップのSHAも再照合して一致した。

| ホスト | segment成功 | 人物採用 | 人物保留 | shade成功 | color成功 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ubuntu-1 | 1,564 | 1,490 | 74 | 1,490 | 1,490 |
| ubuntu-2 | 2,348 | 2,258 | 90 | 2,258 | 2,258 |
| 合計 | 3,912 | 3,748 | 164 | 3,748 | 3,748 |

segmentの内訳はr5の3,911件と、再開前の成功smokeから引き継いだ1件。
後者のrunに残るcode_versionは`issue122-issue122-terrain-v1`であり、r5と同じ版名とは扱わない。
保存済みr2〜r5のB依存ソース58ファイルを照合し、全件で同一SHAを確認した。
共通依存ファイル表のdigestは`6ae338dfe227692ff03064845057664ee80c0c5f1f7108963bf74f19b9105910`。
旧固定実行証跡はr4のimplementation hash
`959d35a91ba2042b64c200e7679cb39e69c7f0874fae69361522ea90f6163c13`と一致した。
差分は人物reviewと統計側であり、引継ぎrunの固定入力・モデル・prompt・policyも#121の契約と一致した。
個別runの照合表は私有領域の`reused-segment-audit.json`へ保存した。

最終job照合では現行stageの失敗・未終結は0件。
構成修正前に中断した旧smokeの待機job 1件は、対象IDとbatch・版・出力先を限定して
既存Queueの`claim`・`fail(retryable=False)`で廃止した。旧run・ファイルは変更していない。
廃止前後は`obsolete-job-retired.json`、最終内訳は`job-audit-final.json`へ私有保存した。

ubuntu-1の全件監査は成功し、segment・有効mask 1,564件、採用分のshade/color各1,490件、
人物保留74件、失敗・未終結0件を照合した。監査所要時間は39分41秒。
ubuntu-2の全件監査も成功し、segment・有効mask 2,348件、採用分のshade/color各2,258件、
人物保留90件、失敗・未終結0件を照合した。監査所要時間は35分44秒。

固定selectionの内訳は地形候補1,547、建物未集計2,194、人物保留164、v2保留2,495、
v2除外1,196、旧prep失敗4、人確認の新参照待ち7、計7,607件。
人確認の新参照待ちは採用へ変換せず、#114の移管前処理へ残す。
地形統計の別版生成も正常終了した。統計unitの所要時間は1時間31分38秒、CPU時間は1時間13分48秒。
新snapshotは`d53765a48d4b20ed77dbf393c04dad33a2601e5996c9718b44778c5e38448f58`。
18統計行はすべてunsupported、supported 0・条件4 failedであり、M4採用は保留する。
最終保全照合では、新run 15,321件が旧固定集合内の解析とaggregateだけに属し、新2,600 cohortへの追加0件を確認した。
旧M3・#104・#105 v2のmanifest・全Parquet SHAも一致した。
集計値・旧版比較・未達条件は[result.md](result.md)、公開準備文面は`commit.txt`・`pr-title.txt`・`pr-body.md`にまとめた。
commit・push・PR作成・main・releaseへの操作は行っていない。

## reviewer指摘後の修正・検証

固定人確認一覧のraw SHA照合、未完成snapshotの別試行先での再生成、prepの検証後rename、
rawの試行別stage・未完成出力保全を追加した。既存のsnapshot・raw-replicaの検証契約は維持する。
回帰5件は修正前に5 failed、修正後に5 passed。
全pytestは1,444 passed・1 skipped、ruff・sdist/wheel build成功（266.81秒）。
WSLは`Ubuntu-24.04`・隔離PostgreSQL16を明示し、DBは正常停止した。
失敗確認・個別成功・全検証の出力は順に
`/var/tmp/colorstats-issue122-G6EsG6/`、`/var/tmp/colorstats-issue122-YbZ0x9/`、
`/var/tmp/colorstats-issue122-eZFY8y/`へ保全した。

本番使用一覧は#129の固定raw SHA・固定plan・生成時記録のcanonical SHAと一致した。
保留7件の取り漏れ採用0、媒体manifest・完成snapshotの全SHA一致も確認した。
本番の再生成は不要と判断し、既存結果は変更していない。詳細は[result.md](result.md)の追記を参照する。
修正コードは未デプロイ・未commit・未pushのまま引き継ぐ。
