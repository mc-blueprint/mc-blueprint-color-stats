# #117 実API少量確認

2026-11-07、ユーザー許可の5枚・1 USD枠。ubuntu-1でsystemdのLoadCredentialを使用した。
秘密値、画像、原判定、asset ID、出典、個別のrequest IDは本記録へ載せない。

## 対象と分離

- 既存#114 cohortのIDをソートし、seed=11720261107で5枚を事前に固定した。
- 本番DBへの取引はREAD ONLYを確認し、権利・保持・SHAを確認した5枚だけを一時DBへ複製した。
- 一時DBはcolorstats_i117_smoke_20261107。migration 0009はこのDBだけに適用した。
- 上限1 USDの台帳は一時DB内で独立し、本番50 USD枠は使用していない。
- 実行unitはcolorstats-i117-api-smoke-1。実行コードの版は私有証跡に記録した。
- 実HTTP要求はcount 5回・Responses 5回。追加の実API要求は行っていない。

## 実応答と費用

5件ともHTTP 200、返却model=gpt-6-luna、reasoning.effort=low、service_tier=default。
5 review jobが成功した。job成功は採用や品質合格を意味しない。

実usage・費用明細・予約解放額は私有証跡と一時DBへ保全する。
精算後に未精算予約がないことを確認した。画像ごとの実測値はGitへ転記しない。

実usageにはinput_tokens、input_tokens_details.cached_tokens/cache_write_tokens、
output_tokens、output_tokens_details.reasoning_tokens、total_tokensが返った。
適用TTLは30m。cache書込みは入力に含まれる数量であり、通常入力と二重計上しない。

初版は書込み上限250 nano USD/tokenを精算にも使い、保守的に計上した。
公式の30m既定・125 nano USD/tokenと実応答を照合し、v2で予約単価と精算単価を分離した。
保存済み応答だけで再精算し、初版の金額と元review runを監査runから参照する。
元の画像判定runや本番のasset・quality・Subjectは上書きしていない。
金額はusage×標準料金であり、請求書やアカウント全体の請求額を取得したものではない。

## 429と上限

実429を誘発する大量要求はしなかった。一時DBの別schema i117_mock429で、
外部APIを呼ばないfixtureを使い、HTTP 429のRetry-After=300秒、queueの延期、
再開時刻前にclaimされないことを実機確認した。実API台帳とfixture台帳を分離した。
費用cap超過拒否・同時予約・不明請求保持は隔離DBのpytestでも検証する。

## 私有証跡と残り

固定計画・入力SHA・実応答・usage・原判定・再精算記録はubuntu-1の
smoke専用ディレクトリと一時DBへ私有で保全する。
画像・応答は一時DBの保持台帳に登録済み。保持期限を延長しない。
一時的なDB接続規則は除去済み、smoke unitも終了済み。
保持期限と対象ファイル一覧は私有台帳で管理し、期限内に削除する運用を引き継ぐ。
原本ファイルを削除対象へ含めない。
本番での全量判定はmerge・配備後に行う。本Issueの完成条件に含まれるため、
現段階は実装と少量確認までで、本番全量判定は未完了とする。
