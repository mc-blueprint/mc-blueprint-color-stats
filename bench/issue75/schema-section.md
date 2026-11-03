### subject重み付きrule_stat（Issue #75、schema.md統合用下書き）

第1段階は実装・fixture検証まで。本番登録と公開文面は#74の実snapshot後。
docs/schema.md・docs/design.mdへはまだ統合しない。

入口は `python -m colorstats.stats.aggregate_cli`。
`--snapshot <ディレクトリ> --snapshot-id <信頼済みhash> --output <JSON出力名>`
を必須とし、`--config configs/stats.yaml`、`--targets configs/collection_targets.yaml`、
`--taxonomy taxonomy`を固定設定として読み取る。
`--dry-run`はDBへ接続せず、新規出力ファイルへ計算結果を保存する。
通常実行はsnapshot全体のhash検証後にaggregate jobを投入する。
実行は既存Queue CLIの
`--handler aggregate=colorstats.stats.aggregate --stop-file <停止ファイル>`
を使用する。DATABASE_URLを表示しない。

既存のDuckDB/Parquet・taxonomy/目標検証・共起抽出・Queue完了取引を再利用する。
追加依存はない。軸別CDFの確率質量と親との混合を明示的に保持するため、
通常の非重み付きquantileへの置換や分位点同士の平均は行わない。

#### 重みと実測支持

- snapshotが適格としたSHA代表だけを使う。主色は最大クラスタのdominant。
  クラスタのquantilesは生画素の代用にしない。
- 画像内は役割の領域面積比、pairでは面積積で正規化する。
  subject内では当該条件・役割/pairの有効SHA画像へ等配分する。
- subjectの属性と画像の実属性を照合し、対象層へ一意一致する場合だけ事後層化する。
  同じsubjectの画像間の層矛盾も除外する。収集意図で属性を埋めない。
  地域・年代・季節等が欠ける場合も未割当となる。
- 条件に適用可能な目標subjectsを正規化したq_hと、
  適格な確定subjectの層比率p_hからq_h/p_hを求める。
  層0件の目標質量は欠損として残し、観測層だけで被覆率を報告する。
- weightはsubjectへ合計した重みの総和。effective_sample_sizeは
  (ΣW_s)^2/ΣW_s^2。sample_countは実際に主統計へ入れたSHA異なり画像数、
  subject_countはその確定subject数。平滑化で増やさない。
- 未知subjectは主分母へ入れず、SHA単位の無補正診断と、
  各未知SHAを別subjectとした無補正感度分布を保存する。
  未割当理由はattributes_missing、outside_target、multiple_strata、
  attributes_conflict、subject_stratum_conflictとして独立に数える。

#### distribution JSON

| 項目 | 意味 |
| --- | --- |
| kind | palette / relation |
| estimator | subject_poststratified_appearance（観測subjectの外観主色） |
| cdf | 軸→値順の[value, probability_mass]。同値は合算し、累積和が経験CDF |
| quantiles | 軸→[{q,value}]。q=.05/.25/.50/.75/.95、累積質量がq以上となる最小値 |
| hue | relationのみ。range=[-180,180]、左端を含む10度幅36bin、右端180は-180へ折返し |
| hue.bins / null_mass | 全採用重みに対する円周bin質量と無彩色NULL質量。両者の合計は1（空なら0） |
| units | 色・差はOKLab、Δhは度、面積比はB/A |
| direction | relationはtaxonomy順の異役割A→B、差はB−A |
| parent / lambda | 実際の親条件・役割と子CDFの混合係数 |
| diagnostics | raw、uncorrected、capped_5、unknown_as_subject、unknown_onlyの分布 |

paletteの軸はL/a/b、relationはdelta_l/delta_c/delta_e_ok/area_ratio。
Δhには線形分位点を作らない。逆pairはΔL/ΔC/Δhの符号と面積比を反転する。
同役割pair・非co_occurs・ゼロ面積・非有限値・無効面積比は採用しない。

#81の個別支持は実建築door、和集合は実建築wall・実地形tree。
和集合色を個別ラベルの色で置き換えない。和集合を含むpairはsnapshot内の固定した
主色・面積から既存extract_relationsでco_occursを再構成する。
個別領域間のpairはsnapshotのrelationを使用する。
未支持ラベルは親が支持済みでもstatus=unsupportedとし、model_unvalidatedを残す。

#### 平滑化・quality JSON

建築の条件親は(style,building_type,biome_like)→(style,building_type)→style→domain、
地形はbiome_like→domain。条件を全て緩めた後だけ部位親へ進む。
異domainへの借用は行わない。

subject_countとn_effの両方が30以上ならdirect。
10以上30未満は利用可能な親とλ=n_eff/(n_eff+20)で経験CDFを混合する。
10未満はλ=0で親のみ。親も未支持ならunsupportedとし、主分布を空にする。
styleとその子条件の両段で混合する場合、混合済みの親CDFを順に使用する。

qualityにはstatus、flags、raw_subjects、raw_n_eff、parent、lambda、source_quality、
target_mass_coverage、missing_target_mass、missing_strata、max_weight、
unknown_images、unassigned_subjects、unassigned_reasons、snapshot_id、
gate_version、snapshot全体のexclusionsを保存する。
exclusionsはセルの除外件数ではなく、元snapshotのコホート全体の件数。
low_support・smoothed・unsupported・subject_unresolved・attributes_inferred・
intended_only・high_weight・missing_target_mass・model_unvalidated・license_excludedを併記する。
主重みはクリップせず、上限5と補正なしの感度分布を別記する。
confidence_intervalはSQL NULL。

#### 登録と失敗境界

同じsnapshot_id・固定設定・実装版は同じQueueキー。パスはキーの意味へ含めず、
同じjobを再投入する際は元のsnapshot/outputパスを維持する
（既存Queueの同一キー・異payload拒否規約に従う）。
コードはprepareでsnapshotを再検証し、試行固有のJSONを生成する。

registerは適格assetの採用runと推定runを由来閉包として照合し、
processing_run_inputへ結ぶ。除外assetだけのrunを主統計へ戻さない。
runの成功・版・設定・コード・モデル・重み・制約・parameters・入力辺をDBと照合する。
ライブDBの観測や属性でsnapshotを補完しない。
Queue.completeの所有権確認と同一取引でrun・全rule_stat・job成功を確定する。
エラーなら全件rollback、旧統計は保持。未参照artifactは成功結果として扱わない。
既存データの移行・削除は不要。

第2段階では#74の実snapshotからdry-run・実登録を行い、実測支持数・不足・
実データ計測・再計算比較を確認した後、正本節の統合と公開文面を準備する。
