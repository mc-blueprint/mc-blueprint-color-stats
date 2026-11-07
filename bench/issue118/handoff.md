# Issue #118 実装引継ぎ

担当：complex_worker。worktreeは`colorstats-118/mc-blueprint-color-stats`、
ブランチは`feature/issue-118`、起点は`5270a36957e3db4141d29711203e283eb52b904a`。
引継ぎ済みorigin/developを再利用し、fetch・ブランチ変更・再委譲は行っていない。

## 変更と共有契約

- `segment.method=oneformer-region-v1`。既存候補生成と公式semantic後処理を再利用する。
- raw Region/CVATを保全し、整数semantic map・排他role mask・理由別maskを新runへ保存する。
- 後続payloadに`region_policy`を追加する。解決APIは
  `color.region_policy_input(session, asset_id, region_run_id)`。
  旧policyではNone。既存`region_inputs`も引き続き渡す。
- wall/treeは親和集合、異なるroleの交差はvoid。子ラベルの新しいsupportedは作らない。
- shade/colorのrole観測は出力JSONの`roles`、snapshotは有効maskから直接計算したgroupsへ保存する。
  ColorObservationへの親role用の偽Region登録は行わない。
- 新policyのgroupsは`quality_eligible=false`。後続Dでの品質合格・採用対応が必要。
- #66 runnerは契約を引き渡し、異なる入力・モデル・promptや旧segmentの流用を拒否する。
  OOMは再試行不可として記録し、runnerのstopファイルを残す。
- 新しいmaskを別途重ねる経路は未提供。追加人物mask等を使う場合は新runの契約確定が必要。
  今回は実在人物を保留する決定を前提とする。
- schema・migration・既存採用configは変更していない。#117の0009に干渉しない。

契約・取得条件・許容表の方針は[region-policy.md](../../docs/region-policy.md)。
後続C/E/Dへはこの契約を確定したcommitをメインから渡す必要がある。まだcommitは作っていない。

## 検証

隔離DB込み全pytestは**1,136 passed / 1 skipped、245.90秒**。skipは従来の実GPUテスト。
ruff・sdist/wheel buildも成功。既存warning 4件。
artifact：`/tmp/colorstats-issue118-GR41Rd/`。
記録：`20261107T070338Z-b640c65b77784b039d6d6de2edf2e115.jsonl`。

全件検証開始後にsky/person maskの全画素保存と診断数の区別を明確化したため、
最新ソースで関連unit **28 passed**、DB統合 **7 passed**、ruff・sdist/wheel buildを確認。
最新DB統合artifact：`/tmp/colorstats-issue118-wAi2ji/`。
記録：`20261107T070757Z-31b0954155024b6f89f0e5aaf697d4fa.jsonl`、
`20261107T070850Z-135634d8fa1d419b86ed2481b1aceeb4.jsonl`。
検証用DBは各試行の終了時に停止済み。バックグラウンド処理は残していない。
wheelの固定JSON 3点の同梱、`bash -n`、`git diff --check`も確認。

関連85件の隔離DB検証も成功。初回全件検証で旧snapshotの早期終了前にpayloadを
読み出す回帰を検出し、旧経路の順序を維持するよう修正した。
OOMの通常再試行も重点確認で修正した。

## 未解決・残作業

- 重みは取得していない。著者HFの`pytorch_model.bin`は879,517,517 bytes、
  設定・README等の8ファイル合計は881,200,070 bytes、MIT表示。
  revisionは`4a5bac8e64f82681a12db2e151a4c2f4ce6092b2`。
  取得規模は報告済みで、ユーザーの了承は未受領。固定SHA一覧は作成済みだが、
  重み本体の実SHA確認は取得後に必要。
- GPUは実行禁止のため8GB/12GB smoke・ピークVRAM・実GPUでの単独常駐は未検証。
  mockの解放順・OOM停止検証を実GPU成功とは扱わない。Issue #118のGPU完成条件は未達。
- roof/snowなど専用semanticクラスがない部位、window内競合は欠測になる。
  有効領域を出しただけで品質採用にしない。coverageを含む後続Dの検証が必要。
- 本番DB書き込み、API実行、全量統計、commit/push/PR作成・merge・Issue closeは未実施。
- この担当は再委譲禁止。公開する場合はメインが残条件と差分を確認し、別モデル公開担当へ
  ownerを引き継ぐ。本引継ぎは公開済み・通常PR完成の報告ではない。

新規ドメイン知識として外部保存すべき事項はない。実装契約はプロジェクト文書へ記録した。

## 用意したコミット文

```text
fix: OneFormerの排他領域で統計用マスクを制約する

- 固定revisionのsemantic mapで部位候補をclipし親和集合と競合voidを保存する
- 有効role maskの不変参照をshade・color・snapshotへ渡し旧観測の流用を拒否する
- 合成maskと隔離DBで由来・欠測・排他性・OOM停止を検証する
```

PRタイトル：`fix: OneFormerの排他領域で統計用マスクを制約する`

ラベル候補：既存の`type: bug`、`priority: high`。
優先度根拠はIssueと同じく主要な色統計入力の汚染。
作成前に既存ラベルとテンプレートを公開担当が照合する。

## 用意したPR本文

```markdown
## 概要

- 空・人物・異なる部位の混入を防ぐため、OneFormerのsemantic mapで統計用領域を制約する。
- 新方式の品質採用は保留し、旧policyの再現経路を維持する。

## 変更内容

- 版付きsegment method、固定モデル証跡、raw候補・排他role mask・除外理由の別保存を追加。
- wall/treeの親和集合と異role競合のvoid化、coverage・欠測を記録。
- shade/color/snapshotを有効role maskへ接続し、旧run・旧観測の流用を拒否。
- #66 runnerの共有payloadとOOM停止を追加。schema・migration・既存採用設定は変更なし。

## 検証

- [x] 隔離DB込み全pytest：1,136 passed / 1 skipped（従来の実GPUテスト）
- [x] 最後の診断数変更後：関連unit 28件、DB統合7件成功
- [x] ruff・sdist/wheel build・git diff --check
- [x] 合成mask、raw保全、shade/color/snapshotの関連85件の隔離検証
- [ ] 8GB/12GB実GPU smoke・ピークVRAM：実行禁止のため未実施

## 関連Issue

Refs #118（GPU完成条件が未達のため、この本文ではcloseしない）
```
