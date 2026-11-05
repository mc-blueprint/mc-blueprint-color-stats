# feat: LoCの取得停止と一括データ候補を記録

ラベル: `type: feature`、`priority: medium`

## 概要

- LoC APIのCloudflare challenge停止を実装し、公式一括データ候補を調査する。

## 変更内容

- APIアダプターをsource policyで無効化し、challenge時に再試行せず停止する。
- Free to Use metadata/manifestとRights欄、画像経路・容量を調べ、未承認の取り込み案を記録する。

## 検証

- [x] source policy YAML構文
- [x] Python 3.12構文compile
- [x] 関連テスト — 627 passed, 271 skipped
- [x] ruff
- [x] build
- [x] API実取得 — 403 challenge、適格画像0。画像一括取得なし

## 関連Issue

Refs #92
