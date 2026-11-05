# Issue #94 Mapillary アダプター

担当worktree: H:/mc-blueprint/worktrees/colorstats-94/mc-blueprint-color-stats。
branch: feature/issue-94。引継ぎ起点: origin/develop cecc325。
起点・fetch確認はメインからの引継ぎを再利用。primaryのcheckoutは変更していない。
ユーザー指示によりcommitまで。再委譲・push・PR作成・merge・Issue closeなし。

## 完成条件と残作業

| 条件 | 状態・根拠 |
| --- | --- |
| 規約・用途・大量保存・保持・レートの確認記録 | 完成条件1は未完了。規約全文はIssueコメントのユーザー確認を再利用。公開API・内部色解析・CC BY-SA 4.0・30日保持を記録。ユーザー決定によりレートは自主上限。robotsと規約§5・§11の関係をMapillaryへ確認し、回答まで全host停止 |
| 1ページ・継続・順位・画像対応のfixture | 実装・fixture検証済み。固定意図/bbox、整数offset→内部cursorをSTATE_DIRECTORYに永続化。別インスタンスの再開、未知offset拒否、同ページ再検索、URL失効を検証。fixtureは公式SDKのフィールド契約に基づく合成データであり実画像応答ではない |
| 禁止・未確認・人物主体・非画像・対応不明の事前除外 | 実装・fixture検証済み。無効policy、作者/ID/sequence/日時/寸法不足、CDN未確認、人物検出、検出未確認/継続を取得前に拒否。APIの人物検出ゼロだけで内部privacy確認を省略しない |
| 重複・連写・作者/地域集中・subject | 実装・fixture/既存全回帰で確認。同条件の同sequenceを抑制、native ID・安定URL・SHA・既存prepのpHash・bias予約を再利用。作者/地域を記録。subject_idを推測せず未確定とする。確定subject支持は増えない |
| 認証非保存・別host非転送・非公開保持/削除 | 実装・fixture/隔離DBで確認。LoadCredential経由を実際に起動、秘密非表示。API完全一致先だけOAuthヘッダー、CDN/redirectに転送しない。署名queryは台帳/例外から除去。rollback、再投入、期限拒否、native ID停止を共通stageで検証 |
| 少量実取得による再開/停止・byte・適格画像 | 未完了。API 1要求/11 byte、候補0・画像0・適格0。robots判明後の追加通信を停止し、実画像での再開/保持は未検証。モック継続/停止は確認済み |
| 原画像・CVAT・個人情報の配布混入防止 | 共通analysis_only・privacy・retention・public出力ゲートの回帰成功。画像配信機能なし。M4実パックビルダーは本Issueの変更範囲外 |

## 実通信の記録（2026-11-05）

- 事前予算: API30要求、画像15枚以内。保存先 `/mnt/data/work/issue-94/`。
  `budget.json`を通信前に作成。取得画像は0枚で、永続画像の削除・上書きは行っていない。
- ubuntu-1の一時unit `colorstats-issue94-probe3.service` に
  `LoadCredential=mapillary-client-token:/etc/colorstats/credentials/mapillary-client-token`を指定。
  root専用認証ファイルの内容表示・コピー、秘密の環境変数/引数注入は行っていない。
- robots 1要求: HTTP200、`User-agent: *` / `Disallow: /`。robots応答byteは未計測。
- 初回スクリプトがrobots拒否時に停止しない不備により、その後Images APIへ1要求を送信。
  HTTP200、11 byteの空結果、画像0枚・適格0枚。API byteにrobots応答は含めていない。
  判明後に追加通信を停止し、policyを無効化。probeにも禁止/未確認時の停止を追加した。
- 運用者へ公開APIとrobotsの関係に関する既存判断・公式根拠を照会中。
  robotsを無視して実取得・有効化することはしない。再開にはMapillaryの回答が必要。
- API条件・認証の一次情報:
  [公式SDK entities](https://github.com/mapillary/mapillary-python-sdk/blob/main/src/mapillary/config/api/entities.py)、
  [公式SDK client](https://github.com/mapillary/mapillary-python-sdk/blob/main/src/mapillary/models/client.py)。
  SDKの導入・複製はせず、既存urllib/HttpClientを再利用した。
- 固定意図は京都の小bbox。#105の目標未確定のため、本収集や地域・年代適格性を断定しない。
- 自主レート: API/CDN各同時1・終了後2秒、API30要求/60秒、CDN5,000,000 byte/10秒。
  公開上限を検証済みとは扱わない。429/503はRetry-Afterと60秒backoff以上を守って停止。
- 実行ログ: `20261105T100009Z-d652f5c1d37e4fe8824367e14e84afd3.jsonl` と配下SSHログ。
  unitは終了、DB検証プロセスはtrapで停止。本番DBには接続していない。

## 検証

- WSLはUbuntu-24.04、ext4の`/tmp/colorstats-issue94/code`で実施。Python3.12、PostgreSQL16。
- 初回実装の全pytest: 911 passed / 1 skipped、147.51秒。skipは既存の実GPUテスト。
  colour-scienceの既存任意Matplotlib未導入警告が1件。実GPU成功とは扱わない。
- 追加差分の重点検証: 20 passed。署名query全除去・継続状態保全を含む。
- ubuntu-1の隔離PostgreSQL16: 20 passed。既存の一時検証venv・PostgreSQLバイナリを読み取り利用。
  `/mnt/data/work/issue-94/pgdata`、socket、専用DBを新規作成。本番DB利用なし。
  最後のcredentialファイル欠落・API類似host拒否の追加は最終WSL回帰で確認済み。
- 最終差分のruff、sdist/wheel、diff check成功。
- 実APIの候補応答・CDN/画像MIME/人物検出の現行挙動・実画像の再開は未検証。
  API結果が空だったためフィールド対応を実測済みと扱わない。
- 再現: `bench/issue94/verify.sh`、ubuntu-1は`remote.py <新規名> 'bash bench/issue94/remote-verify.sh'`。
  probe再開はpolicyの有効化前提を解消してから、一時unitのLoadCredentialを必須とする。

## 共有契約・公開準備

共有SearchRequest/Candidate型・DB schema・stats・collection_targets.yamlは変更していない。
追加はstageのprovider分岐、targetsの`mapillary_searches`、source_policyの自ソース、docsの自ソース追記のみ。
画像エンティティ識別子をoriginal_urlとし、実画像の署名URLとは区別する。詳しくはdocs/collect.md。
公開文面は同ディレクトリのcommit.txt・pr-title.txt・pr-body.md・labels.json（UTF-8 BOMなし）。
未解決条件が残るため、通常PRとして完成したとは報告しない。push・PRはユーザー指示どおり未実行。
新しいドメイン知識候補: 公開APIのhostもrobotsが全面拒否を返す事実。規約解釈は未確定。
外部AI-Knowledgeは編集していない。メインで正本・記録要否を判断する。

## 反証指摘への修正（同一owner、2026-11-05）

基準commit: 549f5c13d0d6520a143c5442f8864b61af167e70。既存worktreeを継続。
ユーザー決定により、回答までMapillaryは全経路で通信しない。レートは既存の自主上限を維持。
今回の修正・検証で外部サイトへ通信していない。SSHは指定された本番DB件数のREAD ONLY確認のみ。

- P1修正: HttpClient共通層でmapillary.com・fbcdn.netと全subdomainを現行policyに従わせる。
  Openverseの元ページ照合・原画像取得、古い許可host表、別host redirectにも同じ停止を適用。
  全host・元ページ照合・redirectの回帰テストを追加した。
- P2共有枠修正: media_transferと台帳に実hostとrate_groupを併記。
  復元はgroup単位で行い、旧台帳のgroup欠落は記録時policyのsuffix規則で対応付ける。
  メモリ内レート状態を初期化し、a.fbcdn.netの4MBをb.fbcdn.netの受信へ復元するDB回帰を追加。
  新旧両台帳で5MB/10秒の共有枠を超えないことを確認した。
- P2認証拒否修正: 401/403をNonRetryableErrorに変換。
  worker子プロセスの失敗応答へ再試行可否を含め、Queue.fail(retryable=False)で1試行のfailedにする。
  401・403それぞれについて実spawn経由でfailure_reasonと再claim不能を検証した。
- 懸念修正: prepare開始時に現在のprovider許可を再確認。
  Mapillary hostはHTTP送信直前にも再確認し、レート待機中の無効化も拒否。
  現行ファイルはCOLORSTATS_SOURCE_POLICY、未指定時はcwd/configs/source_policy.yaml。
  payload内の過去policy・任意のpathで現行停止を迂回しない。過去enabledジョブと待機中停止の回帰を追加。
- 本番READ ONLY確認（2026-11-05 10:28:42 UTC）: transaction_read_only=on。
  provider=mapillaryかつ保存policy.enabled=trueのcollect jobは全状態合計0件。
  Mapillary hostの許可を持つOpenverse collect jobも全状態合計0件。個別payload・接続情報は非表示。
  ログ: 20261105T102842Z-23f788163ebe4c60a8b206c67b9df67b.jsonl。
  再現スクリプト: read-production-counts.py。本番DBは変更していない。
- 最終全体検証: WSL Ubuntu-24.04、Python3.12・隔離PostgreSQL16で923 passed / 1 skipped、149.90秒。
  skipは既存実GPUテスト、任意Matplotlib未導入の既存警告1件。ruff・sdist/wheel・diff check成功。
  関連回帰64件も成功。専用PostgreSQLはtrapで停止済み。新規回帰は計12件。
- PR本文はRefs #94へ変更。完成条件1・6未達とMapillary回答待ちを明記。
  push・PRは行わない。変更範囲は指摘のHTTP/policy/stage/台帳・queue伝播と対応テスト・文書だけ。

## probeの残存P2修正（同一owner、2026-11-05）

基準commit: d0d9b3de7c4083310d98894cb20a333e22e3d92d。同じworktreeを継続。
probeの直接urlopenを廃止し、現行policyのload_policyと共通HttpClientを使用する。
COLORSTATS_SOURCE_POLICYを優先し、未指定時だけcwd/configs/source_policy.yamlを読む。
現行policyが無効なら予算ファイル作成・robots取得より前に停止し、
robots取得でも共通HTTPの送信直前照合・redirect・レート制御・UAを適用する。
robotsには認証ヘッダーを送らない。API取得は従来どおりMapillaryAdapterを使う。

回帰2件: cwdの有効設定で現行の無効化を迂回できず通信0件であることと、
cwdに設定がなくても現行設定を読み、robotsを共通HTTPで取得して禁止時にAPI取得前に止まること。
WSL Ubuntu-24.04で関連33 passed（3.11秒）、ruff・sdist/wheel・diff check成功。
今回の全pytestは未実行（直前修正の全923件成功は上節）。実通信・SSH・本番DB操作なし。
検証専用PostgreSQLは停止済み。Mapillary無効・完成条件1/6の回答待ちを維持し、push・PRなし。
