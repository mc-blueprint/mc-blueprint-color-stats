## 目的・優先度

空が窓系になる、山がtreeになる、建物と地形が重複する予測を、有効領域で制約する。
priority: high：新旧の色統計の主要入力が汚染され、有効な統計更新が止まっている。
type: bug。Refs #114、#81。

## 設計・範囲

- OneFormer ADE Swin-L（shi-labs/oneformer_ade20k_swin_large）のsemantic mapを主方式とする。
  著者repoと著者HF checkpointはMIT表示。取得時にrevision・全ファイルSHA・ライセンス証跡を固定する。
  Mask2FormerのコードMITと配布重みCC BY-NCを混同せず、M4用open重みとして代用しない。
- 既存Transformers 4.57.6/torch 2.11を再利用し、Detectron2環境を追加しない。
  DINO/SAM2追加promptだけの方式は比較基準に留め、既存の部位候補生成は再利用する。
- 既存segmentの版付きmethodとして実装し、stage/schema enumを増やさない。
  raw候補・semantic class map・有効role mask・除外理由を新runへ保存する。
  既存mask・Region・旧runを上書きしない。
- 同じprep入力SHAと寸法へsemantic logitsを復元して整数class mapを作る。
  resize/pad/復元とid2label対応をhash固定し、ADE注釈IDとモデルIDのずれを検証する。
  class map/最終bool maskにJPEG・色補間を用いず、入力画像の色は変えない。
- sky/person/対象外を統計の色から除外。部位ごとの許容semanticクラス表で候補をclipする。
  treeをmountain/rock/snowへ許容せず、building全体をwallの正解へ昇格させない。
- 建物/地形・異なる統計役割の有効maskは排他とする。semantic対応でも解決しない競合画素はvoid。
  独立scoreの単純な大小で勝者を決めない。同じwall/tree内の候補は和集合で1回だけ計数し、
  未確定の子ラベルは診断用のままにする。新しい個別supportedを捏造しない。
- 空・人物・競合で失う画素、欠測、coverage/void率を出す。全面voidで高precisionを作らない。
- region-policy-v1としてsemantic map/有効role maskのpath・SHA、入力SHA、model/revision/policy hashを固定する。
  #66共有payloadへ渡し、shade/color/snapshotの新policy経路は有効role maskから直接色を計算する。
  生Region ORへのfallback、古い色観測の再利用を拒否する。旧policyの再現経路は変えない。

## GPU・精度・依存

ubuntu-1はRTX 4060 8GB、ubuntu-2はRTX 4070 12GB。batch=1、有界入力、モデルは逐次ロードする。
両機でsmokeとピークVRAMを測るまで適合と扱わない。8GB不適合なら12GB側で粗分割を先行し共有する。
12GBでも不適合なら停止し、入力解像度やモデルを暗黙に変更しない。
著者のADE mIoU 57.0は所有画像・部位精度の保証ではない。品質の採否は後続Dで別に判定する。
Aとはソース範囲を分けて独立実装できる。確定したrole mask契約commitをC/E/Dへ渡す。

## 完成条件・検証

- [ ] 合成maskでsky/person除外・異群交差0・同親和集合・void/欠測・IDずれを検証する。
- [ ] 寸法・向き・pixel座標・入力/出力SHAを検証し、許容しない再利用を拒否する。
- [ ] raw候補の保全と、shade/color/snapshotが新しい有効role maskを使うことを統合検証する。
- [ ] 8GB/12GB実GPU smoke、単独常駐、OOM時停止または明示した工程分離を記録する。
- [ ] WSL隔離DB込み全pytest・ruff・build成功。Dの品質未合格では全量統計へ進めない。

参考：[OneFormer checkpoint](https://huggingface.co/shi-labs/oneformer_ade20k_swin_large)、
[公式processor](https://huggingface.co/docs/transformers/v4.57.1/model_doc/oneformer)、
[Mask2Former重みの条件](https://github.com/facebookresearch/Mask2Former/blob/main/MODEL_ZOO.md#license)。
