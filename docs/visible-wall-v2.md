# 可視壁材の領域制約 v2

Issue #130の2026-11-08決定に基づく別method `oneformer-visible-wall-v2`、
artifact版 `visible-wall-policy-v2`。この方式でwall親群は
「窓・扉・装飾などを除いた、壁材が見えている面」を意味する。
旧`oneformer-region-v1`、旧評価・統計を新定義として再利用しない。

## 処理と設定

`segment` payloadのmethod以外は従来のOneFormer方式と同じ。
固定prep run・SHA、向き確定・長辺2560px以下、配置済み3モデルが必要。
候補threshold=0.35、text_threshold=0.25を固定し、異なる値は拒否する。
`prompts`には通常のtaxonomyラベルだけを渡す。補助3promptは新policyが追加し、
payloadのtaxonomyを拡張したり、新しいRegionラベルを登録したりしない。

```python
payload["method"] = "oneformer-visible-wall-v2"
payload["threshold"] = 0.35
payload["text_threshold"] = 0.25
```

1. 従来のOneFormerを実行・解放してからDINO/SAM2を実行する。
2. 窓・扉・柱・屋根・装飾等の固定ラベルと、balcony/shopfront/window sillの
   補助候補をconfidence>0.35でunionする。semantic親で切る前のmaskを使う。
3. confidence>0.55の壁候補から部位unionを差し引く。検出されない部位の補完はしない。
4. 他建物は>0.55、地形は>0.35を採用し、従来の親表v2と交差する。
   同親はunionし、残る異role競合は全てvoid。scoreで画素の勝者は作らない。

除去ラベル・閾値・座標・class-info JSON内容はpolicy hashへ固定する。
旧v1のclass-info実byte hashは維持し、新v2のhashだけはCRLF/LFに依存しない。
モデル・入力・通常promptはsegmentのconfig hashへ含める。

## artifactと後続参照

通常のraw Region候補は保全する。補助候補はRegionにせず、同じsegment runの
`wall_candidates`へラベル・confidence・二値PNG/SHAを保存する。
`exclusions.wall_parts`は壁候補から差し引いた部位画素で、他roleの有効画素と重なり得る。
それ自体を全roleのvoidとは扱わない。差引き前・除去・残存候補の面積をmetricsへ記録する。

既存の`region_policy.reference`で全pathを確定し、`load_masks`で入力/run/policy・
補助rawを含むSHA・座標・二値性・role排他・壁と除去部位の非交差を検証する。
shade/color/privacy/selectionはこの同じsegment runの契約を使う。
rawへのfallbackはなく、v1 runや異なる設定をv2として再利用しようとすると拒否する。

batch=1。OOMは既存の再試行不可例外を送出し、runnerを停止する。
モデルの自動取得・縮小・別モデルへの代替はない。
本番設定や品質採用の自動変更は行わない。建物の統計は評価合格まで見送る。

## 検証範囲

[新評価版の事前設計](../bench/issue130/visible-plan.md)を参照。
旧CMP/ADEの回帰と新たな補助候補推論、固定6枚の全本番prompt確認を分ける。
既知公開GTは所有画像の独立した保証ではなく、wall合格を他部位の支持へ拡張しない。
