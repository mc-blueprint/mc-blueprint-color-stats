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
  条件3・5は内部確認、条件4は役割別支持から判定する。
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
aggregate 1.907秒、report 0.390秒（hash検証・再計算込み）。
Parquet 9,601 byte、JSON 87,534 byte、Markdown 5,719 byte。
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
