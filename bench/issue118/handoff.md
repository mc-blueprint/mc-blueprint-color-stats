# Issue #118 引継ぎ（GPU検証後）

ownerは同じcomplex_worker。ブランチは`feature/issue-118`、起点は
`5270a36957e3db4141d29711203e283eb52b904a`。前回実装を先に`43a8b5c`へcommitした。
今回も再委譲・push・PR作成・merge・Issue closeは行っていない。

## 現在の状態

- 固定revisionの8ファイルを両機へ取得し、終了後も全SHA一致を確認。
- 既存cohortから固定seedで同じ3入力を選び、両GPUの3件連続smokeが成功。
- OOM・別GPUプロセス混入0。OneFormerと候補工程間のモジュール参照残存0。
- 実機で見つかったprocessor初期化とOneFormer/SAM2のLRU保持を修正。
  後者は新policyだけに適用し、旧`sam2-dino`の常駐は維持した。
- WSL隔離DB込み全pytest **1,138 passed / 1 skipped**、ruff・sdist/wheel build成功。
- **建物の有効画素は両機とも0**。空混入・交差0を実用的な改善合格とは扱わない。
  `Refs #118`として未完を維持し、品質採用・全量統計を保留する。

集計・完成条件照合・検証根拠は[gpu-results.md](gpu-results.md)、
機械可読な件数・率は[gpu-summary.json](gpu-summary.json)。
画像単位の記録、全試行の失敗、入力・出力SHA、mask、確認図はGit外の
`H:/mc-blueprint/private/issue118-smoke-20261107/`に保全した。
本番DBには接続していない。GPUプロセス・監視thread・隔離テストDBは全て終了済み。

## 共有契約・依存先への連絡

`segment.method=oneformer-region-v1`。raw Region/CVATとsemantic/有効role maskを分離する。
後続payloadには`color.region_inputs`と併せて
`color.region_policy_input(session, asset_id, region_run_id)`の戻り値を
`region_policy`として必ず渡す。旧policyではNone。
path/SHA・入力SHA/寸法・revision・policy hashを固定し、省略・差替え・旧観測流用を拒否する。

shade/colorは有効role maskから直接計算してJSONの`roles`へ保存し、
snapshotも有効maskからgroupsを作る。親role用の偽Regionや個別supportedは作らない。
`quality_eligible=false`を維持する。schema・migration・既存採用configは変更なし。
#117の0009には干渉しない。追加人物maskとの重ね合わせは新runの契約確定が必要。

今回のメモリ保持修正はpolicy hashに含む。確定commitをC/E/Dへ渡す際は、
建物全欠測と未採用状態も必ず伝える。旧runの有効maskや色観測を再利用しない。
粗いbuilding/houseをwall等へ許容する判断は共有policyの変更になるため、
勝手に表を緩めず、建物保持と部位誤りを評価してメインが方針を決める必要がある。

## 残作業

- 建物全欠測の解消方針を決め、建物を保持した既知失敗例で検証する。
- 後続Dで独立GT・coverage/recall/IoUを含む品質判定を行う。
  今回のOneFormer sky参照の0%をprecision合格へ読み替えない。
- 完成条件を再照合し、未達が解消したときだけ公開文面を`Closes #118`へ更新する。
- push・PR作成は依頼範囲外。この担当は再委譲禁止。
  公開が必要になったら、メインが差分と未達条件を確認して公開担当へownerを渡す。

## 公開文面の正本3ファイル

- [commit-message.txt](commit-message.txt)
- [pr-title.txt](pr-title.txt)
- [pr-body.md](pr-body.md)：`Refs #118`

baseはdevelop、headはfeature/issue-118。
ラベル候補は既存の`type: bug`、`priority: high`。優先度根拠はIssueと同じ入力汚染。
この引継ぎはPR公開・Issue完了の報告ではない。

新規の外部保存対象となるドメイン知識はない。実装・検証の記録はプロジェクト内に残した。
