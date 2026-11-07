# region-policy-v1（Issue #118）

OneFormer ADE Swin-Lのsemantic mapで既存DINO/SAM2候補を制約する。
既存Transformers 4.57.6 / torch 2.11.0と公式後処理を再利用し、Detectron2は追加しない。
stage、DBモデル、migration、taxonomy、既存の採用設定は変更しない。
旧`sam2-dino`と旧snapshotの再現経路は維持する。

現行の親対応表は[ade-role-parents-v2](region-parents-v2.md)。
外観が粗いbuilding等に分割されることを考慮し、部位候補と粗い親領域の積を取る。
表の版・SHAをrole契約とpolicy/config hashへ含め、旧版成果物を上書き・流用しない。

## モデルの取得条件

2026-11-07のユーザー了承により固定8ファイルの取得と両GPUの3件smokeを実施した。
旧結果は[GPU検証](../bench/issue118/gpu-results.md)、親対応表v2の結果は
[3件＋20件検証](../bench/issue118/parent-v2-results.md)を参照。本番DB更新は行わない。
通常のsegment処理には重みの自動取得を追加しない。

- [著者checkpoint](https://huggingface.co/shi-labs/oneformer_ade20k_swin_large/tree/4a5bac8e64f82681a12db2e151a4c2f4ce6092b2)
  のrevision `4a5bac8e64f82681a12db2e151a4c2f4ce6092b2`を固定する。
- モデルカードはMIT表示。[著者repoのLICENSE](https://github.com/SHI-Labs/OneFormer/blob/main/LICENSE)
  もMIT。モデルカードREADMEのSHAを他ファイルと一緒に固定する。
- Transformers用`pytorch_model.bin`は879,517,517 bytes（約839 MiB）。
  設定類とREADMEを含む8ファイルは合計881,200,070 bytes。
- 著者形式の`250_16_swin_l_oneformer_ade20k_160k.pth`（949,729,587 bytes）は使用しない。
  Mask2FormerのNC重みで代用しない。
- 固定SHA一覧は`src/colorstats/analyze/oneformer-files.json`。
  配布メタデータで固定し、了承後の取得で重み本体を含む全8ファイルの実SHAも両機で照合した。

取得先`models/oneformer/`には一覧の8ファイルだけを置き、次の取得証跡を
`provenance.json`として追加する。`files`は固定SHA一覧と同じ辞書であり、
実ファイルのSHAを全て再計算して一致を確認してから作る。

```json
{
  "repository": "shi-labs/oneformer_ade20k_swin_large",
  "revision": "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2",
  "license": "MIT",
  "files": {"各ファイル名": "対応するSHA-256"}
}
```

`OneFormerProcessor`は通常、`shi-labs/oneformer_demo`からクラス情報を取得する。
本実装は固定JSONから`OneFormerImageProcessor`を直接構成し、metadataから構成した
`oneformer-classes.json`とローカルCLIPTokenizerを使って追加のネットワーク取得を防ぐ。
`from_pretrained`のkwargsによる上書きは初期化に間に合わないため使用しない。
モデルID対応は`oneformer-labels.json`と全150クラスを照合する。
ADE注釈の1始まりIDは受け付けない。例：wall=0、sky=2、tree=4、person=12。

## segmentの入力・処理

既存[segment payload](segment.md)の`method`を`oneformer-region-v1`にし、
`model_paths`へ`oneformer`を追加する。`sam2`と`dino`は従来通り。
同一assetの成功済みprepを指す`input_run_id`と`input_sha256`を必須にする。
prepは長辺2560px以下、EXIF向きは1または未指定とし、座標の暗黙の回転・縮小をしない。

batch=1、短辺640/長辺上限2560、BF16推論を固定する。
公式processorのbatch最大寸法への右・下padは、単画像では追加padを生じない。
公式`post_process_semantic_segmentation(target_sizes=[(height,width)])`で
semantic logitsをbilinear（align_corners=False）復元してからargmaxする。
整数class mapと最終bool maskはPNGで保存し、class mapへ色補間やJPEGを使わない。
統計の画像は元のprepをそのまま使う。

OneFormerのロード前に既存モデルcacheを解放し、OneFormerを解放してから
従来のDINO/SAM2部位候補を生成する。終了・例外時もcacheを解放する。
新policyではOneFormer/SAM2の位置埋め込みLRUと候補モデルの常駐を使わず、
試行間のGPU Tensor保持を防ぐ。旧`sam2-dino`のモデル常駐は維持する。
通常の例外はqueueへ返す。OOMは再試行不可として記録し、#66 runnerは停止フラグを残す。
別モデルや低解像度に切り替えない。
工程別時間、OneFormerのピークallocated/reserved、既存候補生成のVRAM、実行版を記録する。
これは実GPU smokeの代わりにはならない。

## 排他処理と保存

許容semanticクラス表の正本は`region-parents-v2.json`（`region_policy.ALLOW`として読み込む）。
sky/personと対象外クラスは除外し、treeをrock/mountain/snowへ許容しない。
wall/window/roof等には部位ごとの専用クラスと粗いbuilding/house等を許容する。
building/house全体をwallへ変換せず、必ずraw部位候補との積だけを採用する。
roof専用クラスはないため建物・awning/canopyを親とし、snow専用クラスがない雪候補には
mountain/earth/rock等の地表親を許容する。詳細と根拠は親対応表を参照する。

wallの3子ラベル、treeの樹冠・幹はそれぞれ親roleで和集合にする。
その他は既存ラベルごとのroleにする。semantic clip後も複数roleに属する画素は全てvoid。
候補のscoreの大小で決めない。window_glass/window_frameのようにADEクラスで
区別できない交差もvoidにする。未確定子ラベルを個別supportedへ昇格しない。

新しいsegment runの既存RegionとCVAT XMLにはraw候補を保存する。
semantic map、有効roleごとの二値PNG、sky/person/conflict/semantic_mismatch/voidの
除外マスクを別artifactに保存する。既存run・Region・マスクは上書きしない。
sky/person maskは候補がない場所も含む全semantic画素を保存する。
`semantic_pixels`はその総数、`excluded_pixels`はraw候補から失った画素数とする。
画像JSONとrun.parameters.region_policyには以下を固定する。

- policy版・hash、親対応表の版・SHA、prep SHA・寸法、model/revision・全ファイルSHA・id2label hash
- semantic、有効role、除外理由ごとのpath・SHA
- raw/effective画素数、coverage、void率、理由別除外画素数、欠測role一覧

全面voidはcoverage=0、void率=1、全role欠測とし、観測を作らない。
有効領域があっても白飛び・黒つぶれ・透過だけなら色観測は欠測になる。

## 後続の共有payload

`color.region_inputs(session, asset_id, run_id)`と併せて
`color.region_policy_input(session, asset_id, run_id)`を呼ぶ。
後者がNoneでない場合は、戻り値を`payload["region_policy"]`へそのまま渡す。
戻り値の`run_id`はsegment run、pathはqueueが公開した不変path、SHAはsegment時点の値。
`input_sha256`、`input_run_id`、`region_run_id`も必要。
別の`mask_path`/`person_mask`との重ね合わせは拒否し、新しい制約を別runへ固定させる。

#66の`m3_analysis.run_batch`は新方式でこの参照を渡す。
`freeze --settings <別のYAML>`で新方式を明示指定できる。
既存`configs/segment_stats.yaml`の採用方式は変更しない。
新方式を要求したfreezeで旧segmentの再利用を拒否する。

shade/colorはraw Regionから子観測を作らず、有効roleから直接色を計算して
出力JSONの`roles`へ保存する。schema追加や親roleを偽の子Regionへ割り当てる処理はしない。
shadeの補正推定にも有効領域だけを使い、観測色と推定色は同じ画素で計算する。
新policyの参照省略・差替え、旧観測の登録を取引で拒否する。

snapshotは選択segmentとcolorのpolicy一致を確認し、有効role maskから直接色を再計算して
groups Parquetへ出す。旧raw Region ORへのfallbackはしない。
新policyのgroupsは`quality_eligible=false`、理由`region_policy_quality_unvalidated`とする。
旧方式の品質判定を継承せず、後続Dでの合格・明示的な採用対応まで全量統計へ進めない。

## 検証と未実施事項

`tests/test_region_policy.py`は小さな合成mask、色を変えたsky/person/tree画素、
mockモデルによる座標復元呼出し・オフライン初期化・解放順・OOM伝播を検証する。
`tests/test_region_policy_db.py`は隔離DBでprep→segment→shade/color、
snapshotのParquet生成、raw保全、由来、不正再利用のrollbackを検証する。
既存依存を再利用するWSL隔離検証は`bench/issue118/verify.sh`。

実GPUの8GB/12GBで各3件smoke、ピークVRAM、重み本体SHA、工程間のモジュール解放を検証済み。
実OOMは未発生。OOM時停止はmock/隔離DBで検証した。解像度やモデルの暗黙変更はしない。
旧親表で建物の有効画素が0になった診断は[旧GPU結果](../bench/issue118/gpu-results.md)に保全した。
現行表では粗い建物親の許容を追加し、前回3件と追加20件をubuntu-2の別の隔離出力で検証済み。
建物有効率はそれぞれ2.4211%・8.8645%、空混入と建物/地形交差は0となった。
画素GTに基づく品質合格と後続Dの採否判断は別工程とし、smokeの排他性だけで合格にしない。
全量統計・本番DB更新は実行していない。
