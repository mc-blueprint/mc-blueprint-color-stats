# segment stageと分割手法の比較

Issue #40。ハンドラーは`colorstats.analyze.segment`。既存のQueue・Region・
ProcessingRunを使い、DBスキーマは変更しない。SAM 2＋Grounding DINOのGPUジョブは
確認済み。SAM 3.1はユーザー判断により未評価・実行経路なし（restricted・ゲート付き）
として比較から除外する。
Issue #40の完成条件はSAM 2.1＋Grounding DINOの実行・記録で満たす。

## 採用する既存実装

| 手法 | 実装 | 選定理由・制約 |
| --- | --- | --- |
| `sam2-dino` | Transformers 4.57.6のGrounding DINOとSam2Model | 公式配布のsafetensors・processorを使い、独自の検出・分割器を作らない。ラベルごとの英語句でboxを検出し、SAM 2へ1 boxずつ渡す |

語彙は`taxonomy/parts.yaml`の第2階層と`terrain.yaml`。明示したラベルだけを推論する。
検出結果は候補であり、特に`wall_main`と`wall_secondary`の意味的区別や細部装飾の
正確さは保証しない。人手修正用の下書きとし、精度評価は#41・#47へ引き継ぐ。

Python 3.12、`uv sync --locked --extra gpu`でSAM 2系を導入する。
通常の`uv sync --locked`・CIはtorchを導入せず、stageのimportにもGPUを要求しない。
SAM 3の`numpy<2`は通常依存のOpenCV 4.13以上と両立しない。
[uvのconflicts](https://docs.astral.sh/uv/concepts/resolution/#conflicting-dependencies)は
extra同士を別解決するため、必須依存との競合は解消できない。通常環境への影響を避け、
gpu-sam3 extraと実行経路を削除した。NumPy 2.5.4・OpenCV headless 4.14.0.94・
colour-science 0.4.7・SciPy 1.18.1は起点b2a7241のlockと同じ版を使用する。
torch 2.11.0・torchvision 0.26.0を組み合わせ、GPUでは対応するCUDA wheelを使う。
今回の実機は両者の`+cu128`を使用した。

## 重みのライセンス

確認日: **2026-11-02**。配布元・コード・重みの区分を混同しない。

| 対象 | 一次情報 | 区分・扱い |
| --- | --- | --- |
| `facebook/sam2.1-hiera-tiny` | [公式モデルカード](https://huggingface.co/facebook/sam2.1-hiera-tiny)、[SAM 2 LICENSE](https://github.com/facebookresearch/sam2/blob/main/LICENSE) | Apache-2.0、`open`。帰属・通知条件を保持する |
| `IDEA-Research/grounding-dino-tiny` | [公式モデルカード](https://huggingface.co/IDEA-Research/grounding-dino-tiny)、[公式コードLICENSE](https://github.com/IDEA-Research/GroundingDINO/blob/main/LICENSE) | Apache-2.0、`open`。モデルカードで重みの区分も確認 |
| `facebook/sam3.1` | [公式モデルカードとゲート](https://huggingface.co/facebook/sam3.1)、[SAM License](https://github.com/facebookresearch/sam3/blob/f1647e8d0c1d280991f4d1b7d974c2704537fe66/LICENSE) | 独自SAM License、`restricted`。Apache/MITと同等の`open`として扱わない。商用不可という区分ではなく、配布条件と用途制限を個別確認する区分 |

SAM Licenseには再配布時の同ライセンス添付、研究発表時の利用明示、用途制限がある。
利用・配布により契約へ拘束される記載があり、重みの配布ページも情報提供への同意と
ログインを要求する。この作業では同意・ログイン・ゲート付き重みの取得を行わない。
SAM 3.1は[ユーザー判断](https://github.com/rs0325/mc-blueprint-color-stats/issues/40#issuecomment-6567448053)により未評価（restricted・ゲート付き）とし、比較対象に含めない。
`restricted`の結果はdesign §8に従い同梱パックから除外する。
採用したSAM 2・DINOに`noncommercial`・`academic_only`の重みは採用していない。

`bench/download-segment-models.py --models /絶対パス/models`はSAM 2とDINOだけを
認証なしで取得する。毎回公式repoのゲートを検査し、revisionを固定して取得し、
`source.json`へ配布元・revisionを記録する。SAM 3.1は取得対象に含めない。
重み・画像・キャッシュはGitへ入れない。stageは配置済みファイルだけを使い、
Transformersの`local_files_only=True`で動く。

## 投入とpayload

1 asset／job、1画像／batch、1 box／SAM 2推論。現在のspawn方式を維持する。
VRAM実測からまず1件を採用し、16画像バッチやモデル常駐ワーカーは追加しない。
12GB GPUの空きVRAMを確認し、同一GPUにsegmentワーカーを同時起動しない。

```python
import os
import uuid

from sqlalchemy import create_engine

from colorstats.analyze.segment import config_hash
from colorstats.queue import Queue

payload = {
    "method": "sam2-dino",
    "model_paths": {"sam2": "/work/models/sam2", "dino": "/work/models/dino"},
    "input_path": "/derived/採用済み不変パス/resized.jpg",
    "input_run_id": "00000000-0000-0000-0000-000000000001",
    "output_path": "/derived/segment/asset-id/segments.json",
    "license_class": "open",
    "taxonomy_version": "0.1.0",
    "taxonomy_path": "/work/repo/taxonomy",
    "prompts": {"roof_surface": "roof", "wall_main": "building wall"},
    "threshold": 0.35,
    "text_threshold": 0.25,
}
queue = Queue(create_engine(os.environ["DATABASE_URL"]))
queue.enqueue("segment", uuid.UUID("00000000-0000-0000-0000-000000000002"),
              config_hash(payload), payload)
```

UUIDとパスは実在するasset・成功prep run・出力先へ置き換える。
prep入力には成功runの`output_paths`の値と`input_run_id`を指定する。
registerは成功Jobが同じassetのprepを指し、runが完了済み・失敗理由なしで、
input_pathがその不変出力の値に一致することを検証する。不一致は完了取引を
ロールバックし、通常のジョブ失敗・再試行として扱う。
原本到達は#42で扱う。input_run_idは外部テスト入力の場合のみ省略できる。
`license_class`は入力画像の区分。入力asset・入力runの制約もregisterで確認し、
重みの区分と合わせて制約を緩めずrunへ伝播する。複数の異なる制約が混在すれば
`restricted`にする。入力assetや既存runの内容は変更しない。

`prompts`は空でない部位ラベル→単一の英語句。句にピリオドを含めない。
`threshold`は検出／出力確率、`text_threshold`はDINOだけに適用する。
省略時はそれぞれ0.35・0.25。無効な語彙・版・出力拡張子・閾値は拒否する。

設定ハッシュはpayload、入力画像SHA-256、重み・processor・tokenizerの各ファイルの
SHA-256、語彙全体、コード版・固定推論設定から生成する。prepare時も再計算し、
投入後に入力・重み・設定が変わった場合は失敗させる。入力・重みは処理中も不変とする。
`weights_hash`は成分名と各重みファイルのSHA-256を正規化JSONへまとめたSHA-256。
各成分の実ハッシュと配布元は`run.parameters.models`にも保存する。
モデル名は`run.model_name`、設定ハッシュは既存の`run.config_hash`に記録する。

```sh
uv run --extra gpu python -m colorstats.queue \
  --handler segment=colorstats.analyze.segment \
  --stop-file /work/segment.stop --storage-path segment=/derived
```

モデル配置rootも`--storage-path segment=/work/models`で追加できる。
OOMやモデル・ファイル読取り失敗は通常の失敗として最大3試行。CPUへの自動切替や
別モデルへのフォールバックは行わない。停止・リース喪失・保存先保留は既存キュー契約に従う。

## 出力と後続への契約

- `segments-0000.png`以降: 入力と同寸の8bitマスク（0=背景、255=領域）。穴・離れた領域を保持する。
- `segments.xml`: [CVAT for images 1.1](https://docs.cvat.ai/docs/dataset_management/formats/format-cvat/)のmask形式。ラベル定義・入力ファイル名・サイズ・bbox内の行優先RLEを格納する。CVAT側に同じ名前の画像を登録し、CVAT for images形式で取り込む。
- `segments.json`: asset・入力run・領域一覧・計測値。`mask_path`は出力識別名であり、そのファイルを直接開かず、同じrunの`output_paths[mask_path]`で不変パスへ解決する。
- DB `Region`: 不変`mask_path`、第2階層ラベル、run内の`instance_id`、`label_source=model`、confidence、面積比、bboxを登録する。

bboxは入力画素座標の`[left, top, right, bottom]`（右・下端を含まない）。
面積比はマスク画素数／入力全画素数。候補マスクは重複を許し、比の合計は1とは限らない。
confidenceはDINOの検出score。
接地位置・面方向・相対高度・地形属性は推定せずNULL。0検出は空の成功結果。
ファイルはすべて試行専用一時パスへ書き、Queue.completeで別々の不変パスへ公開する。
JSONの隣にPNGがあるとは限らない。CVAT XMLはマスクを内包するため単独で参照できる。
DB失敗・リース喪失時には既存契約どおり未参照ファイルが残りうる。
DBへ確定したrun・Regionを正本とし、ファイルの存在だけで成功扱いしない。
後続の部位色抽出はRegion.mask_pathとこの入力画像を使う。既存color stageの
画像全体観測を部位観測へ自動変更する処理は#45の範囲とする。

## 計測と検証

初期化を`load_seconds`、CUDA同期を挟んだ推論とCPU転送を`inference_seconds`、
入力・ハッシュ読取りからPNG/XML書出しまでを`prepare_seconds`に記録する。
prepare時間にJSON自身の書出しとDB確定は含めない。
`peak_allocated_bytes`・`peak_reserved_bytes`はモデル初期化を含むPyTorch allocatorの
最大値で、OSや他プロセスを含むnvidia-smiの総使用量とは異なる。
`mask_bytes`と`cvat_bytes`はPNG合計とXMLの容量。GPUテストのreportにはJSONを含む
公開ファイル合計の`output_bytes`も記録する。GPU名・torch/runtime CUDA版も保持する。

2026-11-02、ubuntu-2 RTX 4070（12,282MiB）、torch 2.11.0+cu128、
torchvision 0.26.0+cu128、Transformers 4.57.6で実行した。
自作CC0家屋画像512×384、door・grass・roof・building wallの4句、threshold=0.25。
同一の自作画像による動作確認の最終実行値であり、精度・代表的なスループットの評価ではない。

| 項目 | SAM 2.1 tiny＋DINO tiny | SAM 3.1 |
| --- | ---: | --- |
| モデル初期化 | 2.824秒 | ユーザー判断により未評価・実行経路なし |
| 推論 | 1.352秒 | 未実行 |
| prepare | 6.686秒 | 未実行 |
| 最大割当VRAM | 2,040,869,888 bytes（約1.90GiB） | 未計測 |
| 最大予約VRAM | 2,447,376,384 bytes（約2.28GiB） | 未計測 |
| PNG合計 / XML / 全出力 | 7,638 / 14,537 / 24,620 bytes | 未計測 |
| 出力領域 | 6（door 3、grass・roof・wall各1） | 未確認 |

SAM 2公式revision: `de431c4043854a71d8101e17995dfe596bf101a5`、
DINO公式revision: `a2bb814dd30d776dcf7e30523b00659f4f141c71`。
実重みSHA-256はそれぞれ
`48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7`、
`1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3`。
合成weights_hashは`d57b8884742eb8e07e6328b220c63ddd1b7e883cf656e38b612ba33378e36795`。
同じ画像・重みの2回のGPUジョブで、6件のPNGマスクのSHA-256が全件一致した。
上表はNumPy 2系・既存OpenCVへの依存復元後の再実行値。復元前の最終reportと
比較して、6件すべてのPNGマスクのSHA-256とweights_hashが一致した。
入力runの検証は成功prepの不変出力による正常系と、不明run・stage違い・未完了・
失敗理由あり・asset違い・出力名・無関係なパス・出力なしの8不一致ケースを
一時schemaのDBテストで確認した。

GPUテストは`tests/test_segment_gpu.py`。`SEGMENT_GPU_MODELS`と
`TEST_DATABASE_URL`を明示した場合だけ実行し、一時schemaに既存migrationを適用する。
`SEGMENT_GPU_REPORT`にreport保存先、`--basetemp`にタスク専用の一時領域を指定する。
本番DBを使わない。今回の一時クラスタは`/mnt/data/work/issue-40/pgdata`、
localhost:55440であり、既存PostgreSQLのデータ・設定・サービスは操作していない。
検証後にこの一時クラスタだけを停止し、データと実測reportは専用領域へ保全した。

一次情報の追加参照（同日確認）:

- [SAM 3.1 release](https://github.com/facebookresearch/sam3/blob/f1647e8d0c1d280991f4d1b7d974c2704537fe66/RELEASE_SAM3p1.md)
- [SAM 3.1 builder](https://github.com/facebookresearch/sam3/blob/f1647e8d0c1d280991f4d1b7d974c2704537fe66/sam3/model_builder.py)
- [Transformers SAM 2](https://huggingface.co/docs/transformers/v4.57.1/en/model_doc/sam2)
- [Transformers Grounding DINO](https://huggingface.co/docs/transformers/v4.57.1/en/model_doc/grounding-dino)

RLEとマスクの往復は単体テストで確認済み。#41の統合作業では上記実出力の6マスクを
ローカルCVAT v2.81.0へ取り込み、APIでpolygonへ編集して一時DBのhuman領域へ登録した。
`colorstats.cvat prepare-draft`はRLEを保持してCVAT XMLとmodel下書きJSONを作り、
`import-cvat --draft`は修正polygonを原画像座標へ戻して下書きとの差分を記録する。
既存segment出力の形式・runは変更しない。操作は[CVAT手順](../ops/cvat/README.md)を参照。
正解セット作成は#41、正解セットによる精度評価は#47で扱う。
