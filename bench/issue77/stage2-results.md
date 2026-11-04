# Issue #77 本番測定結果（第2段階）

2026-11-05 JST。固定設定 issue77-v1／seed 77、ubuntu-1の専用手動collect。
起点62d38b8にorigin/develop a6c1bffをmerge（5c6c626）。#74第2段階の未commit変更は使用しない。
既存Python・認証注入・raw設定を再利用し、停止済みpilotは再開していない。

## 全体結果

- 経過 1539.281秒。ジョブ {'succeeded': 95, 'failed': 2}、試行 105。
- API要求 145、全HTTP要求 344、HTTP応答 344、timeout 0。
- 候補 243、照合 134、取得成功 19、登録 19。
- 新規SHA 19、適格新規SHA 8、SHA重複 0。
- 受信body 254,215,317 byte、取得成功 186,623,050 byte。DB/WALやwire byteとは異なる。
- bodyはアプリが読み取った分であり、未読のエラーbodyやHTTPヘッダーは含めない。
- Asset 7607 → 7626、SHA 3575 → 3594。
- 取得原本・既存データは削除していない。通常失敗時の一時ファイル清掃は既存契約どおり。

## 層・供給元別

要求は失敗・リダイレクト・再試行を含む。照合はCommonsの帰属充足とOpenverseの作者・ライセンス完全照合で強度が異なる。
API0の行は未測定。適格SHA0の応答済み標本を、未来の歩留まり0%や到達不能とは解釈しない。

| 層 | 供給元 | API/HTTP | 応答 | timeout | 候補/照合 | 取得/適格新規SHA | 取得byte | body byte |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| japanese-castle | Commons | 11/12 | 12 | 0 | 10/9 | 1/0 | 225250 | 256229 |
| japanese-castle | Openverse | 5/18 | 18 | 0 | 11/2 | 0/0 | 0 | 5477320 |
| gothic-temple | Commons | 14/15 | 15 | 0 | 11/11 | 1/0 | 10204473 | 10274832 |
| gothic-temple | Openverse | 3/18 | 18 | 0 | 10/5 | 0/0 | 0 | 5554082 |
| forest-autumn-day | Commons | 14/18 | 18 | 0 | 11/11 | 4/1 | 38698795 | 38777375 |
| forest-autumn-day | Openverse | 1/18 | 18 | 0 | 10/8 | 0/0 | 0 | 4813289 |
| modern-house | Commons | 14/15 | 15 | 0 | 12/12 | 1/1 | 746426 | 815441 |
| modern-house | Openverse | 3/18 | 18 | 0 | 11/10 | 0/0 | 0 | 5317641 |
| medieval-house | Commons | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 | 0 |
| medieval-house | Openverse | 2/18 | 18 | 0 | 16/2 | 0/0 | 0 | 6569071 |
| japanese-temple | Commons | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 | 0 |
| japanese-temple | Openverse | 4/18 | 18 | 0 | 14/4 | 0/0 | 0 | 3198744 |
| islamic-temple | Commons | 14/15 | 15 | 0 | 11/11 | 1/0 | 3086033 | 3131434 |
| islamic-temple | Openverse | 5/18 | 18 | 0 | 13/0 | 0/0 | 0 | 1533067 |
| chinese-house | Commons | 14/15 | 15 | 0 | 12/12 | 1/0 | 459983 | 508613 |
| chinese-house | Openverse | 3/18 | 18 | 0 | 15/0 | 0/0 | 0 | 7714242 |
| mountains-summer-day | Commons | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 | 0 |
| mountains-summer-day | Openverse | 3/18 | 18 | 0 | 11/4 | 0/0 | 0 | 5360253 |
| plains-summer-day | Commons | 14/17 | 17 | 0 | 12/12 | 3/3 | 37797056 | 37854561 |
| plains-summer-day | Openverse | 2/18 | 18 | 0 | 11/5 | 0/0 | 0 | 5799479 |
| desert-summer-day | Commons | 0/0 | 0 | 0 | 0/0 | 0/0 | 0 | 0 |
| desert-summer-day | Openverse | 3/18 | 18 | 0 | 14/1 | 0/0 | 0 | 7437601 |
| snowy-winter-day | Commons | 14/21 | 21 | 0 | 12/12 | 7/3 | 95405034 | 95593318 |
| snowy-winter-day | Openverse | 2/18 | 18 | 0 | 16/3 | 0/0 | 0 | 8228725 |

## 停止・失敗と除外理由

各層はAPI20/HTTP40、内訳Commons API14/HTTP22・Openverse API6/HTTP18を超えていない。
失敗した要求の枠も返却せず、検索終端・継続ページ上限と集中枠を維持した。
OpenverseのHTTP 500等は既定キューの最大3試行で打ち切り、失敗分も分母へ含めた。
層別の除外理由・stop_reason・SHA重複の件数はstage2-summary.json、URL・継続位置を含む全試行台帳はremote measurement.jsonに保存する。
取得19件のうちSA条件で11件を除外し、8件が取得時のD15権利ゲートを通った。
同じ画像へlicense_conditionsとlicense_not_allowedが重複して付くため、理由数を画像数として合計しない。

| 層 | 供給元 | 停止理由 | 収集除外理由 | D15除外理由 |
|---|---|---|---|---|
| japanese-castle | Commons | {'stratum_source_limit': 3} | {'stratum_source_limit': 8, 'missing_attribution:author_or_attribution': 1} | {'license_conditions': 1, 'license_not_allowed': 1} |
| japanese-castle | Openverse | {'provider_http_limit': 1} | {'download_http_403': 2, 'source_license_or_author_unverified': 9, 'verification_stopped:provider_http_limit': 1} | {} |
| gothic-temple | Commons | {'provider_api_limit': 2} | {'restricted': 1, 'rediscovered_url': 8, 'stratum_author_limit': 1} | {'license_conditions': 1, 'license_not_allowed': 1} |
| gothic-temple | Openverse | {'provider_http_limit': 3} | {'download_http_403': 5, 'source_license_or_author_unverified': 5, 'verification_stopped:provider_http_limit': 1} | {} |
| forest-autumn-day | Commons | {'provider_api_limit': 2} | {'rediscovered_url': 5, 'stratum_author_limit': 1} | {'license_conditions': 3, 'license_not_allowed': 3} |
| forest-autumn-day | Openverse | {'provider_http_limit': 3} | {'download_http_403': 7, 'source_license_or_author_unverified': 2} | {} |
| modern-house | Commons | {'provider_api_limit': 4} | {'rediscovered_url': 9} | {} |
| modern-house | Openverse | {'provider_http_limit': 2} | {'source_license_or_author_unverified': 1, 'download_http_403': 4} | {} |
| medieval-house | Commons | {'stratum_source_limit': 3} | {} | {} |
| medieval-house | Openverse | {'provider_http_limit': 3} | {'source_license_or_author_unverified': 14, 'verification_stopped:provider_http_limit': 1} | {} |
| japanese-temple | Commons | {'stratum_source_limit': 3} | {} | {} |
| japanese-temple | Openverse | {'provider_http_limit': 3} | {'source_license_or_author_unverified': 10, 'verification_stopped:provider_http_limit': 1} | {} |
| islamic-temple | Commons | {'provider_api_limit': 2} | {'rediscovered_url': 9, 'stratum_author_limit': 1} | {'license_conditions': 1, 'license_not_allowed': 1} |
| islamic-temple | Openverse | {'provider_http_limit': 1} | {'source_license_or_author_unverified': 13, 'verification_stopped:provider_http_limit': 1} | {} |
| chinese-house | Commons | {'provider_api_limit': 5} | {'rediscovered_url': 9} | {'license_conditions': 1, 'license_not_allowed': 1} |
| chinese-house | Openverse | {'provider_http_limit': 3} | {'source_license_or_author_unverified': 15, 'verification_stopped:provider_http_limit': 1} | {} |
| mountains-summer-day | Commons | {'stratum_source_limit': 3} | {} | {} |
| mountains-summer-day | Openverse | {'provider_http_limit': 3} | {'source_license_or_author_unverified': 7, 'verification_stopped:provider_http_limit': 1, 'download_http_403': 4} | {} |
| plains-summer-day | Commons | {'provider_api_limit': 6} | {'rediscovered_url': 7} | {} |
| plains-summer-day | Openverse | {'provider_http_limit': 4} | {'download_http_403': 5, 'source_license_or_author_unverified': 6, 'verification_stopped:provider_http_limit': 1} | {} |
| desert-summer-day | Commons | {'stratum_source_limit': 3} | {} | {} |
| desert-summer-day | Openverse | {'provider_http_limit': 2} | {'download_http_403': 1, 'source_license_or_author_unverified': 13, 'verification_stopped:provider_http_limit': 1} | {} |
| snowy-winter-day | Commons | {'provider_api_limit': 2} | {'rediscovered_url': 5} | {'license_conditions': 4, 'license_not_allowed': 4} |
| snowy-winter-day | Openverse | {'provider_http_limit': 3} | {'source_license_or_author_unverified': 13, 'verification_stopped:provider_http_limit': 1} | {} |

## subjectと固定snapshot

基準snapshotは `3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702`。固定7,607 asset、解析適格代表SHA 1618、確定subject 37。
新規collectは固定snapshotへ追加していない。保存済み共有run-result.jsonのverified=trueとsnapshot IDを参照した。
取得分の根拠付き確定subject（層別）は `{'islamic-temple': 0, 'forest-autumn-day': 0, 'snowy-winter-day': 0, 'plains-summer-day': 0, 'chinese-house': 0, 'modern-house': 0, 'gothic-temple': 0, 'japanese-castle': 0, 'medieval-house': 0, 'japanese-temple': 0, 'desert-summer-day': 0, 'mountains-summer-day': 0}`。検索意図・名称一致だけでは確定に数えていない。
本測定は取得時の権利歩留まりであり、新規分の解析・品質ゲートやsubject推定を実行したという意味ではない。

## 1万→3万→10万への解釈

開始時N0=7607、固定snapshotの代表SHA E0=1618。1万行枠の残りは2393行であり、全て適格でも楽観上限は4011枚。
この1万Asset行枠から適格SHA1万枚への到達を主張しない。raw/解析/subject・供給元構成・集中枠は別途見積りが必要。
今回配分の観測r=0.05517241適格SHA/API要求。下表は同じ歩留まりが維持するとの感度試算であり、検索深度・供給元・層の枯渇を無視した到達保証ではない。

| 適格SHA目標T | 参考API要求 | 参考取得byte |
|---:|---:|---:|
| 10000 | 151924 | 195534300638 |
| 30000 | 514424 | 662091925638 |
| 100000 | 1783174 | 2295043613138 |

## 完成条件・検証・終了状態

- 12層×2供給元の要求・応答・timeout・候補・照合・取得・適格新規SHA・除外・byteを記録。根拠付きsubjectは層別に別掲。
- source_policy・User-Agent・作者完全照合・集中枠・事前固定した通信枠を変更せず測定した。
- Linux隔離PostgreSQL16: 636 passed / GPU 1 skipped。Windows: 452 passed / 185 skipped。
- 収集関連と開始前残存拒否: 188 passed。ruff check .、sdist/wheelビルド成功。
- 原本19件の実在・SHA・合計186,623,050 byteとD15適格8件をREAD ONLYで再照合した（stage2-raw-audit.json）。
- 開始前と終了後の未完了collect runは0。専用unitはinactive、exit 0。別件segment pending 2件は処理・削除していない。
- 原本はraw媒体、完全な台帳と前後状態はstage2-artifacts.json記載の専用rootに保全した。
- docs/collection-bias.mdは#76担当のため編集せず、結果の転記用下書きを同ディレクトリへ更新した。

監査ログは `%USERPROFILE%/.codex/logs/commands/` に保全した。
開始は`20261104T185003Z-8e50a9fde4954f058ed4378f36c768a3.jsonl`、
全Linux検証は`20261104T185055Z-cc7e1199d9f24655b6bc818f3effeb6d.jsonl`、
原本監査は`20261104T192026Z-e021bfba36484a1ab0a034c6e1825d64.jsonl`。
