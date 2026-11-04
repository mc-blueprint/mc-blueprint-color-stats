# Issue #87 実装・検証引継ぎ

担当worktree：H:/mc-blueprint/worktrees/colorstats-87/mc-blueprint-color-stats
ブランチ：feature/issue-87。引継ぎ起点：4bbafba7cdc02019051ba02a3ffe5aa665687a4f。
未commit。push・PRは実行しない。再委譲なし。primaryと全体正本は未編集。

## 完成条件

1. source・asset・collect/prep/segment/shade/color・queue・CVAT・aggregateの伝播を実装・検証。subjectの非open合成は並行#99側の接続待ち。
2. 適格analysis_onlyをsnapshot・aggregateへ採用。NC/academic/未知重み、根拠欠落、禁止、失効・停止・削除要求を拒否する52件の反例・統合回帰が成功。
3. 帰属不要でも元URL・識別子・provider・日時・確認記録を保持し、既存open/SAの回帰を維持する。
4. schema・D15-v2・M4配布契約とdocs/design §8・§9を更新。全体正本の変更案はglobal-design-proposal.md。
5. 全CHECKのVARCHAR(13)、migrationの拒否・巻戻し・再適用、collectからsnapshot・aggregateとCVATの回帰を確認。

## 検証結果

- Windows Python3.12.15・uv.lock：追加関連52件＋measurement既存25件、計77 passed。隔離PostgreSQL16.15。
- WSL Python3.12.3・同一uv.lock：全pytest 786 passed / 1 skipped（実GPU指定なし）。
- Windows側のI/O待ちを避け、一時Linux scratchpadの検証コピーで全回帰を実行。コード・テスト・設定等143ファイルは担当worktreeとバイト一致を確認。
- Windowsの全pytestはpsycopg待機中にネイティブアクセス違反。WSL全回帰で確認し、Windowsの全件成功とは扱わない。
- ruff check .、git diff --check、最終sdist/wheel build成功。成果物はscratchpad/i87-dist-final/。
- 外部サイト実収集、本番DB書込み、pilot再開、既存cohort変更・再計算は未実行。
- 旧pytestと子プロセスは終了確認済み。検証用PostgreSQL16は停止済み。

## #88・#92・#94への共有契約

- `colorstats.rights.LICENSES`にanalysis_onlyを追加。`combine_license(*values: str) -> str`はopenを中立にし、同じ非openを保持、異なる非openまたは未知値をrestrictedにする。
- `analysis_review_reasons(policy: dict, *, now: datetime | None = None) -> list[str]`。固定確認と期限・停止を理由付き判定する。
- 既存`Candidate`型・`RunInfo`のフィールド構成は不変。元license/URL/authorを保存し、作者未取得はnull。original_idは一意な出典ページURL、native IDは既存metadataへ保存する。
- `license_rules.analysis_only`は元licenseの完全一致リスト。確認済みrights_basis=copyright_act_30_4、rights_review（reviewed_at/terms_url/api_url/robots_url/summary/purpose/decision/reviewer/policy_version、任意expires_at/revoked）、attribution_required、access_scope=internal、image_redistribution=false、retentionを必須とする。
- purpose=non_expressive_color_statistics、decision=allowed。retentionはraw_days<=30、rejected_days<=7、deletion_request_days<=7、backup_days<=30の正の日数。短いソース条件を設定する。
- asset.quality.rightsに確認情報、retention_untilに原画像保存期限、provider/original_id/retrieved_atに追跡情報を保存する。use_stopped/deletion_requestedはsource.policyまたはquality.rightsに記録する。原画像清掃は統計根拠失効ではない。
- `stats.licenses.exclusion_reasons(asset, source, runs)`が共通D15ゲート。source初回情報と取得時根拠が不一致なら除外し、自動更新しない。
- 内部snapshotはformat_version=2、gate_version=D15-v2、access_scope=internal。verifyは旧形式1も読める。旧固定M3 snapshotは不変。配布契約はdocs/pack-contract.md。
- #89向け：configs/source_policy.yaml・collect/http.pyは変更なし。collect/policy.pyに解析専用確認を追加。measurement.recordはD15へsource.policy・asset.url/retrieved_atを追加で渡すだけで、計測方式・既存レート・リトライ設定は不変。
- #99向け：stats/subjects.pyのrun生成時に既存のopen/all以外restricted処理をcombine_licenseへ接続する必要がある。担当外2ファイルは未変更。

## 残り作業

#99側のsubject合成接続と統合回帰後、メインが完成条件を確認して公開担当へ文面と差分を渡す。
#88が保持清掃・削除受付窓口・CVAT/公開境界を完成し、新ソースを有効化する。M4でallowlist混入拒否の実配布回帰を追加する。
公開文面は指定scratchpad/i87-commit.txt・i87-pr-title.txt・i87-pr-body.md（UTF-8 BOMなし）。

## 変更ファイル

- `bench/issue87/global-design-proposal.md`
- `bench/issue87/handoff.md`
- `docs/collect.md`
- `docs/design.md`
- `docs/pack-contract.md`
- `docs/schema.md`
- `src/colorstats/analyze/prep.py`
- `src/colorstats/analyze/segment.py`
- `src/colorstats/analyze/shade.py`
- `src/colorstats/collect/measurement.py`
- `src/colorstats/collect/policy.py`
- `src/colorstats/collect/stage.py`
- `src/colorstats/queue/core.py`
- `src/colorstats/rights.py`
- `src/colorstats/schema/migrations/versions/0006_analysis_only.py`
- `src/colorstats/schema/models.py`
- `src/colorstats/stats/aggregate.py`
- `src/colorstats/stats/licenses.py`
- `src/colorstats/stats/snapshot.py`
- `tests/test_analysis_rights.py`
- `tests/test_analysis_rights_db.py`
