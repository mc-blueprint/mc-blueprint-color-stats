# Issue #76 第1段階の検証結果

基準: #75 第1段階 `57178b653311736d802889224a759ec19a4d638e`。
ブランチ: `feature/issue-76`。
担当worktree: `H:/mc-blueprint/worktrees/colorstats-76/mc-blueprint-color-stats`。
本番の実snapshot・rule_stat登録・M3最終判定は未実施。commit・push・PR作成なし。

## 達成した範囲

- 同じsnapshot・#75設定・集計JSONの全内容を照合してJSON／Markdownを生成するCLI。
- 12層すべての空層、意図／属性一致、率の分母、未知・候補・競合、D15等の除外理由。
- 全体／層別のasset行・SHA異なり・重複・subject数、作者／subject／provider／
  出典site／地域／撮影位置／ライセンスの集中と未知率。
- #75の条件・役割／pair別支持、n_eff、最大重み、欠損目標質量、品質・感度・親借用。
- 建築と地形の各1役割についてモデル品質と直接観測subject>=10、n_eff>=10を確認。
  9/10境界、subject=10でもn_eff=3.6で未達、40 subjectでn_eff=27.9の照合、
  単一subjectの多数画像、両domain達成fixtureを確認。
- 同一SHAが別層にも属する場合、層別SHA合計3でも全体SHAは2のまま。
- 同じsnapshotからJSON／Markdownバイト列が再現され、不正hash・異なる統計／設定、
  既存出力ディレクトリへの上書きを拒否する。
- M3条件1〜6を個別表示。条件1・2・6は外部監査・受領確認が必要なのでunverified。
  条件3は再計算一致で確認し、条件5はD15役割別診断の根拠不足があればunverified、
  条件4は役割別支持から判定する。
  本番監査結果の最終判定は第2段階のM3結果報告で追補する。

## 検証

- Windows Python 3.12のクリーンvenv: 全体387 passed / 152 skipped（97.94秒）。
  この全体実行後に追加したDB fixtureはWindowsでは未実行。
  最終候補の報告fixture12件と、その後の重複・n_eff重点反証5件は成功。
  重複する3件を除き報告fixtureは計14件。DB fixtureと合わせて新規15件。
- Linux Python 3.12 / 隔離PostgreSQL 16.15: **541 passed / 1 skipped（116.16秒）**。
  新規15件を含む。スキップは既存の実GPU統合検証。
- ruff check .、sdist・wheel build成功。
- wheelインストール後、作業ツリー外・DATABASE_URLなし・PYTHONPATHなしでCLI成功。
- Matplotlibを使わないWindows検証に、colourの任意API未導入警告1件。
- 最初のLinux全体実行でCLIテストがパッケージ未導入のため失敗した。
  共有venvを変更せず専用venvへwheelを入れて解決。
- 次の全体実行で既存スキーマテストの空DB要件が失敗した。
  データを削除せず、新しい空UTF8 DBで最終全体検証を成功させた。

隔離クラスタ: `/mnt/data/work/issue-76/pgdata`、
socket: `/mnt/data/work/issue-76/socket`、port 5576、TCP待受なし。
最終DB: `colorstats_test76_final`。
依存は既存の#46/#40検証venvと#74 depsを専用venvから参照した。
本番DBを変更せず、#66サービス・GPUジョブ・ubuntu-1 pilotを操作していない。
検証後にIssue76専用クラスタのみ停止し、データ・ログ・artifactを保全する。

## 合成fixture計測

[fixture-metrics.json](fixture-metrics.json)と[fixture-report.md](fixture-report.md)を参照。
80 asset行→40 SHA、40確定subject、subject n_eff=30、最大重み2。
統計24行: direct 9 / smoothed 6 / unsupported 9。
aggregate 1.406秒、report 0.282秒（hash検証・再計算・採用観測照合込み）。
Parquet 9,601 byte、JSON 97,112 byte、Markdown 7,992 byte。
Windowsの合成入力1回分であり、本番7,607件の支持や性能へ外挿しない。

再現（dev依存を導入した環境で、出力先は新規ディレクトリ）:

~~~sh
python bench/issue76/reproduce.py <新規出力ディレクトリ>
~~~

snapshotとstatistics.json・report.json・report.md・計測JSONを出力する。
今回の出力は依頼で指定されたscratchpadの`i76-fixture/`に保全した。

## 第2段階へ残す作業

#74/#75の実snapshot・DB登録対象JSONを同じhashで照合し、本番レポートを生成する。
#66全件の成功・失敗・品質・速度・容量、#72再実行・誤結合監査、
建築／地形の実支持・G受領を確認して、M3の最終結果を報告する。
snapshotは成功した選択runを主に保持するため、全量失敗や未選択runの実測を
そのまま復元できるとは扱わない。レポートのprocessing.scopeにも明記した。
未確認の既存値・地域／年代等の属性不足・D15除外は支持不足として残す。

既存docsは編集していない。追記案は同ディレクトリの
collection-bias-section.md、design-section.md、schema-section.md、
G引継ぎはg-handoff.mdに置いた。統合・本番結果・公開文面は第2段階。
重要な知識・根拠はこれらの下書きをメイン担当へ返し、外部知識保存先は同時編集しない。


## 反証2・3・4の修正と最終差分検証

修正基準は#76第1段階3d7db7df98b6c39950e64211525e94344af42467。
report-v2としてsubjectのlocation→region・eraを既存coverageから読み、
weights.assign_strataでsubject単位の棄却・採用数・不足数を照合する。
classificationの画像属性未割当と統計採用subject未割当を別の分母で表示する。
#75修正との統合はメイン担当が確定commitで行う。担当外ファイルは変更していない。

層・条件と役割ごとのD15前後の保存済み色観測subject数と集合差を追加した。
同じsubjectの適格観測が残れば失った数は0。採用支持には既存aggregate._pointsを再利用し、
ゼロ面積・未検証モデル等を保存済み観測の件数と混同しない。
D15除外前の和集合色がなければ前後差をnullとし、条件5をunverifiedにする。
#74に同じsnapshotへ結び付く追加診断根拠が必要であることは未解消で、
本修正で#74側や本番データを変更して補ったとは扱わない。

反証の回帰は、実12層の地域・年代、同一subjectの異なる層とD15除外画像の扱い、
壁／樹木の個別部位と和集合の根拠有無、適格な別画像によるsubjectの残存、
ゼロ面積を含む9件を追加した。既存の報告23件とDB1件の計24件で最終差分を検証。
- Windows全体: 396 passed / 153 skipped（86.83秒）。
  その後の採用観測照合と追加2件を含む最終報告fixture: 23 passed（34.96秒）。
- Linux/PostgreSQL16全体: 548 passed / 1 skipped（131.68秒）。
  最終差分の報告・wheel CLI・DB統合: 24 passed（20.69秒）。
- ruff check .と最終sdist・wheel build成功。実GPU統合は未実行。
- DBはIssue76専用クラスタ内の新規空UTF8 DB colorstats_test76_fix2。
  共用venv・本番DB・#66サービスは変更していない。検証後に専用クラスタのみ停止。
- 合成report-v1 artifactは再生成し、対応するJSONとsnapshotは指定scratchpadの
  i76-fixture-fix2-finalへ保全。fixture-metrics.jsonとfixture-report.mdもreport-v2へ更新。
- 中間commit文は指定scratchpadのi76-commit2.txtへUTF-8で保存した。
  commit・push・PR操作は行っていない。
