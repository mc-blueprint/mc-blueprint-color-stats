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
HTTP 429/503とAPI maxlag/ratelimitedはRetry-After（秒数・HTTP日時）と5秒からの指数待機の
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
JPEG・PNG・WebP・TIFF・GIF・SVGが対象で、それ以外は理由mimeでスキップする。
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
