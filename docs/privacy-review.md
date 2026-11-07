# 新しい人物確認契約

`privacy-review-v1` は実在人物あり・不明・画像判定と画素判定の不一致を保留する。
像・絵・装飾を実在人物へ変換せず、semantic personだけが陽性でも保留する。
両方陰性は採用の必要条件であり、人物見落としの安全性保証ではない。
mask救済・永久除外・migrationは追加していない。

## review writer

既存の`ProcessingRun`、review job、`ProcessingRunInput`を使用する。
追加依存は不要で、#117の画像判定artifactと#118の確定semantic/person PNGを再利用する。
API通信はしない。判定根拠を別runへ保存し、Asset/qualityや旧snapshotを変更しない。

```python
from colorstats import privacy_review

run_id = privacy_review.write(
    queue, asset_id, image_gate_run_id, segment_run_id, code_version=code_version,
)
row = privacy_review.selection(session, asset_id, run_id)
```

`write`は同じ画像の成功済みA/B・prep jobを検証してreview jobを同期完了する。
`selection`は採用可能な明示runだけを返し、保留・改変・人の訂正後の旧runは拒否する。
画素根拠が欠落・改変している場合は採用可能なrunを作らず、例外で停止する。
prep runには取得画像SHAを新たに保存する。SHA記録のない旧prepを新版へ流用する場合は
prepから再生成する。旧保存データの移行や既存runへの追記は行わない。
新旧の入力画像はサイズも符号化も異なるため、次のSHAを別々に保持する。

- `image_gate_input_sha256`：#117で1024px以下へ正規化した画像。
- `input_sha256`・`size`：#118のprep画像とその画素座標。
- `person_mask_sha256`：同じprep座標のperson PNG。semanticのモデルID 12と画素一致を検証。
- `image_gate_run_id/hash`・`privacy_review_run_id/hash`・`region_policy_run_id/hash`：判定と入力根拠。

review内部には確認時の`subject_id`も固定し、同じdomain内のsubject付け替えでも古い承認を拒否する。

`row`を既存のshade/color payloadへ展開する。`region_run_id`は同じsegment runを指定する。
workerの入力検証と完了登録で再検証し、色runからprivacy runへの依存を保存する。
新snapshotのasset selectionにも同じ`row`を展開する。色runと選択の全参照が一致しない、
または訂正で承認が失効した場合、新snapshot作成を拒否する。旧snapshotの読み取りは変えない。
新版参照が一部でもあれば、旧`quality.privacy_review`へ代替しない。
旧契約のpayload・selectionは従来の検証経路を使う。

## 人の訂正と表示担当への接続

表示・番号返信の変換は#120が担当する。画像・対応表・個別所見は私有artifactへ置く。
Windows操作やJSONファイル作成をユーザーへ求めない。
取得解像度の原画像を単一HTMLで提示し、実際に提示した画像だけを番号返信から対応付ける。

```python
human_run_id = privacy_review.write(
    queue, asset_id, image_gate_run_id, segment_run_id, code_version=code_version,
    input_run_id=run_id, reviewer=reviewer, real_people="present",
    presented_source_sha256=source_sha256, note=note,
)
```

提示済み原画像SHA・確認者・所見・元privacy runを必須とし、人物画像根拠だけを訂正する。
semantic personや保留方針を人の一括承認で解除しない。元runは残し、その承認に依存する
旧色解析を新snapshotへ採用する操作を拒否する。再訂正も直前のrunを指定する。
画像判定自体の訂正は#117のwriterを使い、新しいimage gateからprivacy runを作り直す。
人物方針・subject・mask・入力が変われば新しいprivacy/shade/color runとselectionが必要。

## 検証と未確定

`bench/issue119/verify.sh`はWSL Ubuntu-24.04で一時PostgreSQLを作成し、ruff・全pytest・
hatchlingによるsdist/wheel buildを実行する。終了時に当該DBプロセスを停止する。
既定の検証Pythonは既存のPython 3.12環境で、`COLORSTATS_TEST_VENV`でも指定できる。
ビルド依存は既存の`/tmp/colorstats-issue88/builddeps`を再利用し、`COLORSTATS_BUILD_DEPS`で変更できる。
実画像・外部API・本番DBを使わず、生成画像と合成maskで契約を検証する。

実画像での新しい無作為・難例の固定と品質採否はDの評価へ引き継ぐ。
`evaluation_input(session, samples)`で`(asset_id, privacy_run_id, group)`の列を渡すと、
採否を問わず全根拠とreview hashを含む私有manifestを固定できる。
`group`は`random_old`・`random_new`・`challenge`で区別する。訂正前runと画像SHAの重複は拒否する。
抽出seed・cohortの分母・既知試験画像の除外は、結果を見る前にDの計画で固定する。
見落とし許容基準・必要標本数は未確定であり、本Issueの合成テストを品質合格と扱わない。
