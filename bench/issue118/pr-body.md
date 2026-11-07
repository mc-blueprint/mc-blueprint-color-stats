## 概要

- OneFormerのsemantic親領域と部位候補の積で空・人物・地形への混入を制約する。
- 外観がbuilding等に分割される場合の建物全欠測を、版付きの親対応表で修正する。

## 変更内容

- 全41部位の親表v2を固定し、表の版/SHA・入力/出力SHA・model/revisionをrun契約へ保存。
- raw候補を保全し、wall/treeの同親和集合、異role交差のvoid化、欠測・coverageを記録。
- 有効maskをshade/color/snapshotと#66 runnerへ渡し、旧hashや旧観測の流用を拒否。
- オフラインprocessorと新policyのGPU解放を実装。schema・migration・旧policyは維持。
- 前回3件と追加20件をubuntu-2で別々に検証。画像・個別記録はprivate、Gitには集計のみを保存。

## 検証

- [x] WSL隔離DB込み全pytest：1,160 passed / 1 skipped（従来の実GPUテスト）
- [x] ruff・sdist/wheel build
- [x] 親表の網羅・空/人物除外・候補外への拡張なし・旧hash拒否・後続stage統合
- [x] 先行の8GB/12GB各3件smoke、新表の12GB 3件＋20件smoke。OOM・別GPU処理混入0
- [x] 建物有効率：前回3件は0→2.4211%、追加20件は8.8645%
- [x] 空混入・建物/地形交差はいずれも0。地形有効率28.4416%/21.3064%、void率69.0670%/67.9523%
- [x] 旧3件のraw/semantic 89ファイルはSHA一致、旧成果物を保全

`bench/issue118/parent-v2-results.md`に詳細を記録する。
部位精度の独立した採否は後続Dで判断し、`quality_eligible=false`と全量統計の保留を維持する。
本番DB更新・サービス配備・全量処理は行っていない。

## 関連Issue

Closes #118
