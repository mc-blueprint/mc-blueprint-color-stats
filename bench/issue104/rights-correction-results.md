# Issue #104 反証P2の訂正

## 反証P2：確認根拠URLの訂正

Robot policyとRate limitsの指定2 URLを2026-11-05に取得し、両方HTTP 200を確認した。
`api_url`はRobot policyのAction API rules節へ訂正し、`rate_limits_url`を追加した。
確認日時は`2026-11-05T08:37:41.631340+00:00`、policy_versionは`issue104-v2`。
Robot policy自身が`/w/api.php`を例示して未認証の同時1・5 req/s未満・1秒超の要求後5秒待機を
定めていることを根拠とし、robots.txtを踏まえた利用継続は2026-11-05のユーザー判断である旨を
docs/collect.mdとrights_review.summaryに記載した。

asset 4,531件・source 1,955件のrights_reviewを同じ取引で訂正し、再実行は両方変更0件。
訂正前後の完全な値と件数をreview-correction-*.jsonに記録し、確認記録以外の全列hashは一致した。
区分・元license・出典・元qualityの他の値は変えていない。
訂正後の全7,607件の再分類dry-runも変更予定0件で、現在の計画hashはclassification-v2-dry.jsonへ保存した。

訂正前snapshot `fb7bc1af34b036cb111ae9ae6274195931e2c2271d764eb040e96bda55326942` とrun `3b46cfe4-9965-48d3-b041-b9b63bba75fc`は
履歴として保持し、本書の現行IDを訂正後の新しいIDへ差し替えた。
asset・provenanceの2 Parquetだけが変化し、残る5 Parquetはhashが同一。
全569行を含む統計全体は、置換対象のsnapshot_idとrows[].quality.snapshot_id以外が完全一致した。
統計値hash：`789d23b9ec91ea13124c90e2769aa1cfe2823839f31b680b68bb3b3feaa04549`。許容誤差や数値改変は使っていない。
旧M3 snapshotと旧runに加え、訂正前#104のsnapshotとrunの不変も確認した。
