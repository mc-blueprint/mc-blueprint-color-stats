# Issue #87 実装・検証引継ぎ

担当worktree：H:/mc-blueprint/worktrees/colorstats-87/mc-blueprint-color-stats
ブランチ：feature/issue-87。ownerは同一セッションで継続。
元の起点：4bbafba7cdc02019051ba02a3ffe5aa665687a4f。
2026-11-05継続時にfetchし、origin/develop=7492f6d（#99 / PR #101）を確認。
未commitの#87をee26ff4へ保全し、8f9eb86でorigin/developをmerge。競合なし、rebase・resetなし。
subject接続修正・統合回帰・本引継ぎはこの後の同じ論理コミットに含める。
push・PRはユーザー指示に従い未実行。再委譲なし。primaryと全体正本は未編集。

## 完成条件

1. 達成：source・asset・collect/prep/segment/shade/color・queue・CVAT・subject・aggregateへ区分を伝播する。subject runはrights.combine_licenseを使い、open+analysis_onlyをanalysis_only、異なる非open混在をrestrictedにする。
2. 達成：適格analysis_onlyをsnapshot・aggregateへ採用し、NC/academic/未知重み、根拠欠落、禁止、失効・利用停止・削除要求を除外する。
3. 達成：帰属不要でも元URL・識別子・provider・日時・確認記録を保持し、既存open/SAの結果を維持する。実subject runを経由する解析専用・open入力は適格、restrictedなsubject runは理由restricted_runで不適格となることを確認。
4. 達成：schema・D15-v2・M4配布契約とdocs/design §8・§9を更新。全体正本への変更案はglobal-design-proposal.mdに保存。
5. 達成：全CHECKのVARCHAR(13)、migrationの拒否・巻戻し・再適用、subjectを含む全後続stageの回帰が成功。

## 継続作業の検証結果

- WSL Ubuntu 24.04、Python3.12.3、uv.lock固定、クライアントと専用PostgreSQL16.15を同じ環境で実行。
- 全pytest：788 passed / 1 skipped（実GPU指定なし）。skipは公式重み・CUDAの明示指定が必要な実GPUテストのみ。
- 関連DB回帰：9 passed。collect→subject→prep→segment/shade/color→snapshot→aggregateを解析専用・openの両経路で実行し、restricted_run除外理由も照合。
- 時間依存テスト：断続失敗なし。単独再実行による救済は行っていない。
- WSL ruff check、sdist/wheel build、git diff --check成功。
- 検証はWindowsファイルシステム越しのI/Oを避けたLinux一時scratchpadのコピーで行い、コード・テスト・設定は担当worktreeとバイト一致を照合。
- 検証コード：/tmp/colorstats-issue87/scratchpad/integrated-code/
- 検証venv：/tmp/colorstats-issue87/scratchpad/integrated-venv/
- 全件結果：/tmp/colorstats-issue87/scratchpad/integrated-results.xml
- ビルド成果物：/tmp/colorstats-issue87/scratchpad/integrated-dist/（指定Windows scratchpad/i87-dist-integrated/へも保存）
- 前回のWindows関連77件・WSL全786件成功は前回時点の結果。今回の統合後結果は上記を正とする。Windows全件のネイティブ例外は成功扱いにしない。
- 検証専用PostgreSQL16は停止し、自分が起動した未完了テストは残さない。
- 実サイト収集、本番DB書込み、pilot再開、実GPU推論、既存cohort変更・M3再計算は未実行。

## 共有契約と後続Issue

- rights.LICENSESにanalysis_onlyを追加。combine_license(*values: str) -> strはopenを中立にし、同じ非openを保持、異なる非open・未知値をrestrictedにする。
- analysis_review_reasons(policy: dict, *, now: datetime | None = None) -> list[str]は根拠不足・停止・失効を理由付き判定する。
- 既存Candidate型・RunInfoのフィールド構成は不変。元license/URL/authorを保存し、作者未取得はnull。original_idは一意な出典ページURL、native IDは既存metadataへ保存する。
- license_rules.analysis_onlyは元licenseの完全一致リスト。rights_basis=copyright_act_30_4、rights_review（reviewed_at/terms_url/api_url/robots_url/summary/purpose/decision/reviewer/policy_version、任意expires_at/revoked）、attribution_required、access_scope=internal、image_redistribution=false、retentionを必須とする。
- purpose=non_expressive_color_statistics、decision=allowed。retentionはraw_days<=30、rejected_days<=7、deletion_request_days<=7、backup_days<=30の正の日数。短いソース条件を設定する。
- asset.quality.rightsに確認情報、retention_untilに原画像保存期限、provider/original_id/retrieved_atに追跡情報を保存する。use_stopped/deletion_requestedはsource.policyまたはquality.rightsで記録する。原画像の期限清掃は統計根拠失効ではない。
- stats.licenses.exclusion_reasons(asset, source, runs)が共通D15ゲート。source初回情報と取得時根拠が不一致なら除外し、自動更新しない。
- 内部snapshotはformat_version=2、gate_version=D15-v2、access_scope=internal。verifyは旧形式1も読める。旧固定M3 snapshotは不変。配布契約はdocs/pack-contract.md。
- #89向け：source_policy.yaml・collect/http.pyは変更なし。collect/policy.pyに解析専用確認を追加。measurement.recordはD15へsource.policy・asset.url/retrieved_atを追加で渡すだけで、計測方式・既存レート・リトライ設定は不変。
- #99：PR #101の変更をmerge済み。collect/bias.pyの名称一致確定削除とsubjects.pyのcollection_assignment再評価を保持し、subject runの区分合成だけを追加修正。接続待ちは解消。
- #88が保持清掃・削除受付窓口・CVAT/公開境界を完成し、新ソースを有効化する。#92・#94は上記共有契約を利用する。M4でallowlist混入拒否の実配布回帰を追加する。

## 公開準備・残り作業

#87の実装・検証・接続に未解決事項なし。ユーザー指示に従い、push・PR作成は行わない。
メインが完成条件と差分を確認した後に公開する。#88・#92・#94・M4の範囲を#87の未完了と混同しない。
指定scratchpad/i87-commit.txt・i87-pr-title.txt・i87-pr-body.mdを更新済み（UTF-8 BOMなし、Closes #87、Issue同一ラベル）。

## origin/developに対する変更ファイル

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
- `src/colorstats/stats/subjects.py`
- `tests/test_analysis_rights.py`
- `tests/test_analysis_rights_db.py`
