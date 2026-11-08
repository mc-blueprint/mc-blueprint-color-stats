# 可視壁材v2：実装・両GPU評価

**両GPUとも不合格。建物統計の見送りを継続し、PRはRefs #130とする。**
検出部位のunionを壁から差し引く方式は動作したが、除去maskがGT壁を広く覆い、
可視壁材を残せなかった。結果を見て定義・GT・分割・prompt・閾値を変更していない。
旧評価・旧decisionは維持し、別版の[decision](visible-v2-decision.json)を保存した。

## 予測前固定と評価範囲

- [事前設計](visible-plan.md)、[公開freeze](visible-v2-freeze.json)。新評価版
  `issue130-visible-wall-eval-v2`、method `oneformer-visible-wall-v2`、
  policy `visible-wall-policy-v2`。
- private freeze SHA：`e4c151e861ae57e225a0a50c87a1903f1e3410b825524861c2a8d46c34ad26b9`。
  policy SHA：`6a3ee354dc9c8be3dab33e7cee5219528166704a1bd66f5d045fbc3c6aa80ab1`。
- 壁GTはCMPのPNG ID 2（部位で上書きされた後の残り）。全非void画素を評価し、
  背景・窓・装飾等を負例から外していない。ADE buildingを壁GTへ追加していない。
- 既知のCMP606枚・ADE617枚、seed73の元tune/holdoutと、旧regular候補・semanticを維持。
  RGB/GT/候補/semanticをSHA検証した1223個のnpzと台帳を新予測前に固定し、同じ束を両GPUへ渡した。
- **新たな確認**は、CMP606枚の補助3prompt推論を両GPUで実行し、
  元のholdout282枚でそれぞれprecision>=0.80かつrecall>=0.30を要求したもの。
  tuneも保存したが再選定しない。既知公開GTへの新推論であり、独立した新GT・盲検ではない。
- dataset別の旧regular promptを使う全件評価と、全本番26＋補助3promptの新規6枚smokeを分離。
  後者のCMP3/ADE3は新予測前に入力SHA順・固定seedで抽出し、両GPUで同じ画像を使った。
  全本番29promptの全件品質、所有画像の独立GTは未検証。

## 方式

既存OneFormer/DINO/SAM2・親表・artifact・#121の全非void計数器を再利用し、依存・migrationを追加しない。
通常候補の検出は0.35/text0.25、壁と他建物の出力採否は>0.55、地形は>0.35。
除去対象の開口・柱・屋根・装飾等は>0.35でunionし、**semantic親で切る前**に壁から除く。
taxonomyにないbalcony/shopfront/window sillは補助候補として追加し、Region語彙を増やさない。
同じ親の壁はunionし、残る異role競合はvoid。scoreで画素の勝者は作らない。
検出されない部位をGTや別クラスで補完しない。

補助raw・除去画素・有効roleは新segment runの同一契約へ保存する。
raw Regionは保全し、shade/color/privacy/selectionは有効maskと同じrun参照を使用する。
旧v1を変更せず、新v2だけclass-infoをJSON内容でhashし、CRLF/LFの差を除いた。
runnerはv2のモデル構成・再利用拒否・OOM停止へ対応した。
詳しくは[API/契約](../../docs/visible-wall-v2.md)を参照。

## CMP holdout 282枚：新評価版の合否

| GPU | TP | FP | FN | TN | precision | recall | IoU | 判定 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ubuntu-1 / RTX4060 | 1,749 | 28,641 | 21,130,527 | 32,347,245 | **0.057552** | **0.0000827644** | 0.0000826524 | failed |
| ubuntu-2 / RTX4070 | 1,644 | 28,347 | 21,130,632 | 32,347,539 | **0.054816** | **0.0000777957** | 0.0000776915 | failed |

旧specific55はprecision0.445507・recall0.569862だったが、旧版の判定は変更しない。
新たに部位を差し引いても、狙った壁面を残せず、現行の単純差引きは改善として採用できない。
全GT IDへのヒストグラム、各群のTP/FP/FN/TN・coverage/voidと判定は
[ubuntu-1](visible-v2-ubuntu1.json)、[ubuntu-2](visible-v2-ubuntu2.json)に保存した。
画像ごとのsmoke記録はprivateへ残し、Git側はdataset集計にした。

### 削り過ぎ・見逃し・欠測

| 指標 | ubuntu-1 | ubuntu-2 |
| --- | ---: | ---: |
| 壁候補から除去した画素 | 33,936,216 | 33,936,610 |
| うちGT壁（親制約前の候補上） | **14,867,521** | **14,867,611** |
| うちGT非壁 | 19,068,695 | 19,068,999 |
| 有効壁に残った部位FP | 4,708 | 4,647 |
| 壁が全欠測の画像 | 144/282 | 145/282 |
| 有効壁画素総数 | 30,390 | 29,991 |

部位FPは減ったが、同時にGT壁の大部分も除去した。残存壁は全画像画素の約0.057%だけで、
残るFPは主に背景（23,933/28,641、23,700/28,347）だった。
この残存FPと削り過ぎが両立しており、部位混入をゼロにするだけでは合格しない。
除去したGT壁の数は「raw壁候補上のGT壁」であり、元から親や競合で落ちる画素も含み得る。
実写真上の壁材の厳密な正解ではないというCMP矩形GTの限界も維持する。

全roleのcoverageは10.9756%/10.9748%、voidは89.0244%/89.0252%。
これは他部位も含む値で、壁のcoverageとは区別する。群間重複は0。
空予測・全面voidによって合格にしていない。CMPの全群はfailed。
ADEではstairs/tree/waterの群指標は基準を満たすが、壁以外へ採用範囲を広げていない。

## 壁色のずれ：前回と同じOKLab平均

各sRGB画素を復号してOKLabへ変換してから平均し、平均間のユークリッド距離ΔOKを求めた。
L=0〜1、100倍なし、shade補正・k-meansなし。
P=有効壁、G=CMP facade、TP=P∩G。両maskが非空の画像だけに定義し、未定義を0差にしない。

| 比較 | ubuntu-1 件数/282 | ΔOK画像平均 | 中央値 | 95%分位 | ubuntu-2 件数/282 | ΔOK画像平均 | 中央値 | 95%分位 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P対TP | 111 | **0.04866** | 0.02938 | 0.15901 | 105 | **0.04449** | 0.02693 | 0.15755 |
| P対G | 138 | **0.11192** | 0.08493 | 0.29353 | 137 | **0.11082** | 0.08401 | 0.28188 |

P対TPは171/177枚が未定義。P対Gは144/145枚が未定義。
前回specific55のP対TPは0.05266（234枚）、P対Gは0.05238（236枚）。
新方式のP対TPだけを見ると小さく見えるが、残した画素・計算できる画像が大幅に減っている。
同じ評価可能集合の改善量ではなく、壁全体Gとのずれも大きいので、色品質の改善とは扱わない。
材質色そのもの・本番パレット・subject重みを検証した値でもない。
画像別平均と色差はprivate、Gitには分布とpool平均だけを残した。

## 地形・同親union・競合・旧版の回帰

- 両GPUとも、旧policyに対するtree/waterの**全1223枚の画素差は0**。
  treeのprecision0.940182・recall0.534000、waterの0.981858・0.852000を維持。
- 合成maskで、同親union・除去maskのunion、部位の親が不一致でもrawから差し引くこと、
  削り過ぎ・見逃し・厳密閾値・残る異role競合void・入力不変を検証した。
- segment→color/shadeの隔離DB統合で、raw保全、補助候補の別artifact化、有効壁42画素、
  同じsegment run参照を確認。genericなprivacy/selection読取器は同じ契約を検証する。
  所有画像でのprivacy/人確認取込は本タスクでは実行していない。
- 新methodの補助prompt追加・工程間解放・模擬OOM送出、runnerの停止・再試行不可、
  旧run・SHA差替え・policy版差替えの拒否、class-infoのLF/CRLF不変性をテストした。
- 旧v1のhash・処理は維持し、旧評価・旧decisionを新しい定義へ読み替えない。

## GPUと必須検証

開始前は両GPUとも空き。host別slot lockを保持し、全件loopは画像前に外部GPUプロセスを確認した。
全本番promptのsmokeも同じlock内で実行した。終了後に残存プロセスがないことを確認した。
1 host 1 slot、batch1。補助工程はDINO/SAM2だけを常駐させ、
全prompt工程ではOneFormerを解放後に候補モデルを実行した。
実OOM・モデル取得・代替・暗黙の縮小はなし。固定512px入力の適合であり、最大2560px等を保証しない。

| GPU | 1223件loop秒（CMP606補助推論を含む） | 全工程秒（6枚smoke含む） | 補助工程peak allocated bytes | 補助工程peak reserved bytes |
| --- | ---: | ---: | ---: | ---: |
| RTX4060 8GB | 747.17 | 814.02 | 2,321,626,624 | 6,119,489,536 |
| RTX4070 12GB | 489.13 | 528.92 | 2,320,663,040 | 6,119,489,536 |

torch2.11.0（cu130/cu128）、transformers4.57.6、既存重み全SHAを照合した。
GPU間で補助maskと最終値は完全一致しておらず、各GPUを別に判定した。
全6枚smokeのstage合計時間・VRAMとCMP/ADE別指標も各GPU集計へ保存した。

最終WSL Ubuntu-24.04 root・隔離PostgreSQL16：**1389 passed / 1 skipped**、383.32秒。
全ruff・sdist/wheel build成功、既存warning4件。skipは従来の実GPUテストで、今回のGPU評価とは別。
検証artifact `/tmp/colorstats-issue130-jtA3TN`、DBは正常停止。
ログ `20261108T114841Z-63e4d61f36b24e75b554230ce2efd12f.jsonl`。
前段1386件版も成功後、新methodのOOM等3ケースを追加した最終構成を全件検証した。
一時venv消失時はlock/cacheから隔離環境を再作成し、既存GPU環境へ依存を追加していない。

private原本：

- ubuntu-1：`/home/toumokorosi/issue130-20261108/visible-v2-20261108/`
- ubuntu-2：`/mnt/data/work/issue-130/visible-v2-20261108/`

入力台帳・npz・画像・各補助raw・policy/mask・画像別色はこの領域に保全した。
Gitは集計・コード・版/hashだけ。本番DB接続/更新0、統計更新0、migration0、push0。
公開文面は指定scratchpadのi130-commit.txt、i130-pr-title.txt、i130-pr-body.mdへ保存する。

## 改善の余地と次の案（今回は実装しない）

1. 除去ラベルごとにGT壁を巻き込む面積と境界を診断し、どの候補がunionを過大にするか分離する。
2. 除去候補の採否と部位maskの範囲を改善する。壁全体を覆う候補をそのまま差し引かない方式を
   調整集合で検討し、部位の見逃しとの交換条件を別版の予測前に固定する。
3. 壁の定義・負例・precision0.80/recall0.30は維持し、同じ既知回帰と独立した確認を分けて再評価する。

今回の数値を見て閾値を上げる、負例を外す、GTをFacade全体へ広げる変更はしていない。
scoreによる競合勝者への変更もしない。建物統計を見送り、合格済み地形の先行を妨げない。
