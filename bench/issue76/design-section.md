# design.md §12 追記案（部分層補正・本体未統合）

正本はIssue #75の「設計変更：既知属性による部分層補正」（2026-11-04）と
Issue #76の追従コメント。詳細な推定量・単位・割合の定義は
[bench/issue75/design-section.md](../issue75/design-section.md)を参照する。

## M3完成条件4の置換案

建築・地形の各1役割以上で、モデル品質が検証済みであり、
**既知属性による部分層補正の主結果の確定subject数>=10かつsubject n_eff>=10**を満たす。
補正率・属性別未知率・情報なし割合を同じ条件・役割の分母とともに併記する。
unknownは周辺化し、検索意図や候補値で補完しない。全層と両立するsubjectだけでも
主結果で判定するが、補正率0・情報なし割合1を隠さず、属性が判明したとは扱わない。
親からの借用だけでは観測subject数やn_effを増やさない。D15は変更しない。

これは#75のdirect_min=30という支持ラベルとは異なる内部有用性ゲート。
10〜29 subjectでも主結果の閾値を満たせる。パック生成・同梱や10万画像目標は別状態。

## レポートの責務と層表示

report(snapshot, snapshot_id, statistics, settings)はDB・元画像に接続せず、
全hash検証と同じ#75設定での再集計により統計JSON全体の一致を要求する。
入力はaggregate-v2の登録対象JSON。report-v3として旧集計・レポートは再生成する。

属性統合はweights.asset_attributes、両立判定はcompatible_strata、
subjectの既知値統合・矛盾判定はassign_strataを使用する。
独自の完全一致・一意層割当は行わない。欠損・None・空文字・unknownは照合せず、
適格画像間の既知値の競合・対象外subjectを除外理由へ残す。
複数層との両立や一部属性の不足だけでは未割当としない。

画像の両立件数と採用subjectの両立件数は層間で重複し得る。
層の所属質量は#75 calculateから得るm_shの和とし、
被覆=所属質量/目標subject数、不足=max(0, 目標subject数-所属質量)とする。
全体は一度だけ数えたsubject数。unknownを各層へ1 subjectずつ足さない。
画像の条件別観測には実際に分かる条件だけを使い、#75の_conditionsを再利用する。

分類の補正率・未知率・情報なし割合の分母は各domainの適格確定subject数
（役割品質の前）。条件・役割/pairの主結果は、当該セルの#75 qualityをそのまま表示し、
分母のsubject_countも併記する。適用層が1つなら情報なし割合1となる定義も維持する。
条件4は役割別の主結果を使い、分類全体のn_eff等を代用しない。
p_h=0の層・欠損目標質量、high_weightと補正なし感度を維持する。

## D15・完成条件・実行

D15診断は保存済み部位色の両立subject数、失ったsubject集合差、
品質・部分層補正後の採用数と所属質量を分ける。
権利除外前の和集合色が未保存なら構成部位から代用せず、前後差をnullとする。
条件5は根拠不足があればunverified。#74最新6c8534bの取込みはこの変更に含めず、
追加のrights_eligible等の列やD15前unionがあっても既存の列読取りを維持する。
#74統合後の実snapshot照合は第2段階へ残す。

条件3はhash検証・再計算一致、条件1・2・6は全量監査・再推定監査・G受領を別途確認する。
m3_completeは自動確認の全条件がpassedの場合だけtrueとし、外部確認を推測しない。

~~~sh
python -m colorstats.stats.report_cli --snapshot /path/snapshot --snapshot-id <hash> --statistics /path/aggregate.json --config configs/stats.yaml --targets configs/collection_targets.yaml --taxonomy taxonomy --output /path/new-report
~~~

出力は未使用ディレクトリのJSON／Markdown。書込み失敗時の部分出力は再利用しない。
コード・taxonomy・設定・snapshot・統計hashを保存し、同一入力から同じバイト列を再現する。
