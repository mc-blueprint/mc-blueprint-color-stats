# Issue #39: prep/color 計算プロセス方式の計測

## 結論

採用方式は、ワーカーごとに計算子プロセスを1つ常駐させ、親がキューjobを1件ずつ渡して結果ごとに個別commitする方式とする。prepはspawn-per-job比で2.03倍、colorは3.96倍の処理速度になり、最大RSSの増加はそれぞれ約6 MiB、約8 MiBだった。16件・64件の一括返却は常駐1件処理に対して追加の速度向上が小さく、途中失敗時にbatch全体を再試行するため採用しない。

## 条件

- 実行先: ubuntu-1、6 CPU、メモリ約15 GiB
- Python 3.12.3、Pillow 12.3、OpenCV 4.14.0。既存サービス環境を使い、新規インストールなし
- 専用DB `colorstats_bench39` の成功済みprep対象754件と、そのraw画像を `/var/tmp/colorstats-bench39` へコピーして使用
- 各方式を同じ754件に対し順番に実行。方式ごとの生成先は分離
- `bench/issue39_benchmark.py` で処理時間、親子プロセスの合計最大RSS、出力バイト数とSHA256を計測
- RSSは約20 ms間隔のサンプル最大値。1回ずつの逐次測定であり、負荷変動やキャッシュの影響を排除した統計比較ではない

## prep

| 方式 | 経過秒 | 件/秒 | 最大RSS MiB | 出力 bytes | bytes/件 |
| --- | ---: | ---: | ---: | ---: | ---: |
| spawn 1件/job | 891.614 | 0.846 | 1864.09 | 47,124,985 | 62,500 |
| batch 16 | 478.652 | 1.575 | 1865.20 | 47,124,985 | 62,500 |
| batch 64 | 456.986 | 1.650 | 1865.57 | 47,124,985 | 62,500 |
| 常駐 1件/job | 439.824 | 1.714 | 1870.14 | 47,124,985 | 62,500 |

常駐方式はspawn-per-job比で2.03倍。最大RSS差は+6.05 MiB。全754件の出力ハッシュは全方式で一致した。

## color

| 方式 | 経過秒 | 件/秒 | 最大RSS MiB | 出力 bytes | bytes/件 |
| --- | ---: | ---: | ---: | ---: | ---: |
| spawn 1件/job | 1021.576 | 0.738 | 249.27 | 4,597,418 | 6,097 |
| batch 16 | 302.782 | 2.490 | 254.16 | 4,597,418 | 6,097 |
| batch 64 | 264.817 | 2.847 | 254.86 | 4,597,418 | 6,097 |
| 常駐 1件/job | 257.916 | 2.923 | 256.84 | 4,597,418 | 6,097 |

常駐方式はspawn-per-job比で3.96倍。最大RSS差は+7.57 MiB。全754件の出力ハッシュは全方式で一致した。

## 失敗時の再試行範囲

計算の途中で例外を注入したところ、spawn-per-jobと常駐方式は失敗したjobだけを再試行できた。batchは途中まで計算した結果を返却・commitしない設計のため、batch16では16件、batch64では64件全体が再試行範囲となった。常駐方式では通常例外後も同一子プロセスを再利用し、子プロセス異常終了時だけそのjobを失敗にして次job用に再起動する。

## キュー契約・検証

キューのjob key `(stage, asset_id, config_hash)`、job単位のlease/token、結果ごとの完了・失敗処理、jobごとの不変出力先と登録処理は変更しない。一括claimや一括commitは導入しない。

回帰テストでは常駐プロセスの再利用、通常例外後の継続、異常終了後の再起動、リース喪失・更新時のDB例外後に旧結果を次jobへ混入させないことを確認する。停止・保存先異常では計算子を直ちに終了し、停止時のDB返却上限と#30の保留・available_atの契約を保つ。

ubuntu-1からubuntu-2への初回DB接続は`pg_hba.conf`で拒否されたが、2026-11-02にWSL2 Ubuntu-24.04のIssue39専用PostgreSQL 16コンテナで統合検証を行った。本番DB、パイロット、NFS、pg_hbaは操作していない。

### 実画像スモーク

`bench/issue39_smoke.py`は`TEST_DATABASE_URL`のDB内に専用schemaを作り、検証後にそのschemaだけを削除する。DB自体は作成・削除しない。実行はリポジトリ直下から以下の形式とする。

```sh
python -m bench.issue39_smoke --images /absolute/astronaut.png /absolute/chelsea.png --output /absolute/issue39-output
```

- Python 3.12.3、PostgreSQL 16、`uv sync --locked`の依存を使用。
- [scikit-image v0.25.2の実画像](https://github.com/scikit-image/scikit-image/tree/v0.25.2/skimage/data)からastronaut.pngとchelsea.pngを使用。[公式ライセンス説明](https://scikit-image.org/docs/0.25.x/api/skimage.data.html)では前者はpublic domain、後者は撮影者によるCC0。画像はGitへ含めない。
- 同じ常駐ワーカーで異常終了試験jobを再試行し、長時間job、実画像2枚のprep各2回・color各2回の計10件を完了。異常終了前後のPID変更と、成功10件での同一PIDを確認。
- リース更新6回。再試行は失敗jobだけで2試行目に成功。
- 同一asset・同一入力runに対する繰り返しでJPEGとcolor JSONのバイト列が一致。各結果は別の不変パスへ登録され、既存出力のハッシュが変わらないことを確認。color JSONにはasset/run IDが含まれるため、別スモーク実行間のJSONハッシュ一致は比較対象外。
- AssetのpHash更新、ColorObservationの件数とJSONの一致、成功時のrun登録を確認。

### 長期稼働の扱い

計算子は通常例外を含め256件の結果返却後、次jobの前に更新する。追加依存・RSS監視スレッドを導入せず、jobをまたぐキャッシュやリークの蓄積期間を制限するための固定上限とした。1件の処理中のメモリ上限・計算時間制限は設けていない。子だけのOOM終了は取得中jobの失敗、親を含む終了はリース切れで回収する。リース更新の取引タイムアウト時も、旧計算子を破棄する。

上の754件の速度・RSSは定期更新を加える前の常駐方式の測定値であり、256件ごとの更新を含む最終実装の性能値ではない。定期更新の境界と失敗後の再利用は小さい上限に差し替えた回帰テストで確認する。

### 最終検証（2026-11-02）

- 基準: 最新`origin/develop`の`4e016c5`をfeature/issue-39へfast-forwardし、未コミット成果を復元。#38・#40・#41・#43の変更を保持。
- WSL2 Ubuntu-24.04 / Python 3.12.3 / 専用PostgreSQL 16の空DB: 全pytest `360 passed, 1 skipped`。DB接続不足によるskipは0。1件のskipは公式重み・CUDAの明示指定を要する既存`test_segment_gpu.py`。
- Windows / Python 3.12.15: 常駐プロセスの回帰テスト`6 passed`。
- `uv run ruff check .`、`uv build`（sdist/wheel）、`git diff --check`成功。
- 任意Matplotlib機能の未導入警告1件あり。prep/color処理は成功。

実行環境ではcolor処理ごとにcolour-scienceのMatplotlib任意機能警告が出たが、全件が正常終了した。prepでは巨大画像に対するPillowのDecompressionBombWarningが出たが、処理は正常終了した。

計測には処理・一時出力ファイルの作成とrenameを含むが、PostgreSQLのclaim/renew/complete commit時間は含まない。測定値は同一ノードでの単一回比較で、別ノードや同時負荷時の性能保証ではない。

### 反証対応と再検証（2026-11-02）

- 子が受信前に停止すると、大きい要求の同期送信が親を止める問題を修正。標準の`threading.Thread`と`Event`で送信・受信を監視ループから分離し、新しい依存やIPC形式の変更を避けた。
- `poll()`後の`recv()`にも部分フレームで停止する余地があるため、要求送信から結果受信までを同じ通信スレッドで扱う。中断時は子を終了してから接続を閉じ、通信スレッドを回収する。
- 2 MiBの要求を受信しない子と、結果のフレーム長・本文1バイトだけを送って停止する子を実パイプで注入。停止フラグ、リース喪失、更新時のDB例外、保存先異常の各条件で、更新が続き、4秒以内に中断し、完了登録されず、子・通信スレッドが残らず、次jobが成功することを確認した。部分フレーム注入はPOSIXの生パイプ用。
- Windows / Python 3.12.15: `tests/test_queue_worker.py`は`10 passed, 4 skipped`。skipは上記POSIX専用の部分フレーム注入4条件。
- WSL2 Ubuntu-24.04 / Python 3.12.3: 同ファイルは`14 passed`。専用PostgreSQL 16の空DBによる全pytestは`368 passed, 1 skipped`（70.79秒）。DB理由のskipは0。既存GPUテストだけが公式重み・CUDAの明示指定不足でskip。
- `ruff check .`、`uv build`（sdist/wheel）、Windows側の`git diff --check`が成功。任意のMatplotlib未導入による既存警告1件あり。
- Dockerのbridge作成が失敗したため、専用コンテナ`issue39_review_postgres`をhostネットワーク・localhost:55439で起動。認証なし接続はこの一時DBのlocalhostだけに限定した。データはtmpfsで、検証終了時にコンテナと付随volumeを削除した。本番DB・pg_hba・パイロット・NFSは操作していない。
- コマンド記録は`~/.codex/logs/commands/`。全pytestは`20261102T040630Z-f553a0f0ed2b4e7ea4576335a23a4f3e.jsonl`、ビルドは`20261102T040813Z-63067fea3bcb44a6b85de9d55bf622a5.jsonl`。

### 再確認の指摘対応（2026-11-02）

- 送信詰まり中の`KeyboardInterrupt`が`except Exception`を抜け、終了処理が同じ接続へ`send(None)`して元の例外を`ValueError: concurrent send_bytes() calls are not supported`で上書きする問題を、Windows実パイプの回帰テストで再現した。
- `BaseException`で抜ける場合にも子・接続を破棄し、通信スレッドを回収してから元の例外を再送出する。終了処理は破棄済み接続へ再送しない。標準の例外処理を拡張し、依存追加・公開API・保存形式の変更はない。
- 既存の通信停止テストを`run(once=True)`経由にし、`KeyboardInterrupt`と`SystemExit`を追加。送信詰まり・部分フレーム受信中に、元の例外オブジェクトが維持され、4秒以内に中断し、子・通信スレッドが残らず、次jobが成功することを確認した。
- Windows / Python 3.12.15: `tests/test_queue_worker.py`は`12 passed, 6 skipped`。skipはPOSIX専用の部分フレーム注入6条件。WSL2 Ubuntu-24.04 / Python 3.12.3では同ファイルが`18 passed`。
- WSL2・専用PostgreSQL 16の空DBによる全pytestは`372 passed, 1 skipped`（74.96秒）。DB理由のskipは0。既存GPUテストのみ公式重み・CUDA等の明示指定不足でskip。任意Matplotlib機能の未導入による既存警告1件あり。
- `ruff check .`と`uv build`（sdist/wheel）が成功。最終差分の`git diff --check`も成功。
- 一時コンテナ`issue39_interrupt_postgres`をhostネットワーク・localhost:55439、tmpfsで起動し、全pytest後にコンテナと付随volumeを削除した。初回のシェル引数受け渡し失敗時も削除済み。一時検証スクリプトも作業差分から削除した。本番DB・pg_hba・パイロット・NFSは操作していない。
- コマンド記録: 修正前再現`20261102T041753Z-f5cd7ce8ffec404a9b3dfa446c38644e.jsonl`、Windows回帰`20261102T041807Z-8a646c09906c4902b490c6297e0d9a95.jsonl`、POSIX回帰`20261102T041808Z-2cc5222e90224d498f75545da6dc8dc3.jsonl`、全pytest`20261102T041914Z-de6623b3f7b84e18bc318cfc7ea192cd.jsonl`、ruff`20261102T041858Z-bc4a0b92ec0b4413bed922da02da1a6d.jsonl`、ビルド`20261102T041941Z-d9b972106b3747f6bc640099d5d8aeca.jsonl`。
- HEADは引継ぎどおり`4e016c5`。今回確認した追跡参照では`origin/develop`より2コミット遅れており、最新化操作は行っていない。公開前の基準整合確認はメインに引き継ぐ。
