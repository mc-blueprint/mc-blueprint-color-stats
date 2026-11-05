# Issue #92 LoC adapter validation

確認日: 2026-11-05

## 固定予算

- API: 最大30要求。画像: 最大15要求。UAは`source_policy.yaml`に固定。
- LoC Legalの全マシン合計10要求/分以下の推奨を優先し、API・画像とも実要求間隔は6秒以上とする。
- HTTP要求は再試行しない。429・503・HTML/CAPTCHAは測定停止として扱う。

## 規約・経路・robots

- JSON APIは認証不要、JSON 20/min、Image 150/min。Legalはアプリへの合計10 req/min以下を推奨。
- `/collections/{collection}/`と`/photos/`に`fo=json`を付ける。`/search`と`/pictures/search`は使わない。
- `www.loc.gov/robots.txt`: `/search`・`/pictures/search`禁止、Crawl-Delay 5。
- `tile.loc.gov/robots.txt`: HTTP 404。
- `cdn.loc.gov/robots.txt`: `/service`・`/master`禁止、Crawl-Delay 10。

## 実取得

- collection候補: `john-margolies-roadside-america`。識別条件はLoC公式collection JSON内のitem URL、Rights and Access、画像URL。検索要求は固定UAで1回。
- 結果: HTTP 403。JSON要求1、成功応答0、候補0、適格カラー画像0、画像要求0。
- 403エラー応答の受信byte数は保存されておらず不明。画像やDBレコードは作成していない。
- `/mnt/data/work/issue-92/` は存在しないことを確認後に作成を試みたが、ubuntu-1でPermission denied。別保存先への切替や権限回避はしていない。

## 2026-11-05 再確認: challenge停止と一括データ候補

### API・利用条件・robots

- [LoC JSON APIの利用制限](https://www.loc.gov/apis/json-and-yaml/working-within-limits/): 認証不要、JSON 20 req/min・image 150 req/min。全体の初期間隔は6秒以上とする。
- [LoC Legal](https://www.loc.gov/legal/): 著作権・利用制限は各itemで確認し、全マシン合算で10 req/min以下を推奨。
- [www.loc.gov/robots.txt](https://www.loc.gov/robots.txt): `/search`、`/pictures/search`、`/pictures/related`は禁止、`Crawl-Delay: 5`。
- 公式JSON APIはWindows端末・ubuntu-1の双方で403と`Cf-Mitigated: challenge`を返すことを確認済み。対策回避・UA変更・別IP利用は行わない。
- `data.labs.loc.gov/robots.txt`と`tile.loc.gov/robots.txt`はHTTP 404。画像候補の実hostはdata.labs.loc.gov。公式ドキュメント・metadata・manifestのGETはHTTP 200で、challenge headerなし。画像本体URLは未取得のため、その応答は未確認。`www.loc.gov`はRightsページ参照先だが、APIのchallengeによりitemページの個別確認手段には採用しない。

### 一括データ候補

| 候補 | 件数・建築/カラー識別 | 権利情報 | 画像取得経路・条件 | 容量・判断 |
| --- | --- | --- | --- | --- |
| [Free to Use and Reuse](https://data.labs.loc.gov/free-to-use/) | 2,610 records / 2,610 images。metadata内の建築関連語検索345 item、manifest一致345画像。写真・図面等が混在し、カラーの確定は画像判定が必要。 | READMEはRightsが`item.rights_advisory` / `item.rights` / `rights`由来、97.73% populatedと説明。実データでRights非空2,552件。原文をitem単位で保持し、セット全体の説明を個別権利判定に使わない。 | manifestのitem/image id・MD5・bytes・URLを使い、`data.labs.loc.gov/free-to-use/data/{file}`から個別取得可能。API経由は既存challengeを回避できないため使わない。Preview_urlとIIIF_manifestも全2,610件に存在するが、別hostへの新規アクセスは設計承認後に調査する。 | metadata 10,805,007 + manifest 415,561 + README 43,683 = **11,264,251 bytes**。全画像は1,058,879,130 bytes、建築関連語345画像は125,161,359 bytes。サンプルzipは画像入りのため取得せず。調査候補として継続。 |
| [Stereograph Cards](https://data.labs.loc.gov/stereographs/) | 39,526画像。写真またはphotomechanical printの立体写真が混在。カラーを確定する項目は未確認。建築用途の絞り込みはサンプル/全件内容の追加評価が必要。 | 公式説明は著作権状態が混在し、未公表作品等の権利期間確認が必要とする。個別rights要確認。 | manifest個別URLまたはデータ一括取得。README/DPPと1,000件metadata sampleは合計50MB未満だが、今回Free to Useファイルを含む累計上限を守るため追加サンプルは未取得。 | 全metadata 290.7MB、全画像manifest 6.5MB、画像zip合計約3.5GB。50MB調査枠外のmetadata・大容量画像であり今回は不採用。 |
| [Selected Datasets](https://www.loc.gov/collections/selected-datasets/about-this-collection/) | collectionページはHTTP 403で確認不能。建築・カラー件数は未確認。 | collection単位の説明からitem別Rightsを代替できない。 | `www.loc.gov`上の各dataset/item経路。403のchallenge有無をヘッダーで確認できず、再試行・別経路探索はしない。 | 件数・全体容量・候補ファイル容量を確認できず、現時点で採用不可。 |

Free to Use の集計対象はタイトル・説明・subjects・genre・medium・format・setに建築関連語を含むitemであり、建築写真の確定件数ではない。カラー語はmetadata中に971件出現したが、記述語だけでは画像の色を証明できない。記録した小容量ファイルはubuntu-1の`/mnt/data/derived/issue92-20261105/`に保全した。画像本体は一括取得していない。

### 取り込み方式案（実装保留・メイン確認待ち）

1. #105の`configs/collection_targets.yaml`が対象とするcollection/item選択を優先し、Free to Use全体を無条件の標本にしない。metadataとmanifestをdataset version/hash付きの索引として扱い、item ID・Set・source URL・個別Rights原文・image file ID/URL/bytes/hashを候補記録へ保持する。
2. #87の権利台帳に従いitem別Rightsを確認し、`No known restrictions`やセットの紹介文をPD/CCへ変換しない。利用可能な原文がない・不明な候補はreview除外とする。Rights欄が実際のitem Rights and Access原文を網羅するかは取り込み設計レビューでサンプル照合が必要。
3. #88の保持登録・期限・内部限定を既存経路で適用し、metadata取り込みのみで画像assetを生成しない。カラー判定対象だけを個別取得する。
4. #90/#109の既定thumbnail方針に沿い、`Preview_url`の実寸・MIME・variantを確認して既定縮小として扱えるかを先に検証する。manifestのフル画像URLを暗黙に取得せず、縮小経路が確認できない場合は取得を保留する。
5. data.labsのrobots 404を許可とみなさず、公式利用条件、個別URLへのアクセス応答、host間6秒以上、固定UAを先行確認する。採用・実装は本案のメインレビュー後とする。

### 実装・検証状態

- `source_policy`でLoC APIを無効化。403と`Cf-Mitigated: challenge`は一度で停止し再試行しない回帰テストを追加。
- API実取得: 要求1、レスポンスbyte未記録、適格画像0。画像要求0。データ一括画像取得0。
- 今回のmetadata/manifest/README転送は合計11,264,251 bytes。これらは候補調査用であり、統計用の取得画像ではない。
- WSL Ubuntu-24.04 / Python 3.12.3: `ruff check .`成功、`pytest -q` **627 passed, 271 skipped**、`python -m build`でsdist/wheel成功。全件pytestはext4一時コピーから実行。
- LoC対象回帰テスト: 7 passed。challenge 403で要求1回のみ、source policy無効時は通信前に拒否。
