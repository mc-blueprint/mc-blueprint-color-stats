# #114 修正設計とIssue分割

2026-11-07。owner・worktreeを継続。根拠は[診断](review-diagnosis.md)、
[既存機能・一次資料調査](remediation-sources.md)、ユーザー指定の私有API試験集計。
画像・ユーザー所見・個別のAPI応答はGitへ入れない。
今回は設計・Issue作成だけで、製品コード・DB・モデル/API実行・環境構築は変更しない。

## 確定する構成

```text
取得・権利/保持確認 → API用1024px画像 → A: Luna lowの画像判定
                                    ↓ 不適格/不明は理由付き除外・保留
既存prep → B: OneFormerの排他クラスmap ＋ DINO/SAM2部位候補
                                    ↓ 領域制約・競合画素を除外
                              C: 人物採用方針と整合確認
                                    ↓
                 E: 私有HTML・番号返信 → D: 品質の判定
                                    ↓ 合格と実行許可が必要
              G: 旧7,607の訂正版基準 → #114: バッチ1再解析・統計比較
```

A/B/C等は下記の担当Issue記号。実際の番号は[Issue一覧](remediation-issues.md)に記録する。
既存M3・#105 v2のsnapshot/run/asset・subject関連付けを上書きせず、別版を作る。
旧保留993枚の除外決定は維持し、再判定を理由に自動再採用しない。

## 領域方式の選択

**OneFormer ADE Swin-Lのsemantic mapで排他領域を作り、既存部位候補を制約する方式を採る。**
gpt-imageを画素maskに使わない。DINO/SAM2は部位候補に再利用し、主体・人物の実在判定は任せない。

| 案 | 利点 | 問題・結論 |
| --- | --- | --- |
| DINO/SAM2へsky/building等を追加して後処理 | 現配置を再利用できる | 各promptの独立検出は排他でない。誤った高scoreに勝者を決めるだけでは悪化し得る。比較基準として残すが主方式にしない |
| Mask2Former ADE Swin-T | 小型、semantic mapを出せる | コードMITでも公式重みNC。M4のopen重み必須条件から不採用 |
| OneFormer ADE Swin-L | 著者checkpointはMIT表示、semanticの単一クラスmap、既存Transformersに実装 | 第一候補。8GB/12GBのVRAM・精度は未測定で、品質合格までは本番採用しない |

### 入出力と競合規則

- 色を読むprep画像のSHAと幅・高さを固定し、同じ座標でsemanticを後処理する。
  推論resize・pad・復元設定をhashへ含め、class mapは整数PNG、最終bool maskは無補間とする。
- checkpoint revision・重み/processor/tokenizer/id2labelのhash・torch等の版を固定する。
  対応表はクラス名で点検し、ADE注釈IDとモデルIDの1ずれを許さない。
- sky/person/対象外は色の採用領域から除く。建物と地形の役割maskは交差0にする。
  部位ごとの許容semanticクラス表を事前固定し、treeをmountain/rock/snowへ許容しない。
- building全体をwallの正解とはしない。屋根/開口等の対応と部位品質はCMP等で別に検証する。
  粗分割で区別できない壁・屋根の誤りが残れば、Bの幾何条件を満たしてもDの品質は不合格とする。
- 同じ親役割の候補（wall内の3ラベル、tree内の幹/樹冠）は和集合で1回だけ計数する。
  異なる統計役割が競合し、semantic対応でも解消できない画素はvoidにする。scoreだけで勝者を捏造しない。
  子ラベルの未確定な重複は診断用候補として残し、個別supportedへ昇格させない。
- raw候補と有効role map/maskを別artifactに保全する。空・人物・競合・役割欠測の画素/画像数を残す。
  空mask・全面voidを成功精度と扱わない。coverage・recall・IoUを必ず併記する。
- Bの出力はsemantic map、sky/person mask、effective role mask、policy/revision/hash、除外理由。
  新policyのshade/color/snapshotはeffective maskを共有payloadで明示参照し、raw候補へ戻らない。
  wall/treeは新runの有効role maskから直接色を計算し、旧版のraw Region ORを誤って再利用しない。
  taxonomyへsky/personや親roleを架空の子ラベルとして追加しない。

GPUは1 host 1推論slot、batch=1。OneFormerとDINO/SAM2を同時常駐させない。
入力上限を固定して両hostでsmoke・ピークVRAMを測り、8GBで不適合ならubuntu-2粗分割先行へ分担する。
その場合も共有artifactのSHA・寸法・run参照を#66 runnerで固定する。暗黙の縮小やモデル代替はしない。

## A：画像単位のゲート

### 置き場所・推論

収集登録後、重い解析へ入る前のreview jobとして置く。D15・保持・送信可能性を先に確認する。
収集は候補を保存し、内容合格枚数は別台帳で数える。検索中のAPI成功を取得登録取引に結合しない。
既存画像にも同じ経路を使え、API停止がCommonsの取得取引を再実行させない。

OpenAI Responsesを直接呼び、model=gpt-6-luna、reasoning.effort=low、store=false、toolsなし。
これは製品内の画像推論であり、開発を委譲するAPIワーカーではない。Codex/ChatGPTプランや別モデルへ代替しない。
実装は既存urllib/jsonschemaを使い、APIキーは指定の秘密管理からworkerのプロセスへだけ渡す。
今回キーの探索・コピー・配置はしない。UbuntuへのAPI認証配置は実行準備の確認条件とする。

APIへはEXIF等を除いた長辺1024px画像と固定promptだけを送る。asset ID・出典・所見は送らない。
画像内文字を指示として扱わない。試験promptを基準にschema/promptを版管理し、変更した版を再評価する。
出力はtarget、subject(building/terrain/mixed/other/unknown)、実在人物(present/absent/uncertain)、
室内・白黒・暗所、固定reason code。人物の同定や要配慮属性の推測は要求しない。
schema不適合・refusal・incomplete・不明・mixed・方針未決定の白黒等は保留で、採用に変換しない。

### 保存・上書き・後続契約

- review jobのkindで画像内容判定を既存の取得品質reviewと区別する。stage enumは増やさない。
- 原判定JSON・usageは私有artifact、ProcessingRunへrequested/returned model、effort、prompt/schema/policy版とSHA、
  画像SHA・前処理版、request ID、費用根拠を保存する。返らないmodel実版は確認済みとしない。
- 有効入力SHA・要求モデル・effort・prompt/schema/policy hashを再利用キーにする。同一画像の判定を共有しても、
  assetごとの権利確認・subject整合確認は省略しない。旧試験応答を黙って本番承認へ転用しない。
- 人の訂正は元runを入力とする別review runへ追加する。元判定・旧quality・M3のasset行を変更しない。
  新しいrun選択で有効判定を決め、過去のsnapshotが参照する判定は動かさない。
- 共有selection/payloadにimage_gate_run_id、privacy_review_run_id、region_policy_run_idとそれぞれのhashを追加する。
  analysis_domainは確認済みsubjectから新selectionへ固定し、旧Asset.domainという検索意図を上書きしない。
  既存の確定subjectのdomainと矛盾する場合は保留で、既存Subjectや関連付けを付け替えない。
- 新policyのcheck_privacy・snapshotは明示runを検証する。新policyで失敗した結果を旧quality.privacy_reviewへ
  fallbackしない。旧run・旧snapshotの読取り再現だけは既存の契約を維持する。

### 費用・失敗

USDの整数最小単位でapi_budget/api_callを管理する。既存の画像/API/byte枠で代用しない。
予算IDと料金版を固定し、取引内で確定額＋不明請求＋予約額＋次要求上限がcap以下のときだけ予約する。
画像入力tokenは公式count機能を使い、非対応・料金上限を算出不能なら本判定を起動しない。
上限予約は非キャッシュ側の価格・適用され得るcache書込み・出力上限を含め、平均実測額で予約しない。
count等の補助要求も要求数と費用確認の対象。実usageで精算し、不明請求を0円として解放しない。

1画像1foreground要求を既定とし、リトライは台帳と同じ試行キーで制御する。
429/一時5xxはRetry-Afterを尊重して延期し、最大3試行。連続障害・quota/billing/authはバッチ停止。
応答消失・タイムアウトで課金/完了不明なら自動再送せず保留し、保存応答があれば再利用する。
lease切れ・再起動・DB確定失敗後も二重送信/二重請求を防ぐ。費用cap未決定なら本番起動を拒否する。

## C：人物

推奨する初期運用は、Lunaの実在人物present/uncertainを画像単位で保留する方式。
semantic personとLunaの不一致も保留し、陰性1モデルだけで採用しない。
人物ありを永久除外するか、maskで救済するかはユーザー判断が必要で、現在は未確定。

mask方式を選ぶ場合はOneFormer personを画素候補とし、必要なDINO/SAM2補助との和集合を評価する。
元画像と同じ座標の画素maskを固定し、gpt-imageやLunaの大まかな位置を画素maskへ変換しない。
群衆・小人物は取得画像の高解像度で検証し、prep座標への変換・膨張・寸法・SHAを固定する。
Lunaが人物ありなのにmaskが空、不一致、未検証なら保留。新しいmaskではshade/colorも新runにする。
人物の見落としの許容基準・検証標本数もDの実行前に決める。13件中3人物の試験だけで安全としない。

## D/E：品質評価と携帯端末での人確認

- 旧138枚と今回の既知失敗例は開発・回帰用。修正後の合格用標本へ混ぜない。
- 新しい固定seedで旧/新cohortから各50枚を選び、重複画像と既知試験画像を除く。
  結果を見る前に対象とhashを固定する。全体率を出すときはcohortごとの分母を使い、50:50を母集団比率としない。
- 追加の閾値付近・不一致・人物疑い・白黒/暗所例はchallenge集合として分け、無作為率へ混ぜない。
- Eは原画像・クラス別の単独画像・輪郭線を縦1列へ並べる。色blendを使わず、文言/線種/凡例でも区別する。
  画像をdata URIへ埋めた単体HTML、各25MB以下（必要なら2分割）、通し番号と私有asset対応表を作る。
- rawだけの確認と予測比較を区別できる表示にし、予測を見た後の確認を完全な盲検と主張しない。
  ユーザーは全件確認済みと問題番号・理由をチャットで返す。JSON作成・Windows操作は要求しない。
- 未提示を人確認済みにしない。問題番号は理由付き保留、人の変更は別runへ記録し、解析差分と承認を失効させる。
  Cの人物方針を保留から採用へ自動変更するような包括承認はしない。
- #81旧指標を再現した上で、ADEのsky/building等の既知負例を含む全非void画素、クラス別混同行列、
  precision/recall/IoU、void・coverageを出す。CMPの部位GTを使い、ADE buildingをwall正解へ追加しない。
  voidと意味不明な対応は理由別に分け、都合の悪い負例を評価から消さない。
- ADE学習済みcheckpointをADE validationで測る値は公開benchmark診断であり、所有画像への独立保証ではない。
  旧617枚との対応比較と全validationでの診断を区別し、新しい所有画像の人確認も行う。
- 新しい品質目標（役割precision・coverage/recall・人物見落とし許容）と対象定義を事前に決める。
  旧precision>=0.50を新方式の安全性合格へ自動継承しない。空予測・全面voidも不合格とする。

## Gと#114：旧版・M4・再生成範囲

Gで旧固定7,607 assetを新方針で再評価し、許可された新runだけから旧母集団の訂正版基準を作る。
旧snapshotやasset/subject行は変えず、権利停止・保持条件を再確認する。
新しい全体判定で外れた画像は、分母・理由・SHA代表・subject・n_effへの影響を残す。
成功prep・raw部位候補は入力/model/prompt/前処理hashまで一致する場合だけ再利用できる。
有効maskや色観測を旧版のまま流用せず、新policyの入力辺・hashを持つ別runへ固定する。

#114では新規2,600枚を同じ方針で判定するが、元の保留993枚は別判断なしに再採用しない。
旧訂正版と旧訂正版＋新規の2版を比較し、旧#105 v2からの方式変更と画像追加の効果を分ける。
適格画像・SHA代表・subject・n_eff・補正率・情報なし・supported・条件4・実ソース内訳を比較する。
Commonsへの偏り、source_share固定上限0.8、集中枠は維持する。追加収集はこの修正の実行に混ぜない。

M3固定7,607の履歴と#105 v2を消さず、新しいpolicy/snapshot/build IDで訂正版を発行する。
M4と配色パックは新しい品質合格snapshotを明示選択し、旧版aliasを自動で差し替えない。
公開allowlistを維持し、画像・mask・個別API判定・ID・自由文を出さない。
既存pack formatは数値・policy/build版で表現できる限り維持し、外部schema変更は別契約確認を要する。
品質未達なら旧版へfallbackして新パックを公開せず、どちらも品質未確認として保留する。

## 費用・時間の推定

私有試験と同じCLI経路・平均単価0.002922 USD/枚、3.315秒/枚を仮定した参考値。
直接Responses・prompt/schema変更後の値は未測定で、実行予算や品質保証ではない。

| 範囲 | 枚数 | API参考費用 | 直列参考時間 |
| --- | ---: | ---: | ---: |
| 新規 | 2,600 | 7.60 USD | 約2時間24分 |
| 旧固定cohort | 7,607 | 22.23 USD | 約7時間 |
| 旧＋新の実対象上限 | 10,207 | 29.83 USD | 約9時間24分 |
| DB全件を仮定した参考上限 | 10,226 | 29.88 USD | 約9時間25分 |

最後の19件まで権利除外を解除して送る設計ではない。同一の正規化画像のAPI結果は再利用できるが、
その減額を事前capへ織り込まない。429・再試行・確認待ち・GPU処理・検証費用は上表と別。
実装と検証の目安：A 2〜3日、B 3〜5日、C 1〜2日、E 1日、D 2〜4日、G 1〜2日、#114 1〜2日。
A/Bの並列を使っても全体約8〜15作業日＋GPU/API・人の確認待ち。性能達成・終了日時の保証ではない。
GPUの総所要時間はBの100画像計測で確定し、旧SHA代表3,570＋新規2,600だけを全再処理数と断定しない。
従来の解析不足画像も含むため、候補は7,607＋2,600 assetの固定集合から改めて選ぶ。

## 未確定と実行停止条件

作業依頼末尾の指示に従い、判断待ちを含むIssueも本文に明示して作成する。
未回答の数値・方針を既定の承認としない。

1. API費用cap、補助要求・再試行・評価用を含む予算範囲、Ubuntu認証の配置。
2. 人物presentを保留・永久除外・mask救済のどれにするか。推奨は当面保留。
3. 建築部位接写、mixed、白黒/暗所の扱い。試験は接写5枚も除外し対象外21枚、診断の明示所見は16枚で定義が異なる。
4. 新品質ゲートのprecision/coverage/recall・人物見落としの許容基準。
5. 保留993枚を将来再採用対象へ戻すか。決定までは除外継続。

Issue作成は実装・API費用・本番migration・解析サービス起動の許可ではない。
本段階の検証は資料・依存・文書整合・Git差分だけとし、製品コード未変更の全pytestは繰り返さない。
