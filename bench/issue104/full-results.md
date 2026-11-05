# Issue #104 本番再評価の結果

2026-11-05。起点73d3c3d、担当feature/issue-104。
#89 PR #106のdevelop d97c218をabd66ddでmerge。競合なし。
hosts・レートと解析専用の確認根拠を両方保持し、collect配下は独自編集していない。

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

## バックアップとmigration

- バックアップ：`/mnt/data/work/issue-104/backup-20261105T074401Z/colorstats.dump`。
- 完全pg_dump custom形式、580,605,022 byte。
- SHA-256：`3a2328cdaf909795857dc7f5d98eb34c1062bd6729d17c8415fc63bfbb9bbe6c`。
- 保存前の空きは約855 GiB。archive目録と全SQLストリームの読み出しに成功。
- alembic upgrade headで0005→0007（0006・0007）を適用。復元はしていない。
- 既存ファイル・アーカイブ・M3 snapshot・旧rule_statの削除や上書きなし。

## 区分追記

統合後dry-runは前回と全内容・計画hashが一致し、書込み前に[dry-integrated.json](dry-integrated.json)へ保存。
保存済み区分open 7,607件から、open 3,076件・analysis_only 4,531件へ単一取引で追記した。
NC・根拠欠落・未知表記の区分除外は各0件、合計7,607件。
同じ計画の再実行は変更0件で、hashも不変。
元license・URL・作者・日時・元quality・取得時設定・保存場所のhashは追記前後と最終監査で一致した。
旧画像のretention台帳は0件で、期限設定・清掃・アーカイブ移動はしていない。
Openverseは対象0件のため、実測されていない短縮表記の許可は追加していない。
画像解析入力22,808 runはopen、属性根拠1 runを別扱いし、NC・評価用・未知重みは0件だった。

## 新snapshotと統計

- snapshot ID：`e60bc14c7076a405b75333d1a0b280d9b088534796bdc4fedec0fbdebe414471`。
- rule_stat run：`928993fa-d498-4f68-85f4-35169d5d07c5`。
- aggregate job：`36b5dfc9-0cf7-40d2-9cd1-5c68ca1484a3`。
- 正本：`/mnt/data/derived/stats/issue104-full-20261105T084843Z`。
- コード版：`5ffa603+i104-v2-658d3c05cef6fa29`。全src・設定・taxonomyのhashをimplementation.jsonに固定。
- #74の既存snapshot CLI、#75のdry/register、#76のreport CLIを使用。
  新規収集、segment・colorのjob実行、再推定はしていない。
- 新snapshotの全7ファイル・D15・SHA代表・失敗6件の非算入を全量監査し、違反0。
- 新rule_stat全行と入力辺を固定計算と照合し、二重完了・再投入でも同じjob/run/行数を維持。
- 旧snapshot 3e785e67…の全hashと旧run d7297e42の569行・4,856辺・統計hashは不変。
- v1初回2回のsnapshot起動はDATABASE_URL未設定で停止。失敗領域を保全し、設定後の新規領域で成功した。
  元画像・maskはM3と同じroot読取り、DBはREAD ONLY、生成物は非公開の新規領域だけへ保存した。

## 新旧比較

| 指標 | 旧版 | 新版 |
| --- | ---: | ---: |
| D15適格画像 | 3,076 | 7,607 |
| 必要解析あり | 3,074 | 7,601 |
| SHA代表画像 | 1,618 | 3,570 |
| 適格確定subject | 37 | 154 |
| wall 採用subject / n_eff | 20 / 17.824331 | 121 / 27.048481 |
| wall 補正率 / 情報なし | 100.0% / 0.0% | 100.0% / 0.0% |
| tree 採用subject / n_eff | 7 / 7.000000 | 18 / 15.625000 |
| tree 補正率 / 情報なし | 0.0% / 100.0% | 44.4% / 55.6% |
| supported / unsupported | 0 / 569 | 0 / 569 |
| M3条件4 | failed | passed |

n_effはsubject重みの集中度で、未知の層所属や欠測偏りの不確実性を含まない。
10/10役割ゲートと直接分布30/30を区別し、補正率・情報なし割合・属性別未知率をcomparison.jsonと併読する。
条件4のpassedは層補正の有効性を保証しない。

## M3条件1〜6

- 条件1：passed
- 条件2：passed
- 条件3：passed
- 条件4：passed
- 条件5：passed
- 条件6：unverified

自動reportは外部証跡を受けないため、条件1・2の既存監査と入力不変性の照合はm3-assessment.jsonへ分けた。
同定精度の人手正解による保証や、保護した旧確定2画像の粒度注意は変わらない。
条件6のG受領・利用確認は未実施。条件4の結果とM3全体の完了を混同しない。
今回の区分再評価・新規統計作成・新旧比較に未解決事項なし。push・PR作成は依頼どおり未実行。

## 検証

- WSL Ubuntu 24.04、Python 3.12.3、クライアントと専用PostgreSQL 16.15を同一環境で実行。
- #89統合後の全pytest：868 passed / 1 skipped（既存の明示GPUテストのみ）。
- ruff・sdist/wheel build・wheelでの外部cwd CLIが成功。検証150ファイルはworktreeとバイト一致。
- 配布allowlistで画像・原meta・個別出典の混入拒否を回帰確認。内部snapshotを配布しない。
- 解析専用の確認根拠はIssueのユーザー判断を記録し、外部通信は許可されたRobot policy・Rate limitsの2 URL確認だけ。
- 専用PGは正常停止済み。本番の既存サービスは変更せず、起動した未完了処理は残していない。
