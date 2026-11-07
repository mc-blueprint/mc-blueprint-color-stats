# バッチ1の自動人物判定と目視サンプル

2026-11-07のユーザー決定により、全件目視を自動判定と目視サンプルへ置き換える。
既存の失敗job、成功segment、旧snapshot・統計、全停止履歴は保全する。

## 判定根拠

既存segmentは建物・地形26クラスだけで人物を問い合わせていない。
その未検出を人物不在と解釈せず、同じローカルSAM2.1 tiny・Grounding DINO tinyで
人物の補助検出を行う。重みは既存segment記録と全ファイルSHAを照合する。追加取得はしない。

最初の補助検出ではperson/human face、検出閾値0.25を試したが、顔が風景・建物の大面積を
誤検出した。非公開12枚の視覚確認でも誤検出が確認されたため、この結果はprivacy-v1に保全して不採用。
採用方式person-sam2-dino-v2はpersonのみ、検出閾値0.35・text閾値0.25とする。
検出閾値は既存segment設定と同じ。モデルが人物不在を保証する値ではなく、目視で検証する候補である。

人物maskの和集合を2px膨張させ、輪郭の残りも除外する。
膨張後の除外率が1%以下ならmaskを固定して採用し、超過は目視待ちにする。
1%は画像の少量の写り込みだけを自動処理する運用上限で、識別可能性の閾値ではない。
全体の分布・0%群・1%付近・大面積群を記録し、誤検出の多い大面積群を自動で不採用とはしない。
自動不採用は0件とし、ユーザーが不採用へ変更できる。

主体は既存segmentのmask和集合で判定する。partsのcontext以外をbuilding、terrain.labelsをterrainとする。
大きい方の和集合が画像の5%以上、両者の差が2ポイント以上のときだけ主体を固定する。
それ以外は主体不明・混在として目視待ちにする。画素の重複を単純合算しない。
人物・主体の自動判定は医療・私生活等の文脈を意味理解していないため、目視欄には判定誤りの項目を設ける。

## 記録と解析

quality.privacy_reviewにauto:方式名、版を含むmethod、採否、閾値、主体、人物率、mask path/SHA、
補助検出JSONのpath/SHA、固定prep画像SHA、既存segment runを保存する。
目視待ちも同じ台帳へ記録し、採用以外のshade/colorを拒否する。
人の上書きはprivacy_review_historyへ旧記録を残す。

新しい実行枠auto-v2は採用IDを固定し、同じprep入力の既存成功segmentだけを再利用する。
#66 runnerのmanifestへ人物判定SHAとperson_maskを固定し、共有payloadへmaskを渡す。
既存shade/colorのmask除外とファイルhash検証を再利用し、失敗済みjobはリセットしない。
両hostで3件smokeの三段階完了を照合してから全量を処理する。

## 非公開サンプルと取込み

2026-11-07の追加決定により、ユーザーへの提示は[携帯端末用HTMLと番号返信](mobile-review.md)を使う。
以下のJSONダウンロード方式は既存内部ツールの手順として残し、ユーザーへ要求しない。

seed=11420261107、固定UUID順から無作為100枚を抽出する。
人物maskがある画像から1%に近い40枚を追加し、目視待ちは全件を一覧に載せる。
採否の異なる画像を黙って分母から除かず、全2,600枚の採用・mask・保留・理由を記録する。
画像・個別記録はUbuntuの非公開領域とGit外のH:領域だけに置き、Gitには集計とコードだけを入れる。

index.htmlを開き、取得画像・解析画像・赤色maskを確認して各判定欄を記入する。
無作為100枚と閾値付近の項目を全て記入し、確認者名・誤りなしの確認を入力してJSONを保存する。
誤りがあれば「人物の見落とし・判定誤りあり」を記入し、保留・不採用とする。
修正maskを作る場合は解析画像と同寸のPNG（人物画素が非ゼロ）をhuman-masksへ配置し、ファイル名を記入する。
画像や結果を外部サイトへ送信しない。

結果JSONと修正maskを担当へ返すか、登録済みSSH経由でUbuntuの非公開領域へ転送する。
Ubuntu-2の目視取込み用配備 `/mnt/data/work/issue-114/batch1-20261106/review-code-r3` で、
記録付きSSHから既存GPU Pythonとpeer接続を使って次を実行する。

```sh
sudo env PYTHONPATH=/mnt/data/work/issue-114/batch1-20261106/review-code-r3/src:/mnt/data/work/issue-114/batch1-20261106/review-code-r3:/mnt/data/work/issue-74/deps \
  /mnt/data/work/issue-40/venv/bin/python -m bench.issue114.privacy import \
  --root /mnt/data/derived/issue114-batch1-20261106/privacy-v2 \
  --execution /mnt/data/derived/issue114-batch1-20261106/auto-v2 \
  --input /絶対パス/privacy-review-results.json
```

取込みは目視記録をDBへ反映し、版付き結果JSONと最新承認索引を残す。
必須サンプルの記入不足・誤り・採否変更・mask修正があれば統計承認を出さず、必要な再解析へ戻す。
同じ判定の確認だけなら、現在の人物判定全件のSHAを固定して承認する。
後日の上書きは承認を無効にする。新snapshot・rule_stat・reportは承認後だけ作成し、今回は起動しない。

閲覧用画像・補助検出mask・試行版の出力・共有HTML・転送tarも既存保持台帳へ登録する。
POSIXでは画像0600・ディレクトリ0700とし、Windows ACL・NFS設定は変更しない。
H:側の複製はhost=`wsl-Ubuntu-24.04`、path=`/mnt/h/mc-blueprint/private/issue114-review-20261107/...`
として登録し、後日の保持処理は同じhost名のWSLから行う。今回は削除しない。

取得画像の保存先はubuntu-1専用なので、閲覧対象だけを同hostから共有領域へ複製する。
無作為群・閾値付近・保留群の選択関数を共用し、複製元と複製後のSHAをAsset.sha256と照合する。
新しいreplicaは保持台帳に登録し、閲覧HTMLは明示したraw-manifestだけから取得画像を読む。
元のAsset.storage_pathを変更したり、読めない取得画像を黙って解析画像へ置き換えたりしない。
