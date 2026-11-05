# Issue #105 本番補完・不足診断

2026-11-05。起点 `9c0011f5950d40cb347ce42527558aa1af4984d3`、
`feature/issue-105`。#104 の適格7,607画像を同じ解析runで比較した。
新規収集・Wikidata照会・再分割・色job・pilot再開・サービス変更は行っていない。

## 補完結果

2,523画像へ3,314属性を追記した。季節2,354、時間帯956、biome_like 2、building_type 1、
weather 1。別に地形9 subjectへP17の国claimからregionを追記した。eraの追記は0。
既存候補は #72/#99 の保存済みカタログ・独立根拠で再評価し、新規確定は0だった。
非unknownの既存属性、既存subject関連付け、地域・年代の既存値はすべて保持した。

重複しない属性根拠の内訳は次のとおり。

| 根拠 | 属性件数 |
| --- | ---: |
| Commonsカテゴリのみ | 103 |
| 保存撮影日とGPSのみ | 1,585 |
| カテゴリと保存撮影日・GPSの一致 | 50 |
| EXIFのみ（撮影日654、UTCと太陽高度911） | 1,565 |
| 保存撮影日・GPSとEXIFの一致 | 11 |

元画像はubuntu-1にあり、ubuntu-2の旧storage_pathは全件ホスト外だった。
登録済みホストの画像を読み取り、SHA代表3,594件のEXIF台帳を内部領域へ保存した。
有効撮影日2,507、時差565、GPS650、GPS UTC389件。SHA不一致・欠落は0。
Pillowの超大画像制限・壊れたEXIFは保留し、制限を解除しなかった。
Wikidataは既存387キャッシュ・5,338項目を使用し、追加照会の必要数は0。
新規・変更した属性にはstateと根拠があり、推定できない値はunknownを維持している。
詳しい推定条件は [既存データの補完](../../docs/existing-data.md) を参照する。

## 支持の比較

| 指標 | #104 | 補完後 |
| --- | ---: | ---: |
| 適格画像 / SHA代表 / 確定subject | 7,607 / 3,570 / 154 | 同じ |
| wall 採用subject / n_eff | 121 / 27.048481 | 同じ |
| wall 補正率 / 情報なし | 100% / 0% | 同じ |
| tree 採用subject / n_eff | 18 / 15.625000 | 14 / 9.681382 |
| tree 補正率 / 情報なし | 44.44% / 55.56% | 57.14% / 42.86% |
| supported / 全統計行 | 0 / 569 | 0 / 569 |
| 条件4 | passed | failed |

確定subject自体は減っていない。属性が分かった4 subjectが対象層外となり、treeの採用から
外れた。全体のoutside_targetは14→18。他の新しい棄却理由はない。
既知値を隠して条件4を維持せず、10 subject・n_effと直接分布30 subject・n_effを区別した。
n_effの不足は追加画像数・subject数へ単純換算できない。
自動reportの条件1・2・6はunverifiedであり、M3全体を完了扱いにしていない。

## 不足と収集目標

[補完前](deficits-before-full.json) と [補完後](deficits-after.json) は各907行。
条件別と12層別の部位・relationについて、10/30 subject・n_effまでの不足を記録した。
原因は重複を許し、件数の単位は診断行である。

| 原因 | 補完前 | 補完後 |
| --- | ---: | ---: |
| 属性不足 | 341 | 340 |
| subject不足 | 901 | 901 |
| 部位不足 | 839 | 837 |
| 権利除外 | 0 | 0 |

属性追記だけでは新しい確定対象や部位の色観測は増えない。
層所属質量は中国住宅0.25、森林8.2、山岳2.2、平原・砂漠・雪景各1.2であり、
未知属性の周辺化を含む。実測所属のsubject数や加算可能な件数とみなさない。
部位不足の件数減少も新たなモデル検証成功を意味しない。

`collection_targets.yaml`の総枠10,000枚とsubjectsの比率、集中上限を維持した。
優先度1は中国住宅1,000枚・秋の森林1,100枚。山岳・平原・雪景は各900枚、砂漠800枚。
建築の他層は700〜800枚とし、既存を含む上限の合計は10,000枚。
既存Commonsは枠に対する不足率で優先し、#92・#94はpriority・collection_sources・
focus_partsと不足JSONを共通入力にできる。LoCは北米の住宅、Mapillaryは街路の建築と
日時・位置のある地形、Commonsは固有対象・季節・時刻の根拠を持つ対象へ対応付けた。
Commons全体8,000枚・層内80%などの上限は緩めない。既に新しい層内上限を超えた供給元は
追加を止め、既存画像は削除しない。実際の残枠は除外画像を含む収集台帳で再計数する。

## 本番の保全と再現

- 完全pg_dump：`/mnt/data/work/issue-105/backup-20261105T094849Z/colorstats.dump`。
- 582,883,094 bytes、SHA-256 `631c54311147a78ab6acc1aea9456949c39cc83313916297b78cc697dd684e49`。
- pg_restoreの目録・全SQLストリーム読み出し成功。復元していない。
- 初回バックアップは専用ディレクトリの所有者設定で停止し、失敗領域を保全した。
  所有者を揃えて新規パスで取得後にDBへ追記した。上書き・削除はしていない。
- 最終snapshot：`82804e647527696ede91de8022d2dcf04d79503606c2ea397602c2a63e841dd0`。
- rule_stat run：`7c261582-b654-47af-bbb1-bcb08ecb4e1a`、job：`31de6f7d-b722-4c98-92ca-1d49b02ff0bc`。
- 正本：`/mnt/data/derived/stats/issue105-full-20261105T101712Z`。
- コード・保存根拠・追記計画は `/mnt/data/work/issue-105/` 内に保全した。
  実行コード版とファイルhashは [comparison-final.json](comparison-final.json) に固定した。
- 属性根拠runは #85 と同様に画像解析の権利ゲートから分離した。
  一括属性runの区分で別の適格画像を除外しない回帰検証を追加した。
- #104の解析実装hash・成功run全パラメータ・領域・品質の一致を確認し、固定和集合色を
  再利用した。provenance・regions・observations・relations・groupsの5 Parquetは完全一致。
- M3・#104の旧snapshot、旧rule_statの全行hash、原asset情報・sourceのhashは不変。
  [preserved-before.json](preserved-before.json) と [preserved-final.json](preserved-final.json) を照合した。
- 新rule_stat569行と10,714入力辺は固定計算と全量一致した。
  reportはDB全行と一致した`aggregate/dry.json`から生成した。
  Queueが確定する統計ファイルは専用`.output-*`内にあり、通常名の直下とは異なる。
- 初回snapshotは権利ゲート修正のため自分の読取り処理を中断した。
  再利用前の型照合失敗も含め、途中領域を保全し、毎回新規snapshot領域を使用した。
  失敗・中断した領域を成功snapshotとして登録していない。

再現時は固定report・snapshotを指定して [不足一覧CLI](../../docs/existing-data.md#不足一覧の再生成)
を実行する。元画像・原meta・個別EXIF台帳は公開記録へ含めていない。

## 検証と残作業

- WSL `Ubuntu-24.04`、ext4一時コピー、Python 3.12.3・専用PostgreSQL 16。
- ruff成功。全pytest：878 passed / 1 skipped（既存の明示GPUテスト）。
- sdist/wheel build成功。src・configs・taxonomy・testsは検証コピーとバイト一致。
- [verification.json](verification.json) が権利ゲート修正後の最終検証。
  初回検証は`verification-before-rights-fix.json`へ分けて保持した。
- 既存値保持・stateと根拠・5 Parquetの完全一致を本番で全量監査した。
- 専用PGを停止済み。起動した本番処理は終了し、サービス・pilotは変更していない。

#105の実装・本番補完・診断・公開準備は完了。支持不足と条件4未達は残り、
新しい対象の収集・部位観測の改善が必要である。push・PR作成・merge・Issue closeは行わない。
