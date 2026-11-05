# 分類・DBスキーマ初版

Issue #5の対象は分類体系 `0.1.0` とPostgreSQL 16向け初期revision `0001`。
キュー・収集器・解析器・パック生成器は後続Issueで実装する。DB接続のための本番ホスト変更は行わない。

## 採用した既存機能

起点の依存はmc-blueprintのみで、DB管理と分類検証の既存実装はなかった。
SQLAlchemy 2.0の宣言的モデルで列・外部キー・制約を共有し、同じSQLAlchemyメタデータを扱えるAlembicでrevision管理と接続なしのSQL生成を行う。
psycopg 3をPostgreSQLドライバーにする。生SQL＋独自revision管理は差分検出・履歴管理を再実装するため採用しない。SQLiteは分散ライターとJSONBという要件に合わない。
YAML読取りにはPyYAMLのSafeLoader、構造検証にはjsonschemaのDraft202012Validatorを用いる。既存機能で扱えない文書間参照だけを小さなローダーで検証する。
DBサーバー以外のサービス追加は不要。追加依存のライセンスはSQLAlchemy・Alembic・PyYAML・jsonschemaがMIT、psycopgがLGPL-3.0-only（binary同梱物には別ライセンスもある）。公開成果物は統計JSONで、ドライバーや画像を同梱しない。依存の更新は `uv.lock` で固定する。

一次情報:
[SQLAlchemyの宣言的モデル](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html)、
[AlembicのSQL生成](https://alembic.sqlalchemy.org/en/latest/offline.html)、
[jsonschemaの検証API](https://python-jsonschema.readthedocs.io/en/stable/validate/)、
[psycopgのライセンス](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt)、
[SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE)・
[Alembic](https://github.com/sqlalchemy/alembic/blob/main/LICENSE)・
[PyYAML](https://github.com/yaml/pyyaml/blob/main/LICENSE)・
[jsonschema](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING)のライセンス。

## モデルと後続処理の契約

公開モデルは `colorstats.schema.models`。UUID主キーはSQLAlchemyのINSERT時に生成する。
直接SQLで挿入する場合はUUIDを明示する。日時はタイムゾーン付き、ハッシュはSHA-256の16進文字列。
外部キーは削除を連鎖させず、由来が参照されるレコードの削除を拒否する。

| 表 | 責務・主なデータ |
| --- | --- |
| source | 出典ページURL（一意）、サイト、作者、ライセンス表記・区分、帰属、取得日時、サイト別policyのスナップショット |
| asset | 取得イベントごとの出典、任意の確定subject、収集時のタイトル・撮影地点、原本URL・SHA-256・pHash・寸法・論理保存先、domain、license_class、品質、分類版・シーン属性、選ばれ方 |
| subject | 同一建築・場所・作品の集約単位。domain、地域・年代、分類版・シーン属性。画像数と独立subject数を分けて集計する |
| subject_candidate | assetのsubject候補と信頼度・根拠。候補があっても確定するまではasset.subject_idをNULLに保つ。確定済みassetの競合候補・同定根拠も保持する |
| asset_duplicate | subjectと独立した画像重複の辺。UUID昇順のasset_a・asset_bを複合主キーにし、sha256完全一致またはphash近似と信頼度を保存する |
| processing_run | stage、モデル・重みハッシュ・license_class、設定ハッシュ・パラメーター、コード版・分類版、ノード、開始・終了日時・失敗理由 |
| processing_run_input | 解析・集計runが使用した入力runの有向関係。複数モデル工程のライセンス由来を失わないための補助表 |
| region | assetと生成run、分類版・第2階層部位または地形ラベル、instance_id、マスク論理参照、bbox、面積比・信頼度、正規化高さ、面方向・地形属性、label_source |
| color_observation | assetまたはregionと生成run、観測OKLab、任意の素材OKLabと信頼度、面積比。補正しない場合は素材色と信頼度をともにSQL NULLにする |
| relation | 同一assetの2領域と生成run、隣接・包含・上下・左右・共起、OKLCh差分、ΔE_ok、相対面積。領域の順序を保存し、同じrunで同じ組・typeを重複させない |
| block_color | Minecraft版、ブロックID、top/side/bottom、OKLab分布、材質タグ、抽出run。run別に再計算結果を残す |
| rule_stat | 条件キー、対象部位、分布、入力件数・subject数・実効サンプル数・重み、品質・信頼区間、分類版、集計run |

assetは取得イベントごとに記録し、`source_id` は出典ページ、`search_provider` は検索元API・アダプターの安定した識別子（例: `commons`、`openverse`）として区別する。
収集時に `search_provider`、`search_query`、`search_parameters`、`result_rank`、`result_page`、`retrieved_at`、`source_id` を保存する。
`search_parameters` は順位を解釈できる実効検索条件の辞書とし、エンドポイント・API版、並び順、フィルター、言語、ページサイズ、順位とページの起算基準・順位の範囲（ページ内か検索全体か）、使用したカーソル・オフセットを該当する範囲で保存する。APIの既定値も解決して保存し、認証情報は含めない。
順位・ページはAPIの基準をそのまま保存し、0も許容する。APIが返さない順位・ページはNULLにする。検索によらない直接入力は検索元・検索語・検索条件・順位・ページをSQL NULLにし、後で値を捏造しない。これらの整合性は収集側が検証する。
同じ内容を異なる出典・検索で選ぶ場合も記録できるよう、SHA-256に一意制約は置かない。重複判定・採否はprepの責務。

### prepの重複・同定契約（revision 0004）

prepはsubjectを新設せず、既存の確定subjectを変更しない。未同定画像は原則NULLのままにする。
例外はSHA-256完全一致群に確定subjectが1種類だけある場合で、同じ原本を表す未同定assetへ
その値を引き継ぐ。未同定側と確定側のどちらを後からprepしても同じ扱いとする。
完全一致群に複数の確定subjectがある場合は既存値を保持し、未同定assetはNULLのまま候補を残す。
pHashの距離6以下は近似の根拠に留め、subjectを自動確定しない。

重複クラスタは`asset_duplicate`の辺でつながる連結群として表す。完全一致だけの群と
近似を含む群は`method`で区別でき、クラスタの件数を独立subject数に使わない。
単独画像には辺がなく、重複画像が未同定同士なら辺だけを保存する。
いずれかに確定subjectがあれば相手側の`subject_candidate`へ根拠asset ID・手法・ハッシュを保存する。
候補は双方向に記録し、同じasset・subjectの候補は最大信頼度を保持する。
確定済みassetにも競合の確認や同定に使った根拠を残せるが、候補の存在は確定値を変更しない。
信頼度はSHA-256で1、pHashで`1 - distance / 64`であり、同定確率ではない。

既存のSQLAlchemy・PostgreSQL機能を再利用し、依存追加はしない。
prepの登録はREAD COMMITTED取引内で`pg_advisory_xact_lock(29, 1)`を取得して直列化し、
assetをUUID順に行ロック・再読込みして、後から確定した値も保持する。
画像解析・ファイル出力はこの排他区間の外で行う。辺の順序制約と複合主キーで逆向き・二重登録を防ぐ。
現在の全asset走査に合わせた排他範囲であり、大規模化時の探索・ロック範囲の最適化は別途扱う。
同定を変更する将来の処理もasset行ロックを守る必要がある。
revision 0004は表追加だけを行い、既存subject・候補・assetの値は自動補正しない。
`collected_title` と `collected_location` は収集元のタイトルと撮影地点の原情報を保存し、`subject_id` がNULLでも保持する。撮影地点は元の地名表記または座標表記を文字列で保存する。元情報がない場合のみNULLとし、subjectの推定値で補完・上書きしない。推定・確定した建築名や所在地は `subject.name/location` へ保存する。
テキスト資料の寸法はNULL可。scene_attributesはtaxonomyの属性名→値の辞書で、画像の撮影条件をsubjectの恒久属性に混ぜない。

JSONBを用いる可変長データの形:

- `bbox`: 元画像ピクセルの `[x_min, y_min, x_max, y_max]`（右・下端は含まない）。
- CVAT人手注釈の`region.mask_path`: runの`output_paths.masks`をrootとする`<asset UUID>/<region UUID>.json`の相対参照。JSONは`{"format":"polygon-pixels-v1","points":[[x,y],...]}`（元画像ピクセル座標、3点以上）を保存する。`label_source`は正解を`human`、未確定下書きを`model`として別runで区別し、既存領域を更新しない。この形式はCVAT取込みに限る。
- CVATの比較用下書きは`cvat-draft-v1` JSON（`label_source=model`）として元の縮小座標RLEを保持し、人手runの`output_paths.draft`から参照する。`parameters.draft_sha256`と`parameters.annotation_diff`に下書きの入力SHA・画像/ID別の追加削除・ラベル変更・面積差を保存する。既存のsegment run・model領域は更新しない。polygonの原画像座標は注釈座標に原画像幅/注釈幅・原画像高さ/注釈高さをそれぞれ乗じる。詳細と面積差の限界は[CVAT手順](../ops/cvat/README.md)を参照。
- `orientation`: `{"direction": "front", "estimated": true}` 等の推定結果。真の方位とは区別する。
- `terrain_attributes`: `{"relative_elevation": "high", "slope": "steep", "estimated": true}`。画像内の相対値。
- OKLab分布（observed_oklab・material_oklab・block_color.oklab）: `{"dominant": [L, a, b], "quantiles": [{"q": 0.5, "value": [L, a, b]}]}`。Lは0〜1、a/bは符号付き、qは0〜1。チャネル別分位点であり、実在する単一ピクセルを意味しない。
- `material_tags`・`target_parts`: 文字列配列。`conditions`: domainやtaxonomyのシーン条件の辞書。
- `distribution`・`quality`・`confidence_interval`・`parameters`・`policy`・`evidence`: 手法別の辞書。手法と設定はrunで識別する。品質・統計手法の詳細は後続Issueで確定する。

関係の差分はB−A、`area_ratio` はB/A。Δhは度で最短の符号付き差分（−180〜180）、無彩色で未定義ならNULL。ΔE_okはOKLabのユークリッド距離。
regionの面積比は画像全体に対する比。color_observationは `asset_id` と `region_id` の一方だけを必須とし、DB制約で両方指定・両方未指定を拒否する。
画像全体の観測（#12）はassetへ直接関連付け、regionや便宜的な分類ラベルを作らない。部位・地形の観測はregionへ関連付ける。
color_observationの面積比は対象assetの画像全体または対象region内に対する比。
JSON内の色・座標の構造、分類版に対応したラベル、閉じたシーン語彙は書込側が検証する。DBは参照・列挙区分・数値の基本範囲を保証する。分類の正本をDBへ複製しない。

`license_class` はopen/noncommercial/academic_only/restricted。欠損時にopenへ既定化しない。
後続のパック生成はasset/sourceと、region・観測・関係・統計・block_colorのrunおよび全入力runを確認し、open以外を除外する。processing_run_inputは生成時に保存し、呼び出し元が循環と入力の記録漏れを防ぐ。
これは監査履歴でありジョブキューではない。成功runはfinished_atあり・failure_reasonなし、失敗runはfinished_atとfailure_reasonを保存する。
#6のジョブキー・試行所有権・結果確定の境界は[ジョブとワーカーの契約](queue.md)を参照。
revision `0002` で `job` を追加し、成功した `processing_run` と1対1で結ぶ。
同revisionで `processing_run.output_paths`（JSONB、既定は空辞書）を追加する。
出力名→採用済み不変パスの辞書で、解析結果の参照列もこの値を使う。
キュー経由の失敗理由はjobに保持し、成功取引だけがrunと解析結果を登録する。

## 適用と検証

リポジトリルートから `uv run alembic upgrade head`、巻戻しは `uv run alembic downgrade base`。
接続URLは `DATABASE_URL`（`postgresql+psycopg://...`）で渡す。未指定時はlocalhost/colorstats。認証情報をファイル・ログ・Gitに保存しない。
`uv run alembic upgrade head --sql` と `uv run alembic downgrade 0002:base --sql` はDBへ接続しない。
初期revisionは独立した列定義を保持し、将来のモデル変更によって過去の適用内容を変えない。

ローカルは `uv run pytest` でYAMLの構造・親子・参照整合とSQL生成を検証する。
実DBテストはCIのPostgreSQL 16サービスに `TEST_DATABASE_URL` を渡し、空のテストDBへ適用→メタデータ比較・制約確認→巻戻し→再適用→Alembic差分なしを確認する。
テストは空でないDBを拒否する。本番DBでは実行しない。ローカルで実DBテストがskipになることは適用成功を意味しない。

初版は既存保存データの移行なし。`downgrade base` は全対象テーブルとそのデータを削除するため、本番の運用巻戻し前にはバックアップと影響確認が必要。

### Issue #72: 対象推定の根拠

スキーマ・Enumは変更しない。`asset.subject_id`は確定のみで、未確定はNULLを保つ。
`asset.quality.subject_inference`にmethod、state（confirmed/candidate/unknown）、
reasons、config_hash、run_idを全件保存する。候補・未知をsubject件数へ加算しない。
`subject_candidate.evidence`は対象キー、元asset、ルールの根拠、設定hash、run_idを持つ。
confidenceは未校正のルールスコアであり確率ではない。
自分の前回生成候補は再推定し、外部で作られた候補根拠はexternal_evidenceとして保持する。
SHA群の弱い対象名も競合根拠に含め、スナップショットのidentity_targets・sha_conflictsに
対象IDと元assetを保存する。ファイル名だけの旧subjectを別対象の根拠にはしない。

`asset.scene_attributes`にはtaxonomy内の一意に推定できた値だけを追加し、
`quality.scene_inference.attributes`に属性ごとのinferred/preserved/conflict/unknownと根拠を保存する。
既存値を保持し、自分の前回推定値は再計算する。検索意図は推定根拠に含めない。
未知・矛盾の属性を検索意図で埋めて主統計へ渡してはならない。
既存値のpreservedはこの処理で根拠を検証した意味ではないため、後続のsnapshotでは区別する。

`processing_run.stage=subject`はJobを使わない独立処理。
全件更新とrun成功を1取引で確定し、JSONスナップショットの新規パスをoutput_pathsに記録する。
失敗時は部分更新を残さない。ファイルとDBは分散取引ではないため、成功runに参照されない
スナップショットを成功結果として採用しない。旧runの外部スナップショットは上書きしない。

`processing_run.parameters.subject_keys`にdomain・対象キー・subject IDの確認済み対応を保存する。
名称の一致を既存subjectの再利用根拠にせず、候補の再計算で根拠行が消えた場合も成功runの
対応を参照する。旧形式の候補根拠から対応を確認する場合は、対象キーの決定的UUID、
成功runと設定hash、名称・固有カテゴリの独立根拠がすべて一致するものに限定する。

明示的な再評価では、スナップショットのprevious_subject_idがNULLだった関連付けだけを
当該runが新規に付けたものとして扱う。旧スナップショットはexisting_confirmed理由を照合する。
現在のrun参照と対象も一致する場合だけ再評価し、同じ対象へ確定できなければNULLへ戻す。
reconsider_run・reconsidered_assignments・preserved_prior_assignments・revoked_assignmentsを
runとスナップショットへ保存する。取消と再推定、属性再計算も同じ取引内で確定する。

### Issue #79: CommonsカテゴリとWikidataの自動対象キー

既存の手作業カタログを残し、`stats/wikidata.py`で対象を追加する。
保存カテゴリのCommons pageprops.wikibase_itemから、カテゴリ項目ならP301の主題、
実対象項目ならその項目を参照する。既知項目のP373・P910も保存カテゴリと照合する。
一般カテゴリを親へたどって対象へ昇格させない。
P31とP279の上位クラスを照合し、建築・構造物、名前付きの山・湖・公園・河川・島・
森林・砂漠・山脈・丘・洞窟のうち単一domainで、地球上のP625が一意な項目だけを使う。
行政区画・集落・地域・様式・クラス・一覧・Wikimediaカテゴリは除外する。
項目のラベル・別名、座標、クラスとrevision、カテゴリから項目への対応を保存する。

追加キーは`wikidata:Q...`。手作業カテゴリが同じQIDへ結び付く場合は手作業のキー・UUIDを
保持してカテゴリと名称を統合する。カテゴリに直接リンクがない手作業対象は、公式項目の
カテゴリ・名称・所在地を確認したwikidata_idを規則へ明示する。
名称一致だけで既存subjectを再利用しない。
固有カテゴリ＋名称、または固有カテゴリ＋P625と撮影GPSの整合を要求する。
距離は従来の最大撮影範囲の半分（建築2km・地形20km）以内とし、GPSが矛盾すれば
名称一致でも確定しない。名称＋固有カテゴリで支持される撮影位置は、追加キー・座標照合で
候補が除外されても撮影範囲検査から取り除かず、範囲検査が緩まないようにする。
従来の撮影範囲・SHA競合・複数対象の抑止は維持する。
複数domainの対象カテゴリが併存する画像も保留する。既存確定値は保持する。

`subject_candidate.evidence.basis`にwikidata_id、coordinates、location_match、
location_conflict、origin（対象キーがautomatic/manual）を追加する。
`processing_run.parameters.subject_keys`にもwikidata_idを追加し、
`parameters.wikidata`とスナップショットに要求hash→応答hash・項目revision・分類根拠を保存する。
confirmed_subjectsはdomain別の確定subject数、originsは確定assetのキー由来内訳。
SHA継承等で直接の対象根拠がない行はpreserved_or_shaとする。候補数と対象数を混同しない。
テーブル・Enum・マイグレーション・既存の取消契約は変更しない。

取得は既存CommonsAdapterとsource_policy.yamlのUser-Agentをそのまま使う。
直列取得・min_interval・maxlag・Retry-Afterを維持し、要求hash別JSONを保持する。
欠損・壊れた応答・API不通は実行失敗とし、部分カタログで本番反映を続けない。
初回通信はdry-runで済ませ、本実行では同じキャッシュと`--offline`を指定する。
通信を伴う本実行では書込みロックも長くなるため、この順序を守る。

```sh
python -m colorstats.stats.subject_cli --wikidata-cache /保存先/cache --snapshot /新規/dry.json --code-version <内容版> --dry-run
python -m colorstats.stats.subject_cli --wikidata-cache /保存先/cache --offline --snapshot /新規/applied.json --code-version <内容版>
```

取得だけを先に分離する場合は`bench/issue79/production.py export`でカテゴリを抽出し、
`bench/issue79/prepare.py <入力JSON> <cache> <出力JSON>`で追加済み規則を保存する。
そのJSONを`--rules`へ渡しても同じ判定・取得根拠を使用する。
オフライン再生成も同prepare.pyへ`--offline`を指定する。
APIキャッシュ・追加済み規則・完全スナップショットは実測報告に記した外部保存先を正本とする。

利用方針の一次情報（2026-11-03確認）:
[API利用規約](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines)、
[User-Agent方針](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy/en)、
[API Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)、
[Wikidata Data access](https://www.wikidata.org/wiki/Help:Data_access)。

反証修正では、建築クラスでも道路・街路・建築群・複合施設・城郭全体を候補に止める。
Buddhist temple・Shinto shrineを直接のP31とする施設全体、P527に別の建物を持つ項目、
P2670が建物の種類を指す項目も単一建物として確定しない。
本堂等の具体的な建物クラス、窓など建物に該当しない部分は施設全体と区別する。
一般の構造物・柱・身廊等の建築要素は、P527/P2670の建物群の根拠として数えない。
名称の語句や本番の個別QIDを除外判定に使わず、クラスと部分構造を根拠にする。
候補キーのcandidate_onlyとgranularity、および推定理由target_granularityへ保存する。
既存確定は維持し、取り消す場合は成功runを明示した再評価だけを使う。

P301等で複数の対象domainの物理対象へ結び付くカテゴリはambiguous_categoriesに対応項目を残す。
カメラ等のメタデータ主題は物理対象の複数キーとは区別し、元の全主題はcategory_itemsへ保持する。
単独カテゴリも一致していてもmultiple_targetsで新規確定とSHA継承を抑止する。
各要求カテゴリの正規化・redirect後のページ、および要求QIDの応答を全件確認し、
応答そのものが脱落していればキャッシュ・実通信のどちらでも失敗させる。
Commonsが明示的にmissingを返したページは「応答済み・対象情報なし」として扱い、
空のpagesや要求QIDの脱落・missing項目とは区別する。
preferred座標と他の有効P625が併存する場合は、一意性を保証できないため引き続き除外する。


### Issue #85: 建築subjectの地域・年代

`subject.location` は収集層のregion文字列、`subject.era` はera文字列のまま維持する。
unknownはNULLで、既存の非NULL値を上書きしない。地形subject・assetは変更しない。
確定画像（asset.subject_idで参照される画像）を持つ建築subjectだけを集計・反映し、
成功したsubject同定runのsubject_keysでWikidata IDを
一意に確認できる対象だけ取得する。キーなし・競合はunknownのまま記録する。

`python -m colorstats.stats.subject_attributes --snapshot <新規JSON> --wikidata-cache <cache>
--code-version <版> [--dry-run] [--offline] [--cancel-run <run UUID>]` で実行する。
DB接続は既存のDATABASE_URLを使用する。初回dry-runで取得し、本実行は同じcacheをofflineで使う。
#79の取得モジュール、User-Agent、レート制限、要求hash別cacheを再利用し、新規依存はない。
取得失敗・欠損・出力失敗・DB失敗はrun全体の失敗で、部分反映しない。

`configs/subject_attributes.yaml` に国ID→regionと西暦の閉区間→eraを固定する。
時代は共通区分（古代:499年まで、中世:500～1499年、近世:1500～1799年、近代:1800年以降）で、
地域固有の時代区分とは区別する。P17の全有効claimが同じregionを指す場合だけinferred。
P17のないP131・P625・撮影GPSから国境界を推測しない。未対応国・競合はunknown。
P571は精度を年区間へ展開し、全有効claimの区間が単一era内ならinferred。
before/afterは年・月・日・時・分・秒それぞれの精度単位で計算し、月・日の幅を年数にしない。
月末・うるう日は元の暦で計算する。年代境界はグレゴリオ暦基準で扱い、
暦換算をしないユリウス暦は、区間が各era開始年の前後1年に重なる場合unknownとする。
境界跨ぎ、異なるera、修飾付き年代、対応外暦・紀元前等はunknown。
世紀・千年紀の1始まりは[Wikidata日付仕様](https://www.wikidata.org/wiki/Help:Dates)に従う。

state（inferred/unknown/preserved）、理由、元値・更新後値、Wikidata項目ID・revision・
P17/P131/P625/P571の完全claim、asset GPS、設定、要求・応答hashはsnapshotへ保存する。
成功runはstage=subject、method=subject-attributes-v1で識別し、parametersに設定・集計・
変更箇所、output_paths.snapshotに根拠JSONを保存する。APIは#79と同じ要求を使い、
返却結果から4属性だけを今回の根拠へ記録する。既存の列・層照合APIは変更しない。
#85の現行runのlicense_class=restrictedは実装の固定値であり、画像やWikidata claimの権利を判定した値ではない。

#72の取引・排他・snapshot作成を共有し、属性反映はsubject表だけをロックする。
取消は指定成功runの変更前値・更新後値・現在値と後続の属性変更runを照合し、
そのrunが新規に付けたままの値だけを戻す。取消範囲は元snapshotのsubjectとし、
現在は確定画像がない対象や旧実装が誤って反映した候補も含めて戻す。
取消自体もdry-run・1取引・新規snapshot。
同じ値を別経路で書き戻した操作は既存スキーマに履歴がなく識別できないため、
対象列を外部操作した場合は元snapshotと現在の編集履歴を確認してから取消する。

### Issue #74: 固定統計スナップショット

現行形式版は2、権利ゲート版はD15-v2（旧M3固定版は1 / D15-v1のまま保持）。
内部用のParquetとmanifest.jsonを、
未使用の出力ディレクトリへ作る。既存出力へ上書きしない。

実行入口は `python -m colorstats.stats.snapshot_cli`。
`--selection <JSON>`、`--code-version <固定コード版>` を必須とし、
通常実行では `--output <未使用ディレクトリ>` も指定する。
`--quality` は既定で configs/segment_stats.yaml。
`--dry-run` は永続artifactを作らず、一時領域で同じ件数・除外を検査する。
DATABASE_URLは環境から渡し、例外本文・接続情報をCLIへ表示しない。

選択JSONは次の形。全件のasset IDと採用する成功runを呼出し側で明示し、
DBの最新runを自動選択しない。失敗・欠測もコホートへ残す場合はrunを省略する。

```json
{
  "taxonomy_version": "0.1.0",
  "subject_attribute_run_ids": ["<属性反映成功run UUID>"],
  "assets": [
    {
      "asset_id": "<UUID>",
      "prep_run_id": "<UUID>",
      "segment_run_id": "<UUID>",
      "color_run_id": "<UUID>"
    }
  ]
}
```

- 1つのREPEATABLE READ / READ ONLY取引で関連行をまとめて読む。
  観測・関係は4096件単位で一時JSONLへ退避し、取引を閉じてから集合結合と色抽出を行う。
  選択asset欠損・重複、未成功run、別asset・異taxonomy・異stage、
  選択prep/segmentとcolorの直接入力不一致、入力循環、採用分割設定不一致は全体失敗。
- processing_run_inputを再帰的に辿り、全解析入力runの制約を確認する。
  subject/scene_inferenceと明示指定した#85属性の成功subject runも取り込む。
  subjectと属性・候補・推定根拠は現在値をコピーし、再読取り時にDBへ参照しない。
- asset.quality.licenseとsource.licenseの選択値を照合する。
  open経路はPD/PDM・CC0・版付きCC BYだけを許容し、SA/NC/ND・制限付きrun・
  評価専用重み・権利不明・由来/帰属不足を理由別に除外する。
  カテゴリ上の複数ライセンスから選び直さず、別出典による再許諾を推測しない。
  原本や除外された出典を削除しない。
  解析専用経路は本書末尾のIssue #87契約に従い、元権利・根拠・出典が整合する
  analysis_onlyを許可する。両経路ともモデル重みはopen必須。
- 権利と必要解析が適格なassetの中で、SHAごとにUUID文字列最小の代表を採る。
  全別出典とその個別の除外理由を残す。D15除外・解析欠測・SHA重複を区別する。
- 画像全体観測はwhole_image、未支持の個別ラベルはunvalidated_labelとして保持する。
  shade平均をcolorの主色に置き換えない。
- #81の評価artifactはUTF-8/LFでhash照合し、支持済み和集合のメンバーを固定する。
  real_building/wallとreal_terrain/treeは、選択colorの画像・マスクの設定hashを照合後、
  既存color処理で画素和集合から主色を再抽出する。重なる画素は一度だけ数える。
  個別ラベルの支持も評価資料のdomain別に適用し、建築のdoorを地形へ転用しない。
  個別ラベルの観測を足した結果や親からの平滑化を直接支持にしない。
  画像・マスクは生成時だけ必要で、値を固定した後の再集計では不要。
  D15除外された入力の和集合も残すため、必要解析が揃う全入力の画像を読める実行権限が必要。
  入力ファイルの欠損・改変・抽出失敗も全体失敗。

subject_attribute_run_idsは#85属性根拠を使う場合に明示する成功runのUUID一覧。
最新runの自動選択や本番run IDの固定実装は行わない。同じsubjectの根拠は一意に選ぶ。
固定DB値を読み終えてからoutput_paths.snapshotの根拠JSONを読み、
run・設定・非dry-run状態とregion/location・eraの現在値を照合する。
値・run・taxonomyの不一致、根拠ファイル欠損、同じsubjectの複数根拠は全体失敗。

assets.data.subject.attribute_evidenceに#85のsubject行をコピーし、
run_id・method・config_hash・snapshot_sha256を添える。
attributes.region/eraのvalue・state（inferred/unknown/preserved）・reasonとderived、
before/after、Wikidata ID・claim・revision・GPSをDBなしで監査できる。
Subject.location/eraは従来どおり文字列またはNULLで、state付き辞書へ置き換えない。
根拠未指定の値は保持するが、#85由来やinferredと推測しない。
対応runと全入力をruns.parquetおよびmanifest.input_run_idsへ含める。
属性根拠として選択したrunは画像のD15判定集合に加えず、画像・解析モデル由来の権利判定は維持する。

Openverseの照合済み短縮表記by/by-saは、source_verified、元ライセンスの一致、照合済みmetadataの版に基づき、
D15判定時だけcc-by/cc-by-saの版付き表記へ正規化する。未照合・版欠損は許可しない。
assets.data.d15_licenseに判定用のasset/source表記を残し、元qualityとprovenanceは変更しない。

Parquet一覧:

| ファイル | 主な列と意味 |
| --- | --- |
| assets | id、sha256、domain、subject_id、representative_id、eligible、reasons、data（選択run・属性・subject・候補・根拠・収集意図）、rights_eligible、analysis_available |
| provenance | asset_id、source_id、data（元URL・サイト・作者・選択ライセンス・帰属・収集時点） |
| runs | id、stage、data（設定・コード・重みhash・制約・成功時点・input_run_ids） |
| regions | id、asset_id、run_id、label、data（領域面積比・信頼度・位置等） |
| observations | id、asset_id、region_id、run_id、eligible、reasons、data（主色・クラスタ分位点・面積比）、quality_eligible |
| relations | id、asset_id、run_id、eligible、reasons、data（順序付き領域参照・B−Aの差・B/A面積比）、quality_eligible |
| groups | id、asset_id、run_id、role、eligible、data（構成領域・画素和集合面積比・主色・由来hash）、quality_eligible、reasons |

data/reasons列はParquetのJSON文字列。ID・参照・ゲートは独立した型付き列。
assets.eligibleは権利・必要解析・SHA代表の入口ゲートであり、
subject・属性・有効標本数の支持条件を満たしたという意味ではない。
観測と関係のeligibleはさらに個別ラベル品質を要求する。
quality_eligibleはD15・SHA選択前の品質支持を示す。groupsは明示的な粗い役割だけの支持。
観測・関係・groupsのreasonsには、個別の品質除外とassetのD15・欠測・SHA除外を併記する。
groupsはD15除外前にも抽出する。asset_idでassetsのsha256・subject_id・属性へ結び、
quality_eligibleで品質を固定したうえでrights_eligibleの前後を比較できる。
rights_eligibleは権利だけの通過、analysis_availableは権利と独立した必要解析・domainの確認。
SHA重複前後はsha256とrepresentative_id、最終採用はeligibleを使う。後続#75で確定subject・根拠ある属性を
選び、未知subjectの診断分布と主統計を分離する。

manifestは選択集合とhash、input_run_ids（採用した全入力run ID）、
taxonomy/コード版、固定品質設定とhash、
DB分離レベル・READ ONLY状態、段階別件数、複数該当を許す除外理由の件数、
全ParquetのSHA-256と行数、DuckDB版、snapshot_idを持つ。
rights_eligibleは権利ゲート後、analysis_eligibleは必要解析・domainの確認後、
representativesはさらにSHA代表選択後のasset件数。
sha_distinctは入力全体、confirmed_subjectsは代表の非NULL subject異なり数。
*_rowsは保存行数、*_eligibleは入口・品質ゲート後の行数。
クラスタ行数を画像数・subject数へ読み替えない。
除外理由の合計は複数該当があるため除外asset数とは限らない。

全Parquetのhashと件数を照合してからmanifestを最後に作る。
失敗した出力ディレクトリは成功artifactとして採用せず、新しい出力先で再試行する。
snapshot_idはsnapshot_id自体を除くmanifestの正規JSONのSHA-256。
正規JSONはUTF-8、キー順・区切りを固定しNaNを禁止する。
`verify(path, expected_hash)`へ信頼済み呼出し元が保持したsnapshot_idを渡し、
manifest・ファイル集合・全ファイルhash・行数を照合してから読む。
同じ固定データ・入力集合・設定・コード版・DuckDB版では全Parquetとsnapshot_idが一致する。
入力の列挙順はasset_id順に正規化する。OpenCV・DuckDBはCPU一スレッドで処理する。
DB取引識別子と読取り時間・全体時間はexecution.jsonへ分離し、内容hashに含めない。
execution.jsonは監査・計測用であり、集計入力や信頼済みhash検証の対象ではない。
属性根拠・新列・D15除外前の和集合を使うレポートには新snapshotの生成が必要。旧artifactは上書きしない。

後続aggregateは成功snapshotのhashと固定設定をQueueのキーへ含め、
runs.parquetの入力runをprocessing_run_inputへ結ぶ。
Queue.completeの所有権確認・取引境界を経て統計を採用する。
snapshot作成自体はDB無更新で、aggregate登録やrule_stat生成は#75の責務。

既存データの移行・削除は不要。実7,607件からの生成は全量解析と対象推定の成果を
確認した第2段階とし、第1段階のfixture成功を実データの支持数の達成とは扱わない。

全量7,607件のsnapshotと監査の記録は[Issue #74全量検証](../bench/issue74/full-results.md)を参照。

### Issue #75: subject重み付きrule_stat

入口は `python -m colorstats.stats.aggregate_cli`。
`--snapshot <ディレクトリ> --snapshot-id <信頼済みhash> --output <JSON出力名>`
を必須とし、`--config configs/stats.yaml`、`--targets configs/collection_targets.yaml`、
`--taxonomy taxonomy`を固定設定として読み取る。
`--dry-run`はDBへ接続せず、新規出力ファイルへ計算結果を保存する。
通常実行はsnapshot全体のhash検証後にaggregate jobを投入する。
実行は既存Queue CLIの
`--handler aggregate=colorstats.stats.aggregate --stop-file <停止ファイル>`
を使用する。DATABASE_URLを表示しない。

既存のDuckDB/Parquet・taxonomy/目標検証・共起抽出・Queue完了取引を再利用する。
追加依存はない。軸別CDFの確率質量と親との混合を明示的に保持するため、
通常の非重み付きquantileへの置換や分位点同士の平均は行わない。

#### 重みと実測支持

- snapshotが適格としたSHA代表だけを使う。主色は最大クラスタのdominant。
  クラスタのquantilesは生画素の代用にしない。
- 画像内は役割の領域面積比、pairでは面積積で正規化する。
  subject内では当該条件・役割/pairの有効SHA画像へ等配分する。
- subjectの属性と画像の実属性を照合し、既知属性と両立する層へqに比例した所属を配分し、部分層補正する。
  同じsubjectの画像間の既知層属性の矛盾も除外する。収集意図で属性を埋めない。
  地域・年代・季節等のunknownは周辺化する。詳細は[部分補正設計](../bench/issue75/design-section.md)。
- 条件に適用可能な目標subjectsを正規化したq_hと、
  適格な確定subjectの所属質量からp_hとq_h/p_hを求め、所属で平均したW_sを使う。
  層0件の目標質量は欠損として残し、観測層だけで被覆率を報告する。
- weightはsubjectへ合計した重みの総和。effective_sample_sizeは
  (ΣW_s)^2/ΣW_s^2。sample_countは実際に主統計へ入れたSHA異なり画像数、
  subject_countはその確定subject数。平滑化で増やさない。
- 未知subjectは主分母へ入れず、SHA単位の無補正診断と、
  各未知SHAを別subjectとした無補正感度分布を保存する。
  未割当理由はoutside_target、
  attributes_conflict、subject_stratum_conflictとして独立に数える。

#### distribution JSON

| 項目 | 意味 |
| --- | --- |
| kind | palette / relation |
| estimator | subject_partial_poststratified_appearance（観測subjectの外観主色） |
| cdf | 軸→値順の[value, probability_mass]。同値は合算し、累積和が経験CDF |
| quantiles | 軸→[{q,value}]。q=.05/.25/.50/.75/.95、累積質量がq以上となる最小値 |
| hue | relationのみ。range=[-180,180]、左端を含む10度幅36bin、右端180は-180へ折返し |
| hue.bins / null_mass | 全採用重みに対する円周bin質量と無彩色NULL質量。両者の合計は1（空なら0） |
| units | 色・差はOKLab、Δhは度、面積比はB/A |
| direction | relationはtaxonomy順の異役割A→B、差はB−A |
| parent / lambda | 実際の親条件・役割と子CDFの混合係数 |
| diagnostics | raw、uncorrected、capped_5、unknown_as_subject、unknown_onlyの分布 |

paletteの軸はL/a/b、relationはdelta_l/delta_c/delta_e_ok/area_ratio。
Δhには線形分位点を作らない。逆pairはΔL/ΔC/Δhの符号と面積比を反転する。
同役割pair・非co_occurs・ゼロ面積・非有限値・無効面積比は採用しない。

#81の個別支持は実建築door、和集合は実建築wall・実地形tree。
和集合色を個別ラベルの色で置き換えない。和集合を含むpairはsnapshot内の固定した
主色・面積から既存extract_relationsでco_occursを再構成する。
個別領域間のpairはsnapshotのrelationを使用する。
未支持ラベルは親が支持済みでもstatus=unsupportedとし、model_unvalidatedを残す。

#### 平滑化・quality JSON

建築の条件親は(style,building_type,biome_like)→(style,building_type)→style→domain、
地形はbiome_like→domain。条件を全て緩めた後だけ部位親へ進む。
異domainへの借用は行わない。

subject_countとn_effの両方が30以上ならdirect。
10以上30未満は利用可能な親とλ=n_eff/(n_eff+20)で経験CDFを混合する。
10未満はλ=0で親のみ。親も未支持ならunsupportedとし、主分布を空にする。
styleとその子条件の両段で混合する場合、混合済みの親CDFを順に使用する。

qualityにはstatus、flags、raw_subjects、raw_n_eff、parent、lambda、source_quality、
target_mass_coverage、missing_target_mass、missing_strata、max_weight、
unknown_images、unassigned_subjects、unassigned_reasons、snapshot_id、
gate_version、snapshot全体のexclusionsを保存する。
部分補正ではq_h・m_sh・p_h・r_h・W_s、correction_rate、attribute_unknown_rates、
no_information_rateを追加する（詳細はbench/issue75/design-section.md）。
exclusionsはセルの除外件数ではなく、元snapshotのコホート全体の件数。
low_support・smoothed・unsupported・subject_unresolved・attributes_inferred・
intended_only・high_weight・missing_target_mass・model_unvalidated・license_excludedを併記する。
主重みはクリップせず、上限5と補正なしの感度分布を別記する。
confidence_intervalはSQL NULL。

#### 登録と失敗境界

同じsnapshot_id・固定設定・実装版は同じQueueキー。パスはキーの意味へ含めず、
同じjobを再投入する際は元のsnapshot/outputパスを維持する
（既存Queueの同一キー・異payload拒否規約に従う）。
コードはprepareでsnapshotを再検証し、試行固有のJSONを生成する。

registerは適格assetの採用runと推定runを由来閉包として照合し、
processing_run_inputへ結ぶ。除外assetだけのrunを主統計へ戻さない。
runの成功・版・設定・コード・モデル・重み・制約・parameters・入力辺をDBと照合する。
ライブDBの観測や属性でsnapshotを補完しない。
Queue.completeの所有権確認と同一取引でrun・全rule_stat・job成功を確定する。
エラーなら全件rollback、旧統計は保持。未参照artifactは成功結果として扱わない。
既存データの移行・削除は不要。


全量snapshotからの登録・支持・再実行の記録は[Issue #75全量検証](../bench/issue75/full-results.md)を参照。


属性根拠runはassets.data.subject.attribute_evidence.run_idから採用入力へ結ぶ。
subject_attribute_run_idsとして集計JSONとrun.parametersにも保持する。
Subjectのregion/eraがinferredの場合もattributes_inferredを付ける。
#85のmethod=subject-attributes-v1として明示された属性根拠runだけは、
license_classの固定値restrictedを画像の制約と解釈しない。
解析runのrestrictedや、未指定・別methodのrunは従来どおり登録を拒否する。
由来runと入力辺は256件ずつ照合し、画像の観測・属性をライブDBで再集計しない。

n_effはW_sの集中度であり、未知の層所属・欠測の偏りの不確実性を含まない。
target_mass_coverageは所属質量に基づく被覆で、層属性の直接観測数ではない。
補正率・情報なし割合を併記し、支持やM3条件4を層補正の有効性の保証としない。
この解釈は集計JSONとrun.parametersのsupport_interpretationにも保存する。

選択一覧の独立したshade none runはpaletteの入力とせず、prep・segment・colorおよび
実際の入力辺の閉包を採用する。colorの入力辺にshadeがある場合はその由来も保持する。

## 固定snapshotの偏りレポート（Issue #76）

DBとsnapshot-v1の形式は変更しない。
report CLIへのstatisticsは#75 aggregate CLIの出力全体を渡す。
rowsはrule_statの登録対象行と同じで、snapshot_id・taxonomy_version・input_runsを保持する。
DBのrule_stat単体を抜き出したJSONは由来が足りないため本CLIの入力にはしない。
本番run d7297e42-3b35-49e2-a0f8-903809a9af59の569行・入力辺4856件をREAD ONLYで照合済み。

report.json:
- snapshot_id、コード版、aggregateコード版、taxonomy版、設定／統計hash。
- overall、strata（意図／属性一致／意図比較）、classification。
- observation_exclusions、snapshot_exclusions、model_quality。
- support（条件・役割／pair・sample_count・subject_count・effective_sample_size・
  単位／方向・quality・感度分布）。
- processing（snapshot保存runと件数、Parquet byte数、計測範囲）。
- scale_target（10万適格画像の段階目標、M3必須条件とは別）。
- usefulness_gates、m3_checks、m3_complete、handoff。
- 率は{numerator, denominator, value}。空分母はnull。

supportの数値・品質・感度分布は再計算一致を検証した#75の値。
sample_countは採用SHA画像数、subject_countとn_effはsubject基準。
relationの方向はB-A、面積比はB/A、Δhはdegree、色はOKLab。
親借用と欠損目標質量を隠さず、未支持分布を支持済みとして扱わない。
権利除外はsnapshotに保持し、帰属の正本はprovenance.parquet。
Gの配色パックSchemaやDATA_LICENSEを本レポート形式で先取りしない。

### report-v3の出力契約

- confirmed_subjects_afterは当該層に両立する採用subject数（層間で重複あり）。
  confirmed_subjects_after_snapshotは権利・解析・SHA重複除外後、層割当前のsubject数。
  subject_massは#75のm_shの和、subject_coverageは質量/目標、subject_deficitは目標-質量。
  unassigned_subjectsは既知値矛盾・対象外などのsubject数。
- classification.image_unassignedは全asset行に対する画像属性の未割当率。
  classification.unassignedは適格SHA代表画像を分母とするsubject未割当率。
  subject_stratum_conflictも同じ分母で、unassigned_subject_reasonsはsubject単位の件数。
- rights_supportはcondition／stratumと役割ごとの保存済み色観測の確定subject数。
  recorded_subjects_before_d15／recorded_subjects_after_d15／lost_subjects_d15は、
  同じ役割でD15通過後にも観測を持つsubjectを残して集合差で求める。
  subjects_after_analysisはsnapshot適格段階、adopted_subjectsは品質・部分層補正後の両立subject数。
  n_effを再計算した値ではない。統計支持は従来のsupportに保持する。
- 和集合色が未保存なら該当前後数・集合差はnull。
  unverified_union_assetsとcomplete、理由を出し、条件5をunverifiedにする。
  unobserved_rights_excluded_assetsは部位色観測自体のない権利除外画像数。

旧合成artifactは同じ入力からreport-v3で再生成する。
DB・snapshotの移行は不要。レポート旧形式の互換処理は追加しない。


部分層補正ではassign_strataの戻り値は既知属性辞書。複数両立・属性不足だけでは棄却しない。
classification.partial_correctionはdomain別の適格確定subjectを分母とした補正・未知・情報なし率。
supportおよびusefulness_gates.correctionの割合は当該条件・役割の#75主結果をそのまま使用する。
rights_support.adopted_subject_massも層の所属質量とし、両立subject数と分ける。
入力JSONはaggregate-v2。旧方式の統計・report-v2は再生成し、互換処理は追加しない。

補正率等は#75定義に従い、N=0では0。件数比率の空分母nullとは区別する。


条件4のm3_checks項目にrole_results（domain別の判定候補役割）を添える。
各役割はsubject_count・n_eff・補正率・情報なし割合・passed・quality_flagsを保持する。
情報なし割合>0.5でweak_correction。ちょうど0.5には付けない。
domainのusefulness_gatesと条件4のquality_flagsは役割フラグの和集合。
判定の閾値は従来どおりで、#75の統計quality・支持・補正率は変更しない。
reasonに「passed は層補正の有効性を意味しない」と明記する。

subject.attribute_evidenceのregion/era stateを属性state表示へ使用する。
rights_excluded_without_analysisは必要解析がない権利除外画像数で、色支持へ含めない。
解析失敗を根拠欠落と区別し、失敗理由・全体分母は保持する。
自動m3_checksと外部監査後のm3-assessment.jsonは区別する。

属性state集約では、値の有無にかかわらず保存済みconflictを保持する。
値なしのinferredや根拠なし値なしはunknownとし、矛盾を未知へ統合しない。

## 解析専用区分と内部snapshot（Issue #87）

revision `0006`はsource・asset・processing_runのVARCHAR(13)と全license_class CHECKへ
`analysis_only`を追加する。native PostgreSQL enumではない。既存行を更新しない。
downgradeは全対象表をロックしてanalysis_only行の存在を検査し、残っていれば例外で拒否する。
削除・自動変換は行わない。通常のupgrade/downgradeはAlembicの取引内で行う。

確認根拠は既存source.policyとasset.quality JSONBへ追加する（[収集契約](collect.md#解析専用入力issue-87)）。
全runはopenを中立として合成し、analysis_onlyとNC/academic等の混在はrestricted。
内部snapshotはformat_version=2、gate_version=D15-v2、access_scope=internal。
assetの元URL・取得日時・確認根拠を保持し、原画像保存期限と統計利用失効を分離する。
verifyは固定済みformat_version=1も引き続き照合するが、旧M3 snapshotを再生成・上書きしない。
snapshotは配布パックではなく、[M4配布契約](pack-contract.md)に従って別の出力を作る。

## 新規入力の保持・停止台帳（Issue #88）

revision `0007`は既存行を登録せず、次の3表を追加する。

- retention：assetごとの画像期限expires_at、停止時刻stopped_at、理由reason、受付Issue URL、
  backup最大残留期限backup_until。画像期限だけでは数値統計を失効させない。
- retention_file：asset/host/絶対pathを一意な依存参照とし、raw/derived/mask/cvat/replica/cache/backupを
  区別する。released_atは参照解除、deleted_atは物理削除確認、errorは共有保護・削除失敗。
- retention_stop：provider/source_url/target_urlごとの停止台帳。target_urlの空文字列は出典全体、
  それ以外は対象の原画像URL。detailsは原画像URL・受付時刻・理由・受付Issue。
  asset/sourceの復元より古いbackupでも再取得を拒否できるよう、外部キーを持たず別保管する。

downgradeは保持・停止台帳が残っていれば拒否する。台帳を暗黙削除しない。
asset.quality.privacy_reviewは目視確認者・建築/地形の主体・確認時刻・人物除外maskとSHA-256。
新規画像は確認前の色処理を拒否し、maskはcolor設定hashへ含める。
停止入力を除いた新selectionの生成、復元時の停止台帳先行適用、共有ファイル保護は
[管理手順](retention.md)に従う。旧snapshotの内容・識別子は変更しない。
