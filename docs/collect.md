# 収集契約

## 原本とAPI縮小の比較（Issue #90）

新規収集の既定はCommonsのAPI縮小（長辺1280px）。原本は明示指定できる。

```python
from colorstats.collect import SearchRequest

request = SearchRequest("wikimedia_commons", "castle")
original = SearchRequest("wikimedia_commons", "castle", download_mode="original")
```

`enqueue_collect`の設定ハッシュは取得モードを含む。Candidate末尾の省略可能な
`download_url`と`rendition`以外は原本契約を維持する。原本URLを縮小URLで置き換えない。
Commonsは`imageinfo`へ幅・高さとも1280と`thumbmime`を要求し、返されたURL・実寸・MIMEを使う。
長辺1280以下の原本は`thumbnail_not_smaller`、
URL/寸法/MIME欠落は`thumbnail_missing`、版欠落は`thumbnail_revision_missing`で除外する。
原本への暗黙fallback、任意サイズURLの生成、archive取得は行わない。

`rendition`は`provider/native_id/revision/variant`、要求幅、原本のURL・実寸・MIME・API SHA-1を持つ。
API SHA-1と受信SHA-256は別物で、縮小から原本SHA-256を推測しない。
`Asset.sha256`と`quality.received.sha256`は受信SHA-256、`quality.rendition.original`は原本の情報。
新規jobは原本・縮小とも画像ヘッダーから受信寸法・MIMEを検査する。
通常原本の画素展開は行わず、API値はrendition.originalへ分離して保持する。
原本を取得した場合だけ原本SHA-256が既知になる。API SHA-1がある原本は受信物と照合し、
不一致なら`original_sha1_mismatch`で候補だけを除外して予約を解放し、バッチを継続する。
不一致でも取得件数・byteは計上する。SHA-1欠落の原本は従来どおり扱う。
取得URLと日時もrenditionへ残す。prepはvariantとRGB/LANCZOS/JPEG品質90の変換条件をrunへ記録する。

取得前に既存原本URL・出典URL・provider/native ID＋revisionを照合し、bias予約にはvariantも含める。
Wikimedia原本URLの追跡query違いも同じ元画像として扱う。登録時も排他して再照合し、
縮小を含む同じ原画像の組や同じnative ID＋revision＋variantの再投入は、
既存assetを参照して`rendition_reused`へ記録する。
別variantのSHA一致や確定subjectは捏造せず、pHashも従来どおり候補だけに使う。
この収集経路から解像度違いの独立asset支持を増やさず、既存asset/raw/runを更新しない。
計測のSHA重複・新規判定には受信SHAを使い、再利用した既存assetのSHAへ置き換えない。

公式[移行告知](https://meta.wikimedia.org/wiki/Tech/News/2026/36)に従い
`thumb.wikimedia.org`もmediaとして登録する。`rate_group: upload.wikimedia.org`によって
原本hostと同じ同時枠・待機・25Mbps/10秒帯域窓を共有し、計測台帳復元でも両hostを合算する。
イベントのhostは実接続先を保持する。同時process間の原子的な共有予約は#91の担当。
UA、既定の画像間隔1秒、license_rules/rights_reviewは変更しない。

比較手順・固定100枠・失敗/未評価を含む分母は`bench/issue90/results.md`とJSONを参照。
原本・縮小のSHA不一致を「重複なし」としない。色距離、主要/細部分割の一致度、
品質フラグ反転は観測値であり採用閾値ではない。人手正解がない入力のIoUは未評価とする。
品質許容差・最低実解像度・既定切替は以下の#109で確定した。

## 閾値付きの縮小既定（Issue #109）

2026-11-05のユーザー決定に従い、新規jobの`quality_policy`へ次を固定する。
主色OKLab距離の平均は0.02以下、主要部位一致は0.85以上、最低実解像度は長辺1280px。
原本・縮小とも受信実寸が最低値未満なら`below_min_resolution`として除外する。
原本の受信寸法とAPI寸法が一致しなければ`original_dimensions_mismatch`を優先して記録する。
ヘッダー検査のPillow上限は`received_header_image_limit`、読取り不能は
`received_header_unreadable`として候補単位で除外・予約解放し、同バッチの先行取得を保持して続行する。
通常の原本取得では画素を展開しない。既存job・asset・raw・runの一括更新はしない。
APIの幅・高さ1280は要求値であり、CDNのサイズ段階により受信長辺が1280を超える場合がある。
採用可否と解析はAPIの表示寸法と区別した受信実寸で記録する。
Openverse・LoC・Mapillaryは各ソースの既存方式を保つ（縮小APIを共通に仮定しない）。
共通の最低実解像度は適用する。LoC・Mapillaryの無効化と権利・認証の停止条件は維持する。

縮小版の品質判定はprepの既存検査を再利用する。`watermark_suspected`・`blur_suspected`・
`collage_suspected`のいずれかがtrueなら、登録取引で`review` jobを明示予約する。
`original_review_jobs`へjob ID・理由・元variant、job payloadへ元asset ID・収集run ID・
原本候補とrevisionを残す。workerには`--handler review=colorstats.collect.quality`を追加する。
通常collectのhandlerは従来どおりstageまたはbiasを使う。

再判定jobは固定原本URLを取得し、#90のSHA-1照合、現行source停止・削除停止、
#89のinterval・Retry-After・rate_groupを適用する。測定job由来なら同じ測定IDの通信枠・
media台帳も使用し、再試行分も枠へ含める。新たな検索やarchive取得、暗黙fallbackはしない。
結果は元assetへ書き戻さず新規review runの不変出力と`original_results`へ保存する。
原本でも対象フラグが残れば`rejected`、すべて消えれば`accepted`。
最低実解像度・SHA-1不一致・HTTP除外・枠停止で結果がなければ`unevaluated`として理由を残す。
専用の原本再判定でPillow上限に達した場合も`original_quality_image_limit`の理由付き未評価とし、
検査不能なら`original_quality_unreadable`とする。原本取得バッチ全体の失敗にはしない。
これは機械的な品質再判定であり、人手確認済み・統計採用済みを意味しない。
元画像を別assetとして増やさず、同一画像の支持数を水増ししない。

対応解析後の監査は#90の`comparison.json`形式（各行の`comparison`）を使う。
`colorstats.collect.quality.enqueue_audit(queue, comparison_path, output_path, code_version=...)`
で入力SHA-256・閾値を固定したreview jobを投入する。同じquality handlerが監査JSONと
run.parameters.auditを新規に記録する。主色距離は組の平均、主要部位は全主要ラベルの
intersection/unionの合算比。閾値超過は`warning`とログ、欠測は`unevaluated`数を残す。
比較組または主要部位の有効unionがなければ合格とはしない。人手正解に対するIoUとは区別する。
監査のためのモデル実行や原本の一律再取得は自動では行わない。
根拠と実取得・検証結果は`bench/issue109/results.md`を参照。
reviewもcollect/prepと同じraw媒体停止マーカー・媒体欠落の検査を受ける。

## 追加収集の測定（Issue #77）

`bench/issue77/plan.md` と `targets.yaml` が測定前に固定した条件。
任意の `measurement` 設定（id、api_requests_per_stratum、http_requests_per_stratum）を
持つbiasジョブだけが測定対象になる。通信枠は層ごと・両provider合算・再試行込みで予約する。
`measurement.providers` で供給元別のAPI/HTTP枠を固定でき、合計は層枠を超えない。
リダイレクト先も要求前に同じ枠・待機・User-Agentを適用する。
`commons_categories` はCommons限定のカテゴリ内検索を追加し、通常検索と同じ継続を使う。
既存設定の枠・作者完全照合・source_policyは維持する。

`bias_cli report --measurement-id <ID>` は検索履歴と失敗を含む全試行を層別に出力する。
試行runのstateはrunning、prepared、stopped、failed、committed。上限停止は取得済み分を
確定するcollect runとstop_reasonを残す。通信前の停止なら空のcollect runとなる。
画像登録の完了前に台帳を成功実績へ数えず、通信量は失敗後も残す。
`stage.prepare(..., observer=...)` は測定イベントを呼び出す。callbackの例外は一時出力を清掃し
伝播する。observerを省略すれば従来の呼出し契約になる。
新規SHAは全既存Assetと直列比較し、適格判定には#74の`stats.licenses.exclusion_reasons`を使う。
Openverse by/by-saは照合済みの選択値と版から測定時だけ正規化し、SA等の除外を維持する。
測定予約のattributes内の`_original_url`で未確定候補も原本URLを照合する。
この予約用キーはAssetの検索意図へ転記しない。
上限停止では取得成功分を保持し、途中失敗でも条件・候補・除外理由と受信済み継続位置を残す。
確定subjectの報告には後続#72のconfirmed根拠を要求する。測定時点で未同定なら0件として残す。

Issue #7。後続 #8 はアダプターを追加し、#9 は検索リクエストを計画・投入する。
DBスキーマ、ジョブキュー、論理保存先は変更しない。

## 共有API

`src/colorstats/collect/__init__.py` が正本。各型はdataclassで、
`dataclasses.asdict` によってJSON辞書へ変換できる。

| 型 | 契約 |
| --- | --- |
| `SearchRequest` | `provider`、`query`、`language`、0始まりの`page`、任意の`offset`、`limit`（1〜10）、任意の層識別子`stratum`。`offset`を優先し、省略時は`page * limit`。provider名はCommonsが`wikimedia_commons`、#8は`openverse`を使用する |
| `Candidate` | 出典ページ`source_url`と原本`original_url`、検索全体の0始まり`rank`、要求の`page`、タイトル・作者・ライセンス名とURL・説明・地点・解像度・MIME・取得時メタデータ。`attribution`はアダプターが構成した帰属表示、`exclusion_reason`は原本取得を許可できない理由（許可時None）。任意文字列は未取得ならNone。`metadata`はJSON値だけを含む |
| `SearchResult` | `candidates`、実効API条件`parameters`、継続位置`next_offset`。終端はNone。欠落・非画像を除いても順位を詰め直さない |
| `Adapter` | `search(request) -> SearchResult`、`download(candidate, target) -> None`。前者は検索とメタデータまで、後者は指定された試行専用パスへ原本を書く。禁止ソース・restrictedの取得を通信前に拒否。通信・APIエラーを呼出し元へ送出する |

1リクエストは1ページだけを扱い、自動巡回・層選択・目標件数判定はしない。
#9は返された`next_offset`を次のリクエストへ指定し、`page`も計画上のページとして更新する。
言語はCommonsのUIとメタデータの指定であり、全文検索をその言語に限定するものではない。
Openverseのページ方式との差は#8のアダプターが実効条件へ記録する。

`prepare(claim, *, decide=None)`は許可候補ごとに原本取得直前に
`decide(request, candidate)`を検索順に呼ぶ。戻り値Noneで採用、理由文字列で除外し、
理由・出典URL・元の順位をログとrun.parameters.skippedへ残す。省略時は全許可候補を採用する。
restricted・帰属不足・非対応MIMEの候補はdecideへ渡さず除外する。
#9は専用ハンドラーのprepareからこの引数を渡し、層判定・作者等の集中上限を実装する。
状態を持つ判断関数で同じバッチ内の採用予約を反映できる。別ジョブとの排他や失敗時の予約解放は
呼出し側の責務であり、関数自体をジョブpayloadにシリアライズしない。
判断関数の例外は呼出し元へ伝播し、その試行の一時原本を清掃する。

## source_policyとCommons

`configs/source_policy.yaml` の`sources`からprovider名で読み、有効な設定がないソースは拒否する。
共通の`check_policy`は`enabled`、連絡先付き`user_agent`、`min_interval`、`retries`、`backoff`、
帰属表示`attribution`、再配布条件`redistribution`、`license_rules`を検証する。
`hosts`は接続先ドメイン suffix と区分（`api`/`page`/`media`）の許可表であり、未登録先と
未登録先へのredirectは通信前に拒否する。秘密query parameterは測定observerへ渡す前に除去する。
APIのrolling枠、API/mediaの待機間隔、mediaの10秒転送量はprovider policyに固定する。
Commons固有の正の`maxlag`は`check_commons_policy`が共通検証に加えて検証する。
投入時とアダプターの構築・通信時に適用し、#8等の別ソースにmaxlagは要求しない。
ライセンス名を小文字化して許可リストへ完全一致させる。解析専用の明示確認がない
不明・独自・複合表記・NDはrestricted（解析専用の確認契約は本書末尾）。
Commonsの`extmetadata.License`を使い、作者は`Artist`から取得する（投稿者を作者と見なさない）。
複数ライセンス画像もCommonsMetadataが選択したライセンスを採用する。
asset.quality.metadata.license_selectionに選択方法・選択値と、カテゴリから取得できた
CC系・CC0・PD系・GFDL系の候補根拠を保存する。`prop=categories`の継続分も読み、
全カテゴリの元情報をmetadata.categoriesへ残す。これは全利用条件の網羅や独自ライセンスの
自動解析を保証する一覧ではなく、候補が空でも多重ライセンスでないとは判定しない。
既定はCC0・PD・確認したバージョンのCC BY/BY-SAのみopenとして取得する。
他ソース向けにはnoncommercialとacademic_onlyの規則も指定できる。
restricted原本は取得せず、理由と元の順位をrun.parametersへ残す。

帰属表示はHTMLをテキスト化した`Attribution`を優先し、なければ`Artist`と`Credit`を使う。
その後に出典ページURL・`LicenseShortName`（なければLicense）・ライセンスURL・
「原本・改変なし」を` | `で連結し、source.attributionとasset.quality.attributionへ保存する。
CC BY/BY-SA、または`AttributionRequired=true`では作者か指定帰属、LicenseShortName、
LicenseUrlが必須。不足時は`missing_attribution:<不足フィールド>`で原本取得前に除外し、
ログとrun.parameters.skippedへ保存する。downloadを直接呼んでも拒否する。
CC BY系はフラグ欠落・falseでも必須情報を確認する。PD・CC0はフラグがtrueでなければ
これらの帰属情報の欠落だけでは除外しない。

検索はnamespace 6の`list=search`で`srwhat=text`・`srqiprofile=classic`・`srsort=relevance`を
明示する。実効条件には送信パラメーター、エンドポイント、API名とformatversion、
未指定のinterwiki・検索語自動修正がfalseであること、順位の起算0・検索全体の
`sroffset + index`、要求pageの起算0を保存する。API既定の非順位情報srprop/srinfoは保存対象外。
各候補のメタデータは`prop=imageinfo|categories`で取得する。
高負荷なextmetadataは1件ずつ要求する。原本URLには縮小画像URLを使わない。
HTMLを含む作者・説明はテキスト化し、元のimageinfoもasset.quality.metadataへ保存する。
撮影地点はGPS座標を優先し、なければLocation、双方なければNone。

Commons Action APIは同時接続1、1秒未満の応答後は0.5秒以上、1秒を超える応答後は5秒待つ。
policyのAPI rolling枠は1分199要求未満、`maxlag`・429/503・Retry-Afterと指数待機を適用する。
Wikimedia mediaは実host `upload.wikimedia.org` ごとに同時接続2、要求間1秒以上、
10秒窓31,250,000 byteまでに制限する。Openverse匿名APIは実host `api.openverse.org` の
rolling 5/hour・100/day枠を適用し、計測DBの直近request ledgerから再起動後も消費を復元する。
短周期interval・backoffは同一プロセス内のhost stateを共有する。media byte窓は
measurement runごとにhost・byte・取得時刻をDB台帳へ記録し、spawnされた次のjobが直近10秒分を復元する。
同じprocess内でもhost stateを共有する。API/mediaの
区分と枠はproviderや呼出し側の指定よりredirect後の実host policyを優先する。ジョブ末尾にも
残りの待機を完了してから次のspawnへ進む。短周期interval・backoffの複数process間共有は#91のDB共有予約まで行わない。
GET・JSON、非対話用`maxlag=5`、連絡先付きBot User-Agentを使用する。
HTTP 429/503とAPI maxlag/ratelimited/cirrussearch-too-busy-errorは
Retry-After（秒数・HTTP日時）と5秒からの指数待機の
長い方を守って最大2回再試行する。最終試行でも待機してから失敗し、キュー側の最大3試行へ返す。
それ以外のHTTP/APIエラー、通信失敗はそのまま試行を失敗させる。
Content-Lengthがある原本は受信サイズを照合し、途中で切れた応答を成功にしない。

2026-11-05のユーザー判断により、Commons Action APIは
[Robot policyのAction API rules節](https://wikitech.wikimedia.org/wiki/Robot_policy#Action_API_rules)と
[Rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)の識別User-Agent枠
（200 req/min）に従って利用する。Robot policy自身が`/w/api.php`を例示し、未認証では同時1・
5 req/s未満、1秒を超える要求の後は5秒待機、batch推奨の条件を定めていることを根拠として、
[Commons robots.txt](https://commons.wikimedia.org/robots.txt)の`Disallow: /w/`を踏まえて
Action API利用を継続するのが、このユーザー判断である。
Robot policyとRate limitsは2026-11-05に取得し、両URLのHTTP 200を確認した。
確認日時・本文hashは`bench/issue104/rights-url-verification.json`に記録し、
確認記録は`issue104-v2`とする。HTMLの動的ページは巡回せず、
`upload.wikimedia.org`では`/archive/`を巡回しない。source_policyの`disallow_paths`により、
直接URLとredirect先のどちらも通信前に拒否する。

`upload.wikimedia.org`にはproviderではなく接続先hostの制限を適用する。Wikimediaの25 Mbps/10秒窓は31,250,000 byte/10秒、同時要求2、要求間隔1秒として設定し、`/archive/`は取得対象外とする。帯域窓と長周期API枠は計測台帳から復元する。短周期interval・backoffの複数process間共有は#91の対象とする。

2026-11-01に確認した一次情報:

- [API利用ガイドライン](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines)：負荷制限の指示、コンテンツのライセンス、運用者単位の節度を守る。
- [User-Agentポリシー](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy)：アプリ名・版・連絡先を識別できる値を送る。
- [API Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)：直列取得、maxlagを推奨。読み取りの固定上限は示していないため、1秒間隔は本プロジェクトの自主制限。
- [Commons再利用条件](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia)：ファイルごとの作者・ライセンス条件と帰属を保存する。再配布は個別ライセンスに従い、統計パックに画像は含めない。
- [Search](https://www.mediawiki.org/wiki/API:Search)、[Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)：検索位置と原本・拡張メタデータのパラメーター。

導入済みPyYAML・SQLAlchemyとPython標準のurllib、hashlib、HTMLParserで要件を満たす。
HTTP専用依存や外部収集フレームワークを追加せず、キューの既存再試行・所有権管理を使う。

## 投入と保存

```python
from pathlib import Path
from sqlalchemy import create_engine
from colorstats.collect import SearchRequest
from colorstats.collect.stage import enqueue_collect
from colorstats.queue import Queue

# 接続URLは秘密情報をログへ出さない方法で取得する。
queue = Queue(create_engine(database_url))
job_id = enqueue_collect(
    queue,
    SearchRequest("wikimedia_commons", "姫路城", language="ja", limit=1, stratum="japan-castle"),
    policy_path=Path("configs/source_policy.yaml"),
    storage_config=Path("configs/storage.yaml"),
    host="windows", domain="real_building", code_version="使用commit",
    taxonomy_version="0.1.0",
)
```

```sh
uv run python -m colorstats.queue --handler collect=colorstats.collect.stage --stop-file data/collect.stop
```

投入時に検索・層・ポリシー内容・保存先設定の内容ハッシュ・コード版などを含めたSHA-256で
ジョブキーを作る。ポリシーはpayloadへ固定し、後から設定を変えても投入済みジョブは変えない。
緊急停止はstop-fileで行い、設定変更後は新しく投入する。保存先設定のファイルはワーカーから
同じ絶対パスで読める必要があり、投入後に変わっていれば取得前に拒否する。

`domain`はreal_buildingかreal_terrain。画像の再分類、subjectとの同定、重複画像の選別は後続Issue。
`prepare`は検索→候補の許可判定→原本取得→SHA-256計算を行う。
rawのハッシュ確定前はURLのハッシュで仮の媒体を選び、確定後に必要なら媒体間コピーを行う。
論理名は`raw/<sha先頭2桁>/<sha>.<MIMEに対応する拡張子>`。
prepが読めるラスター形式のJPEG・PNG・WebP・TIFF・GIFが対象。
SVGなどそれ以外は予約・原本取得前に理由mimeでスキップする。
同一ジョブ内の同内容は出力を共有し、候補ごとの順位・メタデータは保持する。

`Prepared.files`でキューへ渡し、`register`は`run.output_paths[str(target)]`を
asset.storage_pathへ保存する。論理名はasset.quality.logical_pathに残す。
既存キューの契約により実体はハッシュ名を持つ試行固有の不変ディレクトリ内にあり、
単純に論理名を再解決せず成功runの参照を使う。確定済みrawは上書きしない。

sourceは出典URLで共有し、初回の作者・ライセンス・ポリシー・取得日時・帰属表示を保持する。
assetは検索機会ごとに作り、同じ画像でも別検索の選ばれ方を失わない。
assetにはprovider・query・全検索条件（言語、層、ページ、offsetなど）・実効API条件・順位・ページ・
取得日時・収集時タイトル・地点・解像度・ライセンスを保持する。
後日のライセンス・作者変更もasset.qualityの取得時スナップショットに残る。
run.parametersは継続offset、除外理由、登録asset_idsも保持する。
原本取得の4xx（429を除く）は候補単位で除外し、理由・出典URL・順位をskippedへ記録する。
429・503は共通HTTP処理で再試行し、上限到達・その他の5xx・通信失敗はジョブの再試行に任せる。
runのlicense_classはopenのみならopen、非open区分が一種類ならその区分、
noncommercialとacademic_onlyの混在時は保守的にrestrictedとする。
出典・asset・run・job成功はキューの同一取引で確定し、失敗はまとめてロールバックする。
通常の通信失敗では一時原本を清掃する。強制終了・所有権喪失・DB失敗の未参照ファイルは
[キュー契約](queue.md)の清掃手順に従う。

## 検証

`tests/fixtures/commons.json`は2026-11-01の検索・imageinfoレスポンス。
対象は[Martin Falbisonerによる姫路城の写真](https://commons.wikimedia.org/wiki/File:Himeji_Castle,_November_2016_-02.jpg)、
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0)。原本はfixtureに含めない。
テストはこのレスポンスを再生し、原本バイト列のみテスト値へ置き換える。
禁止ライセンス・欠落原本・レート制限のレスポンスはこの記録を元に変更して障害注入する。
`commons-multilicense.json`は2026-11-01に同じAPIから記録した
[Dilution-concentration simple example.jpg](https://commons.wikimedia.org/wiki/File:Dilution-concentration_simple_example.jpg)
の応答。CommonsMetadataの選択はPDで、CC BY-SAとGFDLのカテゴリ候補も含む。
この選択を許可し候補根拠を保持すること、カテゴリの継続取得、帰属不足・採否境界も検証する。
帰属の優先順位は[CommonsMetadata仕様](https://www.mediawiki.org/wiki/Extension:CommonsMetadata#Returned_data)、
複数ライセンスの選択は[公式実装](https://github.com/wikimedia/mediawiki-extensions-CommonsMetadata/blob/master/src/DataCollector.php)に従う。
DBテストはTEST_DATABASE_URLの専用schemaを使用し、実通信なしでキュー確定とspawnも確認する。

手動実取得は`uv run python scripts/check-collect.py`。1件のみローカルの一時rawへ保存し、
作者・ライセンス・サイズ・ハッシュを表示して自動清掃する。fixtureを更新する場合だけ
`--record-fixture`を付ける。ubuntu-1停止中もリモート保存・転送はしない。

## Openverse

`OpenverseAdapter` は匿名の Openverse Images API v1 を使用し、認証キーは導入しない。Openverseは認証時に標準・拡張など異なるスロットリング階層を設けている。Commons・Openverseは`collect/http.py`で検索・元ページ・原本を直列取得する。各測定runはAPI/page/mediaの応答時間、通常待機、backoff、media帯域待機、受信byteを記録する。`database_timing`はadvisory lock取得、Meter内トランザクション処理、flush後のcommit完了までの各実時間を分けて記録する。`elapsed_seconds`はrun開始から最終計測更新までのmonotonic時間。自己計測の再帰を避けるため、最後の計測値を書き込むトランザクション自体は集計外とする。

検索結果の `foreign_landing_url` を `source_url` として保存する。Openverse は第三者サイト上のライセンス情報を保証しないため、元ページのJSON-LDにあるSchema.orgのImageObjectで対象原本URLと一致する`contentUrl`（未指定時は`url`）を探し、その画像の`creator`（未指定時は`author`）と`license`を照合する。作者名は前後空白・大文字小文字を除いて完全一致、ライセンスはAPIの識別子・版から決まるCreative Commons URLとAPI・元ページの両URLの完全一致を必要とする。HTTP/HTTPSと末尾スラッシュだけを同一視し、CC0はpublicdomain/zero、PDMはpublicdomain/markを使う。

同一原本のImageObjectに矛盾がある場合、画像との対応・作者・識別子・版・URLが判別できない場合、未対応の構造化形式では取得しない。ページ全体の文字列や別画像・ページ自体のライセンスは根拠にしない。未確認候補は`metadata.source_verification.status=review`、確認済みは`verified`とし、確認方法も残す。除外理由`source_license_or_author_unverified`はログとrun.parameters.skippedへ記録し、未確認候補をsource・assetへ登録しない。DBのlicense_classや共有Candidate型は変更しない。許可ライセンスは CC0、PDM、CC BY、CC BY-SA に限定する。元画像URLは `original_url` に保持し、Commons 由来の同一画像でも出典ページを区別する。

照合には標準ライブラリのHTMLParser・json・urllibを使用する。既存の依存にはHTML・JSON-LD抽出機能がなく、必要なImageObjectの読み取りだけで足りるため依存は追加しない。対応する構造化データの意味は[ImageObject](https://schema.org/ImageObject)と[license](https://schema.org/license)に従う。参照解決や任意のJSON-LDコンテキスト展開は行わず、確認できない形式はreviewへ回す。

認証・スロットリング階層: [Authentication and Throttling](https://docs.openverse.org/api/reference/authentication_and_throttling.html)。個別作品のライセンス情報の非保証: [Openverse API利用例と注意](https://docs.openverse.org/api/reference/made_with_ov.html)。規約はレート制限遵守、適切な帰属、ホスティング元の条件遵守、および元サイトでの権利確認を利用者に求める: [Openverse Terms of Service](https://github.com/WordPress/openverse/blob/main/documentation/terms_of_service.md)。匿名アクセス先は[Openverse Images API v1](https://api.openverse.org/v1/images/)。

`tests/fixtures/openverse.json`は2026-11-01に匿名APIから`Himeji Castle`を2件取得した記録。テストではこの検索JSONを再生し、元サイト応答はImageObjectの成功・不一致・判別不能を模したHTMLに置き換える。NC・ND・版違い・別画像・同一画像の矛盾を検証し、実DBでも不一致候補がsource・assetへ入らないことを確認する。画像バイト列はfixtureに含めない。

2026-11-02の実API確認では同じ検索を2件に限定して実行し、APIは応答した。
両候補とも元ページで照合根拠を確認できずreviewとして除外し、実画像は取得していない。
確認済み候補の原本取得とHTTP再試行は、記録済み検索JSONとモックの元ページ・原本で検証した。

#### 2026-11-02の不通再調査（Issue #43）

初回調査ではubuntu-1（pilotと同じホスト）のDNS解決、IPv4/IPv6のTCP接続、TLS 1.3と証明書検証が成功した。匿名の`HEAD https://api.openverse.org/v1/`はHTTP 200だったが、Cloudflareキャッシュ（`age: 144942`）の応答だった。検索GETはTLS確立・送信後に応答待ちになった。

続いて02:50〜02:58 UTCにWindows・ubuntu-1・ubuntu-2から匿名GETを比較した。基準URLは次のとおりで、User-Agentは`configs/source_policy.yaml`の値を使用した。ホストごとの比較要求は再試行せず直列に送り、比較スクリプト内では各要求後に4秒待機した。アダプターの実測は既存の直列化・待機処理を使用した。全体でも観測した20回/分の匿名枠を下回り、429は観測しなかった。

```text
https://api.openverse.org/v1/images/?q=Himeji+Castle&page=1&page_size=2&license=cc0%2Cpdm%2Cby%2Cby-sa&mature=false
```

| 比較 | 結果 |
| --- | --- |
| 基準URL、IPv4・HTTP/1.1 | Windows 0.290秒、ubuntu-1 0.111秒、ubuntu-2 0.107秒でHTTP 200。ubuntuの応答JSONは候補2件・result_count 240 |
| ubuntu-2、UAを`curl/8.5.0`に変更 | HTTP 200、0.056秒、同じ2件 |
| ubuntu-2、page_sizeのみ1に変更 | HTTP 200、0.062秒、候補1件 |
| ubuntu-2、qのみ`castle`に変更 | 25秒でタイムアウト、HTTPヘッダー・本文なし。ubuntu-1でも同じ |
| license・matureを省略 | Windows・ubuntu-2とも25秒でタイムアウト、HTTPヘッダー・本文なし |
| ubuntu-2、license・matureの代わりに`license_type=commercial` | 25秒でタイムアウト、HTTPヘッダー・本文なし |
| 基準URL、IPv6・HTTP/1.1 | Windows 0.089秒、ubuntu-2 0.105秒でHTTP 200 |
| 基準URL、ubuntu-2・IPv4・HTTP/2 | HTTP 200、0.059秒（実際の応答もHTTP/2） |
| license・mature省略URL、ubuntu-2でHTTP/2またはIPv6 | どちらも25秒でタイムアウト。HTTP/2の試行は応答がなく、応答プロトコルは未確認 |
| license・mature省略URL、Windowsで最大140秒待機 | TLSは0.095秒で確立。60.824秒でHTTP 504、本文`error code: 504`、`Server: cloudflare`、`CF-RAY: a53fdd962b6e262a-NRT` |

WindowsのcurlはHTTP/2非対応だったため、HTTP/2比較には対応済みのubuntu-2のcurlを使用した。成功した検索はすべて`cf-cache-status: HIT`で、2件検索の`Age`は62316〜62631秒だった。ホスト・UA・IP・HTTP方式を変えても同じ`x-request-id: 71956186-3066-4ab2-b987-f0cf5e86d04e`を返した。匿名枠ヘッダーの20/min・残19、200/day・残199もキャッシュされた値なので、現在の残数や上流の健全性を示すものとして扱わない。

観測された直接原因は検索応答待ちである。約61秒後の504は、既存`HttpClient`の60秒の読取り制限より遅く、アダプター側の`TimeoutError`を説明できる。キャッシュHITは応答し、別URLはCloudflare経由のGateway Timeoutになることから、キャッシュで返せない要求の上流応答に問題があると推定する。Openverse内の検索処理・その手前のゲートウェイ・Cloudflareから上流への経路のどこが根本原因かまでは確定できない。3ホストは同じ拠点内にあり、独立した外部回線での比較は未実施である。

公式[APIページ](https://api.openverse.org/v1/)が参照する[現行OpenAPIスキーマ](https://api.openverse.org/v1/schema/)と照合した。`q`、1始まりの`page`、`page_size`、カンマ区切りの`license`、booleanの`mature`は既存実装と一致する。検索のsecurityには認証なしの選択肢があり、認証の説明も匿名利用を認め、制限超過を429と説明している。[認証階層の説明](https://docs.openverse.org/api/reference/authentication_and_throttling.html)では認証でstandard枠を利用でき、enhanced枠は個別付与となる。APIキー不足を示す401/403や429は今回の直接通信で観測せず、匿名キャッシュHITは取得できた。認証が障害を解消する根拠はなく、登録・認証GETは行っていない。

対処はOpenverseを収集対象から外した現在の設定を維持し、時間を置いて層別GETの復旧を確認すること。タイムアウト延長だけでは504まで待つことになり、UA変更・IP固定・HTTP/2化・照合緩和を採用する根拠もなかったため、アダプターは変更しない。認証比較をユーザーが選ぶ場合は、公式APIの`auth`節に従って`/v1/auth_tokens/register/`で登録し、`/v1/auth_tokens/token/`でトークンを得てBearer認証で比較する。秘密はログ・Gitへ記録せず、認証対応は別途実装が必要となる。

#### 層別実測と照合歩留まり

Python 3.12.15で既存`OpenverseAdapter.search`を各層1回、`page=0`・`limit=2`（API上はpage=1）で実行した。クエリは`configs/collection_targets.yaml`の各層の最初の英語クエリを使用した。検索結果・HTTP記録の保存先は新規作成した`data/issue43-validation-20261102T025234Z/`であり、本番raw・DBは使用していない。

| 層 | クエリ | 検索結果 | 照合成功・除外内訳・原本取得 |
| --- | --- | --- | --- |
| japanese-castle | Japanese castle exterior | 60.141秒で読取りタイムアウト | 応答なしのため未計測 |
| gothic-temple | gothic church exterior | 60.047秒で読取りタイムアウト | 応答なしのため未計測 |
| forest-autumn-day | autumn forest landscape | 60.047秒で読取りタイムアウト | 応答なしのため未計測 |

応答なしを候補0件・歩留まり0%とは扱わない。補助測定として、キャッシュが応答する`Himeji Castle`を同じアダプターで2件検索し、2件とも元ページのHTMLを取得して照合した。照合成功0/2（0%）、`source_license_or_author_unverified`による除外2/2、原本取得0件だった。この2件は既存fixtureと同じ候補で、新規の独立標本ではない。

元ページを再取得してJSON-LDを確認すると、両者とも対象原本URLが一致するImageObjectを1個持ち、CC BY 2.0のURLも一致した。ただし、作者が次のとおり一致せず、前後空白・大文字小文字だけを除く既存の完全照合では除外となる。「照合根拠がない」という先行調査の説明を、今回の具体的な不一致に更新する。

| Flickr画像ID | APIのcreator | 元ページImageObjectのcreator.name | 除外の具体的理由 |
| --- | --- | --- | --- |
| 37899156685 | Dimitry B | Dimitry B. | 末尾ピリオドの差 |
| 214825444 | Freakland - フリークランド | David Sanz | 作者名の差 |

照合を通った候補がなかったため、実画像の検証用保存先への取得は実施できなかった。3層の歩留まり実測と照合済み原本の取得確認は未完了である。再開条件は層別GETが成功すること。その後に候補数・照合結果・除外理由を記録し、照合成功した原本だけを新規検証領域へ1件以上取得して画像形式・サイズ・ハッシュを確認する。本番DBへは登録しない。

#### 検証・証跡

`python -m pytest tests/test_openverse.py tests/test_collect_http.py -q`は60 passed・1 skipped。DB登録テスト1件は`TEST_DATABASE_URL`未設定のためスキップし、DB検証は行っていない。関連するアダプター・共通HTTP実装とそのテストの`ruff check`、`git diff --check`も成功した。実装・公開API・保存形式への変更はなく、追加依存もない。

以下は`C:/Users/ryuma/.codex/logs/commands/`配下の記録。診断スクリプト・スキーマ・実HTML・測定JSONは担当worktreeのGit除外対象`data/`に保全する。

| 内容 | コマンドログ（.jsonl） |
| --- | --- |
| Windows基準GET | `20261102T025024Z-41021ac3f8514c5e8b06de1a9aef1e03` |
| ubuntu-2の8条件比較 | `20261102T025122Z-9f7d57bad1a3436db0ff486cfc142d65` |
| 不通URLのHTTP/2・IPv6比較 | `20261102T025355Z-98724ec0d08343519561ad90dd5dcc0e` |
| Windows不通URL・IPv6比較 | `20261102T025408Z-c0b1e96f4bc440c9b08123ed23ac6f86` |
| ubuntu-1の同時点比較 | `20261102T025539Z-7aecdb705e4b4c478cffc568cf32be38` |
| 3層のアダプター実測 | `20261102T025234Z-4372816b333d4d48bbab7d5f78291e94` |
| 長時間待機での504確認 | `20261102T025621Z-d4caa8040e3a4fa7a58047d3257aaacf` |
| 姫路城2候補のアダプター照合 | `20261102T025634Z-6c8b50bf630d4377b9ce46b05fa49f85` |
| 元ページの作者不一致の確認 | `20261102T025747Z-3096193d399d44ad9e7c24c72e80c5ad` |
| 現行APIスキーマの照合 | `20261102T025532Z-b8563ae4402641c99aa098d4218a6f59` |
| アダプター・共通HTTPテスト | `20261102T025304Z-d2435932adf1460d974852e4837f65c6` |

#### 2026-11-02の再計測（Issue #43）

ubuntu-1から前回と同じ3層のクエリを各1回、`page=1`・`page_size=2`、同じライセンス・mature条件とsource_policyのUser-Agentで直列送信した。要求間は2秒空けた。各要求は約60.8秒後にCloudflare HTTP 504となり、本文はorigin web serverが許容時間内に応答しなかった旨を示した。候補一覧は返らず、候補件数・照合歩留まり・除外理由・原本取得は測定できなかった。APIキーの登録・認証、本番DBへの書込みは行っていない。

| 層 | クエリ | 開始時刻（UTC） | 結果 | CF-RAY |
| --- | --- | --- | --- | --- |
| japanese-castle | Japanese castle exterior | 2026-11-02 06:34:29 | 60.852秒後にHTTP 504 | `a5411d1e3ccf2821-NRT` |
| gothic-temple | gothic church exterior | 2026-11-02 06:35:32 | 60.749秒後にHTTP 504 | `a5411ea6886462b1-NRT` |
| forest-autumn-day | autumn forest landscape | 2026-11-02 06:36:34 | 60.751秒後にHTTP 504 | `a541202ec9082629-NRT` |

再計測でも同じ結果が続いた。照合済み原本の検証用取得は、検索結果が得られないため未実施。再開条件は層別検索が応答することとする。

証跡は`C:/Users/ryuma/.codex/logs/commands/20261102T063428Z-732bd0f9b3b14769acc0be4d0db9d49.jsonl`（SSH実行）と`20261102T063428Z-94564b290bca463084c5753fe43a992d.jsonl`（ubuntu-1側）に記録した。

#### 2026-11-02 13時（UTC）の再計測（Issue #43）

ubuntu-1から3層を各1回、同じ条件で直列に送った。japanese-castleは58.7秒後にHTTP 500、gothic-templeは60.8秒後にHTTP 504、forest-autumn-dayは54.2秒後にHTTP 200（`result_count` 240）だった。続けてWindowsから既存`OpenverseAdapter`で前回と同じ測定スクリプトを実行した（結果は`data/issue43-validation-20261102T134805Z/`）。

| 層 | 検索 | 照合成功 | 除外内訳 | 原本取得 |
| --- | --- | --- | --- | --- |
| japanese-castle | 60.1秒で読取りタイムアウト | 未計測 | 未計測 | なし |
| gothic-temple | 60.0秒で読取りタイムアウト | 未計測 | 未計測 | なし |
| forest-autumn-day | 16.0秒でHTTP 200、2件 | 1/2（50%） | `source_license_or_author_unverified` 1件 | HTTP 403 |

照合に成功したのはFlickrのCC BY 2.0画像（作者Jean-Michel Priaux）だった。原本URL（`live.staticflickr.com`）の取得は、source_policyのUser-Agentで0.4秒後にHTTP 403となった。直後の確認では別のUser-Agent文字列で200が返る場合もあり、拒否の条件（User-Agentの判定か一時的な制限か）は特定していない。宣言したUser-Agentを変えて拒否を回避することはしない。

- 不通の原因：Openverse側のoriginの応答遅延である。同じ層でも、HTTP 200（16〜54秒）、500、504、クライアント側の60秒タイムアウトに分かれ、送信元（Windows・ubuntu-1）やネットワークの条件では説明できない。
- 歩留まり：応答した1層では照合成功は1/2だった。2件だけなので、歩留まりの推定値としては扱わない。
- 原本取得：照合済みの原本1件の取得は、Flickr CDNがHTTP 403で拒否した。

この403は一時的なもので、14時の再計測では同じUser-Agentで取得できた（下記）。

証跡は`C:/Users/ryuma/.codex/logs/commands/20261102T134431Z-e494497330ac4586957fd12b60d4e846.jsonl`（ubuntu-1の検索）と`20261102T134805Z-cd78b6a6015f434ba1aec4cae84efc6e.jsonl`（アダプターの測定）に記録した。

#### 2026-11-02 14時（UTC）の再計測と結論（Issue #43）

同じ測定スクリプトを再実行した（結果は`data/issue43-validation-20261102T140104Z/`）。

| 層 | 検索 | 照合成功 | 除外内訳 | 原本取得 |
| --- | --- | --- | --- | --- |
| japanese-castle | 41.2秒でHTTP 200、2件 | 0/2 | `source_license_or_author_unverified` 2件 | なし |
| gothic-temple | 60.1秒で読取りタイムアウト | 未計測 | 未計測 | なし |
| forest-autumn-day | 0.1秒でHTTP 200、2件 | 1/2 | `source_license_or_author_unverified` 1件 | 成功 |

照合に成功したFlickrのCC BY 2.0画像（作者Jean-Michel Priaux）の原本を、source_policyのUser-Agentで検証用領域へ取得した。JPEG、1023×667、231,387バイト、SHA-256は`dd31521ad45f709068f5ab3a896ebfc5e9a4d8f9acb34e33f51d1ef4051f1924`。本番DBへは登録していない。

- 不通の原因：Openverse側originの応答遅延。同じクエリでも、キャッシュがあれば即時に応答し、なければ数十秒かかって200・500・504・タイムアウトに分かれる。
- 歩留まり：応答した2層の計4件で、照合成功は1件（25%）。除外はすべて元ページとの作者・ライセンスの不一致による。
- 対処：Openverseは応答が不安定なため、補助ソースにとどめ、Commonsを主にする。Openverseを使う場合は、取得間隔を空けたうえで、タイムアウトした層を後で再試行する。作者表記の揺れ（末尾のピリオドなど）を照合で許容するかは、M3の収集方針で決める。

## Library of Congress

`LoCAdapter` は `https://www.loc.gov/collections/john-margolies-roadside-america/` と `/photos/` のJSON経路を実装しているが、現在はCloudflare challenge (403, `Cf-Mitigated: challenge`)を確認したためsource policyで無効。challenge検出時は再試行せず停止し、回避しない。`No known restrictions`をpublic domainやCreative Commonsへ変換しない。候補調査と未承認の一括データ取り込み案は`bench/issue92/results.md`を参照。

このcollectionはJohn Margolies個人による米国沿道商業建築（1969〜2008年）の写真に偏る。[LoCのResearch Guide](https://guides.loc.gov/roadside-america-photographs)は11,710点のカラー35mmスライドと説明している。建築・地形全般の代表標本とはせず、検索語とitem IDを測定記録へ残す。

現行の [LoC JSON API仕様](https://www.loc.gov/apis/json-and-yaml/requests/) はcollection endpointと `fo=json` を文書化している。API制限はJSON 20/min・image 150/minだが、[Legal](https://www.loc.gov/legal/) はアプリへの全機械合計10 req/min以下を推奨するため、APIと画像を同じhost rate groupにまとめて6秒以上の間隔とする。[robots.txt](https://www.loc.gov/robots.txt) は `/search` と `/pictures/search` を禁止し `Crawl-Delay: 5`。確認時の `tile.loc.gov/robots.txt` は404、`cdn.loc.gov/robots.txt` は `/service` と `/master` を禁止し10秒遅延だった。

証跡は`C:/Users/ryuma/.codex/logs/commands/20261102T140104Z-4b7cca7011f04279801936e0012e2053.jsonl`に記録した。

## 解析専用入力（Issue #87）

`license_rules.analysis_only`は元license名の完全一致リスト。既存open/SA/NC/NDを自動変更しない。
`check_policy`と`license_class`は以下の固定policyを検証し、根拠欠落・禁止・失効なら取得前に拒否する。
新ソースの有効化は#88と各アダプターIssue完了後とし、このIssueで有効ソースは増やさない。

| キー | 契約 |
| --- | --- |
| `rights_basis` | `copyright_act_30_4` |
| `rights_review` | `reviewed_at`（タイムゾーン付きISO時刻）、`terms_url`、`api_url`、`robots_url`、`summary`、`reviewer`、`policy_version` |
| `rights_review.purpose / decision` | `non_expressive_color_statistics` / `allowed`。未確認・禁止は許可しない |
| `rights_review.expires_at / revoked` | 任意の統計利用根拠の期限（タイムゾーン付きISO時刻）・失効フラグ |
| `attribution_required` | 真偽値。falseでも台帳を省略しない |
| `access_scope / image_redistribution` | `internal` / false |
| `retention` | 正の日数：`raw_days`=30、`rejected_days`=7、`deletion_request_days`=7、`backup_days`=30。短いソース期限優先 |
| `use_stopped / deletion_requested` | 利用停止・削除受付。source.policyまたはasset.quality.rightsでtrueならD15除外 |

collectは元license/URL/作者（未取得はnull）を保持し、asset.quality.rightsに確認情報を固定する。
同qualityのprovider、original_id（アダプターの一意な出典ページURL）、retrieved_atと、
asset.url/retrieved_atを台帳とする。原サイトのnative IDは従来どおりcandidate.metadataへ保存する。
retention_untilは取得日時＋raw_daysのISO時刻。原画像の保存期限であり統計利用の失効期限ではない。
source.policyは初回の共有情報を保持する。後日のlicense/根拠不一致を無言で書き換えずD15で除外する。
新ソースは取得経路・用途をレビューし、候補の出典と元licenseをアダプター内でも照合する。

`rights.combine_license(*values)`は副作用なしで区分を合成する。異なる非open制約・未知値はrestricted。
`rights.analysis_review_reasons(policy, now=None)`は不足・停止・失効の理由文字列リストを返す。
`stats.licenses.exclusion_reasons(asset, source, runs)`は元権利一致、二経路、全run・全モデルを検査する。
未確認のrestrictedからanalysis_onlyへ落とすフォールバックはない。
## Openverse 登録クライアント（Issue #93）

既定は`auth_mode: anonymous`で、5要求/3600秒・100要求/86400秒を維持します。
credentialの存在でモードを自動変更しません。登録クライアントを使う場合は、
専用policyの`auth_mode`を`standard`にして新しいjobを投入してください。
`standard_api_windows`（100要求/60秒・10,000要求/86400秒）がAPI hostへ適用されます。
policyのモード・credential参照名・上限はpayload/hashへ固定し、既存jobは書き換えません。
enhanced・exemptは選択できません。元ページと画像の照合・禁止hostの停止は共通実装を使います。
Commons画像の縮小既定（#109）も変更しません。

認証は`ops/collect/openverse.conf.example`の2つの`LoadCredential=`で注入します。
実行中は`CREDENTIALS_DIRECTORY/openverse-client-id`と`openverse-client-secret`だけを読みます。
値を環境変数・引数へ入れず、root専用ファイルを直接読んだりコピーしたりしません。
未配置時は匿名設定を維持してください。standardを明示したjobは欠落時に通信前停止します。
このunit例の配置・サービス変更は本変更で実施していません。

標準urllibと既存HttpClientを再利用し、token endpointにだけclient_credentialsをPOSTします。
tokenはメモリ内のみで、有効期限の90%に達すると再取得します。DB枠待機後も再判定します。
BearerはHTTPSのOpenverse images endpointへの直接要求だけに付けます。
登録APIとtoken endpointのredirectは追従せず停止し、登録枠で匿名要求を送りません。
元ページ・画像のredirectでは同hostでも秘密queryを除去します。
401/403・不正token・取得失敗では匿名切替せず停止します。
429/503は共通Retry-After待機を使い、短いbackoffだけで長周期枠を反復消費しません。

standardの本収集は、既存bias収集の`Meter`付き経路に限定します。
台帳のない通常collectは通信前に停止します。同じ運用者のworkerは同じDBを使い、
単一収集unit・同時1で運用してください。token要求も保守的に同じAPI枠へ数えます。
分・日枠は全測定・失敗jobをまたいで同じAPI hostのDB台帳から復元し、
匿名の過去要求も除外しません。上限変更には新job・新測定を使います。
台帳予約はRetry-After・host枠・同時実行枠の待機後、送信直前に行います。
DB枠待機が必要なら予約せず待機し、host枠とtoken期限を再判定します。
観測値にはモード・tier・有効枠だけを加え、client ID/secret/tokenは保存しません。

2026-11-05に[公式認証資料](https://docs.openverse.org/api/reference/authentication_and_throttling.html)と
[公式レート既定](https://github.com/WordPress/openverse/blob/main/api/conf/settings/rest_framework.py)
を確認しました。上記数値は公式コードの既定値で、本番の保証値ではありません。
登録時の提示枠と実応答の確認は認証情報の配置後に必要です。

## Mapillary（Issue #94）

`mapillary`は登録アプリの公開Images APIだけに接続する解析専用アダプターです。
2026-11-05、graph.mapillary.comのrobots.txtが`User-agent: * / Disallow: /`を返しました。
ユーザー決定（2026-11-05）に従い、robotsと規約§5・§11の関係をMapillaryへ確認し、
回答まで`source_policy.yaml`では無効です。Openverse経由を含む全Mapillary hostへの通信を止めます。
実行環境の現行policyは`COLORSTATS_SOURCE_POLICY`、未指定時はcwdの`configs/source_policy.yaml`です。
prepare開始時と各HTTP要求・redirectの送信直前に読み直し、保存済み`enabled: true`より優先します。
現行ファイルの欠落・無効・確認不能時は通信しません。長時間待機後の送信にも停止を適用します。
API文書はログイン画面のため、フィールドと認証は公式Python SDKの実装も参照しています。
Terms of Use（2024-02-15発効）の全文確認はIssue #94のユーザー確認コメントを根拠とします。
§3(b)・5・11・12に従い公開API以外の自動取得、過負荷、再配布、画像配信、
再識別・ぼかし解除は行いません。大量本収集の許可・歩留まりはこの少量確認で保証しません。

認証は収集unitの`LoadCredential=mapillary-client-token:/etc/colorstats/credentials/mapillary-client-token`
で渡します。root専用ファイルを直接読む実装や別認証へのフォールバックはありません。
実行時の`CREDENTIALS_DIRECTORY`からだけ読み、欠落なら通信せず停止します。
`STATE_DIRECTORY`には非公開の専用状態ディレクトリを指定してください。
再開状態はその配下の`mapillary/`に0600で保存します。unit例は`ops/collect/mapillary.conf.example`です。
この例の配置・サービス変更は行っていません。

検索語は任意の文字列検索ではなく、policyの`searches`のキーです。
`kyoto-street-buildings`は京都の小bboxによる道路沿い建築候補の固定意図で、建築の存在・分類は未確認です。
本収集では#105の不足目標に合わせて検索意図とbboxをレビューしてください。
targetsの各層に`mapillary_searches: [kyoto-street-buildings]`を明示した場合だけ先頭ページを生成します。
後続は記録された`next_offset`を使います。cursorを整数へ変換せず、固定条件・limit別に対応を保存し、
未確認offsetと無作為な後続ページは拒否します。状態保存は単一ownerで実行してください。
順位は`request.start + index`であり、API側の時点間ランキングの不変性は保証しません。

候補の`original_url`は署名URLの恒久化を避けるため`https://graph.mapillary.com/<native ID>`という
画像エンティティ識別子です。原本ファイルのダウンロードURLではありません。
公式`thumb_1024_url`だけを取得し、原本へフォールバックしません。
署名付きURLは同じアダプターのメモリ内だけに保持し、候補には全queryを除いたURLを記録します。
失効時は失敗を記録し、同じoffsetを再検索してURLを更新します。
APIへのAuthorizationはHTTPS・標準ポート・graph.mapillary.com・`/images`の完全一致に限定します。
画像CDNと別hostへのredirectにAuthorizationを転送しません。例外にAPI本文や署名queryを含めません。

作者・native ID・sequence・撮影日時・寸法・許可CDNが欠ける候補、人物検出あり、
検出結果未確認・検出結果に継続ありを画像取得前に除外します。
同じ検索条件のページ内・前ページと同sequenceの連写も除外し、subjectは未確定のままです。
作者ID・地域とnative ID/安定URL/受信SHAは既存bias予約・重複契約へ渡します。
pHashは既存prepの補助情報として扱い、独立subjectの自動確定には使いません。
人物検出ゼロはプライバシー確認済みを意味しません。共通の内部確認・人物maskゲートを通す必要があります。

CC BY-SA 4.0の原表記・帰属を保存し、#87の`analysis_only`だけを使います。
30日保持、不採用7日、削除受付時に停止し7日以内、backup残留30日という#88の契約を再利用します。
原画像・縮小画像・CVAT・精密位置は公開せず、配布は既存の非表現的統計ゲートに限定します。
レートはAPI・CDN各同時1、通信終了後2秒、API30要求/60秒、画像5 MB/10秒です。
これは公開上限の断定ではなく、少量検証用の保守的な自主枠です。
公開レート本文は未確認で、2026-11-05のユーザー決定により自主上限で進めます。
CDNのbyte台帳には実hostとrate_groupを記録し、再起動後も別subdomainの同じ共有枠を復元します。
401/403は理由をjobへ記録し、spawnされたworker経由でも1試行でfailedとし自動再試行しません。
429/503はRetry-Afterと60秒以上のbackoffを守ってHTTP内では再試行せず停止します。
通常の負荷制限はキューの既存試行枠に従い、401/403の再試行禁止とは区別します。

実測・未完了条件は`bench/issue94/results.md`を参照してください。
