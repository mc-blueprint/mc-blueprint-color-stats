# Issue #85 最終実装・取消・本番再反映結果

2026-11-04。基準commitは`e7e7b1a7e7994b295110af932dba2f43949f302f`。
worktreeは`H:/mc-blueprint/worktrees/colorstats-85/mc-blueprint-color-stats`、
ブランチは`feature/issue-85`。commit・push・PR作成は依頼に従い未実施。

## 反証対応と既存機能の再利用

初回の681件はSubject表の全建築行で、確定対象の件数ではなかった。
候補のみの行にも書き込んだ誤りを修正し、通常反映・集計・照合は確定画像を持つsubjectに限定した。
確定画像とはasset.subject_idがそのSubjectを参照する画像であり、候補表の参照は含めない。
旧runは元snapshotの対象を使って取り消し、現在の確定画像の有無で取消を制限しない。

日付の幅を年数へ置き換えた誤りを修正し、before/afterを精度単位で計算する。
月は月数、日・時・分・秒は元の暦の閏年を含む日数・時刻から年の閉区間を得る。
グレゴリオ暦の年代境界へ無換算のユリウス暦を割り当てず、各era開始年の前後1年に
区間が重なる場合はjulian_era_boundaryとしてunknownを保つ。
例：ユリウス暦1799-12-31はunknown、グレゴリオ暦1800-07-01の前後1日はmodern。
世紀・千年紀は1始まり、十年は0始まり。
仕様根拠：[Wikidata日付仕様](https://www.wikidata.org/wiki/Help:Dates)。

#79のWikidataCatalog・CommonsAdapter・User-Agent・レート・要求hash別cacheと、
#72の取引・排他・新規snapshotを共有する。新規依存・migrationはない。
国ID対応表と西暦区分はconfigs/subject_attributes.yamlに固定した。
P17の全有効claimが同じregionを示す場合、P571の全有効claimの区間が同じeraに収まる場合だけ推定する。
P131・P625・撮影GPSから国境界を推測せず、修飾付き日付等の対応外はunknownにする。
非NULLの既存値を保持し、state・元claim・更新前後値はrunとsnapshotへ保存する。
#75が読むSubject.location/eraの文字列契約は維持する。
地形・asset・stats/snapshot/aggregate/weights/distributions/report/licenses・
analyze/queue/collectは変更していない。

## 本番取消・再反映

旧run `2ad9a044-f056-49e0-aa4d-3eff2a4d4eee`について取消dry-run後、
run単位取消を1取引で実施した。取消runは`50259438-97df-420f-b629-5522c844f0cf`。
region276列・era94列、計370列を元のNULLへ戻し、候補へのregion147列・era50列も除去した。
その後、修正版の確定subject限定dry-runで取得し、同じcacheをofflineで使用して1取引で再反映した。
最終成功runは`80f5dbf3-f7b7-4115-bbcd-a3a4b81087a5`。

確定画像を持つ建築subject 136件で、regionは確定129／unknown7、eraは確定44／unknown92。
regionの確定内訳：{"north_america": 23, "europe": 81, "japan": 14, "west_asia": 10, "east_asia": 1}。
eraの確定内訳：{"medieval": 13, "early_modern": 7, "modern": 24}。
regionのunknown理由：対象キー不明2・対応表外国5。
eraのunknown理由：P571なし84・修飾付き4・対象キー不明2・対応外日時1・年代競合1。
確定画像のない建築subject 545件にはregion/era値が残っていない。

dry-run・本反映・offline読取り再実行の結果は不変で、取得根拠・実DB値の差分は0。
元runの更新前後値と取消snapshotを照合し、取消差分・国対応・年代区分の違反も0。
5地域・3年代と各unknown理由の代表項目ID・claimを抜き取り、誤った対応付け0件を確認した。
これは保存claimと設定の対応の確認であり、Wikidata自体の史実の正確さの保証ではない。

## 実行版と証跡

ubuntu-2の専用領域`/mnt/data/work/issue-85/`を使用した。
既存の`/mnt/data/work/issue-46/venv/bin/python`とpostgresのpeer認証を使用し、
認証ファイル・接続URLを出力していない。実行コードは`review-code/`。
内容版は`e7e7b1a+i85-66f47037dad78700`。
修正版初回アーカイブSHA-256：
`32242aa390dd982878acda3eeb6e94ff2056f7c56bcc0ae97623825c4a949161`。
アーカイブ作成後の変更はDB再実行補助・文書・実測記録だけで、反映コードは同一。

`results/review-cancel-dry-01.json`・`results/review-cancelled-01.json`に取消証跡、
`results/review-dry-01.json`・`results/review-applied-01.json`・`results/review-replay-01.json`
に最終結果、`results/cache/`にAPI応答を保全した。
旧runのsnapshotとcodeも維持した。絶対パス・hash・抜き取りclaim・違反件数は
[production.json](production.json)を参照。

## 検証・重点反証・残作業

- Windows Python 3.12の専用venv：関連fixture・既存回帰101 passed。
- 専用socket・port5585の隔離PostgreSQL 16全体：574 passed / 1 skipped。
  スキップは既存GPUテスト。初回再実行は旧DBのalembic_versionが空DB前提に抵触したため、
  旧DBを保全し、毎回新規DBを作る補助スクリプトへ直して全体を再実行した。
- 候補だけのsubjectは取得・反映・集計から除外し、確定画像があるキー不明subjectはunknownとするDB回帰。
- 旧runの候補値取消、取消dry-run無更新・出力失敗rollback、後続再反映と既存値の保持をDBで確認。
- 月日精度の幅、年・月末・うるう日、ユリウス暦の境界前後1年、既存の年代・複数claim・cache失敗を確認。
- API不通・出力失敗・DBエラーの全rollback、同一cache再実行、限定取消を確認。
- ruff check .、python -m build（sdist・wheel）、git diff --check成功。

専用PostgreSQLは停止済みでデータ・ログを保全した。#66サービスはactiveを維持し、
ubuntu-1のpilotは再開していない。未停止の自分のバックグラウンド処理はない。
実装・検証・本番修正・公開準備は完了。commit・push・PR・Issue closeは未実施。
docs/schema.mdは編集せず、[schema-section.md](schema-section.md)を#74第2段階で統合する。
根拠不足のunknownは維持する。外部から同値を書き戻した履歴は既存スキーマで検出できないため、
外部編集後に取消する場合はその履歴を確認する。
