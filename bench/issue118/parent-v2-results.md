# #118 親対応表v2：建物の全欠測を修正

2026-11-07。`922d88b`の「wallだけを許容して建物全欠測となる」状態を修正した。
親対応表は[ade-role-parents-v2](../../docs/region-parents-v2.md)。全41部位を明示し、
建物・家・高層建物等を専用部位クラスと併せて粗い親にする。
roof専用クラスがない屋根は建物/awning/canopy、雪候補は地表/山等を親にする。
sky/personは全て禁止し、treeを山・岩・雪へ拡張しない。
親semanticとraw候補の積だけを採用し、building全体をwall等へ昇格しない。

対応表の版は`ade-role-parents-v2`、正規化JSON SHA-256は
`9657fe1c90fae5ea3b87eca49b3b84a91d57d1287dae1a81db519cdd76acc21b`。
policy hashは`3dad77aa16f42d620dc85cdf2e81586288db93c67154c86a39c68fb1774e65ba`。
表の参照をsegmentパラメータとrole契約へ保存し、config hashにも含める。
旧hashの有効maskや色観測の流用は拒否する。
旧版結果は[gpu-results.md](gpu-results.md)・[gpu-summary.json](gpu-summary.json)と
従来privateにそのまま保全し、新しい出力先で実行した。

## smoke

ユーザー指定どおりubuntu-2のRTX 4070 12GBだけで実行した。
前回と同じ3件（seed `11820261107`）と、同じ既存cohortの候補1,271件から
無作為抽出した追加20件（seed `11820261108`）を**別々に集計**した。
追加分は前回3件とID/SHA非重複、追加内のSHA重複も0。
前回3件のraw候補・semantic mapは旧版と89/89ファイルでSHA一致した。
入力・モデル・推論結果の変更でなく、対応表の変更による差分である。

| 指標 | 前回と同じ3件 | 追加20件 |
| --- | ---: | ---: |
| 成功 / OOM / 失敗 | 3 / 0 / 0 | 20 / 0 / 0 |
| 全画素数 | 568,832 | 3,586,048 |
| 建物の有効画素 | 13,772 | 317,886 |
| **建物有効率** | **2.4211%**（旧版0%） | **8.8645%** |
| 地形の有効画素 | 161,785 | 764,057 |
| **地形有効率** | **28.4416%** | **21.3064%** |
| 空への建物mask画素 raw → 有効 | 56,282 → 0 | 68,286 → 0 |
| **空への混入率 raw → 有効** | **9.8943% → 0%** | **1.9042% → 0%** |
| 建物/地形の交差画素 raw → 有効 | 152,720 → 0 | 1,532,979 → 0 |
| **建物/地形交差率 raw → 有効** | **26.8480% → 0%** | **42.7484% → 0%** |
| 有効率（全role） | 30.9330% | 32.0477% |
| **void率** | **69.0670%** | **67.9523%** |
| ピークreserved | 2,476 MiB | 5,074 MiB |
| 処理時間 | 38.00秒 | 242.16秒 |

率は各群の全画素数を分母にした加重率であり、画像ごとの率の単純平均ではない。
建物はtaxonomyのcontext以外、地形はterrainラベル、voidは全roleの未採用画素。
context分があるため建物率・地形率・void率の和は100%にならない。
空はOneFormer semantic skyの参照であり、独立画素GTではない。
既知例3件の空混入1/1→0/1、重複2/2→0/2も維持した。
追加20件は未知例のsmokeであり、既知例や母集団精度の標本と混ぜない。

GPU開始前・群の切替時・終了後はGPU計算プロセス0を確認した。
監視中の別GPUプロセス混入0、工程間の残存モジュール0、監視エラー0。
既存の固定OneFormer 8ファイルのSHAも終了後に再照合した。
本番DB接続・更新、サービス配備、全量統計、モデル/解像度の代替は行っていない。

## 検証と残る範囲

- 全pytest：**1,160 passed / 1 skipped、370.17秒**。skipは従来の実GPUテスト。
- ruff・sdist/wheel build成功。既存warning 4件。
- 全41部位の表の網羅、sky/person禁止、coarse親が候補外へ成長しないこと、
  window/roof/地形の対応、表変更後の旧hash拒否を合成maskで検証。
- raw保全、shade/color/snapshot連携、旧policyの再現経路を隔離DB込みで検証。
- 親表変更によるconfig/policy hashの変更と、新run・別出力への保存を確認。

建物を保持しながら空混入・交差を除去するという今回の欠測修正は確認できた。
ただしvoid率は高く、粗い親クラスとの積は部位ラベルの正解を保証しない。
専用クラスのないroof/snow等、子roleの競合・欠測を含むprecision/recall/IoUの採否は後続Dに残る。
`quality_eligible=false`を維持し、独立した品質合格前の全量統計を実行しない。

機械可読集計は[parent-v2-summary.json](parent-v2-summary.json)。
画像・入力/出力SHA・mask・画像別記録はGit外の
`H:/mc-blueprint/private/issue118-parents-v2-20261107/`へ保存した。
旧3件と20件の集計には、画像IDや個別自由文を転載していない。
テストartifactは`/tmp/colorstats-issue118-PZ0lRH/`。
コマンド記録は`20261107T080308Z-e968d423343a4e47af0b02e4c2d4adfa.jsonl`（全検証）、
`20261107T080254Z-a9558a42ce0d4ac0993a732179057ca2.jsonl`（smoke）、
`20261107T081005Z-75786365f5864014bb82bf02df8c96f5.jsonl`（終了後照合）に対応する。
GPU・監視thread・隔離テストDBは全て終了済み。
