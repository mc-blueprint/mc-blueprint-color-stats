# #130 領域診断の事前固定

起点 `9698f12`。#121 の参照コードは `17b8ddc652a610f7132bf739c690983ed87250b9`。
新checkpoint・依存・migration・本番DB更新は追加しない。
既存の NumPy/Pillow、#73 ZIP/正解読取器、#121 cache読取器・全非void評価器、
#118 OneFormer/DINO/SAM2 を再利用する。画像ゲート #129 は変更しない。

## 入力と判定

- #73 の CMP 606枚・ADE 617枚、seed=73、tune/holdout と GT 対応を維持する。
  CMP 1〜12、ADE 1〜150 の全非void画素を分母にし、ADE building を wall 正解へ追加しない。
- #121 の旧 raw と semantic を SHA 固定して再利用する。改変・欠損時は停止する。
  semantic の番号は #121 public.py の全1223行の順序であり、dataset別に再採番しない。
- precision>=0.80、recall>=0.30。空予測は不合格、正例なしは未検証。
  公開既知GTでの回帰比較であり、盲検・所有画像の独立保証ではない。
- raw、threshold、親との積（候補別）、同親union、異role競合voidを別々に集計する。
  各段階のTP/FP/FN/TN・IoU・coverage/void、GT全IDヒストグラムを保存する。
  prompt別、親で除去、競合で除去、候補間重複、sky/person、欠測を別集計する。

## 固定する改善候補

本番policyの書換えに先立つ実験版 `issue130-region-candidates-v1` とする。
旧候補 .35/.25 を再利用し、以下以外のprompt探索や負例除去をしない。

1. `baseline`：#118 親表v2、threshold > .35、同親union、異role競合void。
2. `specific`：baseline の建物部位のうち直接の ADE クラスがあるものだけを
   そのクラスへ狭める（window=8、door=14/58、shutter=63、column=42、
   roof=86/106、stairs=53/59/121）。壁および対応クラスのない装飾は旧表を維持する。
3. `specific45`：specific の建物候補だけ > .45。地形は > .35 のまま。
4. `specific55`：specific の建物候補だけ > .55。地形は > .35 のまま。

score は採否閾値だけに使用し、競合画素の勝者は作らない。
選定は CMP tune の wall だけで行う。合格候補があれば IoU 最大、なければ
F1 最大（同点は上記順序）。選定結果を新規ファイルへ固定してから holdout を評価する。
全候補の holdout も併記するが、holdout を見た再選定はしない。
壁の合格を他部位の支持へ拡張しない。未対応部位は未検証とする。

## 本番promptとGPU

#121 dataset別promptと `configs/segment_stats.yaml` の差分を記録する。
全promptで固定公開先頭3枚（#121 smoke）を両GPUで新規推論する。
画像GT評価全1223枚は既存promptの範囲であり、このsmokeを全本番promptの品質保証にしない。
1 host 1 slot、batch=1、開始直前のGPU計算プロセス0を確認し、host単位のlockを取得する。
OneFormer→解放→DINO/SAM2、OOMは既存の再試行不可例外で停止し、代替しない。
時間・VRAM・入力/重み/prompt/親/座標/policy SHAを新規artifactへ保存する。

## 契約と公開

実験版hashは JSON内容から算出してCRLF/LF差を除く。旧policy hashは変更しない。
旧hashと新実験hashを取り違えず、旧runを新契約として読み込まない。
候補が合格しても本番shade/color/privacy/selectionの同一run契約を満たすまで採用しない。
本Issueの診断が不合格なら既存地形の成果を維持し、建物追加許可は空に固定する。
共有契約の本番版更新が必要ならメインへ報告する。
画像・個別ID・mask・所見はremote private、Gitには集計・版/hashだけを置く。
WSL root・隔離DB全pytest、ruff、build、両GPU smoke、OOM停止とhash不一致拒否を検証する。
