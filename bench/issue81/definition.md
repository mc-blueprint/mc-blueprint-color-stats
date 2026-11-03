# 評価定義の事前判断（Issue #81）

2026-11-03。#73の既知の結果を出発点とし、#81の画素再集計より先に固定する。
新しい盲検とは主張しない。精度を見た対応の再選択・閾値変更はしない。

1. ADEChallengeData2016の150クラス物体注記は部品階層の正解ではない。
   wallはbuildingと同義でなく、windowpaneはガラス＋枠の完全な和集合でもない。
   door/columnも建物の部品としての正解が網羅される保証がない。
   ADEのwall/window/door/columnを建築部位のゲートから外す。
   buildingを壁の正解に追加すると屋根・開口を壁として許すため追加しない。
   他の対応・屋外選別・分割・モデル・プロンプトは変更しない。
2. 削除したクラスを負例から消さない。評価画素集合は#41の対応IDのまま固定する。
   ADE全151 ID（void=0を含む）への予測ラベル別混同行列を別途保存し、
   元ゲート内FP、building上の予測、無視画素上の予測を区別する。
   正解縮小後の屋外判定を原寸での選別に代用しない。
3. 個別支持は全対応データのholdout precision>=0.50かつTP>0。
   建築wallの3ラベル和集合はtaxonomy第一階層と完全一致するので、
   同じ和集合の直接画素評価に限って第一階層の支持を認める。
   windowはopeningの一部であり、opening全体へ昇格させない。
   地形treeは既存評価の幹＋樹冠の和集合という粗い役割に限定する。
   terrain taxonomyには親階層がないためtreeを新しいtaxonomy語彙とは扱わない。
   #75はこの明示的な和集合を採用する場合だけ粗いtree分布を出せる。
   個別ラベルへの平滑化による支持の捏造はしない。
4. wallとtreeの両ドメインの粗い役割が支持されれば代替手法は比較しない。
   いずれかが未達なら権利条件を満たす代替を検討する。閾値0.50は維持する。

根拠：
- [ADE公式README](https://github.com/CSAILVision/ADE20K/blob/main/README.md#structure)：
  物体マスクとparts階層を別々に配布。
- [著者論文 §3/§4](https://people.csail.mit.edu/bzhou/publication/scene-parse-camera-ready.pdf)：
  SceneParse150とbuilding等のpart segmentationは別課題。
- docs/design.md §6.2・§12 M3完成条件4。品質ゲートと
  本番での確定subject数・n_eff>=10の達成は別判定。
