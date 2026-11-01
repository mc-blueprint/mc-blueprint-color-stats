# M1パイロット実行記録（収集終了）

Issue [#27](https://github.com/rs0325/mc-blueprint-color-stats/issues/27)。2026-11-01実施。
**2026-11-02 04:36 JSTに755枚で収集を終了。prep/colorは754枚成功、SVG 1枚は失敗理由を記録済み。1,000枚と各層100 subjectは未達。**
2026-11-01のユーザー承認に基づきderivedをNFS共有し、12:32:06 UTCにanalysisを開始した。
以下の中間数値・継続手順は履歴として保持する。確定値と現在の停止状態は末尾の「最終集計・新版配置」を参照する。
Minecraft 200枚は対象外。Windows/WSLは実データの処理に参加せず、一時DBテストにだけ使用した。

## 配備と実機変更

- worktree: `worktrees/issue-27/mc-blueprint-color-stats`、branch: `feature/issue-27`。
  引継ぎ基準は`origin/develop cf166b9`。未コミット修正を含む固定スナップショットを配備した。
  commit・push・PR作成は行っていない。
- ubuntu-2: 空の`colorstats`に既存Alembic 0001〜0003を適用し、`alembic_version=0003`を確認。
  専用`colorstats_worker`はLOGIN、非superuser、DB/role作成不可。
  publicのDMLとDB接続・schema使用だけを許可し、`alembic_version`の更新権限は除外した。
  pg_hbaに`host colorstats colorstats_worker 192.168.1.85/32 scram-sha-256`を追記してreload。
  サーバー再起動は行っていない。
- ubuntu-1: Python 3.12.3、uv 0.13.6、既存`uv.lock`の固定依存を専用venvへ導入。
  `/var/lib/colorstats/pilot`はmode 700、`database.json`は所有者toumokorosi・mode 600。
  パスワードは同ホスト内で生成し、ubuntu-2へはSCRAM-SHA-256検証子だけを渡した。
  接続時に`current_user=colorstats_worker`とrevision 0003を確認した。
- rawは`/srv/colorstats/raw-orico`と`raw-suneast`の既存rw mountを使用。
  書込みのため媒体ルートだけをtoumokorosi所有へ変更。既存ファイル・lost+foundの変更/削除なし。
- systemdに`colorstats-pilot-{collect,analysis,scheduler}.service`を配備。
  collectとschedulerは起動、analysisは未起動。自動起動のenableはしていない。
  source_policy・レート制限は変更していない。再起動・netplan/fstab変更・媒体初期化なし。

12:21 UTC時点のunit配置先は`/opt/colorstats/releases/cf166b9-issue27-20261101d`。
collectは起動時のb版プロセスを中断せず継続し、schedulerはd版。b/dのstage実装は同一。
次のcollect起動はunitに設定したd版を使う。旧版と投入済みjobの参照先は保持している。

| スナップショット | 配布tar.gzのSHA-256 | 用途 |
| --- | --- | --- |
| `cf166b9-issue27-20261101a` | `365a47a2025a8554f1a9bf9605156726eb1bd32331ca4bf5cfb7f1f970d5c7b8` | 初回投入・停止再開確認 |
| `cf166b9-issue27-20261101b` | `abd8e357ecff427fd6a4da5209574677dc39abeed442551262b53d1286ef8220` | 容量レポート修正・停止制御 |
| `cf166b9-issue27-20261101c` | `7ff3d6d8dff17a7bab94295979338968ae9c5eddcf415cdf4083bed3618a1b99` | 共有待ちでも収集・集計を継続 |
| `cf166b9-issue27-20261101d` | `082a895263312b4b7d37b101eb99fa05b305ecf96a56a85cf487340752ba2ebf` | 最終検証版。容量集計はcurrent_schemaを使用 |
| `cf166b9-issue27-20261101e` | `cb963925a16cceb75db955948051d42f2124d9e6490b632fb3ef9835efbaf98d` | 12層・層内集中枠・SVG除外・Commons混雑時再試行 |

## 計画とソース

`configs/collection_targets.yaml`を`/var/lib/colorstats/pilot/targets.yaml`へコピー。
予算1,000、subject上限3、作者枠5%、ソース枠80%、地域枠40%を維持。
層はjapanese-castle、gothic-temple、forest-autumn-day、目標は各100 subject。
初回は既存計画器のseed=0で18 collect jobを投入。
schedulerはcollectが空になった時だけseed 0〜19で計画し、次seedを`seed.json`に保存する。
この探索上限・層目標・集中枠で停止した場合は、1,000未達とその理由を追記する。
Commonsのみでは800 assetがソース枠の上限になる。枠は緩めない。

Openverseの既存アダプターによる1件検索は、2026-11-01 12:09〜12:10 UTCに
`TimeoutError: The read operation timed out`となった。同じホストでCommons検索は成功したため、
Issueの許可に従いCommonsのみで進めた。禁止ソースの取得はしていない。

## 停止・再開

2026-11-01 12:12:11 UTC、実行中job `75374097-9091-46e6-b93f-131350f13fb3`
（attempt=1）にcollect.stopを渡した。サービスは正常終了し、jobはpending、
最終理由は「停止フラグによる中断」。フラグ解除後のstartで同じjobがattempt=2となり成功した。
この確認は`/var/lib/colorstats/pilot/pause.json`にも記録した。

配備切替でもフラグで返却し、成功済みjobや失敗回数は初期化しなかった。
job `24a93cb3-455b-44e2-9e83-7fa85a4a72c6`は3試行上限でfailed、
最終理由は「停止フラグによる中断」。過去の個々の失敗理由は既存契約上上書きされるため、
この理由だけから全3試行の原因を断定しない。再試行上限を回避する再投入・状態変更はしていない。

## 中間レポート

以下は**12:16:03 UTC（21:16:03 JST）のスナップショット**。
正本の自動更新JSONはubuntu-1の`/var/lib/colorstats/pilot/report.json`。
処理中のため下記は最終件数ではない。検索で意図した層の属性と、画像の確定分類は区別する。

| 層 | asset | subject/目標 | 作者 | ソース | 最大作者比 | エントロピー bit | subject不明 | 作者不明 | 地域不明 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| japanese-castle | 4 | 0/100 | 4 | 1 | 25% | 2.0 | 4（100%） | 0 | 0 |
| gothic-temple | 4 | 0/100 | 4 | 1 | 25% | 2.0 | 4（100%） | 0 | 0 |
| forest-autumn-day | 3 | 0/100 | 1 | 1 | 100% | 0.0 | 3（100%） | 0 | 3（100%） |

全体11 asset、未割当0。prep未実行のためsubject網羅率は全層0%、不足各100。
3層とも作者集中フラグtrue。これは層内実測比であり、画像予算1,000に対する作者上限とは異なる。
建築の地域はstratum.region由来で、撮影地点を確定したことを意味しない。

ジョブはcollect succeeded=17、failed=1、pending=17、running=1。
prep/colorは0。最終失敗理由を持つjobは「停止フラグによる中断」2件
（再開成功1件・failed1件）。除外内訳は帰属不足1候補、非対応MIME10候補。
失敗内訳はjobの直近理由であり、全試行の履歴集計ではない。

12:16:45 UTCの追加DB確認では14 asset・ユニークSHA-256=11・source=11。
11 source全件がopenで帰属表示あり。14 asset全件にauthor・attribution・metadataを保持。
assetは検索機会単位なので、同一原本の再取得も別assetとなる。

## 時間と容量（暫定）

12:16:03 UTCの11 assetに対応する成功runの測定。
原本容量は成功runが参照するファイルだけの合計。失敗・中断後の未参照ファイルは含めない。
後の検索で同一内容を再取得した別の実体パスは、それぞれ容量に含む。

| 項目 | 合計 | 1 assetあたり |
| --- | ---: | ---: |
| collect成功試行の処理時間（空ページ含む） | 276.369332秒 | 25.124秒 |
| 原本 | 78,150,686 byte / 11ファイル | 7,104,608 byte |
| 縮小画像 | 未生成 | 未測定 |
| 色JSON | 未生成 | 未測定 |
| DB全体 | 9,174,039 byte | 下記差分で算出 |
| publicテーブル・索引・TOAST | 1,081,344 byte | 下記差分で算出 |

空のmigration適用直後はDB全体8,535,063 byte、public合計442,368 byte。
増分はいずれも638,976 byte、1 assetあたり58,089 byte。
DB増分には検索job・JSONメタデータ・失敗記録も含む。小規模測定なので1,000枚へ単純外挿しない。
処理時間は成功試行の合計で、中断・失敗・待ち時間を含む全経過時間とは異なる。
全件のprep/color完了後に最終値を追記する。

## 修正・検証・反証

- prepが`asset.quality`を上書きして収集時の作者・帰属・ライセンス根拠を消す不具合を修正。
  既存値に解析品質を追記し、実DB回帰テストを追加した。保存形式・公開APIの変更はない。
- 後続投入は成功prepの不変パスとinput_run_idを使い、同じ版の再投入を重複させない。
  実DBテストでprep成功前のcolor未投入・由来・不変パス・再投入を確認した。
- PostgreSQLの容量SUMがDecimalでJSON化に失敗する配備時の不具合を修正。
  整数byteへ変換し、実DBでJSON化できることをテストした。
- 全テストはWindows/Python 3.12.15とWSL Ubuntu-24.04の一時PostgreSQL16.15を使用。
  Windowsで対象外のLinux bashバックアップ転送4テストは、WSLで別途実行して成功。
  最終実行は183件成功・Windows対象外4件、別途WSLの4件も成功（合計187件）。
  DB用テストのスキップはない。colour-scienceの任意Matplotlib未導入警告が1件あり、
  使用する色変換・抽出のテストは成功している。
- ruff check全体、uv build（sdist/wheel）、配備shellのbash -n、実機systemd unitのverifyが成功。
  前任時点ではNFS設定は構文確認のみ。今回の実適用・書込み確認は末尾に記録した。
- 重点確認はprovenance保持、成功前の後続未投入、再投入の冪等性、不変入力、
  専用ロールの実認証、停止時の返却と再開、容量の数値型。再委譲はしていない。

WSLテストDBの全インターフェース待受け案は自動権限審査で拒否されたため、
localhostだけで起動した。初回のSQL_ASCII設定はUTF8の専用DBへ修正。
再実行時に残る空のalembic_versionも考慮し、テストごとに新しい専用DBを作成・終了後削除した。
これらの環境前提で失敗した実行は成功件数に含めていない。

## 前任時点の継続状態と残作業（12:21 UTC）

最終確認12:21:45 UTC（21:21:45 JST）ではcollect PID=4994、scheduler PID=5701がactive/running。
analysisはinactive/dead。サービスは動かしたまま残す。
schedulerは共有マウントがない間も収集計画とレポート更新を続け、解析は投入しない。
最新の自動スナップショットは12:21:20 UTC、20 asset・原本参照20ファイル、
ライブDBのユニークSHA-256は11・sourceも11。
層別assetは8/8/4、subjectはすべて不明で目標未達、作者数4/4/1、地域不明0/0/4。
最大作者比は25%/25%/100%、全層集中フラグtrue。
collectは成功37・失敗1・pending15・running1、次seed=2。
除外は帰属不足1・非対応MIME19。prep/colorは0である。
成功collect時間522.816255秒（26.141秒/asset）、原本124,812,187 byte
（6,240,609 byte/asset）。DB全体9,419,799 byte、public合計1,318,912 byte。
適用直後からのDB増分884,736 byte（44,237 byte/asset）、
public増分876,544 byte（43,827 byte/asset）。すべて中間値であり、最終測定は残作業。
再接続後は次を確認する（SSHは規約どおり記録付きのスクリプト実行を使う）。

```sh
systemctl status colorstats-pilot-collect colorstats-pilot-analysis colorstats-pilot-scheduler
cat /var/lib/colorstats/pilot/report.json
cat /var/lib/colorstats/pilot/seed.json
journalctl -u colorstats-pilot-scheduler -n 20 --no-pager
```

1. NFS設定・fstab登録・書込み確認とanalysis開始は完了（末尾参照）。
2. 稼働中schedulerが次の周回で新規assetのprep、その成功後にcolorを投入する。
3. 収集を継続監視し、予算・層目標・集中枠または探索上限の到達理由を確認。
   20 seedを使い切った未達なら、成功runの継続offset・検索語を確認して追加探索を判断する。
4. 全assetのprep/color成功または失敗理由、重複、主色、最終網羅率・時間・原本/derived/DB容量を集計。
5. この文書の中間値を最終値へ更新し、完成条件を再確認する。
   commit・push・PR作成は今回禁止のため未実施のままとする。

## 主な実行ログ

コマンドと出力はWindowsの`C:/Users/ryuma/.codex/logs/commands/`に保存。
以下は再調査時の入口。実機のサービスログもjournalへ保存される。

- Issue正本確認: `20261101T120150Z-1e97c06247be481a9abe91f513969b77.jsonl`
- 本番migration: `20261101T120623Z-18c78fc3f5c24f33952561692cce8e89.jsonl`
- 専用ロール作成: `20261101T120822Z-7dd3b027701b49f78b1fd7d06e45032a.jsonl`
- 認証・Openverseタイムアウト: `20261101T120912Z-647f157931ec4da285837d9024f12f03.jsonl`
- 初回計画とcollect起動: `20261101T121002Z-7132bd6220f34bd2987843efcdae023b.jsonl`
- 停止/再開: `20261101T121210Z-cb01226110db40dca9a5669e7ef3b919.jsonl`
- c版配備: `20261101T121557Z-26d6525d0ba04075b46ed1d59b14f786.jsonl`
- d版配備: `20261101T122113Z-37452edcc59f4ef0a5d7d3bd86dec30d.jsonl`
- 最終到達点/稼働状態: `20261101T122144Z-df1aabf917bb4233a24c8c5b18b2d99a.jsonl`
- 中間集計/サービス状態: `20261101T121644Z-2a890fd781004a60ae22ddba69740064.jsonl`
- 最終全テスト: `20261101T121954Z-ffe087da4483403eb637c26e74fd9db4.jsonl`
- WSL bash転送4件: `20261101T121013Z-909144a306124ee7b2b5db1c657ae3b4.jsonl`
- 最終ruff/build: `20261101T122037Z-e2389069874d4e22b91544873cfd1167.jsonl`、
  `20261101T122039Z-f4d3f3e4999c48ccaa26b3054b8254db.jsonl`

## 公開用文面案（未公開・実行完了後に更新）

コミットメッセージとPRタイトル:

`feat: M1パイロットの配備と実画像収集を整備する`

コミット本文:

- 固定uv環境・SCRAM専用ロール・systemdの配備と停止手順を追加
- 層別計画からprep/colorへの投入と容量・網羅率の実測を接続
- prepの収集時provenance消失を修正し実DB回帰テストを追加
- 12層へ拡張し層内集中枠・非ラスター除外・Commons混雑時の待機を修正
- パイロットの到達点・実行中サービス・未完了事項を記録

PR本文案（収集継続中で通常PRの完成条件未充足）:

```markdown
## 概要

- M1パイロット用の実機配備・層別収集・後続解析の投入と実測を整備する。
- 収集・prep/colorを継続中。最終到達枚数と全件解析の確認は残作業。

## 変更内容

- ops/deployに固定版導入、専用SCRAMロール、systemd、停止/再開と投入・集計を追加。
- ubuntu-1限定のNFS exportと_netdev/nofail付きfstab登録・書込み確認を追加。
- prepで収集時の作者・帰属・ライセンス根拠を保持するよう修正。
- 層を12層へ増やし、作者/providerの層内上限も適用。SVGを取得前に除外する。
- Commons検索混雑を既存バックオフで再試行し、同じ解析設定の再配備では既存ジョブを維持。
- docs/pilot-m1.mdに実機変更・中間レポート・再開手順を記録。

## 検証

- [x] Windows 190件、WSL bash 4件（DBテストはWSLの一時PostgreSQL16、計194件）
- [x] ruff check、sdist/wheelビルド
- [x] 実DB migration・専用ロール認証・実収集の停止/再開
- [x] NFS共有の実適用・書込み、実画像prep/colorからDB主色観測までの疎通
- [ ] 収集の終了理由確認、prep/color全件処理、最終網羅率・容量測定（実行中）

## 関連Issue

Closes #27
```

PRラベル案は既存Issueと同じpriority: high、type: feature。
M1完成条件とM2の前提を扱うため。ラベルの作成やPR公開は行っていない。

## NFS適用後の継続記録

2026-11-01 12:31〜12:38 UTC（21:31〜21:38 JST）。以下も**中間結果**であり、収集の終了理由と最終網羅率は未確定。

### 今回の実機変更

- ubuntu-2にnfs-kernel-server、ubuntu-1にnfs-commonを導入。
  `/mnt/data/derived`を作成し、両ホストのtoumokorosiはUID/GID=1000で一致。
  `/etc/exports.d/colorstats-pilot.exports`は
  `/mnt/data/derived 192.168.1.85(rw,sync,no_subtree_check,root_squash)`だけを追加。
  初回の`/etc/exports.d`未作成を修正し、exportとnfs-server起動を確認した。
- ubuntu-1のfstabへ承認済みの次の1行を追加し、daemon-reloadとmountを実行。
  専用mount unitファイルは作成していない。

  ```fstab
  192.168.1.86:/mnt/data/derived /mnt/data/derived nfs vers=4.2,rw,hard,nosuid,nodev,_netdev,nofail 0 0
  ```

- `findmnt`でnfs4/vers=4.2/rw/hardを確認。通常ユーザーで一時ファイルへ書込み・読取り後、その確認用ファイルだけを削除した。
  systemd生成unitは`/run/systemd/generator/mnt-data-derived.mount`。
  remote-fs.targetのRequiresには含まれずWantsに含まれる。サーバー停止試験・ホスト再起動は行っていない。
- 12:32:06 UTCにanalysisをstart。collect PID=4994、analysis PID=6763、scheduler PID=5701で稼働。
  stage実装・unitはd版のまま、実行中collectは前任から継続するb版。
  NFS設定のローカル修正版を一時スクリプト経由で記録付き適用した。
  source_policy・レート制限・集中枠は変更していない。
- rawは共有していない。**M2で別ノードから原本を使う場合は、rawの共有方式・到達パスの整備が別途必要**。
  今回のprep/colorは原本のあるubuntu-1で実行し、derivedだけをNFS経由で使う。

### 網羅率・重複・失敗

12:37:46 UTCの直接集計（単一取引スナップショットではない）。93 asset・ユニークSHA-256=82・source=82・subject=81。
全93件がopenで作者・帰属・metadataを保持。prep成功93件・color成功93件・主色観測465件。
12:38:11 UTCにubuntu-2側でも縮小JPEGと色JSONの計186ファイルを確認した。

| 層 | asset | subject/目標 | 作者 | ソース | 最大作者比 | エントロピー bit | subject不明 | 作者不明 | 地域不明 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| japanese-castle | 24 | 19/100 | 17 | 1 | 12.5% | 3.9702 | 0 | 0 | 0 |
| gothic-temple | 61 | 56/100 | 10 | 1 | 80.3279% | 1.3222 | 0 | 0 | 0 |
| forest-autumn-day | 8 | 6/100 | 5 | 1 | 50% | 2.0 | 0 | 0 | 6（75%） |

網羅率19%/56%/6%、不足81/44/94、未割当asset=0。全層で集中フラグtrue。
層内の実測比と予算1,000に対する作者枠50件は別の指標。建築の地域は検索層由来で、確定した撮影地点ではない。
subjectは既存prepのSHA-256/pHashによる集約結果で、実建築・場所の人手確認を意味しない。

同一SHA-256の余剰assetは11件（93−82）。subject_candidateの根拠はsha256=20行・phash=2行。
候補行数は重複画像数とは異なり、両者を加算しない。原本参照は取得イベントごとに93ファイルある。
collectはsucceeded=93・failed=1・pending=13・running=1。
failedの最終理由は前任の停止フラグによる中断1件。停止後に成功した別jobにも同じ直近理由が残るため、
`failures`の中断2件をfailed件数と混同しない。prep/colorの失敗は0件。
保存された成功run内の除外候補は帰属不足1・非対応MIME38・restricted5・author_limit7。
全再試行の履歴集計ではない。

### 時間・容量

| 項目 | 合計 | 成功対象1 assetあたり |
| --- | ---: | ---: |
| collect成功試行時間（空ページ含む） | 1,412.310585秒 | 15.186秒 |
| prep成功試行時間 | 120.187493秒 | 1.292秒 |
| color成功試行時間 | 116.810972秒 | 1.256秒 |
| 原本参照93ファイル | 827,264,828 byte | 8,895,321 byte |
| 縮小JPEG 93ファイル | 6,394,895 byte | 68,762 byte |
| 色JSON 93ファイル | 570,226 byte | 6,131 byte |
| DB全体 | 11,992,087 byte | 増分で計算 |
| publicテーブル・索引・TOAST | 3,661,824 byte | 増分で計算 |

適用直後からのDB増分3,457,024 byte（37,172 byte/asset）、public増分3,219,456 byte（34,618 byte/asset）。
成功run参照ファイルだけを集計し、未参照ファイルは含めない。DB容量は稼働中に変化し、空DBとの差に検索job・失敗記録も含む。
成功試行時間の合計であり、停止・再試行・待機を含む全経過時間ではない。最終値は収集終了後に再測定する。

### 検証と再開

- 全テスト183件成功・Windows対象外4件、別途WSLのbash転送4件成功（合計187件）。DBテストのスキップなし。
  最初の一時DB接続はタイムアウト。WSLの`/tmp`に前任のDB実体が残っていなかったため、UTF8・localhost限定で作り直して成功した。
  再作成前に開始した別の実行も接続タイムアウトで終了し、成功件数には含めていない。
- ruff全体、sdist/wheelビルド、修正したNFSスクリプトを含むbash構文確認、実機unit verifyが成功。
  任意Matplotlib未導入の既知警告1件は残るが、実画像の色抽出とDB登録は成功した。
- NFSのIP限定export、UID/GID、実書込み、サーバー上の出力実体、nofailの依存関係を確認。
  公開API・DB形式・共有契約の変更はない。commit・push・PR作成は未実施。

3サービスは起動したまま残す。通常の継続には追加startは不要。
最終稼働確認12:39:45 UTCでも3サービスはactive/running、PIDは上記のまま。
12:39:27 UTCの自動レポートは102 asset、prep/color成功各93件、prep待機8件・実行1件。
collect成功99・失敗1・待機7・実行1、次seed=5。以降の新規assetは引き続き自動処理される。
`report.json`はschedulerが60秒ごとに更新し、新規assetへprep、成功prepへcolorを投入する。
再接続時は前掲のstatus・report.json・seed.json・scheduler journalを確認する。
収集がpending/runningならそのまま待ち、解析だけ停止していた場合はマウントと停止理由を確認してからanalysisを再開する。
停止フラグは対応サービスの停止確認後にだけ解除する。フラグがなければ削除操作は不要。
検証用のWSL一時PostgreSQLは12:39 UTCに停止済み。本番DBと実機ワーカーは停止していない。

全件解析後は単発集計を実行する（収集中でも読み取り集計は可能）。

```sh
cd /opt/colorstats/releases/cf166b9-issue27-20261101d
.venv/bin/python ops/deploy/launch.py ops/deploy/pilot.py \
  --root /opt/colorstats/releases/cf166b9-issue27-20261101d \
  --state /var/lib/colorstats/pilot --version cf166b9-issue27-20261101d
```

残作業は収集の目標・集中枠・探索上限での停止理由の確定、新規分を含む全件prep/color、最終集計への更新。
Commonsのみの上限800にまだ達していない。seed 20到達だけで上限800到達とは扱わず、
成功runの継続offsetと検索結果を確認する。Minecraft収集は未着手のまま対象外。

今回の主なログ（すべて`C:/Users/ryuma/.codex/logs/commands/`）:

- Issue確認: `20261101T123023Z-a59bcf5b15c6475aad1aedc5ce7e8a4e.jsonl`
- NFS server適用: `20261101T123147Z-90d534897fdc40068c9db8be61f3401c.jsonl`
- NFS client・解析開始: `20261101T123156Z-4e961fe6b41048f99e870f2b83532d1a.jsonl`
- 直接集計・nofail確認: `20261101T123744Z-10297493576d44de981623fa053d0ec1.jsonl`
- サーバー出力実体: `20261101T123810Z-a19f789a2c85445e88dc4726913f4692.jsonl`
- 全テスト成功: `20261101T123646Z-ef38d30287394b61b4de6717aff955a1.jsonl`
- WSL転送4件: `20261101T123334Z-cb8d454b6d2547a0af8818b8b083ed27.jsonl`
- ruff/build: `20261101T123250Z-d7f578f67b4744cabd695ab5dfdad6f2.jsonl`・`20261101T123255Z-ac37ab92a6ac473fb2267cb6d2a77252.jsonl`
- shell構文: `20261101T123716Z-42bc07ed2eb649deb2c4a2b60620207e.jsonl`
- 最終稼働確認: `20261101T123944Z-68726655a81a43c8ab62e17ae629b0dc.jsonl`
- WSL一時DB停止: `20261101T123946Z-c7997a4b6be24ab69b52587276fa862f.jsonl`

## 層拡張後の継続記録

2026-11-01 14:06:56 UTCにe版へ切り替えた。**収集は継続中で、最終集計ではない。**

### 修正・設定と配備

- 建築7層・地形5層の計12層、各100 subject、合計1,200 subjectへ拡張。
  近代住宅、中世住宅、日本の寺社、イスラム寺院、中国民居、岩山、草原、砂地、雪原を追加した。
  地域・時代・季節は検索の意図であり、確定した画像分類ではない。
- 予算1,000、作者5%、検索provider80%、地域40%、subject上限3枚を維持。
  作者・providerは全体枠に加えて層目標100に対する枠（5枚・80枚）も検査する。
  #9の層内集中を防ぐ契約修正で、保存形式とmigrationに変更はない。
  既存の城119枚・ゴシック115枚は層内provider上限を既に超えるため、追加取得を止める。
  既存画像・予約・ジョブ・集中フラグは削除や初期化をしない。
  分母は現在の取得枚数ではなく固定目標なので、層内5枚以下でも実測占有率が5%を超えれば
  `concentrated=true`となる。上限遵守と実測集中度は別に評価する。
- SVGを共有collectの対応MIMEから外した。以後は予約・取得前に`mime`で除外する。
  取得済みSVGのprep失敗1件は理由とともに維持した。
- `cirrussearch-too-busy-error`も既存のRetry-Afterと指数待機で再試行する。
  旧版でもキューの再試行はされていたが、APIアダプター内の負荷待機が不足していた。
  source_policy、取得間隔、再試行上限は変更していない。
- scheduler→collect/analysisの順に停止フラグで停止し、旧collectのpending/running=0を確認した。
  新スナップショットのSHA-256を照合し、`uv sync --frozen --no-dev`で配備。
  `targets-before-e.yaml`・`seed-before-e.json`へ旧設定を保全し、新設定のseedを0から開始した。
- 全3サービスのunit・実行プロセスは`/opt/colorstats/releases/cf166b9-issue27-20261101e`。
  解析実装は同じなので`--analysis-version cf166b9-issue27-20261101d`を指定し、
  旧prep/colorジョブを再生成しない。起動直後も290件ずつの成功とSVG失敗1件を保持した。
  自動起動のenable、再起動、netplan/fstab変更、DB認証変更は行っていない。

### 検証・重点反証

- Windowsで190件成功、対象外のLinux bash4件はWSLで成功（計194件）。
  DBテストのスキップなし。WSLの旧`/tmp` DBは消失していたため、新しい一時DBを
  PostgreSQL16・UTF8・127.0.0.1限定で作成した。本番DBはテストに使わない。
- ruff全体・sdist/wheelビルド・配備shellの`bash -n`・実機unit verifyが成功。
  任意matplotlib未導入の既知警告1件は残る。
- 層内作者/provider枠の並行予約、他層で枠を消費しないこと、全体枠も維持することをテスト。
  SVGが採否コールバックや原本取得に到達しないこと、混雑時のRetry-After・指数待機・
  最終試行待機を回帰確認した。保存データの再生成は不要。

### 再開・集計手順

3サービスは起動したまま残す。通常は追加start不要。
`report.json`・`seed.json`とscheduler journalを確認し、pending/runningなら待つ。
新設定もseed 0〜19の上限を維持し、Commonsのみの全体上限は800枚。
seed=20で停止しても800到達と同一視せず、層/provider枠・除外理由・検索結果を調べる。
失敗済みジョブの初期化や試行回数の回避はしない。

単発の読取り集計（scheduler.stopが存在しない通常稼働時）:

```sh
cd /opt/colorstats/releases/cf166b9-issue27-20261101e
.venv/bin/python ops/deploy/launch.py ops/deploy/pilot.py \
  --root "$PWD" --state /var/lib/colorstats/pilot \
  --version cf166b9-issue27-20261101e \
  --analysis-version cf166b9-issue27-20261101d
```

各サービスを再開する場合は停止理由とプロセス終了を確認してから、そのstageのstopフラグだけを解除する。
既存マウント・NFS・旧版の参照パスを維持する。Minecraft200枚は引き続き対象外。

今回の主なログ（`C:/Users/ryuma/.codex/logs/commands/`）:

- 正本Issue確認: `20261101T140322Z-5bd5084e4f584e5ab05c5e60e3aa100b.jsonl`
- 全190テスト: `20261101T140536Z-5577aa4630b440978ea0aa407d7e64dc.jsonl`
- Linux4テスト・shell構文: `20261101T140625Z-70ace513fb8d45a49d6aee9288719ab7.jsonl`
- ビルド: `20261101T140626Z-7b1fc3f41d0b40ac92e522960c92f28a.jsonl`
- 配備・停止/再開・unit確認: `20261101T140649Z-b9b6e7c2068742f791d3b4bebbeaafc4.jsonl`
- ruff・変更範囲: `20261101T140725Z-7573fa7b27be4b4ea9f62c15d7b83bd1.jsonl`

大きなbase64付きSSH引数はWindowsの長さ上限で実行前に失敗した。
アーカイブのみ記録付きSCPで転送し、リモート操作は一時スクリプトとssh_logged.pyで実行した。


### 到達点（14:18:06 UTC／23:18:06 JST、暫定）

REPEATABLE READの同一DB取引で読取り集計。**348 assetで実行中。停止上限・最終件数は未確定。**
旧291件から57件増え、ユニークSHA-256とsourceは各281、subjectは269、主色観測は1,645行。
全348件がopen、作者キー・帰属表示・metadataを欠くassetは0件。重複SHAの余剰assetは67件で、
検索機会ごとの別assetとして保持している。未割当層は0件。

| 層 | asset | subject/目標（網羅率） | 作者/ソース数 | 最大作者占有率 | entropy bit | 不明subject / 作者 / 地域（層内割合） | 集中 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| japanese-castle | 119 | 89/100 (89.00%) | 39/1 | 30.25% | 4.4254 | 1 (0.84%) / 4 (3.36%) / 0 (0.00%) | true |
| gothic-temple | 115 | 89/100 (89.00%) | 36/1 | 42.61% | 3.8441 | 0 (0.00%) / 3 (2.61%) / 0 (0.00%) | true |
| forest-autumn-day | 57 | 44/100 (44.00%) | 30/1 | 10.53% | 4.6392 | 0 (0.00%) / 0 (0.00%) / 31 (54.39%) | true |
| modern-house | 0 | 0/100 (0.00%) | 0/0 | 0.00% | 0.0000 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | false |
| medieval-house | 26 | 26/100 (26.00%) | 15/1 | 19.23% | 3.6574 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | true |
| japanese-temple | 4 | 4/100 (4.00%) | 3/1 | 50.00% | 1.5000 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | true |
| islamic-temple | 5 | 5/100 (5.00%) | 1/1 | 100.00% | 0.0000 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | true |
| chinese-house | 2 | 2/100 (2.00%) | 2/1 | 50.00% | 1.0000 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | true |
| mountains-summer-day | 20 | 10/100 (10.00%) | 12/1 | 20.00% | 3.3842 | 9 (45.00%) / 0 (0.00%) / 15 (75.00%) | true |
| plains-summer-day | 0 | 0/100 (0.00%) | 0/0 | 0.00% | 0.0000 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | false |
| desert-summer-day | 0 | 0/100 (0.00%) | 0/0 | 0.00% | 0.0000 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | false |
| snowy-winter-day | 0 | 0/100 (0.00%) | 0/0 | 0.00% | 0.0000 | 0 (0.00%) / 0 (0.00%) / 0 (0.00%) | false |

subjectは既存prepによるSHA-256/pHashの集約で、実在建築や地点の人手同定ではない。
prep待ちも不明subjectに含む。各層の不足数は100からsubject数を引いた値。

成功試行だけの時間・参照済み不変ファイルの容量:

| stage | 成功run | 時間合計 | 1対象あたり時間 | byte / ファイル数 | byte/ファイル |
| --- | ---: | ---: | ---: | ---: | ---: |
| collect | 413 | 6083.305秒 | 17.481秒 | 2,694,372,876 / 348 | 7,742,451 |
| prep | 338 | 420.261秒 | 1.243秒 | 22,627,088 / 338 | 66,944 |
| color | 329 | 410.407秒 | 1.247秒 | 2,017,496 / 329 | 6,132 |

collectの時間は空ページを含む成功runの合計を348 assetで割った値。
prep/colorは各成功run数で割る。再試行・停止中・待機を含む総経過時間とは異なる。
未参照ファイルは含めず、同じ原本でも別取得の不変ファイルはそれぞれ数える。
DB全体は18,562,071 byte、publicのテーブル・索引・TOASTは9,756,672 byte。
適用直後（8,535,063 / 442,368 byte）からの増分はそれぞれ
10,027,008 / 9,314,304 byte、1 assetあたり
28,813 / 26,765 byte。
DB増分には検索ジョブ・失敗記録も含むため、画像固有の行サイズとは扱わない。

ジョブ状態はcollect成功413・失敗2・pending34・running1、prep成功338・失敗1、color成功329。
この時点では未投入も含めprep残り9件、color残り18件（SVG失敗1件を除く）。
次seedは1（新設定のseed 0を処理中）。最初の72 collectのうち39件成功、残り35件。
旧設定のpending/running collectは0件。

最終失敗状態の内訳は旧collectの停止中断1・Commons混雑1、既存SVGのprep1。
一方、report.failuresは全ジョブに残る直近failure_reasonの集計で、
停止中断2・Commons混雑10・SVG1。成功後も残る理由を含み、失敗試行の総履歴でもない。
除外理由は帰属不足4・mime146・restricted55・全体作者枠288・subject枠1・層内作者枠11。
こちらも成功runに記録された候補の集計で、失敗した試行の全候補数ではない。

14:16:41 UTCの実DB確認では、新規取得分の層×正規化作者の最大件数は5。
既存の集中は保持し、新規の層内作者上限を守っている。e版で新しいfailedジョブは出ていない。
近代住宅のseed 0は両言語とも取得0件。検索語・ランダム位置の次回探索を継続し、
近代住宅やまだ0件の層を達成扱いにしない。

集計ログ: `20261101T141804Z-958727183da74834b1d5353b61a9edc5.jsonl`。

残作業はCommons全体上限800枚または目標・探索上限で停止した理由の確定、
全件prep/color（失敗理由の保持を含む）、最終網羅率・時間容量への更新。
3サービスを稼働継続し、上の再開手順・自動計画を引き継ぐ。コード修正・194テスト・配備は完了、
パイロット全体は進行中。commit・push・PR作成は実施していない。

## 最終集計・新版配置（2026-11-02）

### 終了理由と完成条件

04:36:13 JST（2026-11-01 19:36:13 UTC）にcollectとschedulerの停止フラグを作成した。
終了処理中の空ページ6件も成功として確定し、04:36:54 JSTまでに3サービスの停止・PID 0を確認した。
analysisは754枚のprep/colorが完了済みで未処理ジョブがなかったため停止した。
最終値は04:38:49 JSTのREPEATABLE READ取引による集計。以降の実機検証でもasset数・ジョブ状態・試行数を増やしていない。

- raw保存・登録: **755 asset / 1,000枚（75.5%）**。全件open、source・asset・帰属・元metadataを登録し、必要なprovenanceの欠落は0。Issueの「停止枚数と理由を記録する」代替条件を満たすが、1,000枚自体は未達。
- prep/color: 各754枚成功。取得済みSVG 1枚はPillowの`UnidentifiedImageError`でprep失敗、color対象外。全755枚について成功または失敗理由が確定。主色観測は3,770行。
- 層別網羅率・集中度・不明群、1枚あたり時間・容量を以下に記録。各層100 subjectの目標を満たした層はない。
- 統合不具合を修正し回帰テストを追加済み。層内集中枠、SVG取得前除外、Commons混雑時再試行、provenance保持、容量欠損の記録、明示停止と自動再起動の区別を検証した。

Minecraft 200枚は自作スクリーンショット未整備のためM2へ延期し、今回の実画像予算1,000枚には含めていない。
その延期だけで今回の245枚不足を説明するものではない。
Openverseは既存アダプターの読取りタイムアウトにより使用できずCommonsのみとした。
全体provider枠80%により最大800枚、各層の固定目標100に対するprovider枠は80枚である。
forest・medieval-house・islamic-temple・snowyは80枚に達し、旧設定で取得済みのcastle119枚・gothic115枚も新しい層内上限を超えるため追加取得を止めた。既存データは保持した。
他の層は未充足で、検索結果不足やMIME・帰属・権利・作者枠による除外で増加が鈍化した。
04:05〜04:35 JSTの増分が6枚となったため、オーケストレータの締め判断に従って800枚到達を待たず明示停止した。
seedは20（0〜19を投入済み）だが、collect pending59件（試行数合計1）を保全している。
**全検索の完走・候補枯渇や800枚到達を確認した終了ではない。** 目標・集中枠の緩和や失敗ジョブの初期化はしていない。

### 最終網羅率

各層のsubject目標は100。最大作者比が5%を超える非空11層はすべて`concentrated=true`。
ソース数は検索provider数で、非空層はCommonsの1、modern-houseは0。
subjectはSHA-256/pHashによる集約であり、建築・地点の人手同定ではない。
層属性は検索時の意図を含み、地域は確定撮影地を意味しない。不明群も集計した。

| 層 | asset（provider枠80） | subject / 網羅率 / 不足 | 作者数 | 最大作者比 | entropy bit | 不明subject / 作者 / 地域（件数） | 追加取得の制約 |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| japanese-castle | 119 | 89 / 89% / 11 | 39 | 30.25% | 4.4254 | 1 / 4 / 0 | 旧取得分が層内上限超過 |
| gothic-temple | 115 | 89 / 89% / 11 | 36 | 42.61% | 3.8441 | 0 / 3 / 0 | 旧取得分が層内上限超過 |
| forest-autumn-day | 80 | 50 / 50% / 50 | 34 | 7.50% | 4.8037 | 0 / 0 / 44 | provider枠到達 |
| modern-house | 0 | 0 / 0% / 100 | 0 | 0% | 0 | 0 / 0 / 0 | 成功検索120件で取得0、MIME除外199・restricted2 |
| medieval-house | 80 | 71 / 71% / 29 | 38 | 6.25% | 4.9122 | 0 / 0 / 0 | provider枠到達 |
| japanese-temple | 42 | 33 / 33% / 67 | 19 | 11.90% | 3.9167 | 0 / 8 / 0 | 未充足、MIME除外31など |
| islamic-temple | 80 | 72 / 72% / 28 | 37 | 6.25% | 4.9463 | 0 / 2 / 0 | provider枠到達 |
| chinese-house | 44 | 35 / 35% / 65 | 17 | 11.36% | 3.8131 | 0 / 0 / 0 | 未充足、層内作者枠除外96・MIME61 |
| mountains-summer-day | 65 | 41 / 41% / 59 | 27 | 7.69% | 4.5099 | 0 / 0 / 54 | 未充足、MIME除外41・層内作者枠18 |
| plains-summer-day | 29 | 25 / 25% / 75 | 9 | 17.24% | 2.9548 | 0 / 0 / 29 | 未充足、MIME除外237・層内作者枠40 |
| desert-summer-day | 21 | 21 / 21% / 79 | 13 | 23.81% | 3.4226 | 0 / 0 / 14 | 未充足、MIME除外14・restricted6 |
| snowy-winter-day | 80 | 60 / 60% / 40 | 43 | 6.25% | 5.1845 | 0 / 0 / 56 | provider枠到達 |

未割当層0、subject586（層別の和も586、総目標1,200の48.83%）。
不明subjectは1/755（0.13%）、不明作者17/755（2.25%）、不明地域197/755（26.09%）。
表の除外数は成功runに残った候補記録であり、検索母集団全体や一意な候補の件数ではない。

### 時間・容量・重複・失敗

| stage | 成功run | 成功試行の時間合計 | 1枚あたり時間 | 参照容量 / ファイル数 | 1枚あたり容量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| collect（原本） | 1,757 | 24,444.640秒 | 32.377秒（755 assetで除算） | 5,340,689,816 byte / 755 | 7,073,761 byte |
| prep（縮小JPEG） | 754 | 928.310秒 | 1.231秒 | 47,124,985 byte / 754 | 62,500 byte |
| color（主色JSON） | 754 | 935.144秒 | 1.240秒 | 4,623,054 byte / 754 | 6,131 byte |

derived合計51,748,039 byte。全stageで`file_errors=[]`、`capacity_complete=true`。
成功runが参照する不変ファイルだけを数え、未参照ファイルは含めない。ファイル削除・整理はしていない。
collect時間には取得0件の成功検索も含む。成功試行の処理時間の合計であり、待機・失敗試行・並列処理を含む全経過時間ではない。
DB全体34,757,655 byte、publicのテーブル・索引・TOAST合計26,058,752 byte。
空DBの8,535,063 / 442,368 byteとの差分は26,222,592 / 25,616,384 byte、755 assetあたり34,732 / 33,929 byte。
検索ジョブ・失敗記録・DB管理領域も含む増分であり、asset行単体の容量ではない。

755 assetは596種類のSHA-256・596 sourceを参照し、同一SHAの余剰assetは159件。
pHash登録754枚、異なるpHash590、同一pHashの余剰164件（SHA重複と加算しない）。
subject586。検索機会ごとのassetを保持し、同一原本の別不変ファイルもそれぞれ容量に数える。

最終ジョブはcollect成功1,757・失敗2・pending59、prep成功754・失敗1、color成功754、running0。
failedはcollectのCommons混雑1件、過去の停止中断1件、prepのSVG読込み1件、計3件。
一方、全jobに残る直近`failure_reason`はCommons混雑10・停止中断3・SVG1件で、再試行後に成功したjobや今回返却したpendingも含む。失敗試行の全履歴ではない。
成功runの候補除外は帰属不足14・MIME874・restricted122・全体作者枠593・層内作者枠665・subject枠7・層内provider枠337。

### 新版配置と実機検証

配置先はubuntu-1の`/opt/colorstats/releases/cf166b9-06a615d-issue27-20261102f`。
基準HEAD `cf166b9`とmerge中のdevelop `06a615d`、未コミット#27を含むスナップショットであり、commit版ではない。
配布tar.gz SHA-256: `439bbb78199468a150582583fe0dbc922e87fb84985d89f527faf984df1ce56a`。
uv 0.13.6・Python 3.12.3・`uv sync --frozen --no-dev`で配置し、unit verify成功。
解析版`cf166b9-issue27-20261101d`を維持し、成功済みprep/colorを再生成しなかった。
#30のraw停止・保留対応を含むワーカーと監視を配置した。disks.jsonは配布版と内容一致し、監視serviceは`Result=success`・`ExecMainStatus=0`。

- 3サービスを起動しMAINPIDをSIGKILLした後、`Restart=on-failure`で自動再起動。collect23968→24019、analysis23969→24018、scheduler23970→24020、各`NRestarts=0→1`。障害終了時に停止フラグは作られなかった。
- 既存停止記録がないことを確認してORICOの一時blocked記録を作り、新規収集を保留させた。前後のstage別件数・試行数は完全一致。検証用blocked記録だけを撤去した。
- 再起動後の`systemctl stop`で、全サービスの停止フラグあり・`inactive`・MAINPID 0を確認。
- colorの成功参照1ファイルを削除せず一時退避し、scheduler実プロセスで`FileNotFoundError`と`capacity_complete=false`を記録。容量は読めた753ファイルの4,616,924 byte、参照数は754を保持した。19:40:34→19:41:43 UTCの次周期でも同一PID24138でactive・レポート更新継続。停止後に元のパスへ戻し、SHA-256 `afb7e98cc9e64e30f70b0316873e2703f872956bb98d40ce92b3e5c88eb84060`の一致を確認。

04:43:29 JSTの最終確認で、3サービスとも新版を参照し`inactive/dead`・MAINPID 0、3停止フラグあり。
検証用の退避ファイルとblocked記録は残っていない。`report.json`も通常集計で更新し、全stageの容量欠損なしを再確認した。
最終集計の保存先は`/var/lib/colorstats/pilot/final-report-issue27.json`、実機検証の記録は同ディレクトリの
`runtime-verify-issue27.json`・`capacity-verify-issue27.json`。DB認証ファイルは所有者専用mode 600を維持している。

NFSの通常umount・hard→soft変更を含む最初の配置要求は、実行前に自動権限審査で拒否された。
理由は「I/Oエラーやサービス障害の運用リスクに対し、具体的なsoft設定の明示承認を確認できない」。
拒否対象を実行せず、NFS操作を含まない配置だけを実施した。
現在も`hard,timeo=600,retrans=2`で、fstabの`_netdev,nofail`も維持している。
soft設定の適用と隔離NFSでの断・復帰試験は未実施・承認待ちであり、NFS断時の待機制限を実機確認済みとは扱わない。
ホスト再起動・netplan変更・媒体フォーマット・取得済みデータ削除・平文秘密のホスト間移送はしていない。

本実行でアプリコードは変更していないため、引継ぎ時の全233テスト・ruff・build成功を再利用する。
mergeは未コミット、#30のstage済み差分と#27の未stage・未追跡成果物を保持し、commit・push・PR作成は行っていない。

主要ログ（`C:/Users/ryuma/.codex/logs/commands/`）:

- 停止要求: `20261101T193613Z-2e6477e8338848f29f8430ac291d634b.jsonl`
- 全サービス停止: `20261101T193654Z-46b27c851fb64bef94a4dbda63f9efbf.jsonl`
- 新版配置: `20261101T193822Z-f22a651709784a2291eda72345f0c106.jsonl`
- 最終集計: `20261101T193847Z-ed314210cc7e4405bf2e8242fc3bf629.jsonl`
- 自動再起動・明示停止・保留: `20261101T193927Z-1dc1468269714fbcafee03c70ff30e05.jsonl`
- 欠損時のscheduler継続: `20261101T194024Z-0f2d17070f244c088cdad9a22f1bea99.jsonl`
- 復元・最終停止状態: `20261101T194329Z-6b9edf24054c4dc080a8c328db05fcba.jsonl`

