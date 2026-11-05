# 現在値の所有権確認とdevelop取込み

通常補完では属性ごとの最新推定履歴が書いた値と現在値が一致する場合だけ再評価する。
`owned_attributes`だけでは許可せず、最新履歴と不一致でも古い履歴に一致する値を再評価対象に戻さない。
訂正専用処理の明示的な`mutable`は、保存計画・所有run・現在値を呼出し元で確認した属性に限る。
手動訂正・他runの値は保持し、自身が書いたunknownは現在値が一致する場合に再評価できる。

本番ubuntu-2はREAD ONLYで成功済み3 run、現在2,523画像、owned属性740件を照合した。
現在値が所有runの記録と異なる属性0件、保存履歴上の手動・他run変更値を上書きした属性0件。
集計・対象範囲・限界・コマンド記録は[owned-value-audit.json](owned-value-audit.json)を参照。
本番への書込み、snapshot/run/reportの再作成は行っていない。

`origin/develop`をfetchし、指定の`e51843c2fb8195b3f597716e9c43d42ee9bd45cd`と一致した。
merge commitは`443d7c4b9792ed741cdba69d27390fa490823ec4`。競合なし。
#90・#94の変更はmergeで取り込み、担当外の収集・前処理・source_policyの実装を独自編集していない。
rebase・push・PR作成は行っていない。

通常補完のDB回帰では履歴を残したautumnがsummerへ戻らず、更新runも増えないことを検証する。
単体回帰では最新履歴と異なり古い履歴とは一致する値の保持、および所有unknownの再評価を検証する。
統合後の全検証結果は`owned-value-verification.json`へ記録する。

最終コードの検証: ruff成功、全pytest 959 passed / 1 skipped、sdist/wheel build成功。
WSL Ubuntu-24.04のext4一時コピーと専用PostgreSQL 16を使用し、DBは終了済み。
検証済みsrc/configs/tests/taxonomyと担当worktreeのバイト一致を確認した。
