# Issue #93 Openverse 登録クライアントと長周期枠

担当worktree: `H:/mc-blueprint/worktrees/colorstats-93/mc-blueprint-color-stats`。
branch: `feature/issue-93`、引継ぎ起点: `origin/develop c83edb0`。
基準確認はメインからの引継ぎを再利用し、primaryのcheckoutは変更していない。
再委譲・push・PR・merge・Issue closeは行わない。

## 完成条件

| 条件 | 状態・根拠 |
| --- | --- |
| token取得・期限前更新・失効と停止 | fixture検証済み。client_credentials POST、90%期限更新、DB枠待機中の失効、短すぎる期限、不正応答・401/403後の停止 |
| payload/hash/DB/ログ/例外への秘密非保存 | fixtureで検証。credentialローテーションでもjob hash不変、匿名/standardでは別hash。systemd credentialから読み、tokenはメモリだけに保持。観測値にはmode/tier/有効枠のみ |
| 原host・redirectへのAuthorization非転送 | fixture検証済み。元ページ・原画像・別host・同host images/token redirectで非転送。token取得自体のredirectは拒否。HTTPS標準ポート以外と未対応APIを拒否 |
| 分/日枠・429延期・匿名への自動切替禁止 | fixture・隔離DBで検証。100/60秒、10000/86400秒、別jobへの台帳復元、境界ちょうどの解除、Retry-After 86400秒。認証失敗・欠落は停止 |
| 元ページ完全照合・禁止sourceの拒否維持 | 既存Openverse/HTTP/LoC/Mapillary回帰成功。LoC・Mapillary無効、Commons縮小既定（#109）を維持 |
| 登録後の少量実通信でstandard経路検証 | 未達。2026-11-05 13:04 UTC、ubuntu-1のclient ID・secret両方が未配置。配置確認はsudo test -sの成否だけ。秘密ファイルの表示・コピーなし |

## 実通信と共有契約

- 事前予算はtoken取得2・API20・画像10以内。今回の実通信はtoken0・API0・画像0、受信byte0、適格画像0。
- 認証情報未配置のため、ubuntu-1での一時DB・画像保存先作成・実取得は保留。本番DB接続なし、pilot再開なし。
- 実取得再開にはcredential配置・登録時の提示枠確認が必要。新規の`/mnt/data/derived/`配下と隔離PostgreSQL16を使う。
- 既存urllib/HttpClient・Meter.reserve_quota・LoadCredential方式を再利用し、依存追加・DB schema変更なし。
- standardは既存のMeter付きbias収集経路に限定。台帳のない通常collectは通信前に拒否する。
  同じ運用者は同じDB・単一収集unitで運用し、初期同時1・終了後1秒を維持する。
  token要求と送信前の予約も保守的に枠へ数える。旧匿名jobを書き換えず、新jobだけmodeとstandard上限を固定する。
- 共通HTTPはhost・Retry-After・同時実行枠の待機後、送信直前にDB予約を行う。
  DB枠不足時は予約せず待機し、token期限とhost枠を再判定する。
  元host・redirect先のpolicy判定・LoC/Mapillaryの現行停止は維持する。
- unit例は`ops/collect/openverse.conf.example`。実際のunit配置・サービス変更は行っていない。

## 検証

- `bench/issue93/verify.sh`はWSL Ubuntu-24.04を呼出元で明示し、ext4の新規一時コピー・PostgreSQL16で実行する。
  Python3.12の既存検証venvを再利用し、ruff・DB込み全pytest・hatchling sdist/wheelを実行。専用DBはtrapで停止する。
- 初回重点回帰126 passed。追加認証境界を含む重点回帰170 passed。
- 最終全体検証1021 passed / 1 skipped（166.93秒）、ruff・sdist/wheel成功。
  追加のstandard経路DB秘密非保存回帰も成功。Windows Gitのdiff check成功。
  実行ログ: `20261105T131613Z-0f56042d410d479cb6bfe0287d413b48.jsonl`。
  artifact: `/tmp/colorstats-issue93-rWKbvl/`。隔離PostgreSQL16は停止確認済み。
- skipは既存の実GPU smoke。既存警告は任意Matplotlib未導入とLoCのPillow getdata非推奨。実GPU成功とは扱わない。
- 反証でredirect許可引数とカウンタの名前衝突を発見・修正。DB秘密非保存テストの期待階層もeffective配下へ修正した。
  最終検証の結果に未修正失敗を混ぜない。

## 公式情報と残作業

2026-11-05に[公式認証資料](https://docs.openverse.org/api/reference/authentication_and_throttling.html)と
[公式レート既定](https://github.com/WordPress/openverse/blob/main/api/conf/settings/rest_framework.py)を再確認。
匿名5/hour・100/day、standard 100/min・10000/dayは公式コードの既定値で、本番保証値ではない。
enhanced/exemptは実装しない。API文書トップは閲覧ツールで403だったため、実応答確認済みとは扱わない。

実通信による提示枠・応答・byte・元サイト完全照合の歩留まりが残るため、PR本文は`Refs #93`。
ラベルはIssueと同じ`priority: medium`・`type: feature`。優先度の根拠は匿名APIによる回避手段があること。
公開文面はユーザー指定のscratchpadに`i93-commit.txt`・`i93-pr-title.txt`・`i93-pr-body.md`として
UTF-8 BOMなしで保存・確認済み。保存ログは`20261105T132027Z-1ae3eac8555d48299d288ac747d6c3b0.jsonl`。
Git操作はユーザー指示によりcommitまで。push・PRは行わない。
新しいドメイン知識の外部保存は行っていない。実装上の選択・進捗をAI-Knowledgeへ記録しない。

## 反証3件の修正（同一owner、2026-11-05）

- P2: HTTP台帳予約をhost・Retry-After・同時実行枠の待機後、送信直前へ移動。
  DB枠不足時は未予約で待機して再判定する。86400秒のRetry-After後の実送信と台帳時刻が一致し、
  メモリ状態を消した別jobでも日枠10000件を過小計上せず10001件目を拒否するDB回帰を追加。
- P2: standardのimages要求もredirectを追従せず停止する。元ページから登録APIへredirectした場合も拒否。
  同hostのimages/tokenと別hostへのredirectを匿名で送らない回帰へ更新した。
- P2: redirect先Locationの秘密queryをhost一致に関係なく除去。
  同host/別hostのaccess_token・client_secretを除去し、通常のpage queryを維持する回帰を追加。
- 重点回帰114 passed。最終全pytestは1023 passed / 1 skipped、167.43秒。
  ruff全体・sdist/wheel成功。既存警告4件は前節と同じ。
  ログ: `20261105T133320Z-67968a92d9e04bb9adda47205fb1ffc5.jsonl`。
  artifact: `/tmp/colorstats-issue93-FaQooz/`。隔離PostgreSQL16は停止済み。
- 今回は外部通信・SSH・認証配置の再確認・本番DB操作なし。実取得保留、Refs #93を維持する。
  指定の公開文面3ファイルも修正内容・最終検証結果に更新した。

## 残存P2: host表記によるredirect拒否の迂回（2026-11-05）

起点commit: `4ad7351fc191c403f4bdbe13124790f9f131192e`。同一owner・worktreeを継続。

- 既存のAPI拒否判定1箇所を、policy.check_current_urlと同じ小文字化・末尾ドット除去へ合わせた。
  拒否処理の重複や新しいhelperは追加していない。
- 有効tokenを持つ登録セッションで、元ページからimages/tokenへredirectする経路を検証。
  小文字・末尾ドット・大文字・大文字かつ末尾ドットの4表記、2パスの計8ケースで
  登録APIへの匿名要求を送信前に拒否する回帰を追加した。
- WSL Ubuntu-24.04・ext4一時コピー・隔離PostgreSQL16の最終全pytestは
  1031 passed / 1 skipped、170.14秒。ruff全体・sdist/wheel成功。既存警告4件は前節と同じ。
  ログ: `20261105T134211Z-9e4e41b04eda4b8888c51eaab9339f51.jsonl`。
  artifact: `/tmp/colorstats-issue93-HriN7Q/`。隔離PostgreSQL16は停止済み。
- 外部通信・SSH・認証配置の再確認なし。指定の公開文面を更新し、Git操作はcommitまで。
  実取得保留・Refs #93・push/PR禁止を維持する。
