# 可視壁材の新評価版 issue130-visible-wall-eval-v2

2026-11-08のユーザー決定を実装する。旧評価・旧decisionは変更しない。
壁は窓・扉・装飾などを除いた可視壁材。CMPのPNG ID 2（部位で上書きされた残り）を壁GTとする。
矩形由来GTには遮蔽等の限界があり、材質色の精密な正解とは呼ばない。

## 予測前固定

- 元freeze `6e2b37e65eca4ee08cb12b5ea4fc1828e06f2c353914ec1b004acd49fdd118a2`の
  1223枚（CMP606/ADE617）、seed73の元tune/holdoutを維持する。GT対応・負例は変えない。
- 同じ旧候補とsemanticを再利用し、新たにbalcony/shopfront/window sillの補助3promptを
  両GPUでCMP全606枚へ実行する。CMPのregular候補は#121と同じdataset別prompt。
- 全1223枚の入力RGB/GT/semantic/regular候補をSHA照合し、npzと台帳SHAを先に固定する。
  両GPUは同じ固定入力を使用し、結果を見て標本を入れ替えない。
- primary判定は各GPUのCMP holdout全282枚。precision>=0.80かつrecall>=0.30を
  **両GPUそれぞれ**で満たせばpassed、それ以外はfailed。正例なしはunverified、空予測はfailed。
  tuneも記録するが閾値選択には使わない。
- これは既知公開GTの回帰と、新たな補助候補推論の確認。新しい独立GT・盲検ではない。
  独立した所有画像確認はunverifiedとする。
- 本番26prompt＋補助3promptの新規推論smokeは、各datasetのholdoutから
  SHA256(seed13020261108＋入力SHA)順に先頭3枚ずつ選び、同じ6枚を両GPUで実行する。
  この6枚と全件dataset別promptの指標を混ぜない。本番全prompt全件品質はunverified。

## 固定方式

- new method `oneformer-visible-wall-v2`、policy `visible-wall-policy-v2`。
- regular候補の元検出閾値0.35/text0.25。壁と他建物の出力採否>0.55、地形>0.35。
  前回の固定選定0.55を使い、今回の結果で再選定しない。
- 検出部位は>0.35でunionし、semantic親で切る**前**に壁から差し引く。
  補助3promptと既存の開口・柱・屋根・装飾等の固定リストを使う。
  score勝者は作らず、残った同親をunion、異role競合はvoid。
- 差引き対象の見逃しは補完しない。除去GT壁画素（削り過ぎ）、除去非壁、
  残る部位FP、全欠測、coverage/void、TP/FP/FN/TN/全GTヒストグラムを記録する。
- tree/waterは旧policyと画素一致を全1223枚で必須確認する。
- OKLabは前回と同じsRGB復号・各画素変換後の平均で、P対TPとP対GTの
  画像別ΔOK分布とpool平均を算出する。空maskの未定義件数を残す。色差で合否を変更しない。

## 実行・契約

1 host 1 slot、batch1、GPU開始前と各画像前後の外部プロセス確認、host lockを使う。
補助候補だけの工程はDINO/SAM2を単独常駐させ、smokeは既存のOneFormer解放後に候補を実行する。
OOMは停止し、暗黙の縮小・別モデル・再試行・モデル取得を行わない。
旧重み・実行版・座標を継承し、新policy hashはJSON class-infoの内容を使う。
新artifactは旧出力へ上書きせず、補助raw・差引きmask・role・runを同じ契約に保存する。
shade/color/privacy/selectionは同じ新run参照を使い、旧runの新方式への再利用を拒否する。
本番設定・DB・統計は更新しない。合格まで建物は見送る。

既存NumPy/Pillow・#73読取器・#121指標・#118の推論とartifactを再利用し、依存・migrationを追加しない。
検証は合成mask、artifact/DBを通した後続参照、旧版拒否、全pytest・ruff・build、両GPU。
公開は集計と版/hashだけ。画像・mask・個別台帳はprivate。公開文面は指定scratchpadだけへ保存する。
