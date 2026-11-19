# VLM 30件比較の私有入力・結果契約（Issue #141）

この機能は入力準備と結果照合・比較HTMLだけを扱う。送信、GPU推論、課金、
本番run・提示登録、返信取込みは行わない。後続#142がこの契約を消費する。
#114のdelivery-v3はレビュー中止済みで、旧返信を新方式の承認へ流用しない。

## 保存先とCLI

`result_root` は、Git管理領域の外にある、未作成の絶対パスを必須とする。
親は既存で書込可能でなければならない。symlink、既存出力、相対パスを拒否し、
別ホストや別パスへfallbackしない。集約先PCが未決定でも同じ指定方法を使える。

```sh
python -m colorstats.trial_cli demo --result-root /private/new-synthetic-trial
python -m colorstats.trial_cli prepare --reviews /private/reviews.json --legacy /private/legacy.json --result-root /private/new-trial
python -m colorstats.trial_cli recheck --result-root /private/new-trial
python -m colorstats.trial_cli render --result-root /private/new-trial --configurations /private/configurations.json --results /private/results.json --active-attempts /private/active-attempts.json
```

これらは手順例で、実行済みではない。DBを使うprepare/recheckは既存の安全な
環境変数注入でDATABASE_URLを受け取り、値を引数・ログへ出さない。DB側で
REPEATABLE READ・READ ONLYを指定し、必ずrollbackする。prepare/recheckは、
DBの原画像パスを読める環境で使う。原本の所在を勝手に別ホストへ向け直したり、
新たな共有・転送を自動設定したりしない。集約前は既存の許可済み配置で準備できる。
CLIの標準出力は件数または利用期限だけで、内部対応は出力しない。
demoは合成画像とダミー結果だけで全経路を確認し、manifestとHTMLにも合成と明記する。
実写真の選定、実モデルの動作・精度、送信許可を示すものではない。

## 選定と確認参照

reviews.jsonは私有の行配列で、各行に以下が必要。

| 項目 | 意味 |
| --- | --- |
| asset_id | ローカルDBの内部対応。外部へ出さない |
| source_sha256 | 場面・人物を確認した元画像のSHA-256 |
| subject_group | 確認した建物のsubject参照。現在のDBと照合する |
| scene | single / interior / group / gate / closeup |
| people | absentだけを受け付ける。不明・人物ありは保留 |
| scene_ref、person_ref | その元画像へのローカル確認記録の参照。空欄を拒否 |

旧OneFormerの判定や中止した返信を新しい確認根拠に置換しない。これらは
ローカルで確認済みの記録を渡す境界であり、文字列があるだけで人の判断が正しいと
証明するものではない。確認がそろわない実写真は未選定とする。

legacy.jsonはversion=delivery-v3、presentation_sha256、imagesを持つ。
presentation_sha256は旧4ページの番号表を束ねた私有参照記録のSHA。
imagesには旧108件のasset_id、source_sha256、16桁のphashを含める。
108件・一意性・必須参照が不足したら止める。実データはリポジトリへ入れない。

既存rights・利用停止・削除台帳を再利用し、openの合成区分と明示保持登録を要求する。
DBからSHA、pHash、元パス、subject、保持期限、既知重複関係を読む。
場面や人物の欠測を別の区分で補わない。

候補の内部対応順をそろえ、seed 20261116で並べる。調整は屋外1棟4・屋内1・群1、
確認は屋外1棟20・屋内1・群1・門1・接写1。建物群を両phaseにまたがらせない。
旧108件とSHA一致・pHash距離6以下・既知重複の連結先を除外し、選定内も同様に除外する。
固定seedと建物分離の配分で不足したら停止する。通常の選定中に組合せ探索や
配分変更は行わない。番号T001～T030の前6件が調整用。

### 建物ごとのphase指定

先着選定で不足しても建物単位の割当てが実現可能と事前確認できた場合は、
私有の準備スクリプトから`select_candidates(..., subject_phases=subject_phases)`へ
確定表を渡せる。表は全候補の`subject_group`を過不足なくキーに持ち、値は
`tune`または`confirm`だけとする。不正な表は`ValueError`で拒否する。
省略時は従来の先着選定を維持する。新しいCLIコマンドは追加しない。

同じ建物の異なる写真は同じphase内で複数採用できる。必要数を超えた写真は使わず、
反対phaseへ回さない。異なる場面区分に現れる建物と建物群にも同じ排他を適用する。
表は変更せず、seedによる並び順、重複除外、連番、`prepare`の検査を再利用する。
重複制約がある場合、建物ごとの写真数だけでは成功を保証できない。指定表でも
不足すれば停止し、自動で割当てを変更しない。

2026-11-18のユーザー決定では、調整は屋外1棟4・屋内1・群1、
確認は屋外1棟16・屋内3・群2・接写3へ変更された。
私有スクリプトで承認済みの配分を`trial_inputs.SPLITS`へ設定し、
選定と`prepare`の両方に同じ値を使う。既定配分は変更しない。
元候補・人確認表・配分決定・seed・phase表のSHAを私有の選定記録へ結び、
候補をREAD ONLYで再照合した後で適用する。元の場面・建物・人物の確認参照を
書き換えない。DBやmanifestの形式変更はなく、対応表を外部へ送らない。

## 入力と保持台帳

image_gate.normalizeを再利用し、元SHA再照合後、向き補正・長辺1024以下・拡大なし・
RGB PNG化・EXIF/ICC等除去を行う。元画像を変更せず、正規化後の重複も拒否する。

| 保存物 | 内容と送信可否 |
| --- | --- |
| manifest.json | trial-input-v1。内部対応、確認参照、元SHA、旧提示参照SHA、入力SHA・寸法、番号、phase、期限、synthetic。私有 |
| file-ledger.json | trial-files-v1。作成予定ファイル、SHA、期限。保存前に登録し、途中失敗分も管理。私有 |
| package/inputs.json | trial-package-v1。versionとimagesだけ。各行はtrial_id、file、sha256、sizeだけ |
| package/T001.png等 | 正規化画像。番号以外の元情報をファイル名へ含めない |
| configurations.json、results.json、active-attempts.json | 回収結果の固定記録。私有 |
| number-map.json、pages/ | 番号と案の位置対応、ページSHA・対象、比較HTML。私有 |

validate_packageはディレクトリを完全列挙し、未知ファイル・内部項目混入・
寸法・SHA・PNG内metadataを拒否する。#142はディレクトリを無検査で丸ごと転送せず、
この検査とrecheckを送信直前に実行し、別の送信・課金許可を確認する。
OpenAI専用の既存同意は他提供元の送信許可ではない。

ローカル期限は元期限と作成7日後の早い方。束全体は最短期限で利用を止める。
送信後の上限は24時間か元・ローカル期限の早い方。作成時から24時間と誤解しない。
recheckは送信直前と回収後に停止・期限・元SHA・コピーSHAを再確認するが、
送信を許可する関数ではない。syntheticは実写真の送信対象にできない。
期限でファイルを自動削除するschedulerは本Issueに含めない。#142はこの台帳を使い、
期限・停止要求を確認して自分の新設コピーだけを削除し、未削除を未完了として扱う。
元画像・旧成果物・本番保持台帳の登録は変更しない。

## trial-output-v1：#142への共有契約

configurationsはA～Eの5キー。各構成は次の項目をすべて持ち、未知項目は拒否する。

- model_revision、segmenter_revision：固定commit（40桁）。
- weights_sha256、environment_sha256、code_sha256、prompt_sha256、
  processor_sha256、segmenter_sha256：固定物のSHA-256。
- precision：A/B/DはBF16、CはAWQ4、EはFP32。
- A/B/Cのsegmenter_revision・segmenter_sha256は同一。
  D/Eは独立方式として、使用する分割器自身の参照を記録する。

結果は30×5の150行。成功以外も行を省略しない。各行の必須項目は以下。

| 項目 | 条件 |
| --- | --- |
| version | trial-output-v1 |
| trial_id、configuration_id | 固定30番号とA～Eの一対一対応 |
| configuration_sha256 | api_budget.digestによる構成辞書のcanonical SHA |
| input_sha256、size | 固定PNGのSHA・幅高さと一致 |
| attempt | 試行内の英数字・ハイフン・下線だけの実行識別 |
| status | success / missing / failed / rejected / truncated |
| scene | single / interior / group / gate / closeup / terrain / unknown。Eだけunsupported |
| regions | 最大24領域。part、box、mask以外の項目を拒否 |
| elapsed_seconds、peak_vram_mib | 0以上の有限数 |
| expense_ref | #142の私有費用台帳で解決する論理参照。英数字・ハイフン・下線のみ |

expense_refの文字列検査は請求額・費用台帳の照合ではない。実費・時間課金と
参照の解決は#142の責務。合成demoはnot_billedを使い、実費0の証拠としない。

partはwall、roof、window、window_glass、window_frame、door。
boxは0～1の左上x/y・右下x/yで、範囲外・反転・NaNを拒否する。
maskはfileとsha256を持ち、root内の相対パス、入力と同寸法の二値PNG（1bit/L）を要求する。
symlink・脱出・SHA差・寸法差・多値・色付き画像を拒否する。
失敗・拒否・欠測・打切り行のregionsは空にする。成功でも空領域は「正しい」とは扱わない。
窓全体と細部の包含を許し、全部位を一律に排他化しない。隠れた部分を補完しない。
maskの正しさや、主要部位の取得成功率はこの形式検査だけでは判定できない。

validate_result(root, manifest, configurations, row, active_attempts=...)で逐次回収した1件を検査する。
active_attemptsは試行番号をキー、その中のA～Eをキーとし、有効なattempt識別子を持つ辞書。
#142の実行管理状態から作り、受信結果のattemptを転記して作ることは避ける。
validate_resultsとaccept_resultsにも同じ辞書を必須引数として渡す。
共有検査は各画像・構成の有効attemptと受信結果を照合する。
保存・費用台帳更新はしない。同じ検査をvalidate_resultsでも使い、最終確定時だけ
全150行の過不足と重複も確認する。
accept_resultsが150行を照合し、回収mask・構成・結果・有効attempt表を同じ私有台帳で管理する。
事前登録済みmaskはSHAの完全一致と、登録期限が受領時点より後かつ入力束の元の最短期限以下で
あることを確認して再利用する。期限の短縮は受け入れ、延長・期限切れは拒否する。
保存済みの短い期限を書き換えず、追加登録も省く。未登録maskは元の最短期限で受領時に登録する。
read_resultsは受領時と同じ台帳照合を使い、各maskの登録・SHA・短縮期限を再確認する。
未登録・期限切れ・元期限超過は再読込みを拒否する。build_pagesもこの再読込みを先に行うため、
元期限が残っていてもmaskの短縮期限を過ぎたHTMLは生成しない。
不一致がある場合は受領確定を中止する。有効attempt表も保存時のSHAへ固定し、
再読込みと比較ページの番号表で照合する。
既存の受領結果を上書きしない。台帳更新・受領確定は単一writerで直列化し、並列GPUから直接同時更新しない。
各attemptの受信ファイルは#142が保存前に台帳管理し、
画像・構成ごとの有効attemptを更新し、最後に確定した150行と対応する有効attempt表を渡す。旧設定の結果は構成SHA差で拒否する。未対応の入力・台帳の版も拒否する。
実写真のrender CLIは、受領前にDBのrecheckを必須とする。APIを直接使う#142も
回収後のrecheckを行ってからaccept_results/build_pagesを呼ぶ。

## 確認ページと検証

旧mobileのJPEG・mask・透明輪郭描画をreview_htmlへ抽出した。旧関数名はimportで維持し、
旧提示登録・本番の必須参照検査は変更しない。新しいHTML検査は埋込画像SHA・番号・
UTF-8 byte数・重複属性・画像参照を検査する。
CSSはreview_html.TRIAL_STYLEの固定本文と、埋込画像に一致する
--photo:url('data:image/...')の属性指定を受け付ける。
変更したCSS、image-setやimage等の追加構文は拒否する。この生成CSSの範囲で外部参照0を検証する。

原画像と写真上の線描画を2列で並べ、写真の色を塗りつぶさない。
全面と空の領域は輪郭だけで誤解しないよう明示する。壁・屋根を先に表示し、窓・扉は開いて確認できる。日本語の定義を冒頭にも表示する。
番号ごとにseedを固定して案A～Eの位置を変え、モデル名・構成番号はHTMLへ埋め込まない。
位置対応はnumber-mapだけに保存する。

調整6枚と確認24枚を混ぜず、各12,500,000 byte以下へ分割する。1番号で超過した場合は
画像を勝手に変更せず拒否する。number-mapへ入力manifest・構成・結果・各ページの
SHAと番号・案の対応を結ぶ。旧返信の取込み機能は付けない。
返信は「番号: 使えそうな案を複数／なし／不明」、必要時だけ「案＋部位」。
まず調整6件だけを見て中止でき、長文所見・輪郭修正は求めない。

合成画像・ダミー150行によるE2E、重複・期限・停止・参照差・不正座標・mask・
HTML混入・上書き拒否、および隔離PostgreSQLでREAD ONLY強制と本番形式の行の不変を検証する。
CIは関連／全pytest、ruff、uv build。型検査の専用設定・コマンドは現CIにない。
実写真30件の選定・送信・GPU推論・モデル品質評価は未実施であり、#142の実行許可後へ分ける。

#142の実行・共通USD台帳・終了確認は [vlm-cloud-trial.md](vlm-cloud-trial.md) を参照する。


## 構成Dを省略する試行

構成集合はABCDEまたはABCEの2通りに限定する。A/B/C/Eは必須で、Dだけを省略できる。
30件×ABCEは120結果、ABCDEは従来どおり150結果とする。選択外のD結果や
不足・重複は受領しない。精度・固定参照・共通分割器・有効attempt・保持期限の検査は維持する。
比較ページは4構成なら匿名の案A〜案Dを表示し、実構成との対応は私有番号表へ記録する。
構成集合が変わった既存結果や番号表へ追記せず、別runとして作成する。
実行plan・smoke・費用の扱いは[クラウド試行](vlm-cloud-trial.md#構成dを省略する試行)を参照する。
