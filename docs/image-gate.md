# 解析前の画像内容review

Issue #117。取得済み画像を `review` stage・`kind=image_gate` で判定する。
収集取引では通信しない。既存の原本品質review・監査は従来どおり
`colorstats.collect.quality` のhandlerで扱い、Workerが画像ゲートだけを専用経路へ分岐する。
画像ゲートはprepare_jobでAPI台帳を更新し、既存の計算子プロセスで実行する。
親プロセスの共通ループがleaseを更新し、停止・保存先障害・所有権喪失を監視する。

## 実行条件

- 判定先はubuntu-1。OpenAI Responsesへの直接HTTP要求を使用する。
  `gpt-6-luna`・`reasoning.effort=low`・`store=false`・toolsなし・Standard料金に固定する。
  SDKやモデル重みの追加はない。Codex/ChatGPTプランや別modelへの切替はしない。
- 実APIの開始には別途許可が必要。`enqueue(..., execution_authorized=True)` は
  実際に許可がある場合だけ指定する。既定値はFalse。本Issueのmock検証は開始許可に含めない。
- 現行Source.policyで、`external_image_review="openai-store-false"` と
  `external_image_review_allowed=true` を確認する。これらは外部送信と監視ログ等の保持を含めた
  権利確認の記録であり、既存のD15根拠や画像保持期限の代わりにはならない。
  `analysis_only` は取得時と現行policyの解析根拠も再検証する。
- systemdの `LoadCredential=openai-api-key:/etc/colorstats/credentials/openai-api-key` で渡す。
  workerは `CREDENTIALS_DIRECTORY/openai-api-key` だけを読み、payload・ログへ鍵を保存しない。
  `store=false` は監視ログや画像例外も含めたゼロ保持を保証しない。
- migration 0009を事前に適用し、運用者が下記予算を一度だけ登録する。
  本番へのmigration適用・鍵配置・バッチ起動はこの変更では実施しない。

## 予算と再開

`ApiBudget.key="issue114-image-gate"` を全画像・評価・補助要求・再試行で共有する。
`cap_nusd=50_000_000_000`（50 USD）以下、`pricing=colorstats.api_budget.PRICING`、
`stopped=False`、`failures=0` として登録する。既存予算の自動作成・増額・停止解除はない。
金額は整数nano USD。料金版は2026-11-07のStandard。
登録時にはアカウントの料金条件とcount要求の料金も確認する。

入力画像・prompt・schemaを同じ形でcount endpointへ送り、正の入力token数が取得できた場合だけ
判定要求を送る。入力上限100,000、全出力上限2,048 token。
入力は非cache価格とcache書込み価格の最大値、出力は全出力上限で予約する。
現在の料金版はopenai-standard-2026-11-07-v2。入力100、cache読取10、
30分書込み125、12時間書込み250、出力500 nano USD/token、
count要求0。長文割増の閾値以下、Standardの固定endpointのみを使う。
cacheの内訳（cached_tokens/cache_write_tokens）が欠測・不正・未知の場合、model/tier不一致、
usage欠測では金額を確定しない。実アカウントで書込み内訳が返らない場合も0と仮定せず停止する。
予約には書込み上限250を使い、精算にはTTL別の単価を使う。
cache_write_tokens_detailsが返る場合は30分/12時間の合計と書込みtoken数を照合する。
内訳省略時は要求TTL（API既定30m）で精算し、未知のTTLを採用しない。

共有予算行をロックし、全ApiCallの `coalesce(cost_nusd, reserved_nusd)` 合計と次の予約が
cap以内のときだけ送信済み台帳をcommitする。送信中にDB取引は保持しない。
同じ予算で送信中の要求があれば延期し、初期運用は直列。
共有枠や送信再開時刻の待機は試行数を消費せず、実際のAPI一時失敗だけを失敗に数える。
count要求も別ApiCallとして要求数と保存応答を記録する。

応答は私有artifactへfsyncしてからDBで精算する。API再試行とqueue再試行を重ねない。
429/一時5xxだけRetry-After（秒数・HTTP日付）に従って延期する。
queue・endpointとも最大3試行、連続2障害・auth/quota/billingで予算を停止する。
countだけの成功では判定要求の連続障害を解除しない。
タイムアウト・保存失敗・応答消失では予約額を維持して停止し、自動再送しない。
保存応答がある場合は、lease切れやDB登録失敗後もその応答から再開する。
未精算の送信台帳が残るDBのmigration巻戻しは拒否する。

`ApiCall.details` と保存応答を照合せずにstopped解除・cost=0設定・台帳削除をしてはならない。
課金不明を解消できなければ予約を残す。保持期限経過で応答が消えた要求も再送しない。

## 入出力と採否

`colorstats.image_gate.enqueue(queue, asset_id, artifact_dir, budget_key=..., code_version=...)`
で1画像を投入する。入力ファイルのSHAを取得時SHAと照合し、EXIF向きを補正、RGB化、
長辺1024以下への縮小後にEXIF/ICC等を含まないPNGへ変換する。
APIへ送るのはその画像と固定prompt/schemaだけ。asset ID・出典・人の所見は送らない。
画像内の文字を指示として扱わず、人物の同定・属性推測は要求しない。

原判定schemaは `image_gate.SCHEMA`、prompt/policyも同moduleで版管理する。
人物present/uncertain、暗所、mixed、不明・拒否・不完全・schema不正は保留。
白黒と対象外は除外。建築部位の接写は採用可能。
確定Subject.domainとの矛盾は保留にし、検索意図であるAsset.domainは変更しない。
API失敗のjobはfailedとなり、原判定が得られない画像を旧承認で採用しない。

入力SHA・前処理版・要求model/effort・prompt/schema/policy版とhashを再利用キーにする。
人の確認の転用を防ぐため、機械判定の再利用も同じassetに限定する。
再利用・訂正はProcessingRunInputで元runへ接続する。
ProcessingRun.parametersへ要求identity・返却model・request ID・usage・料金版・台帳IDと
応答hash、判定artifactのSHAと参照を保存する。原判定JSONは私有artifact。
API用画像、保存応答、一時応答、判定artifactは保持台帳へ登録する。
旧assetの保持を遡及登録する場合も取得日起算の期限は延長せず、旧qualityは変更しない。

人の訂正にはenqueueの `input_run_id`・`correction`・`reviewer`・`presented_sha256` を指定する。
同じassetの完了済みrunと実際に提示した正規化画像SHAの一致を要求し、schema適合の訂正を
別review runへ保存する。人物保留等のpolicyは訂正にも適用する。
元run・Asset.quality・固定M3・Subject関連付けを変更しない。

## 後続Issueへ渡す契約

`image_gate.selection(session, asset_id, run_id)` は採用済みrunから次の1行を作る。
`check_selection(session, row)` で現行の保持・主体・run/hash・契約版を再検証できる。

```json
{
  "contract": "image-review-v1",
  "asset_id": "<UUID>",
  "image_gate_run_id": "<UUID>",
  "image_gate_hash": "<ProcessingRun.parametersのcanonical JSON SHA256>",
  "image_gate_input_sha256": "<API用PNGのSHA256>",
  "analysis_domain": "real_building",
  "privacy_review_run_id": null,
  "privacy_review_hash": null,
  "region_policy_run_id": null,
  "region_policy_hash": null
}
```

analysis_domainはreal_building/real_terrain。画像ゲートは画素maskを生成しない。
後続Cがprivacy参照を、Bとの統合側がregion policy参照を付与・検証する。
この行だけではprivacy・領域品質を承認せず、既存のsnapshotや集計の選択を自動置換しない。
新policyの失敗を旧qualityへfallbackさせない責務は後続統合側にも残る。

## 根拠と検証

既存urllib・jsonschema・Pillow・SQLAlchemy・Queue・ProcessingRun・保持台帳を再利用する。
既存の収集予算はUSD・課金不明を表現できないため、独立した金額台帳のみを追加した。
API仕様・料金の根拠は[model](https://developers.openai.com/api/docs/models/gpt-6-luna)、
[料金](https://developers.openai.com/api/docs/pricing)、
[token計数](https://developers.openai.com/api/docs/guides/token-counting)、
[データ管理](https://developers.openai.com/api/docs/guides/your-data)。
2026-11-07に許可された[5枚smoke](../bench/issue117/smoke-results.md)で、
count対応・返却model/effort・usage・台帳精算を確認した。
TTL別料金の根拠は[公式prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)。
外部APIはmockし、隔離PostgreSQLで予算・lease・保存応答の再開・履歴を検証する。
費用fixtureには画像ごとの実測値を転記せず、100 token単位の架空値を使う。
