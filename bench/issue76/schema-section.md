> 2026-11-05: 第2段階でdocs本体へ統合済み。以下は第1段階の設計記録。現状はfull-results.md参照。

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

## report-v3の出力契約

- confirmed_subjects_afterは当該層に両立する採用subject数（層間で重複あり）。
  confirmed_subjects_after_snapshotは権利・解析・SHA重複除外後、層割当前のsubject数。
  subject_massは#75のm_shの和、subject_coverageは質量/目標、subject_deficitは目標-質量。
  unassigned_subjectsは既知値矛盾・対象外などのsubject数。
- classification.image_unassignedは全asset行に対する画像属性の未割当率。
  classification.unassignedは適格SHA代表画像を分母とするsubject未割当率。
  subject_stratum_conflictも同じ分母で、unassigned_subject_reasonsはsubject単位の件数。
- rights_supportはcondition／stratumと役割ごとの保存済み色観測の確定subject数。
  recorded_subjects_before_d15／recorded_subjects_after_d15／lost_subjects_d15は、
  同じ役割でD15通過後にも観測を持つsubjectを残して集合差で求める。
  subjects_after_analysisはsnapshot適格段階、adopted_subjectsは品質・部分層補正後の両立subject数。
  n_effを再計算した値ではない。統計支持は従来のsupportに保持する。
- 和集合色が未保存なら該当前後数・集合差はnull。
  unverified_union_assetsとcomplete、理由を出し、条件5をunverifiedにする。
  unobserved_rights_excluded_assetsは部位色観測自体のない権利除外画像数。

旧合成artifactは同じ入力からreport-v3で再生成する。
DB・snapshotの移行は不要。レポート旧形式の互換処理は追加しない。


部分層補正ではassign_strataの戻り値は既知属性辞書。複数両立・属性不足だけでは棄却しない。
classification.partial_correctionはdomain別の適格確定subjectを分母とした補正・未知・情報なし率。
supportおよびusefulness_gates.correctionの割合は当該条件・役割の#75主結果をそのまま使用する。
rights_support.adopted_subject_massも層の所属質量とし、両立subject数と分ける。
入力JSONはaggregate-v2。旧方式の統計・report-v2は再生成し、互換処理は追加しない。

補正率等は#75定義に従い、N=0では0。件数比率の空分母nullとは区別する。


条件4のm3_checks項目にrole_results（domain別の判定候補役割）を添える。
各役割はsubject_count・n_eff・補正率・情報なし割合・passed・quality_flagsを保持する。
情報なし割合>0.5でweak_correction。ちょうど0.5には付けない。
domainのusefulness_gatesと条件4のquality_flagsは役割フラグの和集合。
判定の閾値は従来どおりで、#75の統計quality・支持・補正率は変更しない。
reasonに「passed は層補正の有効性を意味しない」と明記する。
