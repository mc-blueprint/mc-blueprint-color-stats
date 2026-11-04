> 2026-11-05: 第2段階でdocs本体へ統合済み。以下は第1段階の設計記録。現状はfull-results.md参照。

# collection-bias.md 追記案（第1段階・未統合）

固定snapshotと、そのsnapshotから生成したaggregate CLIのJSONを入力にする。
JSONのrowsはrule_statへの登録対象と同じ内容であり、本レポート自体はDB登録を証明しない。
全Parquetのhash検証後に#75と同じ設定で再計算し、入力JSON全体との一致を要求する。
weights.asset_attributes・compatible_strata・assign_strata・calculateを再利用する。

収集意図の層とsubject・assetの保存属性に一致する層を分ける。
推定stateがない既存属性はrecordedとし、根拠付き推定成功に含めない。
競合・不足・対象外・複数層一致を分離する。件数はasset行／SHA異なり／
確定subject／候補のみ／未知／適格なSHA代表画像を区別する。
全体のSHA異なりは全体で直接数え、層別件数を足さない。
同じSHAが別層にも現れ得る。

率はnumerator・denominator・valueを持つ。分母0はnull。
層の意図比較は当該層の収集意図行数を分母とし、属性不足・不一致・競合を示す。
適格率・除外理由・未知率・集中率は各集計対象のasset行数が分母。
除外理由は重複し得るので合計を除外画像数として扱わない。
D15適格→解析適格→SHA代表の段階と前後のsubject数を出す。
author等は既知値の上位占有率、未知率、既知の個別値と未知1カテゴリの
Shannon entropy（bit）を表示する。regionはsubject.location、
撮影位置はasset.collected_locationを使い、検索意図から補完しない。

条件・役割／pairごとにdirect／smoothed／unsupported、subject基準n_eff、
最大重み、欠損目標質量、感度分布、品質フラグ、親とλを#75から引き継ぐ。
10万枚の達否はD15・解析・重複除外後の画像数で別表示する。
これは現実母集団への無偏推定や材質色の証明ではない。

第2段階で実snapshot・実rule_stat・#66/#72監査を照合し、本番の数値と
M3完成条件の結果を追記する。合成fixtureの値を実データの結果に流用しない。

## 反証修正後の表示

地域・年代は既存coverageと同じsubject.location・subject.eraから取り込む。
同一subjectの画像が異なる層へ一致すれば、各画像の両立は表示するが、
そのsubjectをどちらの層の採用数にも足さず、不足数と未割当理由へ反映する。
D15除外・解析不足の画像は主統計のsubject割当へ戻さない。

rights_supportは層・条件と役割ごとにD15前後の保存済み色観測subjectと失ったsubjectを表示する。
画像件数差ではなくsubjectの集合差であり、同じsubjectの適格観測が残れば失った数に含めない。
個別部位の保存観測と、和集合マスクから生成した色を区別する。
#74でD15除外画像の和集合色が保存されない場合、前後差は不明のまま明示し、
条件5をpassedにしない。構成部位の存在だけから和集合色の支持を作らない。


2026-11-04の部分層補正で、unknown属性は周辺化し、複数層との両立を許す。
既知値の矛盾と対象外だけをsubject単位で棄却する。層の採用数は両立数で重複し得るため、
目標への被覆・不足はm_shの和で計算する。条件・役割の補正率・未知率・情報なし割合は
分母subject_countとともに#75主結果から表示する。分類の全体率とは分母を混同しない。
全層両立でも主結果で条件4を判定し、補正率0・情報なし割合1を併記する。D15は変更しない。
