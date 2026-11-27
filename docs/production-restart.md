# #122/#114 の単独GPU再開

#169 以降の再開先は ubuntu-1 の RTX 4070 一台とする。過去の二分割は
旧manifestを読むためだけに残す。旧root・旧run・旧snapshot・#105 v2・Assetの
採否は変更しない。本書は実行許可ではない。本番への書込みを伴うsmoke・全量・
番号返信の登録・媒体登録は、別途承認を得てから行う。

## 接続と配置

既存のログ付き `scripts/ssh.py` を使い、作業場所を絶対パスで指定する。
`bench.issue122.deploy` は指定した新配置名にだけ転送し、既存配置は上書きしない。
#122 の配置にも #120 の提示・番号変換を含む #114 のコードを同梱する。
移設前の認証読込み用launchは使わない。DB接続は実際のhostnameがubuntu-1である
ことを確認し、local Unix socketのpeer認証を使う。接続時だけpostgresの実効UIDへ
切り替えて元に戻すため、rootまたはpostgresで実行する。認証情報を探索したり、
hostnameを置換して接続条件を通したりしない。

## 表示より前の固定

privateの `sampling.json` に次を保存する。提示後に件数や合格条件を変更しない。

- `population_sha256`: 抽出元となる固定母集団ファイルのSHA256。
- `seed`: 抽出に使った整数seed。
- `groups`: `terrain_required` 14件、`random_old` 50件、`random_new` 50件、
  `challenge` 10件の対象一覧。無作為群同士とchallengeは重複させない。
  地形必須群との重複はまとめ、提示は110〜124件とする。
- `required_ids`: 上の4群の和集合を重複なしで保存する。
- `criteria`: `{"max_problems": 0}`。問題が出た場合は統計へ進まず、原因と対応を確認する。

対象一覧・母集団・個別値をGitに追加しない。旧側と新側で同じ固定条件を使用する。
既存の保留対象は、無作為抽出されたことや返信が「問題なし」であることだけで
採用へ変更しない。人物を含む画像は `privacy-review-v2` の一時保留を維持する。

## 新しいfreezeとrun

旧側は `bench.issue122.production`、新側は `bench.issue114.production` を使用する。
`freeze --root <新しい絶対root> --sampling <固定条件ファイル>` で
`plan.json`、単独の `ubuntu1/inputs.json`、コードと計画SHAを結ぶ
`execution.json` を作る。既存rootや既存計画は上書きしない。
旧計画のroot配下も拒否する。旧実行の `bind` は不要。

既存Bを使う場合は `--reuse-from <旧成果root> --models <固定モデルディレクトリ>`
を加える。旧recordsからB参照だけを引き継ぎ、成功状態・同一対象・prep入力・
method・prompt・実効しきい値・モデル・前処理・領域policy・全maskのSHAを確認する。
Bがない対象は通常のB実行へ回す。不一致のBは流用せず停止する。
閾値は実効値だけでなく、jobとrunのpayloadに明示された値も一致する必要がある。
省略時の既定値が同じでも、統計側の入力契約を満たさないBは再利用しない。
旧C、旧terminal、旧shade/colorは新しいrecordsへコピーしない。

承認後は同じrootで `run --host ubuntu1 --models <固定モデル> --limit 3`、
3件の監査、その後limitを外して全量、全量監査の順に進む。#114の監査は同じ
モジュールの `audit` を使い、smokeでは `--limit 3` を加える。
#122の入力照合と旧行保全は既存のpreflight・統計側の検査も使う。
新しい `execution.json` は以後差し替えない。コード・計画・subsetが変われば停止する。
新rootでは現行version・計画SHA・`human_sampling`を必須とし、旧形式への変更も拒否する。

`bench.issue114.operate` の起動には `--root`、`--code`、`--python`、`--models`、
`--name` を指定する。操作はsmoke/full/audit-smoke/audit-full/status。
statusは実際の各unitを照会し、runを開始しない。直接モジュールを起動する場合も、
媒体の読取り専用bindと新rootのtmp/cacheを用意する。

## v2人物確認と再開

runは既存のappend-only writerで新しいCを作る。中断後は新rootのrecordsを使う。
旧policyのCを持つterminalを成功扱いで飛ばさない。

#120の `bench.issue114.mobile` で、現行A/B/Cと原画像SHAからprivate HTMLを作る。
既存のbundle manifestとexecutionのreview manifestには同じ `sampling` と
提示項目の `required_ids` を入れる。元の固定標本は `sampling.required_ids` に残す。
未提示項目は `nonpresented_holds` に同一assetの現行human hold runの参照を付け、
固定標本＝提示項目と未提示保留の非交和を検証する。自動のpolicy保留、古い訂正や採用runは代用できない。
同一取得SHA・byteの項目は1番号へまとめ、各項目のA/B/C・mask比較はすべて残す。
HTMLの生成・配信検証・番号変換・返信登録は
[mobile-review.md](mobile-review.md) の既存手順を使う。
全件確認の返信を、同じ番号表と提示manifestで変換して既存writerへ追記する。
統計に渡すrootの `human/` には、配信済みHTMLと `number-map.json`、
`review-manifest.json`、適用結果の `converted-review.json` を揃える。
適用結果には各行の `recorded_privacy_review_run_id` が必要である。
旧側・新側で共通の提示を使う場合も、この同じ参照一式を使う。
別の判定台帳は作らない。

消費時に固定条件・番号・全件返信・HTML・原画像SHA・同じ対象/A/B/訂正元C・
確認者・所見を照合する。未確認や問題ありでは統計を開始しない。
番号への判定は全構成項目へ展開するが、未提示保留へは確認runを作らない。
未提示保留は統計でも除外し、旧recordsに採用が残っていても採用へ戻さない。
新しい番号表はv2。生成・返信・統計側を同じ版へ配置し、旧提示物は再生成する。
確認後に同じrunコマンドで再開すると、Bを維持して新C参照へ切り替え、
旧recordsをhistoryへ残し、shade/colorを作り直す。出力ファイルはCごとに分ける。
旧Cを参照した統計や色をそのまま使わない。

## 別版の統計と保持台帳

旧側は `bench.issue122.statistics --root <新root> --output <新統計先>
--policy <新しい版>` を使う。#105の基準snapshotは読取りだけに使う。
新側は `bench.issue114.terrain_statistics` に同じroot/output/policyに加えて
`--baseline <今回の旧基準> --baseline-snapshot <そのsnapshot ID>` を指定する。
まず `--old-only` で同じ確認条件の旧のみを別出力へ作り、比較時は
`--old-only-output <その出力先>` を加える。旧版policyと既存別出力への上書きは拒否する。
旧のみの比較基準は実行内容・対象集合・snapshotを照合し、新cohortを含む出力は拒否する。
旧のみ出力の基準snapshot IDも今回の`--baseline-snapshot`と一致する必要がある。
`bench.issue114.statistics_operate` も同じ引数を受け取り、現行hostで起動する。

集計は保留条件を維持し、新しい人物確認参照と一致するshade/colorだけを選ぶ。
新しい人確認が必要な対象は、旧返信だけでは保留を解除しない。
schema・公開API・旧保存形式の移行はない。DB更新は既存Queue/writerの追記と
そのjob管理、媒体コピーの既存保持登録に限る。新しい媒体のhostはubuntu-1とする。
旧run・Asset/quality・M3 snapshot・#105 v2を更新しない。

現DBに残る廃止hostの保持台帳の整合は**別のDB保守作業**であり、#169には含めない。
既存台帳を新hostへ付け替える処理やmigrationは実装しない。
権利/保持期限・入力SHA・モデル・固定条件・旧行保全の違反、GPU使用中、
目視問題、参照欠落では停止し、保留判定を弱めて通さない。

## 検証

GPUを使わない合成入力と隔離PostgreSQLで、B再利用・v2追記・再開・
人確認後の色再生成・旧成果保全・保持登録を検証する。全pytestと
CIと同じ `uv run ruff check .`（`RUFF_NO_CACHE=true`）、`uv build` を行う。
本番smoke・全量・ユーザーの表示確認は別の実行承認後に行う。
