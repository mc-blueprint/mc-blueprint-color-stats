# #130 領域候補の診断・改善評価

**壁は不合格。建物の追加許可は空。** 事前固定した改善でrecallは回復したが、
precisionは0.80に達しなかった。合格条件・負例・GT対応・分割を結果に合わせて変更していない。
旧policy・raw候補・mask・run・統計、本番DB、画像ゲート#129は変更していない。

## 固定と再現

- 起点 `9698f12e740ec08bee145f15b614253db7b84f39`、`feature/issue-130`。
  [事前設計](plan.md)、[公開固定仕様](freeze.json)、[選定証跡](selection.json)。
- #121の読取器・全非void評価器を参照commit
  `17b8ddc652a610f7132bf739c690983ed87250b9`のSHAと照合して再利用した。
  #73のCMP 606枚＋ADE 617枚、seed=73、元のtune/holdout、画像・正解・raw候補・semanticを維持。
  入力ZIP、個別画像/GT、候補record/mask、semanticのSHA不一致は停止する。
- 新予測前のprivate固定仕様SHA：
  `6e2b37e65eca4ee08cb12b5ea4fc1828e06f2c353914ec1b004acd49fdd118a2`。
  個別semanticのSHA列はprivateに残し、Gitには集合hashだけを保存した。
- baselineの両dataset・両splitの全群TP/FP/FN/TN・全GTヒストグラム・指標・coverageは
  #121と**完全一致**。調整集合で選定を新規ファイルに固定してから確認集合を評価した。
  選定は事前ルールのF1最大によりspecific55。全候補が調整集合でも壁の合格基準に届かなかった。
- CMPは1〜12、ADEは1〜150の全非void画素。背景・sill・balcony・shop等も負例に残した。
  ADE buildingは壁GTに追加していない。公開既知GTの回帰比較であり、盲検・所有画像の独立保証ではない。

## 壁の確認集合（CMP 282枚）

合格条件はprecision>=0.80かつrecall>=0.30。全候補の壁はfailed。

| 候補 | TP | FP | FN | TN | precision | recall | IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 1,183,722 | 1,502,273 | 19,948,554 | 30,873,613 | 0.440701 | 0.056015 | 0.052297 |
| specific | 1,328,821 | 2,192,144 | 19,803,455 | 30,183,742 | 0.377403 | 0.062881 | 0.056971 |
| specific45 | 7,349,712 | 9,445,682 | 13,782,564 | 22,930,204 | 0.437603 | 0.347796 | 0.240360 |
| **specific55（固定選定）** | **12,042,491** | **14,988,465** | **9,089,785** | **17,387,421** | **0.445507** | **0.569862** | **0.333395** |

specificは直接対応クラスのある建物部位の親だけを狭めた候補。
specific45/55は建物候補だけの閾値を変更し、地形は0.35のままにした。
scoreは閾値にだけ使用し、競合画素の勝者は作っていない。

## 原因の分離

baselineの壁を同じ入力で段階別に計数した結果：

| 段階 | TP | FP | precision | recall |
| --- | ---: | ---: | ---: | ---: |
| raw・閾値0.35 | 17,144,589 | 23,065,926 | 0.426371 | 0.811299 |
| 親との積 | 16,944,186 | 22,656,105 | 0.427880 | 0.801815 |
| 同親union | 16,944,186 | 22,656,105 | 0.427880 | 0.801815 |
| 異role競合void | 1,183,722 | 1,502,273 | 0.440701 | 0.056015 |

壁の正例で親が除去したのは200,403画素、競合が除去したのは15,760,464画素。
この集合では親の除去より**異role候補の重複によるvoid化がrecall低下の主因**だった。
一方raw自体のprecisionも0.426371であり、候補を残すだけでは精度基準を満たさない。
部位親の絞込みと閾値変更ではrecallは回復したが、FPが残り不合格になった。
結果を見て追加promptや例外を探索していない。

全候補の段階別計数・除去した画素の正負内訳・prompt別FP/FN・全GTヒストグラムは
[summary.json](summary.json)。同親重複は候補の積算面積とunionとの差（重複度を含む）として記録し、
異role競合面積・有効role欠測数と区別した。
有効領域のcoverageは6.6195%→50.5583%、void率は93.3805%→49.4417%。
空予測・全面voidを合格にはしていない。
semantic参照のsky/person混入は各候補の有効領域で0。
これはOneFormer参照の診断値であり、独立GTでの人物・空の見落とし0を意味しない。
ADEのGT sky/personを含む各IDへの予測は群別ヒストグラムに残した。

## モデルID・部位・回帰判定

OneFormerのmodel ID 0はwall（ADE注釈1）、1はbuilding（ADE注釈2）。
CMPの注釈2=facadeは別データセットの部位正解であり、ADE注釈2へ読み替えない。
粗いbuildingを壁や窓のGTとして追加していない。固定checkpoint/id2labelは両GPUで検証した。

- 選定候補のCMP群はwall/band_course/cornice/column/window/door/shutter/reliefが全てfailed。
  column/window/doorの空予測もfailedであり、精度が未定義であることを隠していない。
- ADEのstairsはprecision 0.989124・recall 0.480302で公開GTの基準を満たした。
  屋根、窓のガラス／枠、壁の主壁／副壁など未対応・群内細分類を支持しない。
- treeはprecision 0.940182・recall 0.534000、waterは0.981858・0.852000。
  両split・**全改善候補**でbaselineの全計数・指標・ヒストグラムと完全一致した。
  既合格地形の先行を妨げない。他のfailed/unverifiedラベルをsupportedへ昇格していない。
- [decision.json](decision.json)に群と各建物部位のpassed/failed/unverifiedを記録。
  公開GTのpassedと本番採用を分離し、`quality_eligible=false`、
  `supported_labels/groups=[]`、`allowed_building_parts=[]`を固定した。

## 本番prompt・hash契約

本番26promptのうちroof_surfaceは旧公開評価の両datasetに存在しなかった。
各datasetに不足する本番promptの一覧はdecisionに保存した。
今回の両GPU smokeは全26promptで実行したが、1223枚のGT評価は旧dataset別promptの範囲。
smokeを本番全promptの品質保証へ昇格しない。

`oneformer-classes.json`の内容が同じでもCRLF/LFの実byte SHAが異なることを再確認した。
旧`region-policy-v1`のbyte依存hashは変更していない。旧runを再解釈・上書きしない。
実験版は`issue130-region-candidates-v1`、JSON内容によるclass-info hashと固定コードに基づく。
実験policy SHA：`4128e1470ebe5be4982eb002d558d740a63ddc13690479770abd4e8652e127e2`。
モデル・prompt・親・座標・コードを含む全体の識別は前記freeze SHAで行う。
LF/CRLFで実験hashが一致すること、policy/コード改変を拒否することをテストした。

**メインへの共有契約事項**：本番のhash正規化はregion-policyの版更新と
shade/color/privacy/selectionの同一run契約の検証が必要。
今回は壁が不合格のため本番版を切り替えていない。旧版を新契約として再利用しない。
本番全prompt品質、所有画像、未対応部位と本番hash移植性は未検証のまま明示している。
新規モデル・依存・migrationは不要であり追加していない。

## GPU・テスト

固定公開3枚、本番26prompt、batch=1、host別lockと毎画像前後のGPUプロセス確認。
開始前・終了後とも両GPUの計算プロセスなし。OneFormer→解放→DINO/SAM2の既存経路を使用した。

| host | GPU | 秒 | peak allocated bytes | peak reserved bytes |
| --- | --- | ---: | ---: | ---: |
| ubuntu-1 | RTX 4060 8GB | 37.08 | 2,659,068,416 | 3,772,776,448 |
| ubuntu-2 | RTX 4070 12GB | 24.62 | 2,659,068,416 | 3,772,776,448 |

固定重み全SHA・実行版を照合し、モデル取得・代替・暗黙縮小はない。
torchは2.11.0、transformersは4.57.6。CUDAビルドはubuntu-1がcu130、ubuntu-2がcu128。
GPU間のbit一致や全形状の8GB適合は主張しない。
実OOMはなく、OOM停止・再試行不可は既存両工程の模擬テストと隔離DB runnerテストで確認した。

WSL Ubuntu-24.04 root・隔離PostgreSQL 16で全pytest **1377 passed / 1 skipped**、345.62秒。
追加hashテスト2件を含む重点7件も成功。全ruff、最終sdist/wheel build成功。
既存warning4件。skipは従来の実GPUテストであり、今回の両GPU smokeは別途成功した。
[検証記録](verification.json)を参照。今回起動したDB・GPU・集計プロセスは終了した。
既定WSLは別タスクのVHDX欠損で起動できず、利用可能なUbuntu-24.04を明示して検証した。
ubuntu-1の最初のsmokeは展開先パスの指定違いで予測前に停止し、構造確認後に修正して成功した。
初期に指定したGPU用base venvにはNumPyがなく、既存のプロジェクト用venvへ正しい実行パスを修正した。
依存の追加インストール・環境の置換はしていない。

## 成果物と再現

private原本：`ubuntu-2:/mnt/data/work/issue-130/evaluation-20261108/`。
ubuntu-1 smoke：`/home/toumokorosi/issue130-20261108/`。
旧入力・GT・候補・semanticは従来のprivate保存先をread onlyで再利用した。
本番DBへの接続0、API要求0、サービス変更0。

再現には固定commitの`bench/issue121/`をGit archiveで独立した参照ディレクトリへ展開し、
`PYTHONPATH=src:.:<参照ディレクトリ>`として`diagnose.py freeze`→`run`を実行する。
引数はprivate原本のコードとコマンド記録に残した。`report.py`は旧#121の全指標一致・
tree/water不変性を必須検査し、個別semantic SHA列を除いた公開集計を作る。
`verify.sh`はWSL rootでタスク専用コード・venv・DBを作り、正常停止まで処理する。

実装・評価・公開準備は完了。公開文面は指定scratchpadのi130-commit.txt、
i130-pr-title.txt、i130-pr-body.mdへ移動した。push/PRは未実施。
後続で建物を統計へ追加するには、別の改善で壁のprecisionを満たし、
#129/#118/#119/#120の本番・同一run契約を揃える必要がある。
