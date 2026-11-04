# 既知属性による部分層補正（#75、design.md統合用下書き）

正本：[Issue #75の設計変更コメント](https://github.com/mc-blueprint/mc-blueprint-color-stats/issues/75)。
ユーザー決定日：2026-11-04。従来の全属性完全一致・一意層割当を置き換える。
D15・SHA代表選択・ラベル品質ゲートは変更しない。
地域・年代の新しい導出は#85、report.pyとdesign.mdの統合は#76が担当する。

## 共通の判定契約

- `asset_attributes(asset) -> (attributes, conflicts)`：
  snapshotのsubject確認済み属性とasset実属性を、既存coverageの地域・年代読取りで統合する。
  収集意図や候補値は使わない。scene_attributesに保持された確認済み・根拠付き推定値という
  従来のstate基準を維持する。欠損・None・空文字・unknownは既知値を上書きしない。
- `compatible_strata(attributes, strata) -> list[str]`：
  domainを必須とし、そのdomainの目標層の属性だけで既知値の一致を調べる。
  unknownの属性は周辺化する。両立層IDを設定順で返し、対象外は空配列。
  #76もこの関数を使用し、別の完全一致・両立判定を実装しない。
  層にないweather等は照合対象にしない。
- `assign_strata(assets, strata) -> (assigned, reasons)`：
  assignedはsubject ID→既知層属性の辞書、矛盾・対象外の場合はNone。
  reasonsはsubject ID→理由配列。適格画像間の既知値を統合し、
  unknownと既知値の混在は矛盾にしない。層属性の既知値が競合する場合は
  subject_stratum_conflict、subject/asset内の競合はattributes_conflict、
  両立層なしはoutside_target。
  従来の「subject ID→一意な層ID」という戻り値は使用しない。

条件生成は引き続き実際に分かる条件属性だけから行う。
unknownを特定style等の直接観測に補完しない。条件が不足した子には既存の親CDF借用を使う。
同じsubjectの別画像から季節・時刻を画像の条件属性へ補完する処理も追加しない。

## 推定量

各domain・条件・役割/pairごとに、条件と両立する目標層へsubjects目標を限定し、
q_hを合計1へ再正規化する。属性が目標層にない条件成分はqを狭めない。
両立する確定subjectが当該セルのNを構成する。未知subjectは主結果へ入れない。

```
m_sh = q_h * 1[両立] / Σ_{両立 h'} q_h'
p_h  = Σ_s m_sh / N
r_h  = q_h / p_h                    （p_h > 0のみ）
W_s  = Σ_h m_sh * r_h
n_eff = (Σ_s W_s)^2 / Σ_s W_s^2
```

subject内は有効SHA画像へ等配分し、画像内は役割領域の面積比、
pairは領域面積積で正規化した重みにW_sを乗じる。
同じ画像・subjectの観測行数を、Nやp_hの独立標本として数えない。
p_h=0の層はmissing_strataに残し、r_h=0等で埋めない。
支持された目標質量だけでCDFを正規化し、欠損目標質量を明示する。

qualityの追加出力：

| 項目 | 意味 |
| --- | --- |
| target_probabilities | 当該セルの再正規化済みq_h |
| memberships | subject ID→層ID→m_sh（非両立層は省略） |
| stratum_probabilities | 層ID→p_h（0の層も含む） |
| stratum_weights | 支持された層ID→r_h |
| subject_weights | subject ID→W_s |
| max_stratum_weight / max_weight | 最大r_h / 最大W_s |
| correction_rate | 両立層を1つ以上かつ全適用層未満へ絞り込めたsubject数 / N |
| attribute_unknown_rates | 層属性ごとの未知subject数 / N。domainは含めない |
| no_information_rate | 全適用層と両立するsubject数 / N |

割合の分母は当該条件・役割で採用した確定subject N。
矛盾・対象外はunassigned_subjects/reasons、未知subjectはunknown_imagesに別記する。
N=0では割合を0、空の支持・欠損質量1を保存する。
情報なし割合は条件で限定した後の適用層に対する値であり、
適用層が1つなら絞込みの余地がなく全採用subjectが情報なしに該当する。

全層両立のsubjectだけならm_sh=q_h、p_h=q_h、r_h=1、W_s=1となる。
これは情報が増えたことではなく、no_information_rate=1・未知率で明示する。
M3条件4はユーザー決定に従ってこの主結果の実測支持とn_effで判定する。

high_weight（従来どおり最大r_h>5）、層比r_hの上限5、補正なし、未知SHAを別subjectとする無補正感度、
円周Δh・経験CDF混合・30/10の支持閾値は維持する。
補正なし感度は対象外・矛盾の確定subjectも含む従来の診断として区別する。

## 再計算と検証

aggregate-v2・estimator=subject_partial_poststratified_appearanceに変更し、
旧方式のQueueキーを再利用しない。旧集計JSONは新方式で再生成する。
保存データの移行・旧推定方式へのフォールバックは追加しない。

回帰はunknown混在・全層両立・既知値矛盾・条件q再正規化・p_h=0・
subject内画像/領域正規化・high_weight・補正なし感度・W_s/n_eff手計算・
主結果と条件への非補完・既存Queue取引の検証を行う。
