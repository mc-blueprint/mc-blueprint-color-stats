# #121 品質評価（原画像目視照合済み）

起点 `d3c742c`、2026-11-07。旧#81 decision・旧run・本番DBを変更していない。
新しい [decision.json](decision.json) は `quality_eligible=false`。
公開GTではwallが不合格。原画像目視による画像ゲート採用分の確認は成功したが、
人物/領域契約と確認run取込は未検証。[110枚目視結果](human-results.md)を参照。
後続の旧基準訂正・#114再実行を許可しない。

## 予測前固定と再現

- [評価設計](plan.md)、[固定証跡](freeze.json)を新しいGPU予測より前に保存。
  公開ZIP・画像・正解・旧分割・旧cache mask・prompt・実モデル全ファイル・parent/policyを照合した。
  `freeze.json`のテキストSHAは改行をLFへ正規化する。画像・maskは実byte SHA。
- 同じCMP 606枚＋ADE屋外617枚、計1,223枚。旧tune/holdoutを維持し、SHA交差0。
  旧#81のafter条件付きprecision/recall/IoUは両dataset・両splitの全群で完全一致した。
  既知集合なので、新たな独立holdout・盲検とは呼ばない。
- 3方式は同じ入力・正解。rawは0.35超、prompt/後処理は既選定0.45超と群の競合void、
  OneFormer制約はrawと親表v2の積・役割競合void。prompt変更による探索は行っていない。
  threshold/text 0.35/0.25、512px入力、nearest正解、OneFormer短辺640/長辺2560。
  候補promptは旧公開評価のdataset別集合。本番の全prompt集合と同一ではないため、
  本番候補との競合を含む品質へ昇格させない。

## 全非void画素の確認集合

CMPは1〜12、ADEは1〜150。void=0だけを無視し、sky/building/person・CMP背景等も負例。
ADE buildingをwall正解にはしていない。同親はunion、異群重複は診断へ残す。
以下は確認集合の画素数によるmicro指標。群内候補の個別支持には拡張しない。

| 方式 | wall precision | wall recall | wall IoU | tree precision | tree recall | tree IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| raw | 0.426371 | 0.811299 | 0.387902 | 0.429746 | 0.558687 | 0.320835 |
| prompt_post | 0.481352 | 0.337244 | 0.247360 | 0.821739 | 0.286162 | 0.269436 |
| oneformer | 0.440701 | 0.056015 | 0.052297 | 0.940182 | 0.534000 | 0.516453 |

合格基準はprecision>=0.80かつrecall>=0.30。OneFormerのCMP全群は不合格。
ADEではstairs・water・treeの公開GT指標が基準を満たした。treeの幹／樹冠やwindowの
ガラス／枠の個別支持、GT対応がないroof/snow等の支持には昇格させていない。
原画像目視は照合済みだが、所有画像の人物/領域契約は未検証なので、
decisionのsupported_labels/groupsは空を維持した。

[paired-summary.json](paired-summary.json)に群別TP/FP/FN/TN、全GT IDへの予測ヒストグラム、
coverage/予測void、GT void、意味対応外の非void画素、群の交差を保存した。
空予測は正例があれば不合格、正例なしは未検証。全voidによるprecisionだけの合格はない。
公開GTのFPは色統計に混入し得る画素として残るが、所有画像の色汚染は目視未確認。

## ADE全validationの別診断

全2,000枚を画像・正解のSHAで先に固定し、同じ512px座標へsemanticを復元した。
全150クラスの151×150行列（GT 0〜150、予測モデルID 0〜149）とクラス別指標は
[ade-summary.json](ade-summary.json)。void行は別保存しprecision/recall/IoUの分母から除く。
全クラスmIoUは **0.560539**。ADE学習済みcheckpointの公開benchmark診断であり、
部位候補の品質や所有画像の独立性能を保証しない。617枚の3方式比較と混ぜていない。

## 両GPU

同じ公開CMP先頭3枚を固定し、1 host 1 slot、batch=1、OneFormerを解放後にDINO/SAM2を実行。
開始・終了時の別GPUプロセス0。追加のモデル取得・暗黙縮小・モデル代替はない。

| GPU | 入力数 | 合計秒 | peak allocated MiB | peak reserved MiB |
| --- | ---: | ---: | ---: | ---: |
| NVIDIA GeForce RTX 4060 | 3 | 25.62 | 2535.9 | 3598.0 |
| NVIDIA GeForce RTX 4070 | 3 | 17.38 | 2535.9 | 3598.0 |

3枚のsmokeは8GBで成功したが、全形状の8GB適合を保証しない。
1,223枚のOneFormer比較はRTX 4070で255.92秒、peak allocated 3,469,362,688 bytes、
reserved 9,426,698,240 bytes。全2,000 semanticは277.16秒、allocated 2,557,013,504 bytes。
全件はOneFormerだけを常駐させた測定で、モデルを毎回切り替える本番スループットと同一視しない。

## 所有画像と残作業

本番DBをREAD ONLYで読み、#117の旧7,626・新2,600と集合SHAが一致することを確認した。
旧7,607固定統計の再評価とは別の#117旧cohortであり、19枚差を隠していない。
保持条件・権利利用停止を既存の判定で確認し、現在の除外0件。
既知138枚、#46・#90試験、#118/#120の3＋20枚等の既存リストからIDと原画像SHAを除外。
既知IDのSHA別名も除外し、cohort間は原画像SHAで一意化した。

抽出後の候補数は旧 3393、新 2441。seed 12120261107で各50枚を固定。
challengeは既知の人物・対象失敗例から別seedで10枚。無作為率に混ぜない。
[owned-proof.json](owned-proof.json)に固定台帳SHA・既知交差0・抽出内SHA重複0を保存した。
全量API判定は抽出より先に開始済みだが、その判定結果は抽出・選別に使っていない。

私有固定台帳：`ubuntu-2:/mnt/data/work/issue-121/owned-20261107/selection.json`。
許可されたLAN内台帳転送後、ubuntu-1で固定110枚のHTMLを作成し、
`H:/mc-blueprint/private/issue121-review/review.html`へ配置済み。
13,679,667 bytes、全110画像の復号・外部参照0・転送SHA一致を検証済み。
画像ゲート判定は#117完了後の固定runで照合済み。人の返信との照合はhuman-results.mdを参照。

残作業：

1. #120の人確認run記録には、今回未提示のprivacy/region runが必要。
   後付けの参照を作らず、保存契約の判断をメインへ返す。人確認run書込み0件。
2. 主体GT・#118/#119の独立した人物/領域評価は未検証。原画像目視だけで採用を承認しない。
3. HTML生成時の許可範囲で、HTML二配置の保持紐付け220件と必要な親1件だけを登録済み。
   今回の返信評価では本番DBへ書き込んでいない。

追加API費用0 USD。追加5 USD以内・#117の50 USD枠という上限を維持した。
新snapshot/rule_stat/report生成・サービス変更・push/PRは実施していない。

## 検証

重点テストは全非void負例、同親union、空予測、境界値、GT/モデルIDの1ずれ、
cohort間SHA重複・既知別ID除外・連番を確認。
最終検証：WSL root・隔離PostgreSQL 16で **1,350 passed / 1 skipped、335.25秒**。
ruff・sdist/wheel build成功。末尾のdecision根拠更新後もCLI生成・重点6件・ruff・buildを検証。
artifactは `/tmp/colorstats-issue121-0eKoov/`。隔離DBは正常停止。
初回は1,349 passed / 1 skipped（既存GPUテスト）、既存warning 4件。
GPU・全validation・公開比較はすべて正常終了し、私有画像や個別IDをGitへ入れていない。

## 契約照合の残る問題

`oneformer-classes.json`は実行時のCRLFとGit blobのLFでJSON内容が一致するが、実byte SHAが異なる。
現行#118の`policy_hash()`はこのbyte SHAを含む。今回の予測は固定された実行時ファイルで照合済みだが、
Linuxでの新規checkout等ではpolicy hashが一致しない可能性がある。
[class-info-provenance.json](class-info-provenance.json)に両SHAを保存し、
decisionの`policy_hash_portability`を未検証にした。共有契約の変更は行っていない。
再利用・後続採用の前にメインで#118のhash正規化・テキスト属性と版更新の方針を判断する必要がある。

原画像目視照合の追加検証は[human-verification.json](human-verification.json)を参照。
