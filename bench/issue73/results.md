# 統計用分割の採用判定（Issue #73）

2026-11-03、ubuntu-2。起点 develop `69ebe7cdb81bcf5c5d6d6efed377be4c63b19359`。
**調整は不採用。sam2-dino、threshold=0.35、text_threshold=0.25、shade noneを維持する。**
個別ラベルのsupported集合は空であり、M3の建築・地形の有用性条件は未達。
改善なしもIssueの完成結果として扱い、品質閾値は下げない。

## 事前固定と入力群

- 既存#41のCMP 606枚・ADE 617枚を評価専用で使用。本番統計の入力・DB登録には使わない。
- 事前にseed=73、細部3群=band_course/cornice/relief、主要4群=wall/window/door/column、
  2候補threshold=0.45/0.55を固定。プロンプト・text_threshold・重複の扱いは既定のまま。
- SHAまたは既知subjectの連結成分を一群とし、群の最小IDとseedのSHAで二分する。
- CMP 調整324／holdout282、ADE 調整310／holdout307。SHA・既知subjectの集合間リークは各0。
- #72確定スナップショットrun: `b5ad2583-fcb2-4ffe-a43f-ab9028729852`。
- 公開画像と一致する確定subjectは0件。公開資料に対象同定表はなく、未知の同一対象を
  完全に除いた保証はない。既にM2で全体評価したデータであり、未使用の盲検とは主張しない。
- 元ZIPを#41 manifestのSHAと照合。画像・正解・縮小RGB・予測レコード・全マスクのSHA、
  モデル重み・設定、対応表、群、code hashはplan.jsonに保存する。画像・マスクは再配布しない。
- 最初にfreezeで同じholdoutの既定基準を保存し、その後tuneの指標だけで候補を選択した。
  反証による境界比較と証跡照合の修正後に再生成し、入力群・全hash・基準値が初回と
  一致することをfreeze-proof.jsonで照合した。閾値・候補・選択則は変更していない。

## 同一holdoutでの採否

| 指標 | 既定0.35 | 候補0.45 | 差 | 必要な差 | 判定 |
|---|---:|---:|---:|---:|---|
| detail_iou | 0.069324 | 0.063490 | -0.005834 | >= +0.02 | 未達 |
| detail_precision | 0.072709 | 0.081642 | +0.008933 | >= +0.02 | 未達 |
| wall_precision | 0.518538 | 0.518273 | -0.000266 | >= +0.02 | 未達 |
| major_iou | 0.319483 | 0.272350 | -0.047133 | >= -0.01 | 未達 |
| ade_iou | 0.148107 | 0.177447 | +0.029340 | >= -0.01 | 通過 |

全5条件の同時達成が必要。丸めによる閾値ちょうどの誤判定だけを1e-12で吸収する。
0.45は調整集合の細部IoU＋細部precision＋wall precisionの和で選んだ1候補であり、
holdoutの結果を見て別候補へ選び直していない。個別画素数・coverageはbaseline.json、
tuning.json、decision.jsonに保存した。IoU等はラベル群のマクロ平均、画素数は全画像の和。


## ラベル支持

公開正解に一対一対応するラベルは、全対応データでholdout precision>=0.50かつTP>0を
必要とする。複数taxonomyラベルの和集合しか評価できない群はgroup_onlyとし、個別ラベルを
validatedへ昇格させない。例えばADE treeのprecisionが高くても、幹と樹冠を個別に保証しない。
未対応の屋根等やモデルconfidence、#41のsol判定もvalidatedの根拠にしない。
診断値は保持するが、M4へ提供するsupported集合からは除く。

| ラベル | 状態 | holdout precision（対応データ） |
|---|---|---|
| accent_other | group_only | cmp: 0.028961 |
| arch | unmapped | 対応なし |
| band_course | below_gate | cmp: 0.142922 |
| beam | unmapped | 対応なし |
| chimney | unmapped | 対応なし |
| column | below_gate | cmp: 0.048430、ade: 0.000000 |
| corner_quoin | unmapped | 対応なし |
| cornice | below_gate | cmp: 0.046243 |
| door | below_gate | cmp: 0.501542、ade: 0.011470 |
| dormer | unmapped | 対応なし |
| eave | unmapped | 対応なし |
| fence | below_gate | ade: 0.112944 |
| floor_visible | unmapped | 対応なし |
| gable_trim | unmapped | 対応なし |
| gable_wall | group_only | cmp: 0.518538、ade: 0.070066 |
| ground_grass | below_gate | ade: 0.368049 |
| ground_soil | below_gate | ade: 0.277318 |
| half_timber | unmapped | 対応なし |
| light_fixture | unmapped | 対応なし |
| path | below_gate | ade: 0.252510 |
| path_natural | below_gate | ade: 0.021862 |
| plinth | unmapped | 対応なし |
| railing | below_gate | ade: 0.040385 |
| relief | group_only | cmp: 0.028961 |
| ridge | unmapped | 対応なし |
| rock_face | group_only | ade: 0.065893 |
| rock_scree | group_only | ade: 0.065893 |
| roof_surface | unmapped | 対応なし |
| sand | below_gate | ade: 0.039250 |
| shutter | below_gate | cmp: 0.127439 |
| snow_ice | unmapped | 対応なし |
| stairs_entry | below_gate | ade: 0.104542 |
| tree_trunk | group_only | ade: 0.859844 |
| vegetation_attached | unmapped | 対応なし |
| vegetation_low | unmapped | 対応なし |
| vegetation_tree_canopy | group_only | ade: 0.859844 |
| wall_main | group_only | cmp: 0.518538、ade: 0.070066 |
| wall_secondary | group_only | cmp: 0.518538、ade: 0.070066 |
| water | below_gate | ade: 0.476889 |
| window_frame | group_only | cmp: 0.610448、ade: 0.000920 |
| window_glass | group_only | cmp: 0.610448、ade: 0.000920 |

## 実行と再現

- 画素評価は既存pixel_counts/scoresを再利用。正解未対応画素は無視し、同一群は和集合、
  異なる群への重複予測は誤ラベル側のFPとして残す。正解縮小はnearest、画像は512px上限。
- 既定0.35の全1,223枚の画素数を再計算し、保存済み#41の画像ごとのTP/FP/FNと全件一致。
- 候補は既存DINO検出scoreをstrict > thresholdで抽出。SAMはboxごとに独立なので、
  閾値を上げる今回の候補に再利用できる。閾値を下げる候補には使えない。
- CMP・ADEの最初の調整画像各1枚について、既定0.35・候補0.45をRTX 4070で再推論。
  4回ともラベル順・領域数・全boolマスクがキャッシュ抽出と完全一致。全1,223枚の
  GPU再推論は実施しておらず、この2画像の確認を全データの独立精度検証とは扱わない。
- 最終4回の推論合計 13.882 秒、
  ピーク割当VRAM 2,045,235,200 bytes。
- #41のsol記録は装飾・壁の過剰検出という定性的な整合確認だけに使用し、画素真値にしない。
- 公開データ・モデル・#41成果は読み取りのみ。ubuntu-1のpilotは再開していない。

```sh
export PYTHONPATH=src
DATA=/mnt/data/work/issue-41/public
CACHE=/mnt/data/work/issue-41/evaluation
OUT=/mnt/data/work/issue-73/新規の評価ディレクトリ
PY=/mnt/data/work/issue-40/venv/bin/python
SUBJECTS=/mnt/data/work/issue-72/production-results/review-applied-02.json
MODELS=/mnt/data/work/issue-40/models
$PY bench/issue73/evaluate.py freeze --data "$DATA" --cache "$CACHE" --output "$OUT" --subjects "$SUBJECTS"
$PY bench/issue73/evaluate.py tune --data "$DATA" --cache "$CACHE" --output "$OUT"
$PY bench/issue73/evaluate.py gpu --data "$DATA" --cache "$CACHE" --output "$OUT" --models "$MODELS"
$PY bench/issue73/evaluate.py finish --data "$DATA" --cache "$CACHE" --output "$OUT"
```

freezeは既存出力先を拒否し、各フェーズの成果も上書きしない。後続フェーズでは
固定コード・ZIP・対応表・レコード・マスクと計画のhashを検証する。
plan.jsonは入力群の正本、baseline.jsonは固定基準、tuning.jsonは候補選択、
gpu-check.jsonは再推論証跡、decision.jsonは採否とラベル支持表の正本。
元の初回成果は /mnt/data/work/issue-73/evaluation、最終成果は evaluation-final に保全。

## #66への引継ぎ

configs/segment_stats.yamlのsegment項目を既存payloadへ使い、実機のmodel_paths、
taxonomy版、成功prepの不変input_path/input_run_id、出力パス・入力区分を追加する。
shade.method=none。settings_sha256はsegment/shadeだけをsort_keys=True・
separators=(',', ':')のJSONにしたSHAであり、入力・モデル込みのstage config_hashとは別物。
stageの既存config_hash/投入時照合を省略しない。quality.supported_labels=[]を保持し、
未検証ラベルの観測を主統計へ流さず診断として区別する。公開画像は統計入力にしない。
構成・依存・保存形式の既存契約は変更せず、追加依存・新規モデル・人手正解は導入していない。

## 検証・反証

- Windows / Python 3.12の専用venvでruff・pytest・sdist/wheelビルドを実行。
- Ubuntu / Python 3.12、PostgreSQL 16.15の新規UTF-8空DBで最終pytest:
  **480 passed, 1 skipped**（78.44秒）。skipは既存GPU DB統合テストで、
  本Issueの独立GPU再推論4回は別に実行済み。
- 初回の隔離DBはSQL_ASCIIだったため接続初期化に失敗した。UTF-8 DBへ修正。
  再実行時の既存migration管理表による空DB前提違反も、新規DBで解消した。
  本番DB・#72のDBは変更していない。
- SHA／subjectの推移的な群化、入力順独立性、全採用条件、欠測、
  閾値ちょうど／直下、複数データ対応、和集合ラベル・未対応ラベルの扱い、
  固定対応表・予測マスクの改変拒否を検証。
- 既定公開評価とモデル推論を再利用し、追加モデル・依存・保存形式変更はない。
- 残存リスクは未知subjectの重複、公開ラベルの粒度・評価画素範囲と実写真との違い、
  個別ラベル支持の不足。新しい独立正解や十分な支持を得るまでM3有用性未達を維持する。

最終Windows全体は **345 passed, 136 skipped**（24.11秒）。lock対象依存の版差は0件。
最終ruff・git diff --check・sdist/wheelビルドは成功。
保存成果の連鎖hash、入力群リーク、採否・支持表の再計算、#47プロンプトとの整合も確認した。
