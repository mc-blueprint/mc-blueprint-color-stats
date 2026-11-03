# 支持ラベル0件の診断（Issue #81）

2026-11-03、ubuntu-2。起点 `1fa8dca36fd68b4f9c484ba9e1e24bfc223e3e79`。
**sam2-dino／threshold=0.35／text_threshold=0.25／shade noneを維持する。**
個別のdoorと、直接和集合としての建築wall・地形treeが既存の品質ゲートを通る。
子ラベルの個別支持、全面画素の精度、M3完成条件4の本番subject支持は保証しない。

## 判断の順序と意味の根拠

1. #73の既知の結果・taxonomy・ADE一次資料を確認し、
   [definition.md](definition.md)と[label-map.yaml](label-map.yaml)を再集計前に保存した。
   #73の評価済み画像なので、新しい盲検とは主張しない。
2. ADEの物体レベルと部品レベルは別正解であり、wallとbuildingは同義ではない。
   windowpaneもガラス＋枠の完全な和集合ではない。door/columnも建物内の
   部品としての網羅性を保証しないため、この4群をADEの建築部位ゲートから外した。
   精度の低い群だけを選んだのではなく、同じ物体／部品の不一致を4群に適用した。
   stairs/railing/fence等の独立した構造物・地形の既存対応は変更していない。
   buildingを壁の正解にすると屋根・開口まで壁と扱うため追加しない。
3. 変更前の全対応IDを評価画素集合として維持した。群を外してもその画素は負例に残り、
   残した群のTP/FP/FN・precisionは変更前後で完全一致する。
4. #41の全1,223画像の画素数、#73のtune/holdout両基準値を再現。
   ADE全2,000枚の原寸正解から屋外選別を再実行し、617枚のリストと完全一致。
5. 個別支持と粗い役割を別に判定した。wallはtaxonomy第一階層に完全一致。
   treeは幹＋樹冠という既存評価の和集合に限る粗い役割で、
   terrain taxonomyの新しい親語彙ではない。windowはopening全体に一致しない。
6. wall・treeの両ドメインの粗い役割がゲートを通ったため、事前条件に従い
   代替手法の比較・新しい重み取得は行わない。閾値0.50を変更していない。
   モデル・重み・既存プロンプトとライセンス判断は#40/#47を再利用し、追加依存はない。

一次資料：
[ADE公式READMEの階層](https://github.com/CSAILVision/ADE20K/blob/main/README.md#structure)、
[著者論文のSceneParse150とpart segmentation](https://people.csail.mit.edu/bzhou/publication/scene-parse-camera-ready.pdf)。
公式の物体／部品分離に基づく評価用途の判断であり、特定画像の窓やドアが
すべてbuildingに埋まっていると確認したものではない。

## 混同行列と無視画素の診断

[confusion.json](confusion.json)は、tune/holdout別、予測ラベル別と既存群別に、
ADE正解の全151 IDへ落ちた画素数を持つ。配列の添字が正解ID。
同じ予測ラベル／群のマスクは和集合、異なる予測ラベル間の重複は残す。
旧ゲートのFPは旧評価IDのうち当該正解ID以外に落ちた画素だけ。
building（id 2）やvoid（id 0）は元から無視され、旧FPには入っていない。

| ADE holdoutの予測群 | 全予測画素 | 旧評価内FP | building上 | 全無視画素 |
|---|---:|---:|---:|---:|
| wall | 13,246,488 | 2,395,888 | 8,401,555 | 10,670,082 |
| window | 10,453,272 | 5,045,011 | 1,789,287 | 5,403,617 |
| door | 1,869,603 | 762,187 | 437,976 | 1,098,572 |
| column | 3,322,876 | 707,008 | 1,518,893 | 2,615,868 |
| tree | 8,056,386 | 513,795 | 2,676,554 | 4,390,506 |
| water | 7,239,821 | 2,065,179 | 449,497 | 3,291,942 |

**原因は対応の意味のずれとモデルの誤検出の両方。**
wall予測の63.42%はbuildingに落ちるが、buildingは旧評価でFPではない。
したがって「buildingが壁のFPになりprecisionが下がった」という説明は誤り。
建物外のtree/earth等への誤検出は旧FPとして残り、window/columnの低精度も
対応表だけで全て説明できない。全画素の行列からこの区別を再計算できる。

ADE holdoutの総45,015,651画素中、旧評価内14,913,584（33.13%）、
無視30,102,067（66.87%）。建物・空・道路などの既知負例も無視されている。
品質ゲートは**対応画素内の条件付きprecision**であり、全面精度ではない。
例えばtreeの非void全画素での診断precisionは約0.430、waterは約0.281。
これらを0.50通過と扱わない。今回の改定でも#73の評価画素範囲は広げていない。
ゲートの支持範囲を超えた利用には、全既知負例を含む別評価や独立正解が必要。

屋外選別はsky>=2%または指定屋外ID>=50%、indoor<=1%、subject>=20%という
既存の代理条件。原寸での2,000枚中617枚を維持し、建物だけ・雪だけの画像を
網羅する真の屋外分類とは扱わない。評価縮小後の比率で選び直していない。

## 改定前後の支持

判定の正本は[decision.json](decision.json)。holdoutはCMP 282枚、ADE 307枚。
改定前・後の全画素数と指標、両分割のcoverage、ドメイン別4状態も保存する。

| 対応群 | CMP precision（前後同じ） | ADE precision（旧定義） | 改定後の支持範囲 |
|---|---:|---:|---|
| wall | 0.518538 | 0.070066 | CMPの3ラベル和集合、第一階層wall |
| window | 0.610448 | 0.000920 | CMP和集合のみ。opening全体は未対応 |
| door | 0.501542 | 0.011470 | CMPの個別door |
| column | 0.048430 | 0.000000 | CMPでもbelow_gate |
| tree | 対応なし | 0.859844 | ADEの幹＋樹冠の和集合のみ |
| water | 対応なし | 0.476889 | below_gateのまま |

個別状態のJSONは既存APIのvalidatedを維持し、以下ではsupportedと表記する。
group_onlyは、その和集合がゲートを通ったかとは別の「個別を保証できない」状態。
reliefやrockのように群自体が低精度でも個別状態はgroup_onlyとなる。

### real_building

| ラベル | 状態 | holdout precision |
|---|---|---|
| accent_other | group_only | cmp: 0.028961 |
| arch | unmapped | 対応なし |
| band_course | below_gate | cmp: 0.142922 |
| beam | unmapped | 対応なし |
| chimney | unmapped | 対応なし |
| column | below_gate | cmp: 0.048430 |
| corner_quoin | unmapped | 対応なし |
| cornice | below_gate | cmp: 0.046243 |
| door | supported | cmp: 0.501542 |
| dormer | unmapped | 対応なし |
| eave | unmapped | 対応なし |
| fence | below_gate | ade: 0.112944 |
| floor_visible | unmapped | 対応なし |
| gable_trim | unmapped | 対応なし |
| gable_wall | group_only | cmp: 0.518538 |
| half_timber | unmapped | 対応なし |
| light_fixture | unmapped | 対応なし |
| path | below_gate | ade: 0.252510 |
| plinth | unmapped | 対応なし |
| railing | below_gate | ade: 0.040385 |
| relief | group_only | cmp: 0.028961 |
| ridge | unmapped | 対応なし |
| roof_surface | unmapped | 対応なし |
| shutter | below_gate | cmp: 0.127439 |
| stairs_entry | below_gate | ade: 0.104542 |
| vegetation_attached | unmapped | 対応なし |
| wall_main | group_only | cmp: 0.518538 |
| wall_secondary | group_only | cmp: 0.518538 |
| window_frame | group_only | cmp: 0.610448 |
| window_glass | group_only | cmp: 0.610448 |

### real_terrain

| ラベル | 状態 | holdout precision |
|---|---|---|
| ground_grass | below_gate | ade: 0.368049 |
| ground_soil | below_gate | ade: 0.277318 |
| path_natural | below_gate | ade: 0.021862 |
| rock_face | group_only | ade: 0.065893 |
| rock_scree | group_only | ade: 0.065893 |
| sand | below_gate | ade: 0.039250 |
| snow_ice | unmapped | 対応なし |
| tree_trunk | group_only | ade: 0.859844 |
| vegetation_low | unmapped | 対応なし |
| vegetation_tree_canopy | group_only | ade: 0.859844 |
| water | below_gate | ade: 0.476889 |

## #66・#75・メインへの引継ぎ

- 推論設定は変更せず、settings_sha256も#73と同じ。
  quality.supported_labels=[door]、supported_groups=[real_building/wall, real_terrain/tree]。
  評価・定義・対応表の参照hashを固定設定へ保存した。
- wallとtreeを採用する場合、#66/#75は同じasset内の構成ラベルのマスク和集合から
  色・面積・関係を直接求める。重複マスク・子観測を独立標本として足さない。
  既存Region・taxonomy・runの保存形式は変更しない。treeをRegionの新語彙へ登録しない。
  union観測を後続snapshotで表す契約は#74/#75側で明示する必要がある。
- 平滑化は条件や標本不足への借用であり、未支持の子やopeningを支持済みにしない。
  主統計は個別doorまたは明示した和集合に限定し、その他はdiagnostic_only。
- M3完成条件4の確定subject>=10かつsubject基準n_eff>=10は#66/#75で未計測。
  公開正解の品質ゲート通過だけでM3完成としない。
- 重要な新知識はこの結果とdefinitionが正本。共有の外部知識への統合はメインへ返す。
  #79のファイル・本番DB・#41/#73の既存成果・ubuntu-1のpilotは変更していない。

## 再現と証跡

```sh
cd /mnt/data/work/issue-81/code
PYTHONPATH=src:. /mnt/data/work/issue-40/venv/bin/python -m bench.issue81.evaluate \
  --data /mnt/data/work/issue-41/public \
  --cache /mnt/data/work/issue-41/evaluation \
  --output /mnt/data/work/issue-81/新規出力先
```

出力先は新規作成のみ。モデル再推論・DB登録・公開画像／マスクの再配布はしない。
ZIP・画像・正解・全マスク・予測設定は#73のplanに照合。
コード・定義・新対応表・混同行列のhashはdecisionに保存。
最終出力はubuntu-2の /mnt/data/work/issue-81/evaluation-final。
最終再集計32.704秒、GPU実行0回・追加重み0件。GPU速度／VRAMは今回未計測。

Windowsの初回転送ではJSONのCRLF、LFへ一律変換した次の転送では
#73がCRLFでhash固定した旧対応表が一致せず、評価開始前に拒否された。
最終コードはテキスト証跡をGitと同じLFで照合し、#73の旧対応表hashだけは
固定時のCRLFへ正規化して照合する。画像・正解・ZIP・マスクは生バイトで照合する。
元成果を変更せず改行差を解消し、最終再集計の全数値と混同行列が初回成功時と完全一致。
改行差で拒否された試行の空出力先も既存成果を上書きせず保全した。

## 検証・反証

- Windows / Python 3.12：全pytest **349 passed, 136 skipped**（24.89秒）。
- Ubuntu / Python 3.12 / 隔離PostgreSQL 16.15：全pytest **484 passed, 1 skipped**（78.05秒）。
  最終DBはissue81_release_ready。専用クラスタは検証後に停止しデータを保全。
  本番DB、#72/#73/#79のDB・コード・サービスは操作していない。
- DBの初回検証は起動スクリプトのmainガード欠落でspawn子が再初期化して失敗。
  起動スクリプトを修正し、新規UTF-8空DBで再検証した。実装の失敗を成功扱いにしていない。
- skipはWindowsでは既存DB/GPU要件、Ubuntuの1件は既存GPU DB統合テスト。
  今回は再推論なしなので当該GPUテストを実行していない。
- ruff、sdist/wheelビルド、git diff --check成功。導入済み依存とuv.lockの版差0件。
  両環境の既存ColourUsageWarning（任意Matplotlibなし）1件はテスト失敗ではない。
- 負例画素維持、完全な和集合と部分集合の区別、全対応データのゲート、
  0.50境界・直下・TP=0、設定と証跡hash・支持再計算、改行差の回帰を確認。
- 全クラス混同行列を含む最終再集計が初回成功結果と完全一致。
  APIのvalid_ids省略時は従来動作を維持し、既存画素評価とラベル支持を再利用した。
- 実装・診断・必須検証・公開準備を完了。commit・push・PR作成は依頼どおり未実施。
  未解消なのは条件付き品質ゲートの範囲、未知subjectの重複、屋外代理条件の偏り、
  本番でのsubject/n_eff支持、和集合の後続snapshot表現である。
