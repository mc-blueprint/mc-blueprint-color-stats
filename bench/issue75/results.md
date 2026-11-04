# Issue #75 第1段階の検証結果

基準: `2ea1ea59008664b3ecf8906bb0b14f3963791539`（#74 第1段階）。
ブランチ: `feature/issue-75`。commit・push・PR作成・本番登録は未実施。
仕様下書きは[schema-section.md](schema-section.md)。

## 検証

- ruff check .: 成功。
- Windows/Python 3.12: 全体375 passed / 152 skipped（88.57秒）。
  nullable検索メタデータ・SQL NULLの最終修正後、新規fixtureは15 passed（54.34秒）。
  スキップはDB接続・OS・実GPU等の条件による。Matplotlib未導入の任意機能警告1件。
- Linux/Python 3.12・隔離PostgreSQL 16: 最終全体526 passed / 1 skipped（97.50秒）。
  新規fixture15件・DB統合5件を含む。実GPU統合は未実行。
- sdist・wheel: 最終コードでビルド成功。

DB検証はubuntu-2の本番と別の `/mnt/data/work/issue-75/pgdata`、
Unix socket `/mnt/data/work/issue-75/socket`、port 5575を使用。
Linuxの既存検証Pythonと#74のDuckDB依存を再利用し、パッケージ追加はしていない。
既存スキーマテストが空DBを要求するため、最終全体検証は新規UTF8 DBで実行した。

## 完成条件と反証

- subject内画像等配分・領域面積比・pair面積積・事後層化・n_effを手計算と照合。
- SHA複製で分布・支持不変。役割の複数検出と最大クラスタ選択を確認。
- 層0件、未知subject、未割当、画像間の層矛盾、high_weightと上限5感度を確認。
- subject数9/10/29/30、およびsubject=40・n_eff=27.9の境界を確認。
- 軸別経験CDF混合、条件親の固定順、10未満での親のみ借用、借用で実測数不変を確認。
- ±180度の36bin・無彩色NULL質量、逆pairの差符号と面積比、ゼロ面積・無効比を確認。
- domain分離・#81未支持ラベルのunsupported維持を確認。
- DBなしCLI、hash改変拒否、固定snapshot再計算一致を確認。
- Worker登録、同一キー再投入、Queue.complete二重実行、リース喪失後の別試行を確認。
- 全統計flush後のDBエラーでrule_stat・run・入力辺が全件rollbackすることを確認。
- #74の実装で生成したDB fixture snapshotと接続し、権利除外・SHA重複の入力runを
  主統計の由来へ戻さず、成功入力runの不一致は登録を拒否することを確認。
- confidence_intervalはJSON nullではなくSQL NULLとして保存する。

## 計測と残り作業

[fixture-metrics.json](fixture-metrics.json)は合成入力だけの計測。
80 asset行→40 SHA代表画像、40 subject、n_eff=30、総重み40。
24統計行（direct 9 / smoothed 6 / unsupported 9）、集計2.316024秒。
snapshot 10,733 byte、結果85,074 byte。子10 subjectのλ=1/3、
styleとbuilding_typeで順に混合したLの質量は7/9と2/9。
計測はWindowsの1回分で、実7,607件の性能・支持数へ外挿しない。

#74実snapshot後のdry-run・本番登録・実支持/不足・実データ性能の確認は第2段階。
地域・年代・季節等の目標層属性が欠ければ確定subjectも未割当となり、
検索意図では補完しない。実用性ゲート達成は現時点で未確認。
snapshot形式の変更は不要だった。和集合pairは固定色・面積から既存共起計算を再利用する。
docs/schema.md・docs/design.mdの統合、公開文面の作成も第2段階へ残す。
