## 追加収集の歩留まり（Issue #77、第2段階で転記）

測定計画・枠・停止条件は `bench/issue77/plan.md`、設定は同ディレクトリのtargets.yaml。
本番測定は未実行。fixtureの結果を本番の歩留まりとして掲載しない。

層ごとに全試行のAPI/HTTP要求、HTTP応答、timeout、候補、照合、取得、受信body byte、
取得成功byte、DB登録数、新規SHA、D15適格新規SHA、SHA重複、確定subjectと新規subject、
除外理由を報告する。適格新規SHA/API要求はtimeout・429再試行も分母に含める。
応答なしを「候補0件の正常応答」としない。source_policy違反・照合不一致を緩和しない。
URL再発見とSHA重複は区別する。確定subjectは検索意図や名前一致だけでは数えない。
台帳のrunning/preparedが残る場合は未完了として扱い、成功試行だけに分母を絞らない。
Openverse by/by-saは照合済みの選択値と版から測定時に正規化する。SA等の除外は維持する。
供給元枠はCommons API14/HTTP22、Openverse API6/HTTP18を層ごとに固定する。
通信0回の供給元は未測定と明記する。1万Asset行枠と適格SHA1万枚は区別し、
層・供給元ごとの要求当たり適格SHAと取得byteを用いた参考外挿の仮定を併記する。

既存保存データの削除・移行、新規依存、権利条件や集中上限の変更はない。
実測表と証跡は第2段階で追記し、#76担当がdocs/collection-bias.mdへ統合する。
