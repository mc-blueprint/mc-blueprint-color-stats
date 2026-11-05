# Issue #90 原本・API縮小の対応比較

## 100件の追加評価（2026-11-05）

ユーザー指示に従い、収集済み原本を読み取りだけで使い、縮小だけを取得した。
固定100件の成否は **acquired 98、thumbnail_not_smaller 2**。品質比較は98/100件、未評価は2/100件。
小原本は1280幅で縮小が成立しないため、原本へのfallbackや便宜的な同一画像比較を行わず分母に残した。
追加取得はAction API 2/10、縮小98/100、原本0/0要求。
APIは最大50件のimageinfo batch、mediaは同時1（上限2）・25Mbps/10秒・終了後1秒。
標準幅1280、Retry-After、/archive/除外、既存UAを維持した。

### 選定と原本の不変性

本番DBには接続していない。#74の固定snapshot
`/mnt/data/derived/stats/issue74-full-20261104T180829Z/snapshot/`と、
既存`bench/issue47/raw-manifest.json`を読み取り、NFS原本を参照した。
母集団は権利適格Commonsの既存原本で、SHA-256ごとに最小asset UUIDを代表とする。
これは#74の独立画像単位であり、pHashによる自動統合や同じsubjectの別写真の削除ではない。
原本を復号できないPillow標準上限超え1件を選定前除外し、
残る175 SHAから建築・地形各50件を選んだ。

順位はSHA256(`issue90-existing-v1:`＋原本SHA256)。各分類で縦横各25件を目標とし、
不足する向きは同じ順位の残り候補で補充。各分類に幅1280以下を1件含め、残りは幅1280超とした。
実内訳：real_building:landscape=32、real_building:portrait=18、real_terrain:landscape=41、real_terrain:portrait=9。小原本2件。
選定は追加API・画像取得と品質比較の前に固定した。ID、原本path、SHA、規則、入力hashは
`existing100/selection.json`に記録。元データの分類であり新しい人手正解ではない。
既存14組との原本SHA重複は0件だったため、その解析の再実行も重複縮小取得も発生していない。

選定した100原本のSHAを読み取り時と終了時に照合した。移動・書込み・削除は行っていない。
原本SHA-1もAPIの現在版と照合し、版不一致ならarchiveへ遡らず理由付き失敗にする。
画像byteのSHA-256とprovider/native ID＋revision＋variantを区別する。

### 容量と時間

対応する取得成功ペアの原本ファイル合計は **678,067,949 byte**、
縮小は **48,908,329 byte**、容量差は **92.79%減**。
原本の新規通信は0 byte。全100件の原本読取り・hash確認は2.581秒。
縮小の取得・待機込み合計は293.508秒、
通信時間は191.644秒、
通常待機は97.996秒、
帯域待機は0.000秒。
原本読取り時間は原本のネットワーク取得時間ではないため、速度改善率を算出しない。
原本/縮小のSHA不一致は98組。これを独立subject支持の証拠にはしない。

### 品質（分母100、評価可能98）

| 指標 | 平均 | 中央値 | 最大 |
| --- | ---: | ---: | ---: |
| pHash距離 | 1.204082 | 0.000000 | 32 |
| 主色OKLab距離 | 0.015433 | 0.001508 | 0.496335 |
| 5色面積重心のOKLab距離 | 0.002346 | 0.000964 | 0.088592 |

bool品質フラグ反転：{"watermark_suspected": 5, "blur_suspected": 2, "collage_suspected": 1}。
主要部位一致は0.869385、細部一致は0.870385。
同ラベルinstanceを和集合にし、交差画素数/和集合画素数を合算した値である。
細部はwindow_frame/column/cornice/relief、他の指定ラベルは主要部位。
人手正解がないため正解IoUは未評価。一致度を精度とは扱わない。

最大主色差のindex 12はpHash距離0・面積重心距離0.000365だが、5色クラスタの面積構成が変化した。
主色1クラスタの距離だけで画像全体の色差を代表させない。index 88では原本I;16→縮小Lの形式差があり、
面積重心距離0.088592・pHash距離22だった。ICCの有無・EXIF方向とともに`existing100/outliers.json`、
最大主色差のクラスタ値は`existing100/outlier-colors.json`へ記録した。既存prepの変換仕様は変更していない。

既存prep（RGB、長辺512以内LANCZOS、JPEG品質90）、SAM2＋DINO、閾値0.35/text 0.25、
seed0・bfloat16・batch1、既存colorを両側へ同条件で適用した。
新しいモデルAPI・人手正解・品質閾値の合意・既定切替は含めない。
固定モデル・不変入力のhashは同一解析process内で再利用する。途中の成功stageは上書きせず再利用した。
モデルと変換条件は`existing100/analysis-config.json`、実環境の版はsummaryのruntimeを参照。

### 永続保全と再現

永続保存先は`/mnt/data/derived/issue90-20261105/`。既存/tmpの56画像と全出力を`previous14/`へコピーし、
全画像のSHAを照合した。`preservation.json`に旧path/新path/hashを記録している。
新100件は`existing100/`、初回コードは`code/`、hash再利用で再開したコードは`code-resume/`。
元の/tmpデータ、既存原本、snapshot、旧コード・成功済み出力を削除・上書きしていない。
本番DB・#77-v1・M3 cohort・pilotサービスは変更していない。

再現時は`existing.py --root <新規保存先> --snapshot <上記snapshot> --raw-manifest <上記原本索引>`で
選定と予算を固定し、追加通信を許可された範囲で同コマンドの`--fetch`を実行する。
続いて`compare.py --root <保存先> --models <既存モデル> --analysis-id analysis`、
`summarize.py --root <保存先> --output <新規report先>`を使う。
旧14組を再利用する場合だけ`--reuse-previous14`を指定し、親のprevious14を保全済みとする。
省略時は旧14組を読まない。再利用時はSHAとvariantの一致を確認する。
100件の成否・未評価と各組の数値は`existing100/comparison.json`、集計は`existing100/summary.json`。

## 初期14組（別の固定入力・参考値）

当初はAPI114・原本28・縮小28要求の予算内で14組を比較し、残り86枠を未評価としていた。
この不足を上記の既存原本100件で補った。母集団が異なるため両者を混ぜて平均しない。
初期入力・比較値は従来の`fixed-input.json`・`comparison.json`・`summary.json`に保持する。
初期14組の原本200,624,430→縮小6,495,498 byte、1秒間隔の経過時間74.226→26.871秒。
0.5秒間隔では62.903→16.214秒。cache・順序・WAN変動を相殺した因果実験ではない。

## 実装と後続契約

- 原本既定を維持してCommonsのthumbnailを明示選択する。小原本・欠落・版不明は理由付き除外。
- 受信SHA/寸法/MIMEと原本情報を分離し、原本URLおよびnative ID/revision/variantで予約・再投入を抑止。
  SHA不一致やpHashだけでsubjectを確定しない。既存asset/runは不変。
- #91：api/target・実hostイベントを維持し、thumbのrate_groupをuploadと合算する。
  別spawnの帯域台帳復元を回帰検証済み。同時processの原子的な共有予約は#91の担当。
- #92：LoCでも原本と別variantのURL/実寸/MIMEを分離し、取得モード対応を明示追加する。
- #94：Mapillaryの失効URLをnative IDにしない。解像度違いと連写を独立支持へ水増しせず、
  規約全文・用途・大量保存条件・token登録の開始条件を維持する。
- #104との境界：stats/、license_rules、rights_reviewを変更していない。

公式根拠：[thumb host移行](https://meta.wikimedia.org/wiki/Tech/News/2026/36)、
[Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)、
[Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy)。
thumbのrobots確認はHTMLへredirectしたため本文確認済みとはしない。公式Media API経路だけを使う。
chunked応答のread(-1)混入とthumbmime要求漏れは修正し回帰検証した。

## 検証と残る判断

反証修正後の最終差分はWSL Ubuntu-24.04のext4コピーと新規の隔離PostgreSQL16で
全pytest 878成功・1スキップ。ruff・sdist/wheel・diff checkも成功した。
スキップはSEGMENT_GPU_MODELS未指定の専用smokeであり、本比較の実GPU実行とは別である。
検証ログ・build出力は`/tmp/colorstats-issue90-review-3xtKPS/`、一時PostgreSQLは停止済み。
追加100件は固定ID・一意SHA・予算・保全・原本不変を監査済み。比較データは再取得していない。

反証修正では原本のPillow検査を外して従来のAPI寸法・MIMEを維持し、縮小だけを検査する。
原本のAPI SHA-1がある場合は受信物と照合し、不一致は`original_sha1_mismatch`として
予約を解放・候補を除外してバッチを継続する。SHA-1欠落時の扱いは維持する。
再利用assetのSHAではなく受信SHAで計測し、旧14組の読み込みは`--reuse-previous14`指定時だけとした。
上限超過原本、SHA-1一致・欠落・不一致、variant再利用のSHA計測、旧14組なしの100件選定を回帰検証した。
品質許容差・最低実解像度・既定切替はユーザー判断を待つ。追加画像取得や本番再計算は行わない。
