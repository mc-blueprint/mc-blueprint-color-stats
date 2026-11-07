# 修正設計の既存実装・一次資料調査

確認日：2026-11-07。資料の読取りだけを行い、モデル取得・推論・OpenAI API実行はしていない。

## 既存機能

- Jobのstageはcollect/prep/segment/shade/color/review/aggregate。新stageを増やさずreviewとsegmentを使う。
- ProcessingRun/ProcessingRunInput、試行別出力、hash付きmanifest、保持台帳、#66の共有payloadを再利用する。
- jsonschema・urllib・SQLAlchemy・Pillow・NumPy、既存GPU依存を使う。APIのためだけにSDKを追加しない。
- 既存の収集予算は要求・画像・byte用。USD予約・確定・不明請求は表現できず、金額台帳が必要。
- quality.privacy_reviewの直接上書きは旧assetの不変条件と両立しない。新方針の結果は別runに記録する。
- M4はopen重み必須。NC・academic・不明な重みは除外する。正本はdocs/pack-contract.md。

## 領域候補

| 候補 | 一次資料で確認した条件 | 選定への影響 |
| --- | --- | --- |
| 現行DINO/SAM2 | [SAM2のコード・checkpointはApache-2.0](https://github.com/facebookresearch/sam2#license)。[GroundingDINOコード](https://github.com/IDEA-Research/GroundingDINO/blob/main/LICENSE)はApache-2.0。既存配置の実ファイルhash・利用区分は維持する | 追加sky/building/person promptだけでは異ラベルを排他にしない。部位候補の生成に再利用する |
| Mask2Former Swin-T ADE | [コード](https://github.com/facebookresearch/Mask2Former/blob/main/LICENSE)はMITだが、[配布重み](https://github.com/facebookresearch/Mask2Former/blob/main/MODEL_ZOO.md#license)はCC BY-NC 4.0。[HFカード](https://huggingface.co/facebook/mask2former-swin-tiny-ade-semantic)もlicense:other | M4用にopen重みとして採用しない。コードと重みのライセンスを混同しない |
| OneFormer Swin-L ADE | [著者repo](https://github.com/SHI-Labs/OneFormer/blob/main/LICENSE)はMIT、[著者HF checkpoint](https://huggingface.co/shi-labs/oneformer_ade20k_swin_large)もMIT表示 | 第一候補として選ぶ。取得時のrevision・全ファイルhash・ライセンス根拠の再照合を実行条件にする |

[Mask2Former公式表](https://github.com/facebookresearch/Mask2Former/blob/main/MODEL_ZOO.md)のSwin-T ADE semantic mIoUは47.7、
[OneFormer著者表](https://github.com/SHI-Labs/OneFormer#results)のSwin-L 640は57.0、219M parameters。
別backbone・条件でのベンチマークであり、所有画像での精度比較や#81の条件付きprecisionと同じ指標ではない。
OneFormerが今回のwall/tree誤りを直すことは未実証。

[Transformers 4.57系OneFormer](https://huggingface.co/docs/transformers/v4.57.1/model_doc/oneformer)に
semantic推論とtarget_sizes=(height,width)の後処理がある。Detectron2や独自CUDA環境を新設しない。
ADEのモデルlabel IDと注釈IDは同一と仮定せず、checkpointのid2labelを固定する。
[ADE画像の非営利研究・教育条件](https://ade20k.csail.mit.edu/terms/)と、checkpointのMIT表示は別に管理する。
評価用画像を本番入力やM4へ混ぜず、モデルのMIT表示をデータの再配布許可には使わない。

実機読取り：ubuntu-1はRTX 4060・8,188 MiB、ubuntu-2はRTX 4070・12,282 MiB。
両機ともtorch 2.11.0系／torchvision 0.26.0系／transformers 4.57.6で、oneformer/mask2former実装が存在する。
重み配置・推論速度・ピークVRAM・8GB適合は未確認。
batch=1・有界入力・単一モデルずつの推論を前提に実測する。学習用GPU数を推論要件へ流用しない。
8GBで不適合なら、12GB側で粗分割を先行生成し両hostへ共有する工程にする。
12GBでも不適合なら実行を止め、別モデルへ自動代替しない。

## OpenAI公式資料

- [gpt-6-luna](https://developers.openai.com/api/docs/models/gpt-6-luna)：指定モデルとlowを維持。画像入力・Structured Outputs対応。
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：JSON Schemaを使う。schema適合を意味精度と扱わない。
- [入力token数](https://developers.openai.com/api/docs/guides/token-counting)：画像を含む同じ入力のcount endpointを利用できる。実アカウントでの対応は後続の許可済みsmokeで確認する。
- [料金](https://developers.openai.com/api/docs/pricing)：Luna入力0.10／出力0.50 USD/百万token、cache書込み等は別区分。取得時の価格版を保存し、平均単価を上限予約へ使わない。
- [rate limit](https://developers.openai.com/api/docs/guides/rate-limits)：Retry-After尊重。quota/billingと一時429/503を分け、SDKとアプリの再試行を重ねない。
- [データ管理](https://developers.openai.com/api/docs/guides/your-data)：store=falseは保存全体のゼロを保証しない。通常の監視ログ保持・画像例外を含め、送信前の権利・保持条件確認へ反映する。

指定の私有試験はCodex CLIのAPI経路で、1枚平均約23,333入力tokenの文脈を含む。
製品のResponses直接呼出しはその文脈を持たないため、試験の単価・速度・精度を保証値にしない。
今回の設計では独立のモデル呼出し試験を追加していない。
