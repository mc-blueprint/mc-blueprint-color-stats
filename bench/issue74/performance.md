# Issue #74 追加対応: 取引短縮とD15除外前の支持

2026-11-03。基準feature/issue-74は2ea1ea5。
変更・検証だけを実行し、commit・pushは行っていない。
元試験の正本は指定scratchpadのd76-results.md
（origin/feature/issue-76 = 3d7db7d、部分解析済み880件）。

## 実装

- asset単位の関連行照会を廃止し、選択asset・全入力runの閉包・source・subject・候補・
  region・観測・関係をまとめて取得する。観測・関係は4096行単位のカーソルで
  一時JSONLへ退避する。固定取引から読み終えて接続を返してから、照合とCPU処理を行う。
- 観測・関係のasset/run/領域照合、ラベル品質、SHA代表、除外理由の伝播は集合結合で行う。
  DuckDBへの逐次挿入はJSONL一括取込みと1取引へ置き換えた。
- 既存colorのマスクと主色抽出を使い、D15除外前にも支持済みunionを抽出する。
  OpenCVとDuckDBを一スレッドに固定し、各マスクをasset内で一度だけ読む。
- 選択assetの列挙順を正規化し、同じ固定入力・設定・コード版から同じ内容hashを作る。
  DB取引識別子・計測時間はexecution.jsonへ分離する。
  このsidecarは計測専用で、集計入力・信頼済みhashの対象ではない。
  manifestと7 Parquetは従来どおりhash・行数を照合してから採用する。

stats/aggregate*.py・weights.py・report*.py、collect/は変更していない。
依存追加・DBスキーマ変更・旧データ移行処理はない。

## 同じ880件での時間比較

元試験と同じselection.json、同じ既存venv、同じUbuntu上の低優先度実行。
#66 colorstats-issue66-full.serviceは実行前・実行後ともactive。
nice 19 / ionice c3、OpenBLAS/OMP/MKL/OpenCV/DuckDBのCPU一スレッド、GPU不使用。
専用の本番DB接続バックエンドもnice 19 / ionice c3にした。
本番DBの取引はREAD ONLY / REPEATABLE READで、書込みとサービス操作は行っていない。

| 実行 | 全体秒 | DB読取り・取引秒 | 照会数 |
| --- | ---: | ---: | ---: |
| 元の880件試験 | 約9,660（2時間41分） | CPU処理も取引内 | asset・行単位 |
| 修正後1回目 | 180.134 | 18.378 | 12 |
| 同じ入力で再生成 | 183.130 | 19.192 | 12 |

元の時間は概数なので、改善倍率も約53.6倍。
同じ1件当たり時間を7,607件へ単純に換算すると約26分。
これは実全量の計測値ではなく、画像サイズ・I/O負荷・空き容量などで変動する。
880件の全Parquetとsnapshot_idは2回の生成で一致した。

snapshot_id:
aa492b6f09df65b8b86b329a9a49e90691cde7b8223e6860d38ca84748d3be70

selection_hash:
092948dc3eab8d407cc9a57c8d20989aaa38837443864a0cb56d75cff16439a2

計測・生成物はubuntu-2の
/mnt/data/work/m3-dryrun/issue74-perf/results/run3、run4、
metrics3.json、metrics4.json、support-audit.jsonへ保全した。
権利除外前の画像には旧pilotの所有者限定ファイルもあるため、
計測は既存管理権限で許可された画像だけを読み、
DB接続時だけ既存postgres peer認証のOS身元を使用した。
認証情報の読取り・コピー、ファイル権限や認証設定の変更はしていない。
postgresだけで実行した最初の2回は旧pilot画像の読取り権限で停止したが、
DB取得はいずれも約18.8秒・12照会で完了し、成功manifestは出力していない。

## #81との接続と除外前後

支持は元の決定どおり:
- real_building: 個別door、wall_main + wall_secondary + gable_wallの画素union。
- real_terrain: vegetation_tree_canopy + tree_trunkの画素union。
- wallの子ラベルや幹・樹冠の個別色を、unionの支持から適格へ昇格しない。

131,675観測行のうち品質適格は2,260行、D15・SHA後は700行。
unvalidated_label 125,015行とwhole_image 4,400行は仕様どおりの個別観測除外。
粗い役割はobservationsとは別のgroupsに保持するため、700だけでは支持を表さない。
最終採用は個別観測700・union313・関係22で元試験と一致する。
旧369 unionのIDは全件保持し、色データ・採用判定の変更はどちらも0件。

| union役割 | 除外前行 | SHA異なり | subject数 | D15後行 | D15後subject数 | SHA後採用行 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| real_building/wall | 510 | 449 | 49 | 194 | 7 | 171 |
| real_terrain/tree | 350 | 275 | 5 | 175 | 1 | 142 |

groupsは従来369行から860行へ増加した。
画像880、SHA742、権利適格383、SHA代表326、最終確定subject8は元試験と一致。
ライセンス条件・非許容ライセンス497、帰属不足2、SHA重複57。
理由は重複該当するため合計を除外画像数にはしない。

## #76へ渡す列

asset_idでassetsへ結合する。dataとreasonsは従来同様JSON列。
- assets: sha256、subject_id、data.scene_attributes・data.subject・候補根拠、
  rights_eligible（D15だけの通過）、analysis_available（権利と独立した必要解析）、
  representative_id、eligible、reasons。
- observations/relations: quality_eligible（D15・SHA前の品質）、
  eligible（最終採用）、reasons（品質理由＋D15・欠測・SHA理由）、従来のdata。
- groups: role、quality_eligible、eligible、reasons、
  data.observations（unionの全主色クラスタ）、data.region_ids、data.area_ratio。
  D15除外assetのunionも保持し、元subjectへ結び付けられる。

品質をquality_eligibleで固定してrights_eligibleの前後を比較し、
SHAはsha256で一度だけ数える。最終寄与はeligibleを使う。
subject不明はNULLのまま保持し、行数・SHA数・subject数を読み替えない。
新列と除外前unionを使う場合は新snapshotが必要。旧artifactは上書きしない。
詳細は[schema追記案](schema-section.md)。

## 検証

- ruff check .、git diff --check、uv build（sdist/wheel）成功。
- Windows全件: 360 passed / 149 skipped、68.92秒。
  DB未指定と既存GPU条件のテストをスキップ。更新した関連単体11件も成功。
- 隔離PostgreSQL 16全件: 508 passed / 1 skipped、70.76秒。
  既存GPU条件付きテストだけスキップ。#74関連24テストはすべて成功。
- SQL照会14回以下、画像処理前の接続返却、同じ入力・並び替えのhash一致、
  多色unionの再現、SA画像のunion・subject・除外理由の保持、
  #81の支持集合、異run・循環・入力欠損・hash改変拒否を検証した。
- 計測sidecarの出力失敗でも成功manifestを残さない公開順序を最終確認し、
  修正後のsnapshot関連24テストも6.12秒で成功した。
- 任意Matplotlib未導入の既存colour警告が1件ある。

専用PostgreSQLは/mnt/data/work/issue-74/pgdata、専用socket・ポート5574。
検証後に正常停止し、DB・ログ・fixtureを保全した。
実全量7,607件の生成・実測と第2段階の公開は未実施。
