# M3 偏り・支持範囲レポート

- snapshot: `d4936e8959eea65731d97faaa64082e3fb85e01f9e482681509cce44c86f4835`
- コード: report-v3 / aggregate-v2
- taxonomy: 0.1.0 / 設定hash: `9ac3fc69f000aa480f9fd5ad193586bd0fbba508eb9353ba6f8b67a29adc6cf9`
- 統計hash: `3810e33993fc68eee9b5e5e7dd71eaa275959a263fc87f4d8988ba9f1f596ae8`
- M3完了: False / 10万枚達成: False
- 両立件数は層間で重複する。所属質量はm_shの和、不足は目標subject数との差。
- unknownは周辺化し、属性が判明したとは扱わない。詳細・感度分布はJSON参照。
- 件数比率の空分母はnull。補正率・未知率等は#75の定義に従いN=0なら0。

| 層 | 意図両立行数 | 属性両立行数 | SHA異なり | 重複行 | 適格/分母 | subject前/適格/両立採用 | 所属質量 | 被覆 | 不足 | 除外理由（件数/分母） |
|---|---:|---:|---:|---:|---|---|---:|---|---:|---|
| 全体 | 80 | 80 | 40 | 40 | 40/80 | 40/40/40 | 40 | None | None | sha_duplicate: 40/80 |
| a | 0 | 20 | 10 | 10 | 10/20 | 10/10/10 | 10 | 0.1 | 90.0 | sha_duplicate: 10/20 |
| b | 0 | 60 | 30 | 30 | 30/60 | 30/30/30 | 30 | 0.3 | 70.0 | sha_duplicate: 30/60 |
| t | 0 | 0 | 0 | 0 | 0/0 | 0/0/0 | 0 | 0.0 | 100.0 | なし |

## 収集意図に対する属性確認

| 層 | 両立/意図行 | 属性不足/意図行 | 非両立/意図行 | 属性競合/意図行 |
|---|---|---|---|---|
| a | 0/0 | 0/0 | 0/0 | 0/0 |
| b | 0/0 | 0/0 | 0/0 | 0/0 |
| t | 0/0 | 0/0 | 0/0 | 0/0 |

## 分類と未知

```json
{"assignment_scope":"適格SHA代表画像。既知値の矛盾・対象外のみsubject全体を棄却","attribute_states":{"biome_like":{"unknown":80},"building_type":{"recorded":80},"style":{"recorded":80}},"attributes_conflict":{"denominator":80,"numerator":0,"value":0.0},"attributes_missing":{"denominator":80,"numerator":0,"value":0.0},"image_unassigned":{"denominator":80,"numerator":0,"value":0.0},"intent_mismatch":{"denominator":80,"numerator":0,"value":0.0},"multiple_strata":{"denominator":80,"numerator":0,"value":0.0},"outside_target":{"denominator":80,"numerator":0,"value":0.0},"partial_correction":{"real_building":{"attribute_unknown_rates":{"building_type":0.0,"style":0.0},"correction_rate":1.0,"missing_target_mass":0.0,"no_information_rate":0.0,"subject_count":40,"target_mass_coverage":1.0,"unassigned_subjects":0},"real_terrain":{"attribute_unknown_rates":{"biome_like":0.0},"correction_rate":0.0,"missing_target_mass":1.0,"no_information_rate":0.0,"subject_count":0,"target_mass_coverage":0.0,"unassigned_subjects":0}},"stratum_counts_are_not_additive":true,"subject_stratum_conflict":{"denominator":40,"numerator":0,"value":0.0},"unassigned":{"denominator":40,"numerator":0,"value":0.0},"unassigned_subject_reasons":{}}
```

## 内部有用性ゲート

- real_building: True（役割: door, wall）
- real_terrain: False（役割: なし）

## 条件・役割別支持

| 条件 | 役割/pair | 種別 | 支持 | subject（率の分母） | n_eff | 最大重み | 欠損目標質量 | 補正率 | 情報なし割合 | 属性別未知率 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| {"biome_like":"forest","domain":"real_terrain"} | tree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | door | palette | direct | 30 | 30 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall | palette | direct | 30 | 30 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | door | palette | smoothed | 10 | 10 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall | palette | smoothed | 10 | 10 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | door | palette | smoothed | 10 | 10 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | wall | palette | smoothed | 10 | 10 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | door | palette | direct | 30 | 30 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | wall | palette | direct | 30 | 30 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building"} | door | palette | direct | 40 | 30 | 2 | 0 | 1 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building"} | opening | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building"} | wall | palette | direct | 40 | 30 | 2 | 0 | 1 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_terrain"} | tree | palette | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"biome_like":0.0} |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall/door | relation | direct | 30 | 30 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall/door | relation | smoothed | 10 | 10 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"gothic"} | wall/door | relation | smoothed | 10 | 10 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building","style":"modern"} | wall/door | relation | direct | 30 | 30 | 1 | 0 | 0 | 1 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building"} | wall/door | relation | direct | 40 | 30 | 2 | 0 | 1 | 0 | {"building_type":0.0,"style":0.0} |
| {"domain":"real_building"} | wall/opening | relation | unsupported | 0 | 0 | 0 | 1 | 0 | 0 | {"building_type":0.0,"style":0.0} |

## 層・条件と役割別のD15前後支持

保存済み部位色を持つ確定subject数。未保存の和集合色はnullとし、採用支持へ足さない。
| 範囲 | 役割 | D15前 | D15後 | D15で失ったsubject | 採用両立subject | 採用所属質量 | 根拠不足画像 |
|---|---|---:|---:|---:|---:|---:|---:|
| {"biome_like":"forest","domain":"real_terrain"} | tree | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | door | 30 | 30 | 0 | 30 | 30 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall | 30 | 30 | 0 | 30 | 30 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | door | 10 | 10 | 0 | 10 | 10 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall | 10 | 10 | 0 | 10 | 10 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"gothic"} | door | 10 | 10 | 0 | 10 | 10 | 0 |
| {"domain":"real_building","style":"gothic"} | wall | 10 | 10 | 0 | 10 | 10 | 0 |
| {"domain":"real_building","style":"gothic"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building","style":"modern"} | door | 30 | 30 | 0 | 30 | 30 | 0 |
| {"domain":"real_building","style":"modern"} | wall | 30 | 30 | 0 | 30 | 30 | 0 |
| {"domain":"real_building","style":"modern"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_building"} | door | 40 | 40 | 0 | 40 | 40 | 0 |
| {"domain":"real_building"} | wall | 40 | 40 | 0 | 40 | 40 | 0 |
| {"domain":"real_building"} | wall_main | 0 | 0 | 0 | 0 | 0 | 0 |
| {"domain":"real_terrain"} | tree | 0 | 0 | 0 | 0 | 0 | 0 |
| a | door | 10 | 10 | 0 | 10 | 10.0 | 0 |
| a | wall | 10 | 10 | 0 | 10 | 10.0 | 0 |
| a | wall_main | 0 | 0 | 0 | 0 | 0.0 | 0 |
| b | door | 30 | 30 | 0 | 30 | 30.0 | 0 |
| b | wall | 30 | 30 | 0 | 30 | 30.0 | 0 |
| b | wall_main | 0 | 0 | 0 | 0 | 0.0 | 0 |
| t | tree | 0 | 0 | 0 | 0 | 0.0 | 0 |

## M3完成条件

- 条件1: unverified — 固定7,607件の#66全件監査・品質評価・速度・容量の実測照合が別途必要
- 条件2: unverified — 候補・確定・未知と属性stateは報告済み。#72再実行・誤結合監査は別途必要
- 条件3: passed — D15 snapshotの全hash検証と同じ設定でのrule_stat再計算が完全一致
- 条件4: failed — 建築・地形の部分層補正主結果のsubject数・n_effとモデル品質で判定
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
