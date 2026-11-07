## 概要

- 空・人物・異なる部位の混入を制約する版付きsegment methodと不変role mask契約を追加する。
- 両GPUのsmokeは成功したが、建物の有効画素が0となるため実用的な改善は未達。品質採用・全量統計は保留する。

## 変更内容

- raw候補を保全し、semantic map・親和集合・排他role mask・除外理由・欠測/void率を別保存。
- shade/color/snapshotと#66 runnerを有効maskへ接続し、旧観測の流用を拒否。
- オフラインprocessor初期化と新policyでの位置埋め込みLRU保持を修正。旧policyは維持。
- 固定revisionの8ファイルを両機でSHA照合し、同じ固定seedの3入力でGPU検証。
- schema・migration・既存採用設定は変更なし。本番DB更新・全量処理なし。

## 検証

- [x] WSL隔離DB込み全pytest：1,138 passed / 1 skipped（従来の実GPUテスト）
- [x] ruff・sdist/wheel build
- [x] RTX 4060 8GB / RTX 4070 12GB：各3件成功、OOM・別GPUプロセス混入0
- [x] 工程間のモジュール参照残存0、OOM時の再試行不可・runner停止を模擬/隔離DB検証
- [x] 空への建物maskは9.8773%/9.8943%から0%、建物/地形交差は26.6506%/26.8480%から0%
- [ ] 建物を保持した改善・品質採用：建物の有効画素0のため未達。上記0%をprecision合格とは扱わない

詳細：`bench/issue118/gpu-results.md`。画像・画像別記述はprivateに保存し、Gitには集計のみを含める。

## 関連Issue

Refs #118
