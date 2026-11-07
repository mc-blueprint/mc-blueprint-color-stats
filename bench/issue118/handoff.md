# Issue #118 引継ぎ（親対応表v2）

ownerは同じcomplex_worker。`feature/issue-118`で作業し、今回の起点は`922d88b`。
初回実装は`43a8b5c`、先行の両GPU検証と解放修正は`922d88b`に保全した。
再委譲・push・PR作成・merge・Issue closeは行っていない。

## 完了した変更・検証

- 全41部位を[親表v2](../../docs/region-parents-v2.md)へ明示し、版・正規化JSON SHAを固定。
  建物・地形の粗い親と部位候補の積を取り、sky/personは全て禁止する。
- 共有payload形式`region-policy-v1`を維持し、`parent_table.version/sha256`を
  segmentパラメータ・role契約へ追加。policy/config hashにも含め、旧版再利用を拒否。
- 前回3件と非重複の追加20件を固定seedで選び、ubuntu-2で別々に実行して全23件成功。
  建物有効率2.4211%・8.8645%、空混入・建物/地形交差0。
  地形有効率28.4416%・21.3064%、void率69.0670%・67.9523%。
- 旧3件のraw候補・semantic map 89/89ファイルがSHA一致。旧成果物を上書きしていない。
- 全pytest **1,160 passed / 1 skipped**、ruff・sdist/wheel build成功。
  mock/隔離DBで候補外への拡張なし、親表の網羅、旧hash拒否と後続stage統合を検証。
- OOM・別GPU処理混入・工程間のモジュール参照残存0。
  GPU・監視thread・隔離テストDBは終了済み。本番DBには接続していない。

今回の結果・完成条件に対応する記録は[parent-v2-results.md](parent-v2-results.md)、
数値集計は[parent-v2-summary.json](parent-v2-summary.json)。
画像・画像別記述・入力/出力SHA・全mask・実行ログはGit外の
`H:/mc-blueprint/private/issue118-parents-v2-20261107/`へ保存した。
旧親表の全欠測という結果は旧GPU結果ファイルと従来privateに保全した。

## 共有契約とC/E/Dへの連絡

後続payloadは引き続き`color.region_inputs`と
`color.region_policy_input(session, asset_id, region_run_id)`を使う。
後者の戻り値を`region_policy`としてそのまま渡す。旧`sam2-dino`ではNone。
粗いbuildingをwallの正解へ変換せず、raw候補の外へ広げない。
wall/treeの同親和集合と、異roleの未解決交差をvoidにする契約は変更なし。

親表の版は`ade-role-parents-v2`、SHAは
`9657fe1c90fae5ea3b87eca49b3b84a91d57d1287dae1a81db519cdd76acc21b`。
現行policy hashは
`3dad77aa16f42d620dc85cdf2e81586288db93c67154c86a39c68fb1774e65ba`。
今回の確定commitを後続へ渡し、旧親表の有効mask・色観測を流用しない。
旧親表の再現は`922d88b`のコードと保存結果を使う。

shade/colorは有効role maskから直接計算し、JSONの`roles`へ保存する。
snapshotも有効maskからgroupsを作る。親role用の偽Regionや個別supportedは作らない。
schema・migration・既存採用configの変更はなく、#117の0009に干渉しない。

## 後続に残す判断

void率は約68〜69%であり、粗い親の許容は部位精度を保証しない。
独立GTでのprecision/recall/IoU、専用クラスのないroof/snow、子role競合の採否は後続Dで判断する。
`quality_eligible=false`と、Dの品質合格前の全量統計保留を維持する。
実在人物の保留方針や、新しい人物maskを別runへ固定する契約も変更しない。

## 公開文面の正本3ファイル

- [commit-message.txt](commit-message.txt)
- [pr-title.txt](pr-title.txt)
- [pr-body.md](pr-body.md)：`Closes #118`

baseはdevelop、headはfeature/issue-118。
ラベル候補は既存の`type: bug`、`priority: high`（主要統計入力の汚染を修正）。
今回の依頼はcommitまでであり、公開担当への再委譲・push・PR作成はしていない。
PR公開・merge・Issue close済みとは扱わない。

新規の外部保存対象となるドメイン知識はない。実装・検証結果はプロジェクト文書に記録した。
