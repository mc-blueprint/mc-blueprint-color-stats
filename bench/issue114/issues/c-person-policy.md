## 目的・優先度

像・絵・装飾を人物とし、実在の小人物・群衆を見落とす現行契約を、画像判定と画素判定を分けて再設計する。
priority: high：人物確認が新画像の採用許可に直結し、現行の判定を安全な回避策にできない。
type: feature。Refs #114、#88。

## 設計・範囲

- A #117の実在人物present/absent/uncertainとB #118のsemantic personを別根拠として保持する。
  present/uncertain、不一致、画素欠落は保留とし、陰性1モデルだけで採用しない。
- 推奨する初期方針は人物あり画像の一時保留。永久除外やmask救済はユーザー決定後に版付きpolicyで選ぶ。
- mask救済が選ばれた場合、OneFormer personを画素候補とし、必要なDINO/SAM2補助との和集合を評価する。
  取得画像の解像度で小人物・群衆を確認し、prep座標への変換・膨張・寸法・SHAを固定する。
  gpt-imageやLunaの大まかな位置を精密maskの代用品にしない。
- Lunaが人物ありでもmaskが空、または未検証なら採用しない。像・描画を実在人物と分けて検証する。
  閾値を上げるだけで、既に弱い小人物の再現率を落とさない。
- privacy判定は別review runへ保存し、原判定・人の訂正・policy版・入力/各maskのSHAを追跡する。
  既存asset/qualityの書換えでM3を変えず、新selection/payloadへprivacy_review_run_id/hashを明示する。
- check_privacyは新policyの明示runを検証し、失敗を旧qualityへfallbackしない。
  人の上書きは履歴を残し、判定/subject/mask変更後の古い解析・統計承認を無効にする。
- mask方式ではshade/color双方で同じperson_maskを除外し、mask変更時は新しい色解析runを必要とする。

## 未確定・依存

- ユーザー判断：人物ありを一時保留・永久除外・mask救済のどれにするか。
- 見落とし許容基準と必要な検証標本数。既存の人物ラベル13件（実在3件）を安全性証明にはしない。
A/Bの確定commit後。表示Issueとは独立ファイルで並列化し、同じreview writer契約を使う。
判断前は保留経路だけを動作確認し、実データの採否やmaskを変更しない。

## 完成条件・検証

- [ ] A/Bの不一致・空mask・像/絵・群衆・小人物・不明結果で採用が漏れない。
- [ ] input SHA・寸法・person_mask SHA・review runが共有payload全段階で一致する。
- [ ] 人の上書き・旧run保全・承認取消し・新旧policyの分離をDB込みで検証する。
- [ ] 選ばれた人物方針と新しい難例・無作為確認で、Dの評価へ渡す入力を固定できる。
- [ ] WSL隔離DB込み全pytest・ruff・build成功。品質の採否はD、本番再解析はG/#114で行う。
