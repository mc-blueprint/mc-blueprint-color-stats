# shade stageと同一建築の一致度評価

Issue #46。既存のPillow・NumPy・Colourとqueue、colorの部位入力契約を再利用する。
スキーマ変更・既存観測の更新は行わない。`shade=colorstats.analyze.shade`をworkerへ指定する。

## 入出力

payloadの必須項目は`method`（`none` / `gray-world` / `intrinsic`）、`input_path`、
`output_path`（JSON）、`license_class`、`taxonomy_version`、`region_run_id`、`regions`。
`regions`は`color.region_inputs(session, asset_id, region_run_id)`の戻り値を使う。
prep画像の場合は`input_run_id`も指定する。model PNGとhuman polygonの両方を受け付ける。
原画像のパスはasset.storage_path、prep画像は同じassetの成功済みprepの不変出力に限る。
model領域は同じ画像・prepから生成されたものに限る。入力runのライセンス制約を伝播する。
投入前に`shade.config_hash(payload)`を計算し、画像・マスク・重みは以後変更しない。
計算時の不一致や推論失敗はqueueの通常失敗として扱う。空の検出結果は空の成功となる。

Gray-Worldは画像全体の有効画素から線形sRGBのチャンネル平均を計算し、その平均値へ
各チャンネルを揃える。補正なしは同一の集約法による対照である。
各部位の不透明画素から全RGBが5以下・250以上の画素を除き、同じ画素集合で
observed_oklabとmaterial_oklabの平均（dominant）・5分位点を求める。
1部位1観測、area_ratio=1。ここでのdominantは領域平均であり、colorの5クラスタと異なる。
material_confidenceは元マスクに対する有効画素率で、材質色の正解確率ではない。
有効画素なしは欠測とする。暗部除外やマスク誤差の影響は別途残る。

## Intrinsic（評価専用）

公式[compphoto/Intrinsic](https://github.com/compphoto/Intrinsic)の
`1a93aafaaf7dbe11be7ec86323d9a06e5950966d`を、プロジェクト本体とは別の評価venvに配置する。
ライセンスの一次情報は2026-11-02に以下を確認した。

- [使用revisionのLICENSE](https://github.com/compphoto/Intrinsic/blob/1a93aafaaf7dbe11be7ec86323d9a06e5950966d/LICENSE):
  ソフトウェアの使用・改変を含む再配布は学術用途に限定され、原著者への帰属が必要。
- [同revisionのREADME「License」](https://github.com/compphoto/Intrinsic/blob/1a93aafaaf7dbe11be7ec86323d9a06e5950966d/README.md#license):
  実装は学術用途限定で、コードまたはモデルを使う場合は論文の引用を求める。
  商用などのライセンスは著者・SFUへの問い合わせ先が案内されている。
- [公式v2.0重み配布ページ](https://github.com/compphoto/Intrinsic/releases/tag/v2.0)と
  [配布ファイル一覧](https://github.com/compphoto/Intrinsic/releases/expanded_assets/v2.0):
  使用する`stage_0.pt`〜`stage_3.pt`の配布元を確認した。
  配布ページにコードとは別のモデル利用許諾は記載されていないため、上記READMEとLICENSEに従い
  モデルも`academic_only`として扱う。重みの再取得・規約同意は行っていない。

`license_class=academic_only`を必ず付与し、入力の制約とも合成する。
商用パイプラインへの採用候補にはしない。通常依存への追加・コードや重みの同梱はしない。

公式v2.0 releaseの`stage_0.pt`〜`stage_3.pt`を同じディレクトリへ事前配置し、
payloadへ`model_path`と`evaluation_only: true`を指定する。
stage=3のhr_alb（線形RGB）をsRGBへ変換して使用する。推論長辺512、seed=0、
PyTorch deterministic algorithmsを有効にし、補間で元画像寸法へ戻す。
モデルは計算子で常駐し、重みハッシュが変われば再読込みする。stage中のダウンロードは行わない。
実重みのSHA-256、公式revision、評価区分はrun.parametersへ記録する。
公式loaderのbackbone取得は、torchvision/geffnetによる重みなしの同一構造へ置換し、
公式stage重みをstrictに読込む。実際に使うIntrinsic・altered_midas・chrislibのPythonファイルの
ハッシュと主要依存のバージョンも設定ハッシュに含める。
EfficientNetには上流hubconfと同じ`geffnet==1.0.2`（Apache-2.0）を評価venvへ導入する。
現行timmはこの旧backboneの属性と互換でないため、この初期化には使わない。
CUDA実行前に`CUBLAS_WORKSPACE_CONFIG=:4096:8`を環境へ指定する。
上流のordinal等化はNumPyで画素を無作為抽出するため、NumPyのseedも画像ごとに0へ固定する。
NumPyの乱数状態とPyTorchの決定性・cuDNN設定は推論後（例外時も）に復元する。
同じversionの依存・CUDA環境を再実行にも使う。別環境でのビット一致は保証しない。

## 評価

本番DBはREAD ONLY取引で元metadataを取得するだけとし、画像・推論・queueは一時DBへ隔離する。
同一建築群にはasset ID、原本SHA、タイトル・撮影地・Commonsカテゴリなどの判断根拠と
確認状況を保存する。原本SHAや出典ページが同じ画像を独立な標本として重複計上しない。
同じ建築の同じ部位ラベルでも別の面・材質が混ざりうるため、これは正解色の誤差ではなく
材質色推定の一致度である。低い値だけで正確さは証明できない。

`python -m colorstats.analyze.shade_evaluation samples.json --output comparison.json`で再集計する。
samplesは各画像・部位・手法に1行、subject_id/asset_id/sha256/label_source/label/method/
material_oklab（OKLab 3成分）を持つ。複数instanceは有効画素数で加重平均してから渡す。
3手法すべてに存在する同じ画像対のユークリッド距離ΔE_ok（0〜1のLスケール）を使い、
部位内の画像対、建築内の部位、建築間の順に平均する。共通画像が2枚未満なら集計しない。
modelとhumanは別集計し、human未入力はnullと件数0で報告する。
マスク修正後はhuman runをregion_inputsへ渡して同じshadeジョブを新規設定hashで再計算する。

## 既存パイロットでの比較結果（2026-11-02）

755 asset（うちreal_building 480件）から同一建築の候補19枚を照合し、5建築15枚を採用した。
建築名・Commonsカテゴリ・座標による同定根拠、asset ID・原本SHA-256・撮影日時、
prep/region run IDと除外理由は[同定manifest](../bench/issue46/manifest.json)に保存した。
AI画像照合は補助であり、人手による建築同定は未実施。
松山城の門と天守が混在した群と、ほぼ同構図・同時刻の連写2枚は除外した。

SAM 2.1 tiny・Grounding DINO tinyのmodel領域を使い、`wall_main` / `roof_surface` /
`door` / `window_frame`を比較した。5建築、18建築×部位、58画像対×部位、
各手法55画像×部位（合計165行）。表は部位内の画像対、建築内の部位、建築間の順に
平均したΔE_okで、小さいほど推定色が一致する。OKLabのLは0〜1スケール。

| 建築 | 画像数 | 補正なし | Gray-World | Intrinsic（評価専用） |
| --- | ---: | ---: | ---: | ---: |
| Dome of the Rock | 3 | 0.060142 | 0.058457 | 0.036546 |
| Dülmen St. Viktor | 4 | 0.146268 | 0.138891 | 0.122408 |
| 掛川城天守 | 2 | 0.138573 | 0.165014 | 0.126603 |
| Münster St. Paulus | 4 | 0.164153 | 0.163504 | 0.129987 |
| Strasbourg Cathedral | 2 | 0.222117 | 0.250149 | 0.256675 |
| **建築間平均** | **15** | **0.146250** | **0.155203** | **0.134444** |

暫定の推奨は**通常処理では補正なしを維持**する。Gray-Worldは平均で約6.12%悪化したため
一律には採用しない。Intrinsicは平均で約8.07%、5建築中4建築で改善したが、
Strasbourgでは悪化し、学術用途限定のため商用パイプラインには採用しない。

集計単位は5建築で、58画像対×部位は独立標本ではない。
建築単位の対応を保つbootstrap（5建築を復元抽出、5^5=3125通りを全列挙、
百分位法・線形補間）による「手法 − 補正なし」の平均差は以下のとおり。
負なら改善で、両手法とも95%区間は0を跨ぐ。優劣が確立したという判断ではなく、
補正なしの維持は小標本と利用条件に基づく暫定の運用判断である。

| 手法 | 平均差 | 建築単位bootstrapの95%区間 |
| --- | ---: | --- |
| Gray-World | +0.008953 | [-0.003754, +0.021771] |
| Intrinsic | -0.011806 | [-0.027929, +0.011508] |

部位の対応は建築・ラベル単位で、別の面・材質も比較に入る。
humanマスク評価は未実施（3手法とも0建築・0対、値はnull）。
画角・日照面・素材・経年変化・model分割誤りが残り、正解色からの誤差や一般的な優位性は示さない。
人手同定とhumanマスク、および#44後のデータで再評価する。

### 再集計

画像・重み・大きな推論生成物は含めず、再集計に必要な
[samples.json](../bench/issue46/samples.json)、
[比較集計](../bench/issue46/comparison.json)、
[bootstrap集計](../bench/issue46/bootstrap.json)をGit管理対象へ置いた。
samplesは最終v4の観測値で、SHA-256は
`d119dac58288443365ad1bae4524f2f34149148e85a6774e1cb19fe5a6148508`。
これらは推論の再実行用画像・マスクを含まないため、以下は保存済み観測値の再集計である。

```sh
python -m colorstats.analyze.shade_evaluation bench/issue46/samples.json --output comparison.json
```

出力JSONを`bench/issue46/comparison.json`と比較する。
bootstrap区間は同じ建築順で差を作り、以下で再計算できる（プロジェクト環境のNumPyを使用）。

```python
import json
from itertools import product
from pathlib import Path

import numpy as np

methods = json.loads(Path("bench/issue46/comparison.json").read_text())["model"]["methods"]
subjects = sorted(methods["none"]["by_subject"])
for method in ("gray-world", "intrinsic"):
    differences = [methods[method]["by_subject"][s] - methods["none"]["by_subject"][s]
                   for s in subjects]
    means = np.mean(list(product(differences, repeat=len(subjects))), axis=1)
    print(method, np.quantile(means, [0.025, 0.975], method="linear"))
```
