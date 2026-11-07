## 目的・優先度

楽譜・文書・絵画等がD15権利ゲートを通り解析される問題を、画像内容の判定で止める。
priority: high：#114の統計更新に品質上有効な回避策がなく、旧統計にも混入がある。
type: feature。Refs #114。

## 設計・範囲

- 取得・権利/保持確認後、重い解析の前に既存review jobへkind=image_gateを追加する。収集取引内で呼ばない。
- 製品内のOpenAI Responses直接呼出し。gpt-6-luna、reasoning.effort=low、store=false、toolsなし。
  ChatGPTプラン、Codexの開発文脈、他モデルへの自動切替は使わない。
  既存urllib/jsonschemaで足りるため、この機能だけのSDK依存追加はしない。
- EXIFを除いた1024px画像と固定promptを送り、target・subject(building/terrain/mixed/other/unknown)・
  実在人物(present/absent/uncertain)・室内/白黒/暗所・固定reason codeをschemaで受ける。
  画像内の文字を指示として扱わず、所見・asset ID・出典を送らない。
- 原判定は私有artifact。ProcessingRunに入力SHA・前処理版・要求/返却model・effort・prompt/schema/policy版とhash、
  request ID・usage・料金版を保存する。画像単位の分類であり、画素maskは生成しない。
- 人の訂正は入力runを持つ別review runとして追加し、元判定・旧Asset.quality・固定M3を上書きしない。
  同一入力/モデル/effort/prompt/schema/policy hashだけを再利用し、人の確認を未提示画像へ転用しない。
- 新selection契約image-review-v1にimage_gate_run_id/hashとanalysis_domainを用意する。
  旧Asset.domainは検索意図として保持し、確定subjectとの矛盾は保留。後続Cがprivacy runを付与する。
- USD整数のapi_budget/api_callを追加するmigrationを作る。共有取引で確定＋不明＋予約＋次要求上限をcap以内にする。
  入力token上限と出力上限・料金版から予約し、平均費用を上限に使わない。補助要求・再試行も計上する。
  count endpoint等が未対応・上限算出不能なら送信しない。実usageで精算し、課金不明を0円にしない。
- 初期直列、最大3試行。429/一時5xxのRetry-After尊重、連続障害・auth/quota/billingは停止。
  応答消失やタイムアウトで課金/完了不明なら自動再送せず、保存応答と台帳から再開する。
  schema不正/refusal/incomplete/不明は保留。採用扱い、旧承認へのfallbackをしない。
- 台帳・画像・応答は既存保持方式へ登録。APIへの送信前に権利・保持条件を再確認し、認証本文をログへ出さない。
  store=falseを監視ログ等のゼロ保持と説明しない。

## 対象外・依存

人物mask、領域の画素修正、統計生成は別Issue。本IssueはBと独立実装可能。
review-runとimage-review-v1の確定commitをC/E/D/G/#114へ渡す。
API型と既存の取得品質reviewのdispatchを明示的に分ける。

## 未確定・実行停止条件

- ユーザーのAPI総額cap、評価・補助要求・再試行の予算範囲、UbuntuへのAPI認証配置。
- 建築部位接写・mixed・白黒/暗所の採否。私有試験の対象外21枚と元所見16枚には定義差がある。
- 実APIの開始許可と新しい品質目標。Issue作成は有償API実行・本番migrationの許可ではない。
未決定の項目は保留として扱い、本番バッチを起動しない。

## 完成条件・検証

- [ ] 既存review/queueの互換性、入力・model・prompt変更時の再利用拒否、人の上書き履歴を検証する。
- [ ] 同時予約・境界額・課金不明・lease切れ・応答保存後のDB失敗で二重送信/上限超過がない。
- [ ] HTTP/schema/拒否/不完全応答/別modelの応答をfixtureで再現し、全て停止・保留を検証する。
- [ ] 旧asset/run不変、保持登録、model/prompt/hash/usageの一対一が確認できる。
- [ ] 費用capと開始許可後だけ、少数の実API smokeで実際のmodel欄・usage・費用を確認する。
- [ ] WSL隔離DB込み全pytest・ruff・build成功。全量判定や品質合格は本Issueの完了と区別する。

参考：[Luna仕様](https://developers.openai.com/api/docs/models/gpt-6-luna)、
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、
[token計数](https://developers.openai.com/api/docs/guides/token-counting)、
[データ管理](https://developers.openai.com/api/docs/guides/your-data)。
