## 目的・優先度

#81の対応画素内precisionを全面品質へ拡張せず、内容・空・異群・人物を含む新方針の採否を判定する。
priority: high：旧wall/treeにも混入があり、現行ゲートでは統計更新の妥当性を判断できない。
type: test。Refs #114、#81、#73。

## 設計・範囲

- A #117・B #118・C #119の固定版とE #120の表示を受けて評価する。
  先に対象・対応表・seed・調整/確認分割・指標・合格条件を固定し、結果に合わせて変えない。
- 旧#81の条件付きprecisionを再現し、同じ617枚での対応比較とADE validation全体の診断を区別する。
  sky/building等の既知負例を含む全非void画素のprecision/recall/IoU・混同行列を追加する。
  voidと意味上対応できない領域は別に記録し、都合の悪い負例を消さない。
- CMPの部位正解を使い、ADE building全体をwallの正解へ追加しない。
  OneFormerのADE学習・公開validation利用を開示し、所有画像の独立性能保証とは呼ばない。
- 純DINO/SAM2、prompt/後処理の基準、OneFormer制約後を同じ入力/正解で比較する。
  役割間交差・空/人物混入・coverage/void率・recallと、色に残る汚染を確認する。
  空予測・全面voidでprecisionだけ合格させない。
- 旧138枚と既知の旧主統計失敗例は開発/回帰用。新たに旧/新cohort各50枚を固定seedで選び、
  既知試験画像とSHA重複を除いて予測前に固定する。cohort別の率と区間を出す。
- 閾値付近・不一致・人物疑い・白黒/暗所は追加challengeとして分離し、無作為率へ混ぜない。
  Eの私有HTMLを会話で渡し、ユーザーから全件確認済みと番号・理由を受ける。
  人が予測を見たこと、画素正解がないことを記録し、完全盲検/全画素正解と称さない。
- Lunaの対象・subject・人物はTP/FP/FN/TNと分母を保存し、accuracyだけで合格にしない。
  試験の対象外21枚と元所見16枚の定義差を解消し、変更版の精度を旧93.5%と同一視しない。
- 新しいdecision artifactと評価版を保存し、旧#81 decision・固定設定・公開画像・旧runは上書きしない。
  保持・ライセンスを守り、公開画像を本番色統計へ混ぜない。

## 未確定・依存

役割precision・coverage/recall・人物見落とし許容基準、接写/mixed/白黒等の扱いはユーザー判断後に固定する。
旧precision>=0.50を新方式の安全性基準へ自動継承しない。
評価設計・公開正解の読取器は先行できるが、A/B/C/E確定前に最終合格は出さない。
有償評価のAPI予算もAの承認枠へ含める。判断待ちならquality=unverifiedを維持する。

## 完成条件・検証

- [ ] 旧評価の再現、sky/building等の負例、ID対応、同親union、空予測・voidを回帰検証する。
- [ ] 入力・正解・model/prompt/policy・分割のhashが揃い、調整/確認間のSHA重複がない。
- [ ] 両GPUの時間/VRAMと各方式の指標を記録し、所有画像の新しい確認結果も取得する。
- [ ] 決めた合格条件ごとにpassed/failed/unverifiedと根拠があり、未検証ラベルをsupportedにしない。
- [ ] 旧統計基準訂正と#114再実行が消費する品質decisionを固定する。
- [ ] WSL隔離DB込み全pytest・ruff・build成功。新snapshot/rule_stat/report生成は別Issueで行う。
