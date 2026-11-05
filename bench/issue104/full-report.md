# M3 偏り・支持範囲レポート

- snapshot: `fb7bc1af34b036cb111ae9ae6274195931e2c2271d764eb040e96bda55326942`
- コード: report-v3 / aggregate-v2
- taxonomy: 0.1.0 / 設定hash: `2f6839819c378129703acecb61cd35007adbb3e2e228f0493427e78a3fb601a4`
- 統計hash: `556f923b097d55fabf819d40aba51bd12d9daa24beb0e3a237704328a152501e`
- M3完了: False / 10万枚達成: False
- 両立件数は層間で重複する。所属質量はm_shの和、不足は目標subject数との差。
- unknownは周辺化し、属性が判明したとは扱わない。詳細・感度分布はJSON参照。
- 件数比率の空分母はnull。補正率・未知率等は#75の定義に従いN=0なら0。

| 層 | 意図両立行数 | 属性両立行数 | SHA異なり | 重複行 | 適格/分母 | subject前/適格/両立採用 | 所属質量 | 被覆 | 不足 | 除外理由（件数/分母） |
|---|---:|---:|---:|---:|---|---|---:|---|---:|---|
| 全体 | 7607 | 7607 | 3575 | 4032 | 3570/7607 | 154/154/140 | 140 | None | None | missing_analysis: 6/7607、sha_duplicate: 4031/7607 |
| japanese-castle | 668 | 3508 | 1750 | 1758 | 1746/3508 | 11/11/11 | 5.75 | 0.0575 | 94.25 | missing_analysis: 4/3508、sha_duplicate: 1758/3508 |
| gothic-temple | 668 | 3776 | 1950 | 1826 | 1946/3776 | 77/77/77 | 43.3333 | 0.43333333333333335 | 56.666666666666664 | missing_analysis: 4/3776、sha_duplicate: 1826/3776 |
| forest-autumn-day | 566 | 2790 | 1146 | 1644 | 1146/2790 | 17/17/16 | 8 | 0.08 | 92.0 | sha_duplicate: 1644/2790 |
| modern-house | 616 | 3859 | 1919 | 1940 | 1914/3859 | 25/25/25 | 25 | 0.25 | 75.0 | missing_analysis: 6/3859、sha_duplicate: 1939/3859 |
| medieval-house | 668 | 3782 | 1895 | 1887 | 1891/3782 | 67/67/66 | 33 | 0.33 | 67.0 | missing_analysis: 4/3782、sha_duplicate: 1887/3782 |
| japanese-temple | 668 | 3585 | 1822 | 1763 | 1818/3585 | 12/12/12 | 6.08333 | 0.06083333333333333 | 93.91666666666667 | missing_analysis: 4/3585、sha_duplicate: 1763/3585 |
| islamic-temple | 535 | 3634 | 1847 | 1787 | 1843/3634 | 10/10/10 | 8.58333 | 0.08583333333333334 | 91.41666666666667 | missing_analysis: 4/3634、sha_duplicate: 1787/3634 |
| chinese-house | 613 | 3609 | 1787 | 1822 | 1783/3609 | 1/1/1 | 0.25 | 0.0025 | 99.75 | missing_analysis: 4/3609、sha_duplicate: 1822/3609 |
| mountains-summer-day | 664 | 2693 | 1095 | 1598 | 1095/2693 | 11/11/11 | 3 | 0.03 | 97.0 | sha_duplicate: 1598/2693 |
| plains-summer-day | 613 | 2650 | 1075 | 1575 | 1075/2650 | 11/11/10 | 2 | 0.02 | 98.0 | sha_duplicate: 1575/2650 |
| desert-summer-day | 664 | 2828 | 1175 | 1653 | 1175/2828 | 12/12/11 | 3 | 0.03 | 97.0 | sha_duplicate: 1653/2828 |
| snowy-winter-day | 664 | 2753 | 1122 | 1631 | 1122/2753 | 11/11/10 | 2 | 0.02 | 98.0 | sha_duplicate: 1631/2753 |

## 収集意図に対する属性確認

| 層 | 両立/意図行 | 属性不足/意図行 | 非両立/意図行 | 属性競合/意図行 |
|---|---|---|---|---|
| japanese-castle | 631/668 | 668/668 | 37/668 | 0/668 |
| gothic-temple | 643/668 | 668/668 | 25/668 | 0/668 |
| forest-autumn-day | 562/566 | 566/566 | 4/566 | 0/566 |
| modern-house | 616/616 | 616/616 | 0/616 | 0/616 |
| medieval-house | 615/668 | 668/668 | 53/668 | 0/668 |
| japanese-temple | 624/668 | 668/668 | 44/668 | 0/668 |
| islamic-temple | 511/535 | 535/535 | 24/535 | 0/535 |
| chinese-house | 562/613 | 613/613 | 51/613 | 0/613 |
| mountains-summer-day | 659/664 | 664/664 | 5/664 | 0/664 |
| plains-summer-day | 607/613 | 613/613 | 6/613 | 0/613 |
| desert-summer-day | 664/664 | 664/664 | 0/664 | 0/664 |
| snowy-winter-day | 599/664 | 664/664 | 65/664 | 0/664 |

## 分類と未知

```json
{"assignment_scope":"適格SHA代表画像。既知値の矛盾・対象外のみsubject全体を棄却","attribute_states":{"biome_like":{"conflict":2,"inferred":373,"unknown":7232},"building_type":{"conflict":4,"inferred":461,"unknown":7142},"era":{"inferred":431,"unknown":7176},"region":{"inferred":659,"unknown":6948},"season":{"inferred":244,"unknown":7363},"style":{"inferred":44,"unknown":7563},"time_of_day":{"inferred":35,"unknown":7572}},"attributes_conflict":{"denominator":7607,"numerator":0,"value":0.0},"attributes_missing":{"denominator":7607,"numerator":7607,"value":1.0},"image_unassigned":{"denominator":7607,"numerator":153,"value":0.020113053766267912},"intent_mismatch":{"denominator":7607,"numerator":314,"value":0.0412777704745629},"multiple_strata":{"denominator":7607,"numerator":6568,"value":0.8634152754042329},"outside_target":{"denominator":7607,"numerator":153,"value":0.020113053766267912},"partial_correction":{"real_building":{"attribute_unknown_rates":{"building_type":0.8934426229508197,"era":0.7540983606557377,"region":0.05737704918032787,"style":0.9918032786885246},"correction_rate":1.0,"missing_target_mass":0.0,"no_information_rate":0.0,"subject_count":122,"target_mass_coverage":1.0,"unassigned_subjects":14},"real_terrain":{"attribute_unknown_rates":{"biome_like":0.6666666666666666,"season":0.8333333333333334,"time_of_day":1.0},"correction_rate":0.4444444444444444,"missing_target_mass":0.0,"no_information_rate":0.5555555555555556,"subject_count":18,"target_mass_coverage":1.0,"unassigned_subjects":0}},"stratum_counts_are_not_additive":true,"subject_stratum_conflict":{"denominator":3570,"numerator":0,"value":0.0},"unassigned":{"denominator":3570,"numerator":3224,"value":0.9030812324929972},"unassigned_subject_reasons":{"outside_target":14}}
```

## 内部有用性ゲート（条件4）

- real_building: True（役割: door, wall）
- real_terrain: True（役割: tree）

建築・地形の部分層補正主結果のsubject数・n_effとモデル品質で判定。passed は層補正の有効性を意味しない

weak_correction は情報なし割合が過半の品質フラグで、passed の判定を変更しない。
| domain | 判定役割 | passed | subject（率の分母） | n_eff | 補正率 | 情報なし割合 | 品質フラグ |
|---|---|---|---:|---:|---:|---:|---|
| real_building | accent_other | False | 0 | 0 | 0 | 0 | なし |
| real_building | band_course | False | 0 | 0 | 0 | 0 | なし |
| real_building | column | False | 0 | 0 | 0 | 0 | なし |
| real_building | context | False | 0 | 0 | 0 | 0 | なし |
| real_building | cornice | False | 0 | 0 | 0 | 0 | なし |
| real_building | door | True | 96 | 24.4792 | 1 | 0 | なし |
| real_building | fence | False | 0 | 0 | 0 | 0 | なし |
| real_building | foundation | False | 0 | 0 | 0 | 0 | なし |
| real_building | frame | False | 0 | 0 | 0 | 0 | なし |
| real_building | gable_wall | False | 0 | 0 | 0 | 0 | なし |
| real_building | ground_grass | False | 0 | 0 | 0 | 0 | なし |
| real_building | ground_soil | False | 0 | 0 | 0 | 0 | なし |
| real_building | opening | False | 0 | 0 | 0 | 0 | なし |
| real_building | ornament | False | 0 | 0 | 0 | 0 | なし |
| real_building | path | False | 0 | 0 | 0 | 0 | なし |
| real_building | path_natural | False | 0 | 0 | 0 | 0 | なし |
| real_building | railing | False | 0 | 0 | 0 | 0 | なし |
| real_building | relief | False | 0 | 0 | 0 | 0 | なし |
| real_building | rock_face | False | 0 | 0 | 0 | 0 | なし |
| real_building | rock_scree | False | 0 | 0 | 0 | 0 | なし |
| real_building | roof | False | 0 | 0 | 0 | 0 | なし |
| real_building | roof_surface | False | 0 | 0 | 0 | 0 | なし |
| real_building | sand | False | 0 | 0 | 0 | 0 | なし |
| real_building | shutter | False | 0 | 0 | 0 | 0 | なし |
| real_building | stairs_entry | False | 0 | 0 | 0 | 0 | なし |
| real_building | tree | False | 0 | 0 | 0 | 0 | なし |
| real_building | tree_trunk | False | 0 | 0 | 0 | 0 | なし |
| real_building | vegetation_tree_canopy | False | 0 | 0 | 0 | 0 | なし |
| real_building | wall | True | 121 | 27.0485 | 1 | 0 | なし |
| real_building | wall_main | False | 0 | 0 | 0 | 0 | なし |
| real_building | wall_secondary | False | 0 | 0 | 0 | 0 | なし |
| real_building | water | False | 0 | 0 | 0 | 0 | なし |
| real_building | window_frame | False | 0 | 0 | 0 | 0 | なし |
| real_building | window_glass | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | accent_other | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | band_course | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | column | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | context | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | cornice | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | door | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | fence | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | foundation | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | frame | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | gable_wall | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | ground_grass | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | ground_soil | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | opening | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | ornament | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | path | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | path_natural | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | railing | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | relief | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | rock_face | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | rock_scree | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | roof | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | roof_surface | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | sand | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | shutter | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | stairs_entry | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | tree | True | 18 | 15.625 | 0.444444 | 0.555556 | weak_correction |
| real_terrain | tree_trunk | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | vegetation_tree_canopy | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | wall | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | wall_main | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | wall_secondary | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | water | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | window_frame | False | 0 | 0 | 0 | 0 | なし |
| real_terrain | window_glass | False | 0 | 0 | 0 | 0 | なし |

## 条件・役割別支持

| 条件 | 役割/pair | 種別 | 支持 | subject（率の分母） | n_eff | 最大重み | 欠損目標質量 | 補正率 | 情報なし割合 | 属性別未知率 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| {"biome_like":"desert","domain":"real_terrain"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | tree | palette | unsupported | 1 | 1 | 1 | 0 | 0 | 1 | {"biome_like":0.0,"season":1.0,"time_of_day":1.0} |
| {"biome_like":"desert","domain":"real_terrain"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"desert","domain":"real_terrain"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | tree | palette | unsupported | 4 | 4 | 1 | 0 | 0 | 1 | {"biome_like":0.0,"season":0.75,"time_of_day":1.0} |
| {"biome_like":"forest","domain":"real_terrain"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"forest","domain":"real_terrain"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | tree | palette | unsupported | 1 | 1 | 1 | 0 | 0 | 1 | {"biome_like":0.0,"season":1.0,"time_of_day":1.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"mountains","domain":"real_terrain"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | tree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"plains","domain":"real_terrain"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | tree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"biome_like":"snowy","domain":"real_terrain"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | door | palette | unsupported | 1 | 1 | 1 | 0 | 0 | 1 | {"building_type":1.0,"era":1.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | wall | palette | unsupported | 1 | 1 | 1 | 0 | 0 | 1 | {"building_type":1.0,"era":1.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | context | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | door | palette | unsupported | 96 | 24.4792 | 15.7433 | 0 | 1 | 0 | {"building_type":0.8958333333333334,"era":0.75,"region":0.052083333333333336,"style":0.9895833333333334} |
| {"domain":"real_building"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | foundation | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | opening | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | ornament | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | roof | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | tree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | wall | palette | unsupported | 121 | 27.0485 | 19.3863 | 0 | 1 | 0 | {"building_type":0.8925619834710744,"era":0.7520661157024794,"region":0.05785123966942149,"style":0.9917355371900827} |
| {"domain":"real_building"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_terrain"} | accent_other | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | band_course | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | column | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | context | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | cornice | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | door | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | fence | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | foundation | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | gable_wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | ground_grass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | ground_soil | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | opening | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | ornament | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | path | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | path_natural | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | railing | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | relief | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | rock_face | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | rock_scree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | roof | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | roof_surface | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | sand | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | shutter | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | stairs_entry | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | tree | palette | unsupported | 18 | 15.625 | 1.29 | 0 | 0.444444 | 0.555556 | {"biome_like":0.6666666666666666,"season":0.8333333333333334,"time_of_day":1.0} |
| {"domain":"real_terrain"} | tree_trunk | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | vegetation_tree_canopy | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | wall | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | wall_secondary | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | water | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | window_frame | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"domain":"real_terrain"} | window_glass | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0,"season":0.0,"time_of_day":0.0} |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"chinese"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"medieval"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"chinese"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | wall/door | relation | unsupported | 1 | 1 | 1 | 0 | 0 | 1 | {"building_type":1.0,"era":1.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"islamic"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"japanese"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"medieval"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | wall/door | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |
| {"domain":"real_building"} | wall/door | relation | unsupported | 96 | 24.4792 | 15.7433 | 0 | 1 | 0 | {"building_type":0.8958333333333334,"era":0.75,"region":0.052083333333333336,"style":0.9895833333333334} |
| {"domain":"real_building"} | wall/opening | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"era":0.0,"region":0.0,"style":0.0} |

## 層・条件と役割別のD15前後支持

保存済み部位色を持つ確定subject数。未保存の和集合色はnullとし、採用支持へ足さない。
| 範囲 | 役割 | D15前 | D15後 | D15で失ったsubject | 採用両立subject | 採用所属質量 | 根拠不足画像 |
|---|---|---:|---:|---:|---:|---:|---:|
| {"biome_like":"desert","domain":"real_terrain"} | accent_other | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | band_course | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | column | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | cornice | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | door | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | fence | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | gable_wall | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | ground_grass | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | ground_soil | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | path | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | path_natural | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | railing | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | relief | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | rock_face | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | rock_scree | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | roof_surface | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | sand | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | shutter | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | stairs_entry | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | tree | 1 | 1 | 0 | 1 | 1 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | tree_trunk | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | vegetation_tree_canopy | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | wall_main | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | wall_secondary | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | water | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | window_frame | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"desert","domain":"real_terrain"} | window_glass | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | accent_other | 2 | 2 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | band_course | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | column | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | cornice | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | door | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | fence | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | gable_wall | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | ground_grass | 4 | 4 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | ground_soil | 4 | 4 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | path | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | path_natural | 4 | 4 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | railing | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | relief | 2 | 2 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | rock_face | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | rock_scree | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | roof_surface | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | sand | 4 | 4 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | shutter | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | stairs_entry | 2 | 2 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | tree | 4 | 4 | 0 | 4 | 4 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | tree_trunk | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | vegetation_tree_canopy | 4 | 4 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | wall_main | 2 | 2 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | wall_secondary | 3 | 3 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | water | 2 | 2 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | window_frame | 4 | 4 | 0 | 0 | 0 | 0 |
| {"biome_like":"forest","domain":"real_terrain"} | window_glass | 4 | 4 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | band_course | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | cornice | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | fence | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | gable_wall | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | ground_grass | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | railing | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | relief | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | rock_face | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | rock_scree | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | roof_surface | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | tree | 1 | 1 | 0 | 1 | 1 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | vegetation_tree_canopy | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | wall_main | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | wall_secondary | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | water | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | window_frame | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"mountains","domain":"real_terrain"} | window_glass | 1 | 1 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | tree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"plains","domain":"real_terrain"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | tree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"biome_like":"snowy","domain":"real_terrain"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"castle","domain":"real_building","style":"japanese"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"chinese"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"medieval"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"islamic"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"japanese"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"chinese"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | accent_other | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | band_course | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | column | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | cornice | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | door | 1 | 1 | 0 | 1 | 1 | 0 |
| {"domain":"real_building","style":"gothic"} | fence | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | gable_wall | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | ground_grass | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | ground_soil | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | path | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | path_natural | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | railing | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | relief | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | rock_face | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | rock_scree | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | roof_surface | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | sand | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | shutter | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | stairs_entry | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | tree_trunk | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | vegetation_tree_canopy | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | wall | 1 | 1 | 0 | 1 | 1 | 0 |
| {"domain":"real_building","style":"gothic"} | wall_main | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | wall_secondary | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | water | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | window_frame | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | window_glass | 1 | 1 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"islamic"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"japanese"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"medieval"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | accent_other | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | band_course | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | column | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | cornice | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | door | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | fence | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | gable_wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | ground_grass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | ground_soil | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | path | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | path_natural | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | railing | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | relief | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | rock_face | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | rock_scree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | roof_surface | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | sand | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | shutter | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | stairs_entry | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | tree_trunk | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | vegetation_tree_canopy | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | wall | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | wall_secondary | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | water | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | window_frame | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | window_glass | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | accent_other | 126 | 126 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | band_course | 122 | 122 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | column | 122 | 122 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | cornice | 130 | 130 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | door | 109 | 109 | 0 | 96 | 96 | 0 |
| {"domain":"real_building"} | fence | 113 | 113 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | gable_wall | 123 | 123 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | ground_grass | 90 | 90 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | ground_soil | 113 | 113 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | path | 128 | 128 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | path_natural | 132 | 132 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | railing | 98 | 98 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | relief | 121 | 121 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | rock_face | 134 | 134 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | rock_scree | 124 | 124 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | roof_surface | 130 | 130 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | sand | 119 | 119 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | shutter | 128 | 128 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | stairs_entry | 96 | 96 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | tree_trunk | 101 | 101 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | vegetation_tree_canopy | 127 | 127 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | wall | 135 | 135 | 0 | 121 | 121 | 0 |
| {"domain":"real_building"} | wall_main | 134 | 134 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | wall_secondary | 134 | 134 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | water | 96 | 96 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | window_frame | 124 | 124 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | window_glass | 119 | 119 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | accent_other | 10 | 10 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | band_course | 14 | 14 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | column | 12 | 12 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | cornice | 14 | 14 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | door | 7 | 7 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | fence | 13 | 13 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | gable_wall | 14 | 14 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | ground_grass | 17 | 17 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | ground_soil | 16 | 16 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | path | 11 | 11 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | path_natural | 13 | 13 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | railing | 11 | 11 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | relief | 15 | 15 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | rock_face | 17 | 17 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | rock_scree | 17 | 17 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | roof_surface | 14 | 14 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | sand | 15 | 15 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | shutter | 13 | 13 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | stairs_entry | 9 | 9 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | tree | 18 | 18 | 0 | 18 | 18 | 0 |
| {"domain":"real_terrain"} | tree_trunk | 14 | 14 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | vegetation_tree_canopy | 17 | 17 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | wall_main | 15 | 15 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | wall_secondary | 15 | 15 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | water | 12 | 12 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | window_frame | 15 | 15 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | window_glass | 17 | 17 | 0 | 0 | 0 | 0 |
| japanese-castle | accent_other | 9 | 9 | 0 | 0 | 0.0 | 0 |
| japanese-castle | band_course | 8 | 8 | 0 | 0 | 0.0 | 0 |
| japanese-castle | column | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | cornice | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | door | 8 | 8 | 0 | 8 | 4.25 | 0 |
| japanese-castle | fence | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | gable_wall | 8 | 8 | 0 | 0 | 0.0 | 0 |
| japanese-castle | ground_grass | 8 | 8 | 0 | 0 | 0.0 | 0 |
| japanese-castle | ground_soil | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | path | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | path_natural | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-castle | railing | 9 | 9 | 0 | 0 | 0.0 | 0 |
| japanese-castle | relief | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-castle | rock_face | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | rock_scree | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | roof_surface | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | sand | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | shutter | 9 | 9 | 0 | 0 | 0.0 | 0 |
| japanese-castle | stairs_entry | 9 | 9 | 0 | 0 | 0.0 | 0 |
| japanese-castle | tree_trunk | 8 | 8 | 0 | 0 | 0.0 | 0 |
| japanese-castle | vegetation_tree_canopy | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | wall | 10 | 10 | 0 | 10 | 5.25 | 0 |
| japanese-castle | wall_main | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | wall_secondary | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | water | 8 | 8 | 0 | 0 | 0.0 | 0 |
| japanese-castle | window_frame | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-castle | window_glass | 11 | 11 | 0 | 0 | 0.0 | 0 |
| gothic-temple | accent_other | 73 | 73 | 0 | 0 | 0.0 | 0 |
| gothic-temple | band_course | 67 | 67 | 0 | 0 | 0.0 | 0 |
| gothic-temple | column | 67 | 67 | 0 | 0 | 0.0 | 0 |
| gothic-temple | cornice | 74 | 74 | 0 | 0 | 0.0 | 0 |
| gothic-temple | door | 62 | 62 | 0 | 62 | 35.0 | 0 |
| gothic-temple | fence | 63 | 63 | 0 | 0 | 0.0 | 0 |
| gothic-temple | gable_wall | 71 | 71 | 0 | 0 | 0.0 | 0 |
| gothic-temple | ground_grass | 49 | 49 | 0 | 0 | 0.0 | 0 |
| gothic-temple | ground_soil | 64 | 64 | 0 | 0 | 0.0 | 0 |
| gothic-temple | path | 70 | 70 | 0 | 0 | 0.0 | 0 |
| gothic-temple | path_natural | 73 | 73 | 0 | 0 | 0.0 | 0 |
| gothic-temple | railing | 53 | 53 | 0 | 0 | 0.0 | 0 |
| gothic-temple | relief | 65 | 65 | 0 | 0 | 0.0 | 0 |
| gothic-temple | rock_face | 77 | 77 | 0 | 0 | 0.0 | 0 |
| gothic-temple | rock_scree | 68 | 68 | 0 | 0 | 0.0 | 0 |
| gothic-temple | roof_surface | 73 | 73 | 0 | 0 | 0.0 | 0 |
| gothic-temple | sand | 69 | 69 | 0 | 0 | 0.0 | 0 |
| gothic-temple | shutter | 74 | 74 | 0 | 0 | 0.0 | 0 |
| gothic-temple | stairs_entry | 48 | 48 | 0 | 0 | 0.0 | 0 |
| gothic-temple | tree_trunk | 58 | 58 | 0 | 0 | 0.0 | 0 |
| gothic-temple | vegetation_tree_canopy | 74 | 74 | 0 | 0 | 0.0 | 0 |
| gothic-temple | wall | 77 | 77 | 0 | 77 | 43.333333333333336 | 0 |
| gothic-temple | wall_main | 76 | 76 | 0 | 0 | 0.0 | 0 |
| gothic-temple | wall_secondary | 76 | 76 | 0 | 0 | 0.0 | 0 |
| gothic-temple | water | 51 | 51 | 0 | 0 | 0.0 | 0 |
| gothic-temple | window_frame | 71 | 71 | 0 | 0 | 0.0 | 0 |
| gothic-temple | window_glass | 67 | 67 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | accent_other | 9 | 9 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | band_course | 13 | 13 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | column | 11 | 11 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | cornice | 13 | 13 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | door | 6 | 6 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | fence | 11 | 11 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | gable_wall | 13 | 13 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | ground_grass | 16 | 16 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | ground_soil | 15 | 15 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | path | 10 | 10 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | path_natural | 12 | 12 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | railing | 10 | 10 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | relief | 14 | 14 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | rock_face | 16 | 16 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | rock_scree | 16 | 16 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | roof_surface | 13 | 13 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | sand | 14 | 14 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | shutter | 12 | 12 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | stairs_entry | 8 | 8 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | tree | 17 | 17 | 0 | 16 | 8.0 | 0 |
| forest-autumn-day | tree_trunk | 13 | 13 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | vegetation_tree_canopy | 16 | 16 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | wall_main | 14 | 14 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | wall_secondary | 14 | 14 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | water | 11 | 11 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | window_frame | 14 | 14 | 0 | 0 | 0.0 | 0 |
| forest-autumn-day | window_glass | 16 | 16 | 0 | 0 | 0.0 | 0 |
| modern-house | accent_other | 23 | 23 | 0 | 0 | 0.0 | 0 |
| modern-house | band_course | 24 | 24 | 0 | 0 | 0.0 | 0 |
| modern-house | column | 24 | 24 | 0 | 0 | 0.0 | 0 |
| modern-house | cornice | 24 | 24 | 0 | 0 | 0.0 | 0 |
| modern-house | door | 17 | 17 | 0 | 17 | 17.0 | 0 |
| modern-house | fence | 20 | 20 | 0 | 0 | 0.0 | 0 |
| modern-house | gable_wall | 23 | 23 | 0 | 0 | 0.0 | 0 |
| modern-house | ground_grass | 17 | 17 | 0 | 0 | 0.0 | 0 |
| modern-house | ground_soil | 20 | 20 | 0 | 0 | 0.0 | 0 |
| modern-house | path | 25 | 25 | 0 | 0 | 0.0 | 0 |
| modern-house | path_natural | 25 | 25 | 0 | 0 | 0.0 | 0 |
| modern-house | railing | 18 | 18 | 0 | 0 | 0.0 | 0 |
| modern-house | relief | 23 | 23 | 0 | 0 | 0.0 | 0 |
| modern-house | rock_face | 24 | 24 | 0 | 0 | 0.0 | 0 |
| modern-house | rock_scree | 23 | 23 | 0 | 0 | 0.0 | 0 |
| modern-house | roof_surface | 25 | 25 | 0 | 0 | 0.0 | 0 |
| modern-house | sand | 20 | 20 | 0 | 0 | 0.0 | 0 |
| modern-house | shutter | 24 | 24 | 0 | 0 | 0.0 | 0 |
| modern-house | stairs_entry | 19 | 19 | 0 | 0 | 0.0 | 0 |
| modern-house | tree_trunk | 16 | 16 | 0 | 0 | 0.0 | 0 |
| modern-house | vegetation_tree_canopy | 21 | 21 | 0 | 0 | 0.0 | 0 |
| modern-house | wall | 25 | 25 | 0 | 25 | 25.0 | 0 |
| modern-house | wall_main | 25 | 25 | 0 | 0 | 0.0 | 0 |
| modern-house | wall_secondary | 25 | 25 | 0 | 0 | 0.0 | 0 |
| modern-house | water | 19 | 19 | 0 | 0 | 0.0 | 0 |
| modern-house | window_frame | 22 | 22 | 0 | 0 | 0.0 | 0 |
| modern-house | window_glass | 19 | 19 | 0 | 0 | 0.0 | 0 |
| medieval-house | accent_other | 63 | 63 | 0 | 0 | 0.0 | 0 |
| medieval-house | band_course | 58 | 58 | 0 | 0 | 0.0 | 0 |
| medieval-house | column | 58 | 58 | 0 | 0 | 0.0 | 0 |
| medieval-house | cornice | 64 | 64 | 0 | 0 | 0.0 | 0 |
| medieval-house | door | 55 | 55 | 0 | 54 | 27.0 | 0 |
| medieval-house | fence | 53 | 53 | 0 | 0 | 0.0 | 0 |
| medieval-house | gable_wall | 62 | 62 | 0 | 0 | 0.0 | 0 |
| medieval-house | ground_grass | 41 | 41 | 0 | 0 | 0.0 | 0 |
| medieval-house | ground_soil | 54 | 54 | 0 | 0 | 0.0 | 0 |
| medieval-house | path | 61 | 61 | 0 | 0 | 0.0 | 0 |
| medieval-house | path_natural | 64 | 64 | 0 | 0 | 0.0 | 0 |
| medieval-house | railing | 44 | 44 | 0 | 0 | 0.0 | 0 |
| medieval-house | relief | 56 | 56 | 0 | 0 | 0.0 | 0 |
| medieval-house | rock_face | 67 | 67 | 0 | 0 | 0.0 | 0 |
| medieval-house | rock_scree | 58 | 58 | 0 | 0 | 0.0 | 0 |
| medieval-house | roof_surface | 63 | 63 | 0 | 0 | 0.0 | 0 |
| medieval-house | sand | 60 | 60 | 0 | 0 | 0.0 | 0 |
| medieval-house | shutter | 64 | 64 | 0 | 0 | 0.0 | 0 |
| medieval-house | stairs_entry | 39 | 39 | 0 | 0 | 0.0 | 0 |
| medieval-house | tree_trunk | 49 | 49 | 0 | 0 | 0.0 | 0 |
| medieval-house | vegetation_tree_canopy | 64 | 64 | 0 | 0 | 0.0 | 0 |
| medieval-house | wall | 67 | 67 | 0 | 66 | 33.0 | 0 |
| medieval-house | wall_main | 66 | 66 | 0 | 0 | 0.0 | 0 |
| medieval-house | wall_secondary | 66 | 66 | 0 | 0 | 0.0 | 0 |
| medieval-house | water | 43 | 43 | 0 | 0 | 0.0 | 0 |
| medieval-house | window_frame | 63 | 63 | 0 | 0 | 0.0 | 0 |
| medieval-house | window_glass | 58 | 58 | 0 | 0 | 0.0 | 0 |
| japanese-temple | accent_other | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-temple | band_course | 9 | 9 | 0 | 0 | 0.0 | 0 |
| japanese-temple | column | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | cornice | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | door | 8 | 8 | 0 | 8 | 4.25 | 0 |
| japanese-temple | fence | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | gable_wall | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-temple | ground_grass | 8 | 8 | 0 | 0 | 0.0 | 0 |
| japanese-temple | ground_soil | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | path | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | path_natural | 12 | 12 | 0 | 0 | 0.0 | 0 |
| japanese-temple | railing | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-temple | relief | 12 | 12 | 0 | 0 | 0.0 | 0 |
| japanese-temple | rock_face | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | rock_scree | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | roof_surface | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | sand | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-temple | shutter | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-temple | stairs_entry | 10 | 10 | 0 | 0 | 0.0 | 0 |
| japanese-temple | tree_trunk | 9 | 9 | 0 | 0 | 0.0 | 0 |
| japanese-temple | vegetation_tree_canopy | 12 | 12 | 0 | 0 | 0.0 | 0 |
| japanese-temple | wall | 11 | 11 | 0 | 11 | 5.583333333333333 | 0 |
| japanese-temple | wall_main | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | wall_secondary | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | water | 7 | 7 | 0 | 0 | 0.0 | 0 |
| japanese-temple | window_frame | 11 | 11 | 0 | 0 | 0.0 | 0 |
| japanese-temple | window_glass | 11 | 11 | 0 | 0 | 0.0 | 0 |
| islamic-temple | accent_other | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | band_course | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | column | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | cornice | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | door | 9 | 9 | 0 | 9 | 8.25 | 0 |
| islamic-temple | fence | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | gable_wall | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | ground_grass | 8 | 8 | 0 | 0 | 0.0 | 0 |
| islamic-temple | ground_soil | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | path | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | path_natural | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | railing | 9 | 9 | 0 | 0 | 0.0 | 0 |
| islamic-temple | relief | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | rock_face | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | rock_scree | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | roof_surface | 9 | 9 | 0 | 0 | 0.0 | 0 |
| islamic-temple | sand | 9 | 9 | 0 | 0 | 0.0 | 0 |
| islamic-temple | shutter | 9 | 9 | 0 | 0 | 0.0 | 0 |
| islamic-temple | stairs_entry | 9 | 9 | 0 | 0 | 0.0 | 0 |
| islamic-temple | tree_trunk | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | vegetation_tree_canopy | 9 | 9 | 0 | 0 | 0.0 | 0 |
| islamic-temple | wall | 10 | 10 | 0 | 10 | 8.583333333333334 | 0 |
| islamic-temple | wall_main | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | wall_secondary | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | water | 8 | 8 | 0 | 0 | 0.0 | 0 |
| islamic-temple | window_frame | 10 | 10 | 0 | 0 | 0.0 | 0 |
| islamic-temple | window_glass | 9 | 9 | 0 | 0 | 0.0 | 0 |
| chinese-house | accent_other | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | band_course | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | column | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | cornice | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | door | 1 | 1 | 0 | 1 | 0.25 | 0 |
| chinese-house | fence | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | gable_wall | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | ground_grass | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | ground_soil | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | path | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | path_natural | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | railing | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | relief | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | rock_face | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | rock_scree | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | roof_surface | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | sand | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | shutter | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | stairs_entry | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | tree_trunk | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | vegetation_tree_canopy | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | wall | 1 | 1 | 0 | 1 | 0.25 | 0 |
| chinese-house | wall_main | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | wall_secondary | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | water | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | window_frame | 1 | 1 | 0 | 0 | 0.0 | 0 |
| chinese-house | window_glass | 1 | 1 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | accent_other | 7 | 7 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | band_course | 9 | 9 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | column | 8 | 8 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | cornice | 9 | 9 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | door | 5 | 5 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | fence | 8 | 8 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | gable_wall | 8 | 8 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | ground_grass | 10 | 10 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | ground_soil | 9 | 9 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | path | 7 | 7 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | path_natural | 7 | 7 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | railing | 7 | 7 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | relief | 11 | 11 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | rock_face | 11 | 11 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | rock_scree | 11 | 11 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | roof_surface | 9 | 9 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | sand | 9 | 9 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | shutter | 8 | 8 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | stairs_entry | 6 | 6 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | tree | 11 | 11 | 0 | 11 | 3.0 | 0 |
| mountains-summer-day | tree_trunk | 9 | 9 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | vegetation_tree_canopy | 10 | 10 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | wall_main | 10 | 10 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | wall_secondary | 9 | 9 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | water | 7 | 7 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | window_frame | 8 | 8 | 0 | 0 | 0.0 | 0 |
| mountains-summer-day | window_glass | 10 | 10 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | accent_other | 7 | 7 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | band_course | 9 | 9 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | column | 8 | 8 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | cornice | 9 | 9 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | door | 5 | 5 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | fence | 7 | 7 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | gable_wall | 8 | 8 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | ground_grass | 10 | 10 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | ground_soil | 9 | 9 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | path | 7 | 7 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | path_natural | 7 | 7 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | railing | 7 | 7 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | relief | 11 | 11 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | rock_face | 11 | 11 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | rock_scree | 11 | 11 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | roof_surface | 9 | 9 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | sand | 9 | 9 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | shutter | 8 | 8 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | stairs_entry | 6 | 6 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | tree | 11 | 11 | 0 | 10 | 2.0 | 0 |
| plains-summer-day | tree_trunk | 9 | 9 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | vegetation_tree_canopy | 10 | 10 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | wall_main | 10 | 10 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | wall_secondary | 9 | 9 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | water | 7 | 7 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | window_frame | 8 | 8 | 0 | 0 | 0.0 | 0 |
| plains-summer-day | window_glass | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | accent_other | 8 | 8 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | band_course | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | column | 9 | 9 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | cornice | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | door | 6 | 6 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | fence | 8 | 8 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | gable_wall | 9 | 9 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | ground_grass | 11 | 11 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | ground_soil | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | path | 8 | 8 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | path_natural | 8 | 8 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | railing | 8 | 8 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | relief | 12 | 12 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | rock_face | 12 | 12 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | rock_scree | 12 | 12 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | roof_surface | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | sand | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | shutter | 9 | 9 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | stairs_entry | 7 | 7 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | tree | 12 | 12 | 0 | 11 | 3.0 | 0 |
| desert-summer-day | tree_trunk | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | vegetation_tree_canopy | 11 | 11 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | wall_main | 11 | 11 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | wall_secondary | 10 | 10 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | water | 8 | 8 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | window_frame | 9 | 9 | 0 | 0 | 0.0 | 0 |
| desert-summer-day | window_glass | 11 | 11 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | accent_other | 7 | 7 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | band_course | 9 | 9 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | column | 8 | 8 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | cornice | 9 | 9 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | door | 5 | 5 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | fence | 7 | 7 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | gable_wall | 8 | 8 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | ground_grass | 10 | 10 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | ground_soil | 9 | 9 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | path | 7 | 7 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | path_natural | 7 | 7 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | railing | 7 | 7 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | relief | 11 | 11 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | rock_face | 11 | 11 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | rock_scree | 11 | 11 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | roof_surface | 9 | 9 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | sand | 9 | 9 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | shutter | 8 | 8 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | stairs_entry | 6 | 6 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | tree | 11 | 11 | 0 | 10 | 2.0 | 0 |
| snowy-winter-day | tree_trunk | 9 | 9 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | vegetation_tree_canopy | 10 | 10 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | wall_main | 10 | 10 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | wall_secondary | 9 | 9 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | water | 7 | 7 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | window_frame | 8 | 8 | 0 | 0 | 0.0 | 0 |
| snowy-winter-day | window_glass | 10 | 10 | 0 | 0 | 0.0 | 0 |

## M3完成条件

- 条件1: unverified — 固定7,607件の#66全件監査・品質評価・速度・容量の実測照合が別途必要
- 条件2: unverified — 候補・確定・未知と属性stateは報告済み。#72再実行・誤結合監査は別途必要
- 条件3: passed — D15 snapshotの全hash検証と同じ設定でのrule_stat再計算が完全一致
- 条件4: passed — 建築・地形の部分層補正主結果のsubject数・n_effとモデル品質で判定。passed は層補正の有効性を意味しない
- 条件5: passed — 全対象層と条件・役割別のD15前後支持を出力
- 条件6: unverified — 単位・支持・権利の引継ぎ内容は出力済み。Gへの実際の引継ぎ確認が必要

## Gへの引継ぎ

- 既知属性によるsubject部分層補正の外観色分布
- 補正率・属性別未知率・情報なし割合の分母は各条件・役割の採用subject数
- unknownは周辺化する。全層両立でも既知属性が増えたとは扱わない
- subject基準n_eff。smoothedは親CDF混合、実測支持を増やさない
- D15除外を維持。帰属・出典はsnapshotのprovenanceに保持。パック同梱許可は別判断
- Gで別途確定。M3報告はパックスキーマを定義しない

## 計測範囲

snapshotに保存された選択runのみ。全量失敗・未選択runと実運用性能は未計測
