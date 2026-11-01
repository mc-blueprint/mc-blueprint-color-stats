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

subjectカタログは任意の補助。subject.nameまたは
設定のsubject_aliases（subject.name→別名の文字列配列）が収集タイトルに一意に含まれる
候補にだけsubjectを関連付ける。照合は同じdomain内で行い、英数字の語の途中は一致としない。
例えば日本語名のsubjectに
`subject_aliases: {姫路城: ["Himeji Castle"]}` と指定すれば英語検索も同じsubjectに集約する。
複数subjectに一致または一致しない候補も、subject_id=NULLのまま取得できる。
一般住宅・地形など未同定の対象を除外せず、候補ごとのsubject新設もしない。
カタログの名称・別名は一意な建築・地点を示すよう人が確認しておく。
subjectの画像上限と割合枠は一意に一致した候補だけに適用する。
subject不明は重複を除いたsubject数や目標達成数に算入せず、レポートで件数・割合を出す。
未同定候補が多ければsubject目標が未達でも画像予算で停止する。収集後のsubject推定は後続工程で扱う。

prepも確定subjectを保持し、pHash近似は`subject_candidate`と`asset_duplicate`に留める。
SHA-256完全一致群に確定subjectが一意に存在する場合だけ、未同定assetへ引き継ぐ。
確定値が競合する完全一致群では未同定を保つ。重複クラスタ数はsubject数・網羅率に算入しない。
詳細は[スキーマのprep契約](schema.md#prepの重複同定契約revision-0004)を参照する。

地域の集中枠はsubject.location、候補の撮影地点candidate.location、意図した層のregionの順で決める。
空の値は使わず、どれもなければ不明とする。regionとregion_basisを予約と
asset.search_parameters.collection_biasへ記録する（subject.location / candidate.location /
stratum.region / unknown）。撮影地点は提供された文字列のまま照合し、座標の逆ジオコーディングや
表記の名寄せは行わない。層の地域区分とは粒度が異なる場合があり、実パイロットで確認する。
作者不明・地域不明も採用し、それぞれ不明群として数える。割合上限は既知の値だけにかける。
成功時は任意のasset.subject_idと層・地域の根拠を登録し、元のタイトル・撮影地点・
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
