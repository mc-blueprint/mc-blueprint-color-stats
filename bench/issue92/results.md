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
