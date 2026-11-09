## 概要

固定7,607件を変更せず、合格済みのwater・tree親群だけで地形側の訂正版比較を作成した。
新snapshotは解析適格1,547件・SHA代表650件・確認済みsubject 13件。
18統計行はすべてunsupported、supportedは0、条件4はfailedとなり、M4・配色パックへの採用は保留する。
建物側は未集計で、旧建物数値へfallbackしていない。

## 変更内容

- 本番DBの完全バックアップとrevision 0009を記録し、既存の両GPU構成で新mask・人物根拠3,912件を作成した。採用3,748件のshade/colorも新maskで再実行した。
- 既存mountを使った私有replicaと一時unitで原画像・prepの配置差を解消し、既知の旧prepだけを原画像から再生成したSHAで由来照合する。永続データの権限や旧runは変更しない。
- #121のモデル・prompt・前処理・policyを照合したwater・tree親群に支持を限定する。欠測色を除外し、集計登録時にも人物承認の失効を再確認する。
- #129の固定人確認一覧をraw SHAで照合し、不一致なら停止する。未完成snapshot・raw stageは保全して別試行先で再生成し、prepは一時ファイルをSHA照合後に確定名へ移す。
- 新snapshot・rule_stat・reportと旧#105 v2の適格数、subject、n_eff、補正率、情報なし率、supported、条件4、実ソースを比較した。実ソースは両版ともCommons 100%で、重みを変更していない。
- 個別情報はUbuntuの非公開領域へ保存し、Gitには集計値だけの`bench/issue122/result.md`と再現・保全記録を残す。

新snapshot: `d53765a48d4b20ed77dbf393c04dad33a2601e5996c9718b44778c5e38448f58`

集計run: `11999124-8f44-4648-8c83-c4aaf6be5487`。M4 buildは生成せず、旧aliasも差し替えていない。

## 検証

- [x] 両GPUで各3件smoke、全量正常終了、有効mask・人物根拠・shade/colorの全件監査。本番の失敗・未終結0件。
- [x] 回帰5件の修正前失敗・修正後成功を確認。
- [x] WSL `Ubuntu-24.04`・隔離PostgreSQL16込みpytest: 1,444 passed・1 skipped。
- [x] ruff、sdist/wheel build成功。
- [x] 旧asset/subject/run/rule_statの変更・欠落0、旧M3/#104/#105 v2のmanifest・全Parquet SHA一致。
- [x] 新2,600 cohortへの新run追加0、asset集合の追加・削除0、元保留993件を含む旧行の不変を照合。

skipは公式重み・CUDA・テストDBの明示設定を要する既存GPUテスト。実GPUの本番照合とは区別する。
source・maskを照合した修正前smokeのsegment 1件は明示的に継承し、構成修正前の中断job 1件は対象を限定して廃止・保全した。

本番使用一覧は#129固定raw SHAと生成時記録のcanonical SHAに一致し、保留7件の取り漏れ採用は0件。
媒体manifest・完成snapshotの全SHAも一致したため、reviewer指摘修正による本番再生成は不要と判断した。
修正コードは未デプロイで、本番のDB・archive・既存成果は変更していない。

## 関連Issue

Refs #122

新しい人確認の参照がない7件は保留し、#114へ移管された確認runの取込を完了扱いにしていない。
建物側の別版追加とM4採用条件も未達のため、Closesは使わない。
後続の#114は、この固定版を診断比較の基準として明示選択する。

優先度・種別はIssueの`priority: high`・`type: bug`を引き継ぐ。旧基準の安全な再利用に影響するため。
