# #121 品質評価の事前固定

起点は `d3c742c`。新しい予測の前に `freeze.json` のSHAを保存する。
旧#73/#81は既知の開発・回帰集合で、新たな盲検とは呼ばない。
既存NumPy、Pillow、ZIP読取器、#118の推論・排他処理、#120のHTML部品を再利用し、
依存を追加しない。旧decision・本番DB・snapshotを変更しない。

- 部位正解・群対応は#81の表を維持。CMPは1〜12、ADEは1〜150の全非void画素。
  CMP背景・sill・balcony・shop、ADE sky/building/person等も負例から落とさない。
  ADE buildingをwall正解にしない。部位GTがないラベルは未検証。
- 旧606 CMP＋617 ADEの同一入力・正解・#73固定tune/holdout分割で対応比較。
  ADE全2,000 validationは別集計。ADE学習済みOneFormerの公開benchmark診断であり、
  所有画像の独立性能保証ではない。縮小は長辺512px、正解はnearest。
- 比較は (1) #41固定promptのDINO/SAM2 threshold 0.35、text 0.25、
  (2) 同じpromptと#73の既選定threshold 0.45＋同親union・異role競合void、
  (3) (1)を#118親対応v2のOneFormerと交差・競合void、の3方式。
  (2)は固定した後処理基準であり、改善を見てpromptを追加・選別しない。
  OneFormerのモデルrevision、全ファイルhash、transform、policy hashを保存する。
- 同親候補はunion、異群重複は診断に残す。群別TP/FP/FN/TN、全正解IDへの
  予測ヒストグラム、precision/recall/IoU、予測coverage/void、GT void、
  意味対応外の非void画素、役割交差を保存する。空予測を合格にしない。
- 合格条件は確認集合の部位precision>=0.80かつrecall>=0.30。
  すべての条件をpassed/failed/unverifiedで区別し、未検証をsupportedにしない。
- 所有画像のseedは12120261107。旧・新cohort各50枚。
  既知138件、既知失敗例、API試験、#118/#120 smokeのIDと原画像/prep SHAを除外。
  母集団の原画像SHAで一意化し、cohort間重複・調整との重複を除く。
  取得可能性や推論成否を見て標本を差し替えない。challengeは別番号・別分母。
- 人物present/uncertain、暗所、mixedは保留。白黒は除外。建築部位接写は採用。
  人物の採用可否は#117/#119の固定判定と照合する。各cohortの採用分を全件目視し、
  見落とし0件なら合格。各群の採用分母と片側95%上限も記録する。
  約100枚0件で言えるのは約3%を超えないまでで、0%を保証しない。
- rawだけの新規目視を先に提示可能。予測比較を見た場合は非盲検と明記。
  画素GTはない。内容target/subject/personのTP/FP/FN/TNは目視返信と
  #117完了後の固定応答から計数し、旧試験21件/元所見16件と混同しない。
- API追加費用は#117予算50 USD枠内の5 USD以下。既存応答の読取を優先し、
  この評価スクリプトはAPI要求も本番DB書込もしない。
- HTML・個別記録・対応表はprivateに保存。保持台帳への登録はDB書込を要するため、
  READ ONLYの本タスクでは未登録として報告し、成果物を本番承認に転用しない。
