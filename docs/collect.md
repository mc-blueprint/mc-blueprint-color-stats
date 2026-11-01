# 収集契約

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
Commons固有の正の`maxlag`は`check_commons_policy`が共通検証に加えて検証する。
投入時とアダプターの構築・通信時に適用し、#8等の別ソースにmaxlagは要求しない。
ライセンス名を小文字化して許可リストへ完全一致させる。不明・独自・複合表記・NDはrestricted。
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

取得間隔は前の通信終了から1秒以上、同時接続は1。**同一運用者のCommons収集は全ホストを通して
単一collectワーカーに割り当てる**。複数ワーカーによるレートの共有・分散制御は実装しない。
ジョブ末尾にも残りの間隔を待ち、次のspawnプロセスへ切り替わっても間隔を保つ。
GET・JSON、非対話用`maxlag=5`、連絡先付きBot User-Agentを使用する。
HTTP 429/503とAPI maxlag/ratelimited/cirrussearch-too-busy-errorは
Retry-After（秒数・HTTP日時）と5秒からの指数待機の
長い方を守って最大2回再試行する。最終試行でも待機してから失敗し、キュー側の最大3試行へ返す。
それ以外のHTTP/APIエラー、通信失敗はそのまま試行を失敗させる。
Content-Lengthがある原本は受信サイズを照合し、途中で切れた応答を成功にしない。

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

`OpenverseAdapter` は匿名の Openverse Images API v1 を使用し、認証キーは導入しない。Openverseは認証時に標準・拡張など異なるスロットリング階層を設けている。Commons・Openverseは`collect/http.py`の共通処理で検索・元ページ・原本の取得を直列化する。source_policyの`min_interval`、`retries`（初回を除く回数）、`backoff * 2**attempt`とRetry-After（秒数またはHTTP日時）の長い方を守る。不正なRetry-Afterではbackoffを使用し、最終試行でも待機してから失敗する。Commons固有のmaxlag・ratelimited・cirrussearch-too-busy-errorも同じ待機処理へ渡す。

検索結果の `foreign_landing_url` を `source_url` として保存する。Openverse は第三者サイト上のライセンス情報を保証しないため、元ページのJSON-LDにあるSchema.orgのImageObjectで対象原本URLと一致する`contentUrl`（未指定時は`url`）を探し、その画像の`creator`（未指定時は`author`）と`license`を照合する。作者名は前後空白・大文字小文字を除いて完全一致、ライセンスはAPIの識別子・版から決まるCreative Commons URLとAPI・元ページの両URLの完全一致を必要とする。HTTP/HTTPSと末尾スラッシュだけを同一視し、CC0はpublicdomain/zero、PDMはpublicdomain/markを使う。

同一原本のImageObjectに矛盾がある場合、画像との対応・作者・識別子・版・URLが判別できない場合、未対応の構造化形式では取得しない。ページ全体の文字列や別画像・ページ自体のライセンスは根拠にしない。未確認候補は`metadata.source_verification.status=review`、確認済みは`verified`とし、確認方法も残す。除外理由`source_license_or_author_unverified`はログとrun.parameters.skippedへ記録し、未確認候補をsource・assetへ登録しない。DBのlicense_classや共有Candidate型は変更しない。許可ライセンスは CC0、PDM、CC BY、CC BY-SA に限定する。元画像URLは `original_url` に保持し、Commons 由来の同一画像でも出典ページを区別する。

照合には標準ライブラリのHTMLParser・json・urllibを使用する。既存の依存にはHTML・JSON-LD抽出機能がなく、必要なImageObjectの読み取りだけで足りるため依存は追加しない。対応する構造化データの意味は[ImageObject](https://schema.org/ImageObject)と[license](https://schema.org/license)に従う。参照解決や任意のJSON-LDコンテキスト展開は行わず、確認できない形式はreviewへ回す。

認証・スロットリング階層: [Authentication and Throttling](https://docs.openverse.org/api/reference/authentication_and_throttling.html)。個別作品のライセンス情報の非保証: [Openverse API利用例と注意](https://docs.openverse.org/api/reference/made_with_ov.html)。規約はレート制限遵守、適切な帰属、ホスティング元の条件遵守、および元サイトでの権利確認を利用者に求める: [Openverse Terms of Service](https://github.com/WordPress/openverse/blob/main/documentation/terms_of_service.md)。匿名アクセス先は[Openverse Images API v1](https://api.openverse.org/v1/images/)。

`tests/fixtures/openverse.json`は2026-11-01に匿名APIから`Himeji Castle`を2件取得した記録。テストではこの検索JSONを再生し、元サイト応答はImageObjectの成功・不一致・判別不能を模したHTMLに置き換える。NC・ND・版違い・別画像・同一画像の矛盾を検証し、実DBでも不一致候補がsource・assetへ入らないことを確認する。画像バイト列はfixtureに含めない。

2026-11-02の実API確認では同じ検索を2件に限定して実行し、APIは応答した。
両候補とも元ページで照合根拠を確認できずreviewとして除外し、実画像は取得していない。
確認済み候補の原本取得とHTTP再試行は、記録済み検索JSONとモックの元ページ・原本で検証した。
