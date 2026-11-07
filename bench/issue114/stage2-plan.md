# Issue #114 第2段階の実行計画（第1段階の計画履歴）

2026-11-07再追記：ユーザー決定により、新規画像の全件目視を「自動判定＋一部目視」に置き換える。
以下の全件目視待ちは過去の停止記録であり、現在の判定・mask固定・採用分解析・目視サンプル・
統計開始条件は[人物判定計画](privacy-plan.md)に従う。目視サンプルの結果確認までは新統計を作らない。

2026-11-07追記：バッチ1は収集2,600枚、prep・GPU segment各2,600件まで完了した。
新規画像に対する内部目視確認が未記録のためshade全件失敗、color未実施で中断した。
`src/colorstats/retention.py` の `review_privacy` / `check_privacy` が再開の必須条件である。
原画像・縮小画像の目視確認と必要な人物除外maskの登録を済ませた扱いにはしない。
確認後はmaskを入力payloadへ固定し、失敗済みjob・部分snapshotを保全した新しい実行枠を設計する。
現状・未完了条件・再開順序は[バッチ1記録](batch1-results.md)を参照する。

2026-11-06追記：ユーザー決定により、source_shareは現行の**設定総枠に対する固定上限**を採用し、
Commonsを先行する。以下に残る実枚数比の運用ゲート・Openverse待機を本収集全体の開始条件とする記述は、
第1段階の試算履歴であり適用しない。現在のバッチ1手順・予算は[バッチ1記録](batch1-results.md)を正本とする。
Openverseは登録値配置後に別途開始する。統計・reportには実ソース内訳とCommonsへの偏りを明記する。

## 開始条件

本計画は第2段階の開始許可を代替しない。現段階では通信・本番書込みを行わない。
正本は`ops/collect/provider-workers.md`（#91）。旧deploy READMEの単一collect/pilot手順より優先する。
収集hostはubuntu-1のみ、GPU解析はubuntu-1/2。ubuntu-0/2のraw収集は有効化しない。
LoC・Mapillaryは停止のまま、Openverse登録値未配置ならstandardを起動せず匿名へ自動代替しない。

1. 新しい配備commit、targets、taxonomy、source policy、storage hash、measurement IDを固定する。
   本stageの起点5d5a7f9を再利用するだけでなく、実行直前に後続修正・現行規約との整合を確認する。
2. 旧collect/pilot、同一providerのworker/prepare子process、古い有効jobが停止済みか確認する。
   今回のREAD ONLY集計ではcollect pending/running=0だが、開始直前に再確認する。
   旧pilotを再開しない。新規unitだけを作り、同一providerは全hostで1所有者にする。
3. DB所有者がworker停止中に0007から`alembic upgrade head`で0008を適用し、
   `ops/deploy/worker_grants.sql`の適用状態を確認する。必要ならcollection_limitのSELECT/INSERT/UPDATEだけを追加する。
   workerにはDDL・superuserを与えない。0008適用は今回未実施。
4. 登録値配置はユーザー作業。存在・空でないことだけ確認し、内容を表示・コピーしない。
   #93の`ops/collect/openverse.conf.example`に沿ってLoadCredentialで注入し、
   権利確認済みpolicyの新しいコピーをstandardに固定する。元ページ・redirectには認証を送らない。
   #93の少量検証はtoken2/API20/画像10の事前上限内で、別measurementに記録する。
   その本番DB登録分も以下の6,000枚・通信総予算から差し引く。
5. 両providerは同一運用者の共有DBを使う。別DB・別modeで通信枠を増やさない。
   ubuntu-1のraw-orico/raw-suneast両方の空容量・mount・実pathを確認する。
   縮小取得を既定にし、#88の保持契約・#87の内部解析区分・権利照合を維持する。

## 予算と配分

以下は**1回の実行全体の事前予算**。probe・smoke・再試行も含め、未使用枠だけを後続batchへ割り当てる。
最初のbatch終了時に歩留まり・byteを評価し、予算の増額や無制限なseed追加は行わない。

| 項目 | 上限 |
|---|---:|
| 新規登録総数 | 22,374枚（既存7,626を含め30,000） |
| Commons新規登録 | 16,374枚 |
| Openverse新規登録 | 6,000枚（匿名・登録共通） |
| Commons API / 全HTTP | 6,000 / 60,000要求 |
| Openverse API / 全HTTP | 12,000 / 132,000要求（token取得をAPIに含む） |
| 全provider HTTP本文受信byteの計画予算 | 20,000,000,000 byte |

API/HTTP枠は既存`measurement`の層別・provider別allocationで強制する。
現行Meterに画像総数のprovider別「追加分」や全期間の受信byte上限を強制する設定はない。
source_shareの固定枠だけで上表のOpenverse6,000枚上限を守れるとは扱わない。
従って未実装の自動停止器を仮定せず、**有限jobを小分け投入しbatch間で集計して止める**。
各検索10候補、`measurement`付きでは各言語の先頭ページだけなので、
1層だけを含むtargetsでの有限smoke（通常2〜4 job/provider）から始める。
上限未確定の応答や残予算で安全に処理できないjobは投入しない。
現行HTTPに応答全量のbyte上限もなく、有限jobだけでは20 GB以内を保証できない。
byteは実測から次batchを見積もり、残予算不足なら投入しない。実行中も消費を監視して停止するが、
監視間隔中や処理中応答による超過はあり得る。**厳密なbyte予算が必要な本収集の前提として、
共有累計byte予約とread前停止を追加・検証する必要がある**（今回未実装、現行10秒窓で代替しない）。
この前提を満たすまで本収集は保留し、通信予算を増やして回避しない。
API/HTTP/byte/枚数のいずれかが次batchを許容しなければ、予算を増やさず停止して未達を報告する。

現行`bias.plan`は画像不足率順であり、priority/priority_orderそのものはソートに使わない。
#105の優先度1→2→3を守るため、同じ集中枠・層上限を持つ実行用targetsを作り、
対象priorityの層だけを各batchに含める。前のbias設定のpending/runningがない状態で切り替え、
設定変更時は新measurement IDを使う。同じIDでpolicy/targetsを変更しない。
各batchのAPI/HTTP層別枠は残予算以内で割り当て、その合計を上表の残枠と照合する。

実枚数比80%も守る運用では、まずOpenverseを増やす。
実測の累積yからCommonsの残追加許可を`max(0,4y-7626-x)`で毎batch再計算する。
層にも同式を適用し、未確定予約と未完了jobの候補最大数（job数×limit）を差し引いて投入する。
残許可が通常batchより少なければ、全言語jobの合計候補数が残許可以内になるlimitで次batchを作る。
最低2言語分を許容できなければ待機する。上限を越える大量jobを先にenqueueしない。
既存100%を直ちに解消できない初期期間はCommonsを停止し、Openverse1,907枚以上で全体の80%を回復する。

次は全体・全層で80%以内にする、満枠到達の**実現可能な枠配分例**。
未割当の既存243枚を保持するため、全層を30,000枚まで埋めるわけではない。

| 層 | 最終層枚数 | OV追加 | Commons追加 |
|---|---:|---:|---:|
| japanese-castle | 2,715 | 591 | 1,456 |
| gothic-temple | 2,040 | 408 | 965 |
| forest-autumn-day | 2,265 | 453 | 1,256 |
| modern-house | 2,040 | 408 | 1,015 |
| medieval-house | 1,797 | 360 | 769 |
| japanese-temple | 2,685 | 537 | 1,480 |
| islamic-temple | 2,310 | 462 | 1,312 |
| chinese-house | 2,865 | 573 | 1,679 |
| mountains-summer-day | 2,775 | 555 | 1,575 |
| plains-summer-day | 2,655 | 531 | 1,557 |
| desert-summer-day | 2,805 | 561 | 1,652 |
| snowy-winter-day | 2,805 | 561 | 1,658 |
| 合計（既存未割当243枚を除く） | 29,757 | 6,000 | 16,374 |

未来の候補在庫・作者分散・適格性を保証するものではない。最初のsmokeから同じ分母で歩留まりを測定し、
枠はあっても候補枯渇・subject到達・集中枠で進まなければ停止して不足層を報告する。
provider別quota台帳と通信規則はbatch/measurementを変えても保持する。

## 起動・監視・停止

実行用targetsに`search.providers: [wikimedia_commons, openverse]`と新measurementを設定し、
provider別の事前予算を割り当てる。リポジトリの標準targetsは今回Commonsのみのまま。
`bias_cli plan`はdry-runではなく**DBへenqueueする操作**なので第2段階でのみ実行する。

```sh
python -m colorstats.collect.bias_cli --targets /新規実行領域/targets.yaml plan \
  --policy /新規実行領域/source_policy.yaml --storage configs/storage.yaml \
  --host ubuntu-1 --code-version <固定commit> --seed <記録したseed>
python -m colorstats.queue --handler collect=colorstats.collect.bias \
  --provider wikimedia_commons --stop-file /run/colorstats/collect-commons.stop \
  --storage-path collect=/srv/colorstats/raw-orico \
  --storage-path collect=/srv/colorstats/raw-suneast
python -m colorstats.queue --handler collect=colorstats.collect.bias \
  --provider openverse --stop-file /run/colorstats/collect-openverse.stop \
  --storage-path collect=/srv/colorstats/raw-orico \
  --storage-path collect=/srv/colorstats/raw-suneast
```

上の起動をubuntu-1の既存Python・DB注入・systemd credentialで包み、新規unitとjournaldを使用する。
逐次比率の回復中はCommons workerを起動せず、許可batchができてから開始する。
`upload.wikimedia.org`とthumbの共有rate_groupは同時2・間隔1秒。
provider-workers.mdの25,000,000 byte/10秒と、現行policyの31,250,000には差があるため、
実行用の両policyをより厳しい25,000,000に揃えて固定する。Commons APIは同時1。

監視は各batch前後、稼働中は1分ごとを目安とし、provider別job状態・lease・失敗理由・429/503・
Retry-After・HTTP/API/byte消費・DB待機・raw空容量・候補→照合→取得→新規SHA→適格を確認する。
DB時計で共有停止を守り、認証・DB・lease障害、容量不足、権利不一致、予算不足では新規投入を止める。
停止は該当stop-fileを作成し、workerとprepare子processの終了、provider所有権返却を確認する。
正常停止できない通信はhost停止を維持し、旧process終了と応答・期限を確認して該当tokenだけを復旧する。
`collection_limit`の手削除・未完了byte予約の払戻し・台帳削除は行わない。
再開は同じmeasurement/settings・既存台帳・保存済みseedから、未完了と成功を照合して行う。
設定・mode変更なら旧jobを消さず停止状態を整理し、新measurementと新jobへ切り替える。

## prepとGPU分担（#66方式）

収集を停止・照合した後、既存7,626 assetと旧run/artifactのID・hashを保全し、新規asset IDを固定する。
prepは新規だけを新しい解析版・出力先へ投入し、成功prepのrun ID・path・SHAを共通不変入力にする。
prep失敗は理由付きで母集団へ残し、成功に数えない。
segment→shade→部位colorは`ops.deploy.m3_analysis`の既存runnerを使う。
既存freezeは7,607 asset / prep成功7,603件を固定検査するため、今回の母集団には使用できない。
第2段階のGPU開始前に、同じmanifest形式・入力hash検証を再利用して新規cohortだけを固定する
入力生成手順を用意・検証する。既存runnerのrun/reportは再利用し、旧成功IDの再処理を拒否する。

1. 両hostのCUDA・lock由来依存・SAM2/DINO重みSHA、共有prep入力のreadと別root出力のwriteを確認する。
   #66の認証経路を再利用し、秘密を転送しない。GPUが他作業中なら開始しない。
2. 新規cohortを固定manifest化し、ubuntu-1/2へasset IDが重複しないsubsetとして分割する。
   #66の初期配分2:3を目安とし、各hostのsmoke実測から残りを配分する。
   既存成功・smoke成功IDとの非重複、全体との和集合一致、設定・入力SHA一致をassertする。
3. `/mnt/data/derived/issue114/<実行ID>/ubuntu1`と`ubuntu2`の別root・別manifestを使い、
   各host専用transient unitで`python -m ops.deploy.m3_analysis run --root <専用root> --models <検証済みmodel>`を実行する。
   Ubuntu-1は既存launch経路、Ubuntu-2は#66のpeer経路。旧#66/pilot unitを再開しない。
4. 各hostで少数件smoke後に新規名の`report --root ... --output ...`を保存し、violations=0で継続する。
   GPU利用率・VRAM・枚/秒・attempt・artifact byte・DB/WALを測定し、成功/失敗/未処理を分ける。
   #66の速度は参考で、今回の固定日数としない。host別DB増分は並行書込みを含むので単純合算しない。
5. 停止は対象unitだけを正常停止し、stage境界・子process終了を確認する。
   再開前に成功IDを除外し、残りだけ新subset/rootへ。旧manifest/run/artifactは書き換えない。

## snapshot・rule_stat・report

#74/#75/#76と#87の内部snapshot契約を再利用し、旧版とは別の保存先・識別子にする。
既存分は旧成功run、新規分は今回の成功runを明示したselection JSONを固定する。
subjectの同定・属性確定は既存CLIのdry-runを先に確認し、新規cohortだけに適用する。
subjectsの目標数や収集意図を、確認済みsubject・統計支持と取り違えない。

```sh
python -m colorstats.stats.snapshot_cli --selection <固定selection.json> \
  --code-version <固定commit> --output <新規snapshotディレクトリ>
python -m colorstats.stats.aggregate_cli --snapshot <新規snapshotディレクトリ> \
  --snapshot-id <検証済みhash> --output <新規statistics.json> --dry-run
python -m colorstats.stats.aggregate_cli --snapshot <同じsnapshotディレクトリ> \
  --snapshot-id <同じhash> --output <別の新規登録用statistics.json>
python -m colorstats.queue --handler aggregate=colorstats.stats.aggregate \
  --stop-file /run/colorstats/issue114-aggregate.stop
python -m colorstats.stats.report_cli --snapshot <同じsnapshotディレクトリ> \
  --snapshot-id <同じhash> --statistics <登録用statistics.json> --output <新規reportディレクトリ>
```

snapshotのhash・input run・ライセンス伝播、rule_statの登録run、再計算JSON一致を確認する。
前版と同じ定義で適格画像・confirmed/adopted subject・n_eff・supported・条件4を比較し、
全体と#105の不足層ごとに増減・未達理由を示す。旧版のasset/run/artifactが不変か照合する。
第2段階の終了時に収集・解析・aggregate unitと子processの終了、全cohortの成功/失敗理由、
残job、予算消費、保全先を記録する。永続データの清掃・削除は本計画に含めない。
