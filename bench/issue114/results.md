# Issue #114 第1段階：設定更新と収集枠のdry-run

起点は引継ぎ済みの`origin/develop 5d5a7f9`、担当は`feature/issue-114`。
総枠と各層のimages・subjectsを3倍にし、#105の優先度・配分比・不足根拠は維持した。
集中枠の設定値、検索provider、source policy、API・保存形式は変更していない。
本書は収集計画であり、Issue全体の実収集・解析・統計更新は未実施。

## 読取りの根拠と条件

2026-11-05 16:02:54.602 UTC（11月6日01:02 JST）、ubuntu-2の本番DBを
`REPEATABLE READ READ ONLY`で集計した。接続は既存SSH wrapperとpostgresのpeer認証。
`capture.sql`がSQL、`db-snapshot.json`が集計結果、`dry_run.py`が通信もDB接続もしない再計算器。
作者名・subject名・画像URL・秘密値は保存しない。
既存7,626枚、すべてprovider・出典siteとも`wikimedia_commons`、未確定予約0件。
層に一致する7,383枚と未割当243枚を区別し、総枠では全7,626枚を数える。
collect jobはsucceeded 4,177 / failed 6、pending / running 0。migrationは**0007**。
並行workerの0008は未適用であり、第2段階の開始前に必要。

## source_shareの意味と決定事項との差

`coverage.images`は`asset.search_provider or source.site`を数える。
新規予約の`source`は`request.provider`（`bias.reserve`）。
OpenverseがCommons元画像を取得しても、providerは`openverse`である。
ただしURL・rendition・SHAの重複排除があり、同じ画像を別ソースとして水増しできない。
匿名と登録はどちらも`openverse`で、枠は共有する。別worker・別DBで枠を増やさない。

`bias.quota_reason`は実枚数に対する比率ではなく、
全体で`floor(image_budget * 0.8)`、層で`floor(layer.images * 0.8)`を検査する。
従って30,000枚設定では、他ソース0枚でもCommonsを**16,374枚追加して24,000枚にできる**。
「他ソースが増えた分しかCommonsを増やせない」は現行コードの逐次判定ではない。
今回この共有契約は変更しない。第2段階は以下の実枚数比も運用上の停止条件とする。

既存CommonsをC=7,626、Commons追加をx、非Commons追加をyとすると、
`(7,626+x)/(7,626+x+y) <= 0.8`、すなわち**x <= 4y - 7,626**。
現在は80%を超えており、まず非Commonsを1,907枚にするとCommons追加2枚まで可能。
y=2,000ならx<=374、y=4,000ならx<=8,374、y=6,000ならx<=16,374。
全30,000枚に到達する最小非Commons構成は、Commons24,000 + Openverse6,000。
層でも同じ比率を課す場合、既存Commons層枚数cに対して`x_layer <= 4*y_layer-c`。
これらは実装の固定枠に**追加する運用条件**であり、現在のコードが自動で守るとは扱わない。

## 追加可能数と層別上限

下表は枠だけから求めた上限。将来の候補が異なる画像で、照合・権利・品質条件を通り、
作者・地域を分散できる場合の値である。実サイトの在庫や適格数は未通信なので未確認。
各providerの単独上限は同時に足せない。全体の追加枠は22,374枚。

| provider / mode | 単独追加上限 | 到達総数 | 条件 |
|---|---:|---:|---|
| Commons | 16,374 | 24,000 | 現行コードの固定枠。実枚数80%の運用なら他ソース増加まで追加0 |
| Openverse匿名 | 22,374 | 30,000 | 下記全層の配分・分散条件。現行targetsのprovidersには未追加 |
| Openverse登録 | 22,374 | 30,000 | 匿名と共有枠。credential未配置の現状では実行不可 |

| 層（#105の優先度） | 既存画像 / subject | 新images | provider上限 | Commons追加 | OV追加 | 作者上限 |
|---|---:|---:|---:|---:|---:|---:|
| japanese-castle (1) | 668 / 4 | 2,715 | 2,172 | 1,504 | 2,047 | 135 |
| gothic-temple (3) | 667 / 49 | 2,040 | 1,632 | 965 | 1,373 | 102 |
| forest-autumn-day (1) | 556 / 5 | 2,265 | 1,812 | 1,256 | 1,709 | 113 |
| modern-house (2) | 617 / 13 | 2,040 | 1,632 | 1,015 | 1,423 | 102 |
| medieval-house (3) | 668 / 41 | 2,040 | 1,632 | 964 | 1,372 | 102 |
| japanese-temple (1) | 668 / 14 | 2,685 | 2,148 | 1,480 | 2,017 | 134 |
| islamic-temple (1) | 536 / 12 | 2,310 | 1,848 | 1,312 | 1,774 | 115 |
| chinese-house (1) | 613 / 4 | 2,865 | 2,292 | 1,679 | 2,252 | 143 |
| mountains-summer-day (1) | 645 / 6 | 2,775 | 2,220 | 1,575 | 2,130 | 138 |
| plains-summer-day (1) | 567 / 0 | 2,655 | 2,124 | 1,557 | 2,088 | 132 |
| desert-summer-day (1) | 592 / 0 | 2,805 | 2,244 | 1,652 | 2,213 | 140 |
| snowy-winter-day (1) | 586 / 2 | 2,805 | 2,244 | 1,658 | 2,219 | 140 |

各層subjects=300。全体作者上限1,500枚、地域12,000枚、subjectはmin(90,3)=3枚。
既存最大作者212枚・最大地域859枚。層別の作者枠が満了した作者は追加できず、別作者が必要。
地域は検索意図の地域とは限らず、予約時のcandidate.locationを優先する。
未知subject/作者/地域は現行コードが集中検査を省略するが、適格subjectの増加とは扱わない。
追加上限は既存を削除・変更せず、枠を満たす別候補を取得する場合の値である。

## 登録の有無による到達見込み（推定）

外部サイトへ今回アクセスせず、#93で2026-11-05に確認済みの
[公式レート既定](https://github.com/WordPress/openverse/blob/main/api/conf/settings/rest_framework.py)と
[認証資料](https://docs.openverse.org/api/reference/authentication_and_throttling.html)、
`configs/source_policy.yaml`を再利用した。公開値は本番保証ではなく、登録時の提示枠を実行前に確認する。
匿名5要求/時・100要求/日、登録100要求/分・10,000要求/日。
検索は現行limit=10。1 jobがadapterを新しく作り1検索するため、登録は検索ごとtoken取得1回も保守的に計上する。
以下の歩留まりは検索候補から重複・元ページ照合・取得・品質を経て新規採用に至る割合。

| 到達構成 | 仮定歩留まり | 検索要求 | 匿名の日枠換算 | 登録の日枠換算（token込み） |
|---|---:|---:|---:|---:|
| Commons24,000 + OV6,000 = 30,000 | 100% | 600 | 6日分 | 1日分（1,200要求） |
| 同上 | 10% | 6,000 | 60日分 | 2日分（12,000要求） |
| 同上 | 1% | 60,000 | 600日分 | 12日分（120,000要求） |
| Commons7,626 + OV22,374 = 30,000 | 100% | 2,238 | 23日分 | 1日分（4,476要求） |
| 同上 | 10% | 22,374 | 224日分 | 5日分（44,748要求） |
| 同上 | 1% | 223,740 | 2,238日分 | 45日分（447,480要求） |

日枠換算は要求数/日枠の切上げで、実経過日数の保証ではない。時/分枠、要求間隔1秒、
既存台帳消費、token期限・再取得、Retry-After、検索結果の枯渇、元サイト制限で延びる。
登録100%のOV6,000枚はAPI要求間隔だけでも約20分、Commons追加16,374枚はmedia開始間隔だけでも約4.55時間。
両方並行できてもこれらと照合・転送時間を要し、30,000枚を20分で収集できるとは意味しない。
Commons-onlyは登録の有無によらず24,000枚で止まり、30,000枚に到達しない。
登録未配置ならIssue設計どおりのstandard本収集は保留。匿名は比較シナリオで、自動代替しない。
新規採用が全て統計適格になる保証はなく、n_eff・supported・条件4の到達日数は推定できない。

## 検証と残作業

- 指定WSL Ubuntu-24.04 / Python 3.12 / 隔離PostgreSQL 16の全pytest:
  **1,052 passed / 1 skipped、214.52秒**。skipは既存の実GPU smokeで、GPU動作成功とは扱わない。
- ruff check .、hatchlingのsdist・wheel build、Windows Gitのdiff checkが成功。
  依存の取得・更新はせず、#93と同じ既存検証venv/builddepsを再利用した。
- 配分比3倍・集中枠不変・全層で現行Commons採用判定が通ること、
  計画のCommons16,374 + OV6,000が全体/全層の80%と各画像枠に収まることを別途照合した。
- 最初の全pytestでは旧subject目標100を前提としたreport期待値2件が失敗。
  新目標300に追従させて上記全体再実行で解消した。最初のruff指摘も修正済み。
  残る警告4件は既存の任意Matplotlib未導入とLoC/Pillow getdata非推奨。
- 最終コマンドログ: `20261105T161009Z-94d5140d43fa48198075d2a55f9a3ff8.jsonl`。
  artifact: WSL `/tmp/colorstats-issue114-m7FIzr/`。検証用PostgreSQLの停止とrunner正常終了を確認。
  本番DBの集計ログ: `20261105T160254Z-3a341748f00a45d8b1d475410b61e6c3.jsonl`。
  ログ正本はWindows `%USERPROFILE%/.codex/logs/commands/`。

変更はtargets、集中枠/reportテスト2ファイル、本ディレクトリのSQL・集計・計算器・結果・計画・検証手順。
commitは任意許可のみのため今回未実施。公開担当への再委譲・公開文面作成は行っていない。
第2段階は[実行計画](stage2-plan.md)に記載。認証配置・0008・実枚数比の運用ゲートに加え、
厳密な累計byte制御と新規cohort用manifest生成手順の準備・検証が残る。
実収集・DB書込み・解析・統計更新・pilot再開・データ削除・push・PRは未実施。
実装契約と運用手順の変更なので、外部のドメイン知識保存先への追記対象はない。
