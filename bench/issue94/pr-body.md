## 概要

- 道路沿い建築の色解析候補を、固定bboxと登録アプリの公開APIから扱うMapillaryアダプターを追加する。
- **完成条件1・6は未達**。ユーザー決定（2026-11-05）に従い、robotsと規約§5・§11の関係についてMapillaryの回答を待つ。回答までOpenverse経由を含む全Mapillary hostへの通信を停止する。レートは自主上限を維持する。

## 変更内容

- 固定検索意図、offset/cursorの永続対応、順位・native ID・sequence・作者/地域の記録、公式thumbnail取得を追加。
- LoadCredential専用認証、API完全一致先だけのOAuthヘッダー、署名URL非保存、未確認/人物/連写候補の事前除外を追加。
- analysis_only・bias・非公開保持/削除・配布境界を再利用。目標の本収集は#105完了後。
- 現行policyをprepare時とHTTP送信直前に照合し、過去の許可・redirect・待機中の無効化にも従う。
- CDNの共有枠をrate_group単位で台帳復元し、401/403をworkerの再試行なし失敗として記録する。
- priority: medium / type: feature（Issueと同じ。Commonsによる回避策があるためmedium）。

## 検証

- [x] HTTP fixture・隔離PostgreSQL16での保持/rollback/再投入/期限/停止確認
- [x] ruff・全pytest（最終件数はbench/issue94/results.md）
- [x] sdist/wheelビルド
- [ ] 実画像取得・実画像での再開確認：API1要求・11 byte、空結果。robots1要求は別計測でbyte未記録。画像/適格0枚で停止
- [x] 反証4点の回帰：全host/集約元ページ/redirect/待機中/過去ジョブ、別CDN共有枠、401/403のspawn伝播
- [x] 本番DB READ ONLY件数確認：該当する過去有効ジョブはMapillary・Openverseとも0件
- [ ] 完成条件1：公開APIとrobots・規約の適用関係についてMapillary回答待ち
- [ ] 完成条件6：実画像での取得・再開確認は回答後。今回の修正では外部サイト通信なし

## 関連Issue

Refs #94

Refs #105
