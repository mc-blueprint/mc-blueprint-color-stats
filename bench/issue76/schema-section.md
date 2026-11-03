# schema.md 追記案（第1段階・未統合）

DBとsnapshot-v1の形式は変更しない。
report CLIへのstatisticsは#75 aggregate CLIの出力全体を渡す。
rowsはrule_statの登録対象行と同じで、snapshot_id・taxonomy_version・input_runsを保持する。
DBのrule_stat単体を抜き出したJSONは由来が足りないため本CLIの入力にはしない。
本番の登録済みrunと同じ出力であることの照合は第2段階で行う。

report.json:
- snapshot_id、コード版、aggregateコード版、taxonomy版、設定／統計hash。
- overall、strata（意図／属性一致／意図比較）、classification。
- observation_exclusions、snapshot_exclusions、model_quality。
- support（条件・役割／pair・sample_count・subject_count・effective_sample_size・
  単位／方向・quality・感度分布）。
- processing（snapshot保存runと件数、Parquet byte数、計測範囲）。
- scale_target（10万適格画像の段階目標、M3必須条件とは別）。
- usefulness_gates、m3_checks、m3_complete、handoff。
- 率は{numerator, denominator, value}。空分母はnull。

supportの数値・品質・感度分布は再計算一致を検証した#75の値。
sample_countは採用SHA画像数、subject_countとn_effはsubject基準。
relationの方向はB-A、面積比はB/A、Δhはdegree、色はOKLab。
親借用と欠損目標質量を隠さず、未支持分布を支持済みとして扱わない。
権利除外はsnapshotに保持し、帰属の正本はprovenance.parquet。
Gの配色パックSchemaやDATA_LICENSEを本レポート形式で先取りしない。
