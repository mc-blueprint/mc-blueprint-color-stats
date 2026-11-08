# #129 image-gate-v2 実装・本番判定結果

## 結果

固定10,226件（旧7,626・新2,600）のv2判定を完了した。
最終候補r8のsmoke12件、既知110件回帰（109判定・既知SVG入力保留1件）に続き、
全量サービスは2026-11-08 15:02:55〜19:22:21 UTCに実行、終了コード0。
最終集計は同日19:25 UTC。10,223 job成功、失敗・待機・実行中・送信中0。
入力保留3件はSVG読取り不可1件とDecompressionBombError2件で、保護制限を解除していない。
成功job数は処理の成否であり、採用数とは区別する。

| 群 | 分母 | 採用 | 除外 | 保留 |
| --- | ---: | ---: | ---: | ---: |
| 旧 | 7,626 | 3,925 | 1,200 | 2,501 |
| 新 | 2,600 | 1,362 | 337 | 901 |
| 合計 | 10,226 | 5,287 | 1,537 | 3,402 |

入力保留も保留数と固定分母に含む。全属性分布・完了条件は[summary.json](summary.json)。
上空属性はtrue377・null44・false9,802・入力保留3で、true/nullを採用しない。

## v1からの遷移

| v1 | v2採用 | v2除外 | v2保留 | 合計 |
| --- | ---: | ---: | ---: | ---: |
| 採用 | 5,039 | 60 | 848 | 5,947 |
| 除外 | 100 | 1,433 | 119 | 1,652 |
| 保留 | 147 | 44 | 2,431 | 2,622 |
| 原判定なし | 1 | 0 | 4 | 5 |
| 合計 | 5,287 | 1,537 | 3,402 | 10,226 |

v1応答をv2承認へ転用せず、新identity・新run・別artifactで記録した。
採用の明示selectionは非公開領域に保持している。

## 固定110件の回帰

GT・対応・所見・補助ラベル・seed129・奇数/偶数の調整/確認分割は変更していない。
既知標本を使ってpromptを調整した回帰であり、独立した精度保証ではない。
群別のv1/v2混同行列と正解不明・予測不明は[regression.json](regression.json)。

| 属性（v2全群） | TP | FP | FN | TN | 正解不明 | 予測不明 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 対象外 | 13 | 5 | 0 | 78 | 13 | 1 |
| 白黒 | 9 | 2 | 0 | 81 | 17 | 1 |
| 人物 | 8 | 9 | 0 | 74 | 17 | 2 |
| 上空 | 3 | 0 | 0 | 103 | 2 | 2 |

- 白黒属性の既知9件はFN1→0。白黒FP2→2、低彩度カラー11件の白黒FP0。
- 対象外FP6→5、既知の問題画像の採用0。上空正例3件すべて保留、通常視点の採用51件。
- 人物FP8→9・予測不明3→2。人物保留方針を維持し、人物の既知FN・採用漏れは0。
  属性単体のFP増分を隠して「全属性で誤判定減少」とは扱わない。個別の変化説明は非公開へ保全した。
- 旧50件は採用32→26（52%）、新50件は26→25（50%）、challenge10件は1→0（0%）。
- 最終候補の予測前に固定した回帰条件を満たし、全量後にも同じ判定・合格を確認した。

初期候補r5は建築装飾を対象外とする増分を確認して全量を正常停止した。
成功654件と未送信34 jobの終了を保全し、r6/r7各109件の応答も残した。
建築部位・植生景観・単色図版・自然に灰色のカラー写真の区別を修正した。
後続候補は同じ入力画像のSHAを再検証し、新prompt hashでAPI判定した。旧応答は流用していない。
候補ごとにFP非増加条件を強化し、失敗後の条件緩和やGT変更は行っていない。

## 費用・使用量・不変確認

全候補・smoke・回帰・count・再試行を含む追加台帳費用は **2.524195660 USD / 5 USD**。
usage精算と、HTTP520の要求を予約上限で確定計上した分の合計。
単一要求に対応する費用内訳は非公開へ保全し、公開側には全要求の合算だけを記録する。
これは台帳の保守的計上であり、請求書の確定額とは区別する。
未精算予約0・unknown outcome0、親予算は **4.260624100 USD / 50 USD**。
不明請求の再送禁止・停止閾値・予約時の二重capは#117と同じ経路で扱った。

全22,191 API callはcount11,095・responses11,096。HTTP200は22,190、520は1。
200の原判定11,095応答で返却model=`gpt-6-luna`・effort=`low`を確認。
LoadCredential・store=falseを維持し、private正解・ID・所見をAPIへ送っていない。
input18,629,364・output1,267,071 token、cached3,800,796・cache write14,735,336・reasoning680,012。
費用内訳と全使用量は[accounting.json](accounting.json)。

既存のAsset10,226行・ProcessingRun65,100行を予測前の行hashと照合し、変更・欠落0。
v1原判定10,221個は保存済みSHA-256との照合で変更・欠落0。API監査不一致0。
最初の候補前に固定した旧run64,228行の不変も途中監査で確認済み。
Asset/quality/subject・旧run・snapshotへの更新、migration追加は行っていない。

## 固定・バックアップ・依存

全量前の完全DBバックアップはubuntu-2で作成、TOCとubuntu-1からのSHA一致を確認した。
最終候補のbefore.dumpは758,021,471 bytes、2026-11-08 14:52:45 UTC。
SHA-256は`fe3c92f1585b077d7d018f6adf0cc44ed018a8aec7ee87e64c85a18e23a26f96`。
前候補の完全バックアップも保全し、専用privateディレクトリ700・ファイル600を維持した。

明示許可されたWindows→ubuntu-1のLAN転送後、review-freeze.jsonのSHAは
`6dec63d6a6d0a93ec31969b8bbaaa5023aeb4037aa20df3e8195ad2e452a4fbf`、dependency.jsonは
`749781c97ad70aee18ad3f867b75f43e4810be8af745df55713ff9e9ca1d8772`で一致した。
Gitには個別ID・画像・原判定・所見・selectionを含めていない。

最終code archive SHAは`4a480c1165a7bd2adfa69b38db4b073afdf4b8e0eda308f636841e58f862c8d4`。
prompt/schema/policy・前処理・固定集合/入力SHAと#121依存commit/SHAは[freeze.json](freeze.json)。
freezeのidentityは共通の版/hashだけであり、画像ごとの入力SHAは非公開計画に保持する。
#121はPR #131の確定commit `27656dc156c47628d5c3dfd0151d8ff313bbed7f`を参照した。
後続#122/#114はv2 runを明示し、#118/#119の成功・mask・人物方針等を別途照合する。
画像ゲートの採用を領域品質の合格と扱わず、#121の合格範囲を拡張しない。#130は変更していない。

## 検証・運用終了

- 最終r8をWSL Ubuntu-24.04/root・隔離PostgreSQL16で検証：pytest **1,385 passed・1 skipped**。
  ruff・sdist/wheel build成功。実行ID49604、検証出力は`/var/tmp/colorstats-issue129-EikBdV/`。
  skipは領域GPUテスト（公式重み・CUDA・一時テストDBの明示指定が必要）で、成功として数えていない。
  #129ではGPUを使用していない。隔離DBは正常停止済み。
- schema不正・拒否・timeout・旧identity・属性欠落・返却effort欠測、二重予算capと並行予約、
  原本/正規化SHA、停止/再開の再送抑止・保留分母を関連テストで確認した。
- 本番はbackup→smoke12成功→回帰109成功＋入力保留1→全量10,223成功＋入力保留3。
  全量unitは`colorstats-i129-full-r8-20261108.service`、終了理由all_terminal・終了コード0。
- 実行codeは`/opt/colorstats/work/issue129-v2-r8-20261108/`、非公開データは
  `/mnt/data/derived/issue129-v2-r8-20261108/`。API再実行は不要。
- 最終report/final_auditも終了コード0。全量・集計・監査unitは終了確認後に停止済み。
  初期freezeの失敗記録（既知SVGを送信対象とするassertion）は保全し、修正後の成功と区別した。

実装・必須検証・本番判定・公開文面作成は完了。merge・Issue close・統計生成・releaseは別作業。
担当branchはfeature/issue-129。履歴書換え後のorigin/develop=46aa56fへ、明示許可された
`git rebase --onto origin/develop 9698f12 feature/issue-129`で#129の1 commitを載せ替えた。
旧起点9698f12（書換え後の対応先ca792728d660b49e77d95bc75a112d5508cecb4a）はHEADの祖先ではない。
競合はなく、載せ替え時点では#129の画像判定・予算・本番運用実装を変更していない。
本番実行のfreeze・archive・依存commitは当時の来歴として保持し、載せ替え後のGit祖先とは区別する。
公開JSON4件は集計・版/hashのみ。asset ID・画像URL・個別判定/理由・要求別費用を含めない。
検索語を表示せず`git grep -i`と`git log -i -G`で現行ファイルと#129差分履歴を確認し、一致0。
載せ替え後のWSL Ubuntu-24.04/root・隔離PostgreSQL16による再検証は
**pytest 1,422 passed・1 skipped**、ruff・sdist/wheel build成功（270.95秒）。
skipは公式重み・CUDA・一時テストDBの明示指定が必要な領域GPUテストで、成功として数えていない。
実行ID94878、出力は`/var/tmp/colorstats-issue129-JeweNA/`。隔離DBは正常停止済み。
rebase時のCRLF変換で最初のshell起動は停止したが、作業用改行をLFへ戻して解消した。
本番APIの再実行・追加課金はなく、pushは実施していない。

## reviewer指摘後の再開終了条件

再開直後に未失効リースのrunning jobだけが残ると、claimできないままall_terminalで
終了する不備を修正した。終了条件にrunning 0件を加え、既存の1秒待機とQueue.claimの
期限切れ再取得を利用する。新しい待機・リース機構は追加していない。
メモリ上で未失効/失効後のclaimを再現する最小テストを追加し、修正前の失敗と修正後の成功を確認した。
既存の停止/再開テストと合わせて2件成功。本番最終集計はrunning 0件だったため結果への影響はない。
画像ゲートの判定・予算・freezeの版/hashは不変で、今回の差分は運用終了条件とその検証・記録に限る。
修正後のWSL root・隔離DB込み全検証は **pytest 1,423 passed・1 skipped**（256.35秒）、
ruff・sdist/wheel build成功。実行ID3385、出力は`/var/tmp/colorstats-issue129-aQ4ZQd/`。
skipは前記の領域GPUテストで、成功として数えていない。隔離DBは正常停止済み。
