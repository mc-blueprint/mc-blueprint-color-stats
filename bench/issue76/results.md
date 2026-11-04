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
aggregate 1.781秒、report 0.297秒（2026-11-04、条件4表示更新後の計測）。
Parquet 9,601 byte、JSON 127,252 byte、Markdown 10,971 byte。
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


## 2026-11-04 部分層補正への追従

Issue #75/#76の設計変更コメントを正本とし、origin/feature/issue-75の
c6c36b7・b16dd69をgit merge --no-editで取り込んだ。
ローカルmerge commit: fef76fecb48f02eb2a7fb21af98b86df5fd48577。
競合なし。#74最新6c8534bは祖先に含まれず、取り込んでいない。
以下は上記の過去の一意層割当・report-v2の説明を置き換える。

report-v3はweights.asset_attributes・compatible_strata・assign_strata・calculateを再利用する。
unknownは周辺化し、既知値の競合・対象外だけを主結果の未割当に残す。
複数層への両立subject数を重複表示し、所属質量m_shの和で不足・被覆を計算する。
他層への非所属をsubject全体の未割当とは数えない。
条件別観測は_conditionsを使い、unknownを特定style等の直接観測へ補完しない。
条件4は#75の部分層補正主結果のsubject数・n_effで判定し、同じ分母で
補正率・属性別未知率・情報なし割合を併記する。D15とモデル品質ゲートは維持した。

回帰: 同一subjectの既知/unknown混在、別subjectでの質量1.5/0.5・不足98.5/99.5、
情報なしでも主結果により条件4を判定する場合、矛盾・対象外subjectの棄却。
情報なしの場合は補正率0、情報なし割合1、属性別未知率1を表示する。
既存のD15前後差・ゼロ面積・重複・再現性・CLIも確認する。

- Windows全体: 413 passed / 153 skipped（123.96秒）。
- Linux/Python3.12・隔離PostgreSQL16全体: 565 passed / 1 skipped（126.74秒）。
- 最終差分の報告・wheel CLI・PG16統合: 28 passed（21.23秒）。
- ruff check .・sdist／wheel build成功。実GPU統合は未実行。
- 専用DBはcolorstats_test76_partial、socketとportは前回同様5576。
  全体検証には新規空UTF8 DBを使用し、本番DB・GPU・共有venvは変更していない。
- 合成artifactはaggregate-v2・report-v3で再生成。建築domainの補正率1、
  情報なし割合0、style/building_type未知率0、40 subject・n_eff30。
  全量への外挿はせず、出力はscratchpad/i76-fixture-partialに保全。
- D15前union追加列のある#74最新との実snapshot統合、実データ判定・docs本体反映は第2段階。
- 変更commit用文面はscratchpad/i76-commit3.txtへUTF-8で保存済み。
  merge以外のcommit・push・PR操作は行っていない。

部分層補正の検証終了後、Issue76専用PostgreSQLクラスタだけを正常停止し、データ・ログを保全した。


## 条件4の解釈と品質フラグの表示

ユーザー決定Aに従い、条件4のsubject数・n_eff・モデル品質の閾値は維持する。
条件4のJSONに役割別の率・分母・passed・品質フラグを添え、Markdownにも
条件4の直下へ同じ表を出す。reasonに「passed は層補正の有効性を意味しない」と明記。
情報なし割合が過半（>0.5）の役割にweak_correctionを付け、domain・条件4にも集約する。
このフラグでpassedを落とさず、#75由来の統計qualityや支持を変更しない。
G引継ぎ・設計・出力契約下書きにも同じ注意を反映した。

- 回帰: 情報なし割合1・0.55でフラグあり、0.5・0.45でなし。各役割のpassedを維持。
  両domainが情報なしの状態で条件4がpassedでも、率・フラグ・注意を表示する。
- ruff check .、sdist／wheel build成功。
- Windows全体pytest: 417 passed / 153 skipped（112.58秒）。
  DB・OS・実GPU等の条件付きテストはスキップ。今回は表示と純粋な品質フラグの変更で、
  PostgreSQL・GPUは起動しておらず、前節のPG16結果は過去の検証結果として区別する。
- 追加fixtureのDuckDB行取得の失敗はfetchallで修正し、全体を再検証済み。
- fixture-report.md・fixture-metrics.jsonを更新。生成元JSONは
  指定scratchpad/i76-fixture-condition4に保全した。
- 指定scratchpad/i76-commit4.txtへUTF-8で中間commit文を保存。
  commit・pushは行っていない。第2段階の実snapshot等の残作業は従来どおり。


## 第2段階の完了記録

2026-11-05の実データ照合・docs統合・検証は[全量結果](full-results.md)参照。
本書の第2段階未着手という記述は第1段階時点の履歴である。
