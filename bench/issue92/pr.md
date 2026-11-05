# feat: LoCのカラー写真収集アダプターを追加

ラベル: `type: feature`、`priority: medium`

## 概要

- LoCの文書化JSON経路、item別権利確認、カラー画像の事前判定を行う収集アダプターを追加する。

## 変更内容

- LoCの検索・継続、順位、画像URL、Rights and Access原文を候補へ記録する。
- `No known restrictions`をpublic domainへ変換せず、解析専用として区別する。
- LoCのレート制限・robots・429/CAPTCHA停止条件をsource policyへ追加する。

## 検証

- [x] source policy YAML構文
- [x] Python 3.12構文compile
- [ ] 関連テスト — WSL環境にpytestとPillowがなく未実行
- [ ] ruff — WSL環境にruffがなく未実行
- [ ] build — WSL環境にbuildがなく未実行
- [ ] 実取得 — API要求1回はHTTP 403。保存先作成もubuntu-1でPermission denied

## 関連Issue

Closes #92
