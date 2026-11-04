# 収集の偏り制御と網羅率

Issue #9、設計書§9.1。既存のPyYAML・SQLAlchemy・PostgreSQL 16とPython標準の
random・mathで実装し、依存追加はしない。共有collectは1ページの取得と登録を再利用し、
計画・採否・予約だけを専用ハンドラー `colorstats.collect.bias` が担当する。
予約の排他には既存DBの取引ロックを使い、別のキューや分散ロック製品は追加しない。

## 設定と採否の根拠

`configs/collection_targets.yaml` の初期値は実パイロット前の仮値。
建築はdomain・style・building_type・region・era、地形はdomain・biome_like・season・
time_of_dayで層を定義する。照明条件には分類体系のtime_of_dayを使う。
scene.yamlにある語彙とtaxonomy_versionを検証し、地域と年代は自由記述の識別子とする。
同じ属性の層を重複登録できない。

採否と層の画像集計には検索要求が指定した「意図した層」を使う。
これは検索条件に基づく推定であり、画像の分類が確定したことは意味しない。
asset.search_parameters.collection_biasに層ID・intended_attributesを記録し、
scene_attributesへ未確認の分類を入れない。M2で分類・補正したscene_attributesがあれば、
レポートではその属性を優先する。

収集候補のタイトルとsubject名の一致だけでは、subjectを確定しない。
名称一致は後続のsubject推定で弱い候補として残し、座標やWikidata照合など独立した根拠を
確認するまでasset.subject_idはNULLにする。検索タイトルが複数subjectに一致する場合や
一致しない場合も候補を取得する。
一般住宅・地形など未同定の対象を除外せず、候補ごとのsubject新設もしない。
名称は同定の補助であり、一意なsubjectの確定根拠にはしない。
subjectの画像上限と割合枠は確定subjectにだけ適用する。
subject不明は重複を除いたsubject数や目標達成数に算入せず、レポートで件数・割合を出す。
未同定候補が多ければsubject目標が未達でも画像予算で停止する。収集後のsubject推定は後続工程で扱う。

prepも確定subjectを保持し、pHash近似は`subject_candidate`と`asset_duplicate`に留める。
SHA-256完全一致群に確定subjectが一意に存在する場合だけ、未同定assetへ引き継ぐ。
確定値が競合する完全一致群では未同定を保つ。重複クラスタ数はsubject数・網羅率に算入しない。
詳細は[スキーマのprep契約](schema.md#prepの重複同定契約revision-0004)を参照する。

地域の集中枠は候補の撮影地点candidate.location、意図した層のregionの順で決める。
空の値は使わず、どれもなければ不明とする。regionとregion_basisを予約と
asset.search_parameters.collection_biasへ記録する（candidate.location / stratum.region /
unknown）。名称一致だけでsubject.locationを取得候補へ結び付けない。撮影地点は提供された文字列のまま照合し、座標の逆ジオコーディングや
表記の名寄せは行わない。層の地域区分とは粒度が異なる場合があり、実パイロットで確認する。
作者不明・地域不明も採用し、それぞれ不明群として数える。割合上限は既知の値だけにかける。
成功時は確定済みsubject_idがある場合だけ登録し、層・地域の根拠と元のタイトル・撮影地点・
検索語・実効条件・順位・ページ・取得日時・帰属情報は共有collectのまま保持する。
カタログ・分類を実行中に書き換えない。

## 集中枠の分母

開始時の1枚は必ず実測占有率100%となるため、採否は固定した`image_budget`に対する
枠で判定する。例えば予算1,000枚、author_share=0.05なら作者ごとに最大50枚。
作者とソースは全体枠に加え、層の`subjects`を固定分母とする層内枠も検査し、
全体枠と層内枠の小さい方まで取得できる。目標100・author_share=0.05なら層内で同作者は5枚。
層内集計にも確定画像と未確定予約を含め、属性の一致を既存の層判定で調べる。
層内枠による除外は`stratum_author_limit`・`stratum_source_limit`として記録する。
これはIssue #27のパイロットで確認された層内作者集中を抑えるための契約修正。
source_shareは出典ページ単位ではなく検索provider単位、region_shareは
上記の地域文字列単位。subjectには割合枠に加えてsubject_imagesも課し、小さい方を使う。
採否・予約はrequest.provider、確定後の集計はasset.search_providerを使う。
同じ出典URLをCommonsとOpenverseの両方で取得してSourceが共有されても、それぞれの
検索providerの枠へ数える。検索providerが未記録の既存画像だけSource.siteで集計する。
割合×予算の端数は切り捨て、0枠になればその区分は取得できない。
作者は空白除去・casefoldで照合するが、異名や複数作者の名寄せは自動化しない。

全asset行と未確定予約を数え、画像予算自体も超えない。
assetは検索機会ごとのレコードなので、同じ原本の別検索による取得も1枠を消費する。
subject数は重複を除く。別経路の既存assetも上限集計に含め、subject不明の既存画像は
網羅率に算入しない。既存画像が上限を超えている場合に削除や再分類は行わず、追加取得を止める。
途中の実測割合が設定割合以下になることは保証しない。未達・高集中はレポートで確認する。
予算・割合は運用全体で同じ設定を使い、変更は旧設定のジョブを処理し終えてから行う。
異なるbias設定のpending/runningジョブがある場合は採否をエラーにして混在を防ぐ。

## 計画と実行

接続URLは認証情報をログへ出さない方法でDATABASE_URLに設定する。
通常のcollectハンドラーを同じ収集DBで並行使用せず、偏り制御対象は全て専用ハンドラーへ渡す。
素のcollectジョブと専用ジョブを同じcollectキューに混在させない。

```sh
uv run alembic upgrade head
uv run python -m colorstats.collect.bias_cli plan --storage configs/storage.yaml --host windows --code-version <commit> --seed 42
uv run python -m colorstats.queue --handler collect=colorstats.collect.bias --stop-file data/collect.stop
uv run python -m colorstats.collect.bias_cli report --output coverage.json
```

CLIの`--targets`・`--taxonomy`はplan/reportより前、他の引数は各サブコマンドの後に指定する。
不足subject率の大きい層から、複数言語の語彙・複数ページ・無作為なオフセットを投入する。
seedで再現可能。同じseed・設定は既存ジョブIDを返し、成功・失敗を初期化しない。
同じseedで再計画すると成功runのnext_offsetも次ページとして投入し、pagesとmax_offsetを
超える継続は行わない。別seedで別の探索を追加できる。予約中のsubjectも不足判定に含み、
層の目標または画像予算を満たせば投入を止める。投入後に満了した層は取得直前に除外する。

wikimedia_commonsとopenverseを利用できる。provider選択・ポリシー検証は共有collectと
同じアダプター生成関数を使い、未対応ソース・不正なポリシーは投入前に拒否する。
Commons固有のmaxlagはOpenverseには要求しない。
source_share=0.8のままCommonsだけでは予算1,000枚のうち最大800枚となる。
実パイロットでは対応ソースと配分、または検証目的の設定変更を先に確認する。

## 予約の取引と回収

revision 0003のcollection_reservationにjob ID・試行トークン・層と属性・任意のsubject・作者・サイト・
任意の地域と根拠・出典URLを保存する。未確定時はasset_id=NULL、成功時にasset_idを設定する。
0001・0002と既存保存形式は変更しない。既存データの再生成は不要。

採否はjob行の所有権ロック→予約テーブル単位の取引advisory lock→期限切れ予約回収→
所有権再検査→実績と予約の上限検査→予約挿入の順。
同じバッチも別ワーカーも同じ排他を使い、通信は取引の外で行う。
ロック待ち・取引停止には既存Queueの取引タイムアウトを適用する。

共有prepareの例外時はその試行の未確定予約だけを削除する。
採用後に原本取得の4xx（429を除く）で候補を除外した場合も、その候補の未確定予約を
次候補の採否判断前に解放する。成功した原本だけを完了取引で確定し、除外理由はrunに残す。
強制終了・停止・登録失敗後は、jobがpending/failed、トークンが変更、またはリース失効なら
枠を再利用できる。次の採否/計画時に短い取引で回収するため常駐清掃プロセスは不要。
回収時にはjob行をFOR UPDATE SKIP LOCKEDで取得し、完了・リース更新中は回収しない。
完了取引が期限をまたいでも二重に枠が配られない。
成功時は共有registerによるsource・asset登録、subjectの関連付け、予約の確定、run・job成功を
同じ取引で確定する。途中失敗は全てrollback。旧試行はQueueの所有権検査で拒否される。
ファイルの不変化・未参照ファイルの清掃は既存queue契約に従う。

## レポートと検証

reportは読取りのみ。層ごとの画像数、重複を除くsubject・作者・サイト数、目標subject数、
網羅率、不足数、最大作者の実測画像占有率、作者分布のShannonエントロピー（bit）、
集中フラグをJSONへ出力する。作者不明は作者数から除き、subject・作者・地域の
不明画像数と層内割合を別に出す。不明subjectを一つのsubjectとして数えない。
エントロピーでは不明を一つの群として含め、占有率の分母は層の全画像数。
空の層は0件で残し、未分類画像は全体のunassigned_imagesへ出す。
予約は実績として表示しない。concentratedは実測最大作者占有率がauthor_shareを超えた層。

tests/test_collection_bias.pyは模擬候補で取得前の採否・同一バッチの予約・失敗回収を確認し、
TEST_DATABASE_URLのPostgreSQL専用schemaで2ワーカーの同時判断、リース失効、登録失敗、
成功との同一取引を検証する。1,000件の模擬asset・500subject・2作者でCLIまで確認する。
schemaテストは0003込みの適用・巻戻し・再適用とAlembic差分なしを確認する。

## ubuntu-1復旧後の実パイロット

本Issueでは実原本を取得しない。復旧後は次の順で実施する。

1. raw媒体の既存データ・mount・到達性を読み取り確認し、保存先設定を確認する。
2. 層と多言語の検索語を多地域・複数様式・一般住宅・地形へ整備する。
   カタログを補助的に使う場合だけ名称・別名を確認し、必須条件にしない。
3. #8統合後の対応ソースと利用ポリシーを確認し、1,000枚の予算・層目標・集中枠を調整する。
4. migrationを対象DBへ適用し、全collectワーカーを専用ハンドラーへ統一する。
5. 到達可能なraw保存ノードで計画・実行し、reportを定期保存する。
   枠の不足で取得が止まった場合は未達を隠さず記録し、追加探索や次回設定を判断する。
6. 1,000件の実画像を用いた最終report、除外理由、作者・サイト別配分を保存して初期値を見直す。

実画面への影響・ユーザー介入がある確認は事前確認し、ホスト再起動や媒体初期化は行わない。

## 固定snapshotの統計偏り（Issue #76）

固定snapshotと、そのsnapshotから生成したaggregate CLIのJSONを入力にする。
JSONのrowsはrule_statへの登録対象と同じ内容であり、本レポート自体はDB登録を証明しない。
全Parquetのhash検証後に#75と同じ設定で再計算し、入力JSON全体との一致を要求する。
weights.asset_attributes・compatible_strata・assign_strata・calculateを再利用する。

収集意図の層とsubject・assetの保存属性に一致する層を分ける。
推定stateがない既存属性はrecordedとし、根拠付き推定成功に含めない。
競合・不足・対象外・複数層一致を分離する。件数はasset行／SHA異なり／
確定subject／候補のみ／未知／適格なSHA代表画像を区別する。
全体のSHA異なりは全体で直接数え、層別件数を足さない。
同じSHAが別層にも現れ得る。

率はnumerator・denominator・valueを持つ。分母0はnull。
層の意図比較は当該層の収集意図行数を分母とし、属性不足・不一致・競合を示す。
適格率・除外理由・未知率・集中率は各集計対象のasset行数が分母。
除外理由は重複し得るので合計を除外画像数として扱わない。
D15適格→解析適格→SHA代表の段階と前後のsubject数を出す。
author等は既知値の上位占有率、未知率、既知の個別値と未知1カテゴリの
Shannon entropy（bit）を表示する。regionはsubject.location、
撮影位置はasset.collected_locationを使い、検索意図から補完しない。

条件・役割／pairごとにdirect／smoothed／unsupported、subject基準n_eff、
最大重み、欠損目標質量、感度分布、品質フラグ、親とλを#75から引き継ぐ。
10万枚の達否はD15・解析・重複除外後の画像数で別表示する。
これは現実母集団への無偏推定や材質色の証明ではない。

### 層分類とD15診断

地域・年代は既存coverageと同じsubject.location・subject.eraから取り込む。
同一subjectの適格画像間で既知の層属性が競合すれば、各画像の両立は表示するが、
そのsubjectをどちらの層の採用数にも足さず、不足数と未割当理由へ反映する。
D15除外・解析不足の画像は主統計のsubject割当へ戻さない。

rights_supportは層・条件と役割ごとにD15前後の保存済み色観測subjectと失ったsubjectを表示する。
画像件数差ではなくsubjectの集合差であり、同じsubjectの適格観測が残れば失った数に含めない。
個別部位の保存観測と、和集合マスクから生成した色を区別する。
#74でD15除外画像の和集合色が保存されない場合、前後差は不明のまま明示し、
条件5をpassedにしない。構成部位の存在だけから和集合色の支持を作らない。


2026-11-04の部分層補正で、unknown属性は周辺化し、複数層との両立を許す。
既知値の矛盾と対象外だけをsubject単位で棄却する。層の採用数は両立数で重複し得るため、
目標への被覆・不足はm_shの和で計算する。条件・役割の補正率・未知率・情報なし割合は
分母subject_countとともに#75主結果から表示する。分類の全体率とは分母を混同しない。
全層両立でも主結果で条件4を判定し、補正率0・情報なし割合1を併記する。D15は変更しない。

解析失敗で色がない画像はmissing_analysisとして明示し、支持へ足さない。
根拠stateはsubject.attribute_evidence（地域・年代）とscene_inferenceから読む。
条件4は「passed は層補正の有効性を意味しない」を併記し、情報なし過半にweak_correctionを付ける。

実測は[全量結果](../bench/issue76/full-results.md)、[実レポート](../bench/issue76/full-report.md)、
[完成条件判定](../bench/issue76/m3-assessment.json)、[G引継ぎ](../bench/issue76/g-handoff.md)を参照。

## 追加収集の歩留まり（Issue #77、2026-11-05実測）

測定計画・枠・停止条件は `bench/issue77/plan.md`、設定は同ディレクトリのtargets.yaml。
本番測定は2026-11-05 JSTに完了した。詳細は `stage2-results.md`、機械可読値は
`stage2-summary.json`、完全な試行台帳の保全先とhashは `stage2-artifacts.json` を参照する。

API145要求／HTTP344要求・応答344、timeout 0、候補243・照合134、取得19・適格新規SHA8。
原本186,623,050 byte、アプリが読み取ったbodyは254,215,317 byte。
新規19 SHAのうち11件はSA条件でD15除外。複数の除外フラグは同じ画像へ重複して付く。
Openverseは36 API要求・216 HTTP要求で全12層を測定したが、原本取得は0件。
元ページの照合不一致108件と原本HTTP403が28件あり、照合やUser-Agentを緩めていない。
Commonsは109 API要求・128 HTTP要求で取得19件。集中枠が満了した4層は未測定とした。
取得分の根拠付き確定subjectは全層0件。追加の解析・同定は未実施で、未知を確定へ昇格しない。

層ごとに全試行のAPI/HTTP要求、HTTP応答、timeout、候補、照合、取得、受信body byte、
取得成功byte、DB登録数、新規SHA、D15適格新規SHA、SHA重複、確定subjectと新規subject、
除外理由を報告する。適格新規SHA/API要求はtimeout・429再試行も分母に含める。
応答なしを「候補0件の正常応答」としない。source_policy違反・照合不一致を緩和しない。
URL再発見とSHA重複は区別する。確定subjectは検索意図や名前一致だけでは数えない。
台帳のrunning/preparedが残る場合は未完了として扱い、成功試行だけに分母を絞らない。
Openverse by/by-saは照合済みの選択値と版から測定時に正規化する。SA等の除外は維持する。
供給元枠はCommons API14/HTTP22、Openverse API6/HTTP18を層ごとに固定する。
通信0回の供給元は未測定と明記する。1万Asset行枠と適格SHA1万枚は区別し、
層・供給元ごとの要求当たり適格SHAと取得byteを用いた参考外挿の仮定を併記する。

既存保存データの削除・移行、新規依存、権利条件や集中上限の変更はない。
実測表と試行証跡は[測定結果](../bench/issue77/stage2-results.md)と[機械可読値](../bench/issue77/stage2-summary.json)を参照する。

### 12層・供給元別の実測

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


### 段階目標への参考外挿

開始時N0=7607、固定snapshotの代表SHA E0=1618。1万行枠の残りは2393行であり、全て適格でも楽観上限は4011枚。
この1万Asset行枠から適格SHA1万枚への到達を主張しない。raw/解析/subject・供給元構成・集中枠は別途見積りが必要。
今回配分の観測r=0.05517241適格SHA/API要求。下表は同じ歩留まりが維持するとの感度試算であり、検索深度・供給元・層の枯渇を無視した到達保証ではない。

| 適格SHA目標T | 参考API要求 | 参考取得byte |
|---:|---:|---:|
| 10000 | 151924 | 195534300638 |
| 30000 | 514424 | 662091925638 |
| 100000 | 1783174 | 2295043613138 |

### 固定全量の属性矛盾

保存済みconflictは値がなくても保持する。分母7607 asset行で、building_typeは
inferred461・conflict4・unknown7142、biome_likeはinferred373・conflict2・unknown7232。
これはasset単位のstate集約であり、役割別の補正率・未知率や採用subject数とは分母が異なる。
