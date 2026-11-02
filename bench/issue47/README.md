# 収集画像によるノード×stage性能計測

`ubuntu1-production.json`は既存の本番DBをREAD ONLY取引で読んだ集計。
`production_snapshot.py`は所有者専用の既存設定をプロセス内部だけで読み、認証値や例外本文を出さない。
ubuntu-1ではプログラムをメモリから実行し、ファイル作成・サービス操作を行っていない。

`selection.json`は母集団スナップショットと層別割当、固定seed 47で選んだ500 assetの由来。
母集団比率を最大剰余法で整数枠にし、層内のasset_id順から非復元抽出した。
原本はubuntu-1からubuntu-2へ直接SCP転送し、`publish_cache.py`でDBのSHA・原本名・内容を照合する。
ubuntu-1への書込み禁止に合わせ、#42のstage用コピーを作らず、転送先でmanifestを生成した。
公開は既存`ops/deploy/raw-replica.py`のcapacity/publishを再利用する。
本番cacheから分離した`/mnt/data/work/issue-47/raw-cache/`だけを使う。

`benchmark.py`は既存のprep/segment/shade/colorのprepareとファイル確定を計測する。
既存venv・配置済みモデルが必要で、パッケージ導入・モデル取得・DB操作は行わない。
作業ディレクトリは転送済みsrc・taxonomy・selection.jsonがある評価rootとする。
監査付きSSHからの実行例（出力先は新規に用意する）：

```sh
cd /mnt/data/work/issue-47
PYTHONPATH=/mnt/data/work/issue-47/src CUBLAS_WORKSPACE_CONFIG=:4096:8 \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
/mnt/data/work/issue-46/venv/bin/python -u bench/issue47/benchmark.py \
  --root /mnt/data/work/issue-47 --models /mnt/data/work/issue-40/models \
  --deadline 2026-11-02T20:15:00+00:00
```

segmentは既存`segment_models._sam2`が返すrunnerを一度だけ生成し、計測中だけprepareのpredictへ渡す。
本番Workerは変えず、常駐時の参考性能として扱う。26句、閾値0.35/0.25、512px以内、batch/box各1。
現行`segment_models.predict`の呼出しごとのモデル読込は、本番側ではそのまま残る。
設定ハッシュ生成（重みの読取りを含む）・prepare・出力renameをstage時間に含め、importとモデル生成を分離する。
最初の推論は含め、別のwarmupは行わない。

shadeは補正ごとの部位平均をJSONへ、colorは同じprep画像とsegmentマスクから全体・部位クラスタと共起関係をJSONへ出す。
shadeは補正画像を出力しないため、colorは補正なしの観測色を測る。Gray-World画像を再符号化してcolorへ渡す経路は追加しない。
run/region IDは評価用の決定的UUIDで、本番DBに登録した由来照合・キュー完了・DB容量の検証ではない。

各stageの`*-items.json`が成功・失敗と画像別時間、`*-telemetry.jsonl`が約1秒間隔のnvidia-smiと同じ計測PIDのRSS。
GPU使用率・メモリはノード全体のサンプル、PyTorch最大値はallocatorの割当・予約byteであり区別する。
CPU stage後半のRSS・GPUメモリには保持中のsegmentモデルも含む。サンプル最大RSSは瞬間的な最大値を保証しない。
最終の`ubuntu2-results.json`に集計とコード・モデルのSHAを残す。
JSON/JSONLは実行時のbyteを保つため、このディレクトリのGit改行変換を抑止する。
Windowsで作ったJSONのCRLFは保持し、行末のCRを空白違反としない属性を指定する。
実装SHAは転送時worktreeのbyte（srcはCRLF）で、Git blobのSHAとは別物。
そのsrcスナップショットは評価rootの`source.tar.gz`にも保全している。

評価出力・原本cacheはUbuntuの評価rootへ保全し、画像や重みをこのディレクトリへ同梱しない。
本番性能、転送帯域、DB確定、全量1万枚の解析完了、精度評価と読み替えない。
