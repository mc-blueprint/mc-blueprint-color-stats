# 反証4件の修正

2026-11-07。担当worktreeで修正し、旧commitは変更しない。本番DB・外部API・GPU処理は実行しない。

## 修正と再現

1. mobile生成は保持ロック下で全assetの停止と画像期限を確認する。各HTMLを掲載assetへ、
   番号表を全提示assetへcache登録し、取引失敗時はこの呼出しが新規作成した出力だけを破棄する。
   stopped/expiredの生成拒否と、生成物が期限後の保持管理対象になることを隔離DBで確認する。
2. 診断の番号別表だけでなく、本文の番号参照・画像ごとの検出値もprivateへ移し、件数・率・傾向へ集約する。
   移設原本は`H:/mc-blueprint/private/issue114-review-20261107/review-diagnosis-numbered-20261107.md`。
   元文書とのSHA一致と、公開文書に個別番号表がないことを検証する。原本・画像はcommitしない。
3. biasの予約から発生する画像予算停止を共有stageの採否境界で捕捉し、取得済みのrecordsとfilesを返す。
   既存の登録取引へ渡すため、正常停止時も取得・登録・確定予約・消費台帳の対応を維持する。
   候補3枚・画像枠1枚で取得1・返却1・登録1・台帳1を検証する。予算消費を払い戻す修正ではない。
4. 完了件数に加え、同一assetのsegment・shade・color成功runを照合する。
   shade失敗、別assetのshade成功、jobs明細欠落を拒否し、smokeでの全量segment再利用は許容する。

追加の再現8ケースは修正前に8失敗、修正後に8成功。別にsegment再利用のsmoke成功ケースも追加した。
既存統計テストのreport fixtureも、実際のjobs明細を持つ契約へ合わせる。

## 検証

WSL Ubuntu-24.04の新規隔離PostgreSQL16で全pytest、ruff、sdist/wheel buildを実行する。
初回の全件収集は旧venvのduckdb不足で停止したため、配置済みのduckdb 1.4.3を含む検証venvを再利用した。
外部通信で依存を取得せず、テスト専用DBは各試行の終了時に停止する。

最終結果：全pytest **1,096 passed / 1 skipped、215.81秒**、既存warning 4件。
skipは従来の実GPU条件付きテスト。ruff check・sdist/wheel buildも成功した。
明細付きreportがselectionへrun IDを渡す点に合わせ、既存テストの期待値も修正した。
検証artifact：`/tmp/colorstats-issue114-fixes-fjQApm/`。
記録：`20261107T055819Z-933811e035394958b0222b5b1bd25c49.jsonl`。

## 残る境界

- 既存mobileコピー・転送先コピーの本番台帳への遡及登録は今回行わない。既存データを削除しない。
- 過去commitに残る個別情報の扱いはオーケストレータがユーザーへ確認する。
- #114は未完了。#117〜#122の品質修正と新しい目視確認後まで、新統計を作成しない。
- 指定の公開文面3ファイルはdevelop宛ての中間PR、Refs #114として更新する。push・PR作成はしない。

## 849784aの再反証修正

前回のcache登録だけでは、有効な別asset参照によって期限切れ画像入りHTMLが残った。
明示種別`image_bundle`を既存の保持APIへ追加し、同じhost/pathの構成画像のどれかが利用不可なら
全参照を解除して束全体を次回cleanupの削除対象とする。原画像や別ページの期限は変更しない。
通常のcache/replica/backup等の共有保護と既存画像の保護は維持する。DB列追加やmigrationは不要。
生成側とcleanup側を対応版へ揃える必要がある。本番への配備・既存行の種別変更は今回行わない。

停止・期限切れ・削除受付と別ページ保護、および診断本文の残存記述を修正前に5ケースで再現した。
修正後は関連9ケースが成功し、通常の共有cache・期限内の別ページ・原画像の保全も照合した。
bench/issue114のMarkdown・JSON・YAML・HTMLを点検し、実画像の単一記述は診断本文から移設した。
他の候補は集計件数・手順・一般的な設計説明であり、JSONにも個別asset_idは含まれていなかった。
移設前の全文は`private/issue114-review-20261107/review-diagnosis-before-rereview-849784a.md`、
点検結果は同じprivate配下の`head-doc-audit-849784a.json`へ保存した。両者はGitに入れない。
番号だけでなく単一画像の採否・mask・検出状況も公開文書へ戻さない。過去の履歴は変更しない。

再反証修正後の全pytestは **1,101 passed / 1 skipped、212.22秒**、既存warning 4件。
ruff check・sdist/wheel buildも成功し、隔離PostgreSQLの停止を確認した。
検証artifact：`/tmp/colorstats-issue114-fixes-18E6zo/`。
記録：`20261107T061522Z-00b48cca53b94ec4b1686e6c9d32a82b.jsonl`。
