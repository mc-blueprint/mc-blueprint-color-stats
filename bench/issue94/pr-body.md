## 概要

- 道路沿い建築の色解析候補を、固定bboxと登録アプリの公開APIから扱うMapillaryアダプターを追加する。
- **完成条件に未解決あり**。robotsの全面拒否を確認したためソースは無効。公開APIとの適用判断・現行公開レート確認・実画像での取得/再開確認が完了するまで有効化しない。

## 変更内容

- 固定検索意図、offset/cursorの永続対応、順位・native ID・sequence・作者/地域の記録、公式thumbnail取得を追加。
- LoadCredential専用認証、API完全一致先だけのOAuthヘッダー、署名URL非保存、未確認/人物/連写候補の事前除外を追加。
- analysis_only・bias・非公開保持/削除・配布境界を再利用。目標の本収集は#105完了後。
- priority: medium / type: feature（Issueと同じ。Commonsによる回避策があるためmedium）。

## 検証

- [x] HTTP fixture・隔離PostgreSQL16での保持/rollback/再投入/期限/停止確認
- [x] ruff・全pytest（最終件数はbench/issue94/results.md）
- [x] sdist/wheelビルド
- [ ] 実画像取得・実画像での再開確認：API1要求・11 byte、空結果。robots1要求は別計測でbyte未記録。画像/適格0枚で停止
- [ ] 公開APIとrobotsの適用関係・現行公開レート確認：判断待ち

## 関連Issue

Closes #94

Refs #105
