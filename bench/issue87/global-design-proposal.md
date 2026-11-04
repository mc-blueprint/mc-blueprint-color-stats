# 全体正本への変更案（未反映）

対象：.github-private/docsのD15・収集方針・M4パック契約。正本は本Issueで編集しない。

- 2026-11-04ユーザー決定：確認済み情報解析専用入力からの非表現的統計をMIT配色パックへ含める。画像自体を再配布せず、元licenseを変更しない。
- D15を既存open経路とanalysis_only経路へ分ける。SA/NC/NDの既存入力を一括昇格しない。全モデル重みはopen必須。
- analysis_onlyはsource/assetの元権利・確認根拠一致、出典・原画像識別子・provider・取得日時、用途・規約/API/robots確認を必須とする。禁止・未確認・失効・停止・削除受付は除外。
- openを中立に区分合成し、異なる非open制約の混在はrestricted。内部snapshotとM4配布物を分ける。
- 保持は新規収集のみ30日、不採用7日、削除受付時の利用停止と7日以内削除、backup残留30日（短いソース条件優先）。既存7,607件は削除しない。原画像期限清掃と統計根拠失効は別。窓口は#88で確定。
- M4配布はdocs/pack-contract.mdのallowlistと混入拒否を実装する。DATA_LICENSEのMITは生成配色データにだけ適用する。
- LoC/Mapillaryは#88と個別Issueの条件完了後に有効化する。Mapillary規約全文・API用途・大量保存条件はユーザー確認待ち。SNS一般を一律許可しない。

根拠：Issue #87、引継ぎd-collect-design.md §3〜§6、m3-cond4-decision.md末尾。
