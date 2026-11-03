# M3 偏り・支持範囲レポート

- snapshot: `d4936e8959eea65731d97faaa64082e3fb85e01f9e482681509cce44c86f4835`
- コード: report-v1 / aggregate-v1
- taxonomy: 0.1.0 / 設定hash: `9ac3fc69f000aa480f9fd5ad193586bd0fbba508eb9353ba6f8b67a29adc6cf9`
- 統計hash: `1acf4c64f1bb85df2924d960ed1290666e59fccf497174a37b61bd1fad9c783e`
- M3完了: False / 10万枚達成: False
- 層は重複し得るため合計しない。空分母の率はnull。詳細・感度分布はJSONを参照。

| 層 | 意図行数 | 属性一致行数 | SHA異なり | 重複行 | 適格/分母 | subject前→後 | 不足 | 除外理由（件数/分母） |
|---|---:|---:|---:|---:|---|---|---:|---|
| 全体 | 80 | 80 | 40 | 40 | 40/80 | 40→40 | None | sha_duplicate: 40/80 |
| a | 0 | 20 | 10 | 10 | 10/20 | 10→10 | 90 | sha_duplicate: 10/20 |
| b | 0 | 60 | 30 | 30 | 30/60 | 30→30 | 70 | sha_duplicate: 30/60 |
| t | 0 | 0 | 0 | 0 | 0/0 | 0→0 | 100 | なし |

## 収集意図に対する属性確認

| 層 | 一致/意図行 | 属性不足/意図行 | 不一致/意図行 | 属性競合/意図行 |
|---|---|---|---|---|
| a | 0/0 | 0/0 | 0/0 | 0/0 |
| b | 0/0 | 0/0 | 0/0 | 0/0 |
| t | 0/0 | 0/0 | 0/0 | 0/0 |

## 分類と未知

```json
{"attribute_states":{"biome_like":{"unknown":80},"building_type":{"recorded":80},"style":{"recorded":80}},"attributes_conflict":{"denominator":80,"numerator":0,"value":0.0},"attributes_missing":{"denominator":80,"numerator":0,"value":0.0},"intent_mismatch":{"denominator":80,"numerator":0,"value":0.0},"multiple_strata":{"denominator":80,"numerator":0,"value":0.0},"outside_target":{"denominator":80,"numerator":0,"value":0.0},"stratum_counts_are_not_additive":true,"unassigned":{"denominator":80,"numerator":0,"value":0.0}}
```

## 内部有用性ゲート

- real_building: True（役割: door, wall）
- real_terrain: False（役割: なし）

## 条件・役割別支持

| 条件 | 役割/pair | 種別 | 支持 | subject | n_eff | 最大重み | 欠損目標質量 |
|---|---|---|---|---:|---:|---:|---:|
| {"biome_like":"forest","domain":"real_terrain"} | tree | palette | unsupported | 0 | 0 | 0 | 1 |
| {"building_type":"house","domain":"real_building","style":"modern"} | door | palette | direct | 30 | 30 | 1 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall | palette | direct | 30 | 30 | 1 | 0 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | door | palette | smoothed | 10 | 10 | 1 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall | palette | smoothed | 10 | 10 | 1 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 |
| {"domain":"real_building","style":"gothic"} | door | palette | smoothed | 10 | 10 | 1 | 0 |
| {"domain":"real_building","style":"gothic"} | wall | palette | smoothed | 10 | 10 | 1 | 0 |
| {"domain":"real_building","style":"gothic"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 |
| {"domain":"real_building","style":"modern"} | door | palette | direct | 30 | 30 | 1 | 0 |
| {"domain":"real_building","style":"modern"} | wall | palette | direct | 30 | 30 | 1 | 0 |
| {"domain":"real_building","style":"modern"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 |
| {"domain":"real_building"} | door | palette | direct | 40 | 30 | 2 | 0 |
| {"domain":"real_building"} | opening | palette | unsupported | 0 | 0 | 0 | 1 |
| {"domain":"real_building"} | wall | palette | direct | 40 | 30 | 2 | 0 |
| {"domain":"real_building"} | wall_main | palette | unsupported | 0 | 0 | 0 | 1 |
| {"domain":"real_terrain"} | tree | palette | unsupported | 0 | 0 | 0 | 1 |
| {"building_type":"house","domain":"real_building","style":"modern"} | wall/door | relation | direct | 30 | 30 | 1 | 0 |
| {"building_type":"temple","domain":"real_building","style":"gothic"} | wall/door | relation | smoothed | 10 | 10 | 1 | 0 |
| {"domain":"real_building","style":"gothic"} | wall/door | relation | smoothed | 10 | 10 | 1 | 0 |
| {"domain":"real_building","style":"modern"} | wall/door | relation | direct | 30 | 30 | 1 | 0 |
| {"domain":"real_building"} | wall/door | relation | direct | 40 | 30 | 2 | 0 |
| {"domain":"real_building"} | wall/opening | relation | unsupported | 0 | 0 | 0 | 1 |

## M3完成条件

- 条件1: unverified — 固定7,607件の#66全件監査・品質評価・速度・容量の実測照合が別途必要
- 条件2: unverified — 候補・確定・未知と属性stateは報告済み。#72再実行・誤結合監査は別途必要
- 条件3: passed — D15 snapshotの全hash検証と同じ設定でのrule_stat再計算が完全一致
- 条件4: failed — 建築・地形それぞれのモデル品質と直接観測subject数・n_effで判定
- 条件5: passed — 全対象層・未知・除外・平滑化・支持を出力
- 条件6: unverified — 単位・支持・権利の引継ぎ内容は出力済み。Gへの実際の引継ぎ確認が必要

## Gへの引継ぎ

- subject事後層化による外観色。母集団への無偏推定や材質色ではない
- subject基準n_eff。smoothedは親CDF混合、実測支持を増やさない
- D15除外を維持。帰属・出典はsnapshotのprovenanceに保持。パック同梱許可は別判断
- Gで別途確定。M3報告はパックスキーマを定義しない

## 計測範囲

snapshotに保存された選択runのみ。全量失敗・未選択runと実運用性能は未計測
