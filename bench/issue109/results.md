# Issue #109 縮小既定・原本再判定・閾値監査

## 変更と完成条件

- 新規Commons収集はAPI縮小が既定。幅・高さとも1280を要求し、原本は明示指定できる。
- 新規jobへ品質設定を固定し、縮小の受信実寸・原本のAPI寸法で長辺1280未満を理由付き除外する。
  通常原本のPillow検査は行わず、#90の巨大原本・候補単位除外の契約を維持する。
- prepの既存品質検査を再利用し、縮小版の透かし・ぼけ・コラージュ疑いから原本review jobを予約する。
  理由、元variant、asset、収集run、原本revisionを記録し、原本のSHA-1を照合する。
  原本でも対象フラグが残る場合はrejected、消えればaccepted、取得不能ならunevaluated。
  結果は新しいrunに保存し、元asset・収集runを変更せず、独立asset支持も増やさない。
- 対応解析後に`enqueue_audit`で監査jobを投入する。平均主色距離と主要部位の画素加重一致を記録し、
  閾値超過はwarning、欠測は未評価として残す。画像やモデルの再取得・再解析は自動化しない。
- collect workerの生成設定にqualityのreview handlerを接続した。稼働サービスは変更していない。
  LoC・Mapillaryの無効化、UA、権利・保持規則、#90のidentityは維持した。

既存のSearchRequest、CommonsAdapter、prep検査、collect.prepare/register、Queueと#89のMeterを再利用した。
依存追加・DBスキーマ変更・既存データ移行はない。

## 既存100枠の許容差監査

`PYTHONPATH=src python bench/issue109/audit_baseline.py`で#90の保存済み比較を再集計した。
入力SHA-256と完全な数値は`baseline-audit.json`に記録した。追加の画像取得・GPU推論はない。

| 指標 | 結果 | 閾値 |
| --- | ---: | ---: |
| 評価組 / 未評価 | 98 / 2 | 未評価を分母から隠さない |
| 主色OKLab距離の平均 | 0.015432534620013913 | 0.02以下 |
| 主要部位一致 | 0.8693846259302518 | 0.85以上 |

主要部位はintersection 32,341,934 / union 37,200,950。人手正解に対する精度ではない。
閾値内でpassed。境界と超過検出、監査run・不変出力への記録はテストでも確認する。
#90の固定100枠は当時の幅1280要求による結果。新条件は以下の固定縦長27件で別途評価した。

## Commonsの小規模実取得（2026-11-05）

ubuntu-1の隔離PostgreSQL 16と新規保存先
`/mnt/data/derived/issue109-20261105T115600Z/`で`smoke.sh`・`smoke.py`を実行した。
実行コードは同ディレクトリのcode/に固定し、budget.json・events.json・report.jsonを保存した。

| 項目 | 実績 / 事前上限 |
| --- | ---: |
| Commons API | 4 / 10 |
| 画像要求 | 3 / 20 |
| 新規asset | 縮小1・明示原本1 |
| フラグからの原本再判定job | 1 |
| 収集assetの受信byte合計 | 821,031 |

既定検索はHimeji Castle、明示原本はMont Saint Michel、各limit=1。collect 2件・review 1件が成功した。
縮小版のcollage_suspectedを理由に原本を取得し、5179×2688 JPEGを同じ規則で再判定してrejectedを記録した。
再取得原本のSHA-256は`1915493550eb3c25d5d58a72d4568331abcf6529614b40a2d65bca4890d4bacc`。
この判定はコラージュを人手で確定したという意味ではない。
再判定前後で2 assetのSHA・保存先・qualityと元collect run.parametersの完全一致を確認した。
本番DB・既存asset/run・pilot・認証設定・UAは変更していない。隔離PostgreSQLは停止済み、画像・結果は保全した。

## 検証

指定WSL Ubuntu-24.04のext4一時コピーと、新規の隔離PostgreSQL 16で実行する。
再現手順は`bash bench/issue109/verify.sh`（Windowsの担当worktreeをコピーする端末専用手順）。
反証修正後の全pytestは992成功・1スキップ（GPUモデル未指定のsmoke）、ruff全体とsdist/wheelも成功した。
全件検証先は`/tmp/colorstats-issue109-5Kcaki/`。
初回実装の要求高さの記録・worker設定の接続差分は、関連135テスト、ruff全体、
sdist/wheelとLinux改行での`bash -n`が成功した（`/tmp/colorstats-issue109-RH029X/`）。
両方の隔離PostgreSQLは停止済み。buildとログは各一時ディレクトリに保全した。
縦長結果を含む最終資料と比較コードは、関連45テスト・ruff全体・sdist/wheel・bash構文を
`/tmp/colorstats-issue109-4CKySD/`で再確認し、すべて成功した。隔離PostgreSQLも停止済み。

重点反証は、最低実解像度の境界と極小画像、原本のaccepted/rejected、SHA-1不一致、
既存asset/run不変、重複支持抑止、#89の通信枠停止、監査の閾値境界・画素加重・欠測・入力改変を対象とした。
初回のfixture重複更新とprovider切替テストの取得mode引継ぎを修正した。

## 反証指摘の修正

通常collectは原本へPillow検査を適用せず、原本の寸法・MIMEをAPI値のまま扱う#90の契約へ戻した。
`quality_policy`あり・なし双方でPillow上限を超える入力、SHA-1の欠落・一致・不一致を再現し、
同じバッチの取得済み候補を失わず、不一致候補だけを除外・予約解放することを確認した。
専用原本再判定でのPillow上限は`original_quality_image_limit`、復号不能は
`original_quality_unreadable`の理由付き未評価とし、一時ファイルだけを除外する。

reviewをcollect/prepと同じ監視対象raw媒体の停止検査へ加えた。
停止マーカー・媒体欠落でreviewが停止し、同じworkerが他のstageを継続することを回帰テストで確認した。

## 新しい幅・高さ1280要求の縦長比較

#90の固定100件のうちheight > widthの全27件を元index順で固定選定した。
新しい画像や都合のよい20件への差し替えは行っていない。
選定ID・原本SHA・新縮小SHA・各組の比較値は`portrait-comparison.json`、集計は`portrait-summary.json`。

| 指標 | 縦長27組の新条件 | 許容差 |
| --- | ---: | ---: |
| 評価 / 未評価 / 解析失敗 | 27 / 0 / 0 | 全選定を記録 |
| 主色OKLab距離の平均 | 0.0020194708505899958 | 0.02以下 |
| 主要部位一致 | 0.8864913192996784 | 0.85以上 |
| 主要部位intersection / union | 10,216,652 / 11,524,819 | 全主要ラベルの画素合算 |
| Commons API / 上限 | 1 / 5 | 再試行も計上 |
| 新縮小画像 / 上限 | 27 / 30 | 既取得を再利用 |
| 原本の追加取得 | 0 | 既存原本のみ |
| SHA不変を確認した原本 | 27 | 開始・終了時に照合 |

両方の許容差を満たしたため、新しい幅・高さ1280要求を既定に保つ。
要求値とは別にCDNの実寸を測定し、受信長辺は1280～1712pxだった。
API応答の表示寸法が1280でもCDNの段階的サイズが返るため、実寸を1280ちょうどと仮定しない。
最初の1枚でこの差を検出して停止後、保存済みAPI応答・画像・予算を引き継ぎ、
その1枚を重複取得せず残り26枚だけを取得した。UA、interval、Retry-After、帯域窓は#89/#90の実装を維持した。

既存原本は#90の固定manifestが参照する保存済みrawを読み取り専用で使用した。
原本のprep・segment・colorの既存不変出力を新規比較先へ参照・再利用し、
新縮小には#90の同じprep（RGB/LANCZOS/JPEG品質90）、SAM2＋DINO、colorを適用した。
モデル・prompts・threshold 0.35/text 0.25・seed0・bfloat16・batch1は#90と同じ。
原本・既存run・本番DB・pilot・モデル配置へ変更はない。

保存先はubuntu-1の`/mnt/data/derived/issue109-portrait-20261105T122000Z/`。
実行コード、selection、API応答、budget、events、manifest、解析出力と失敗履歴も保存した。
既存#66の`/opt/colorstats/work/issue66-20261104/.venv`と保存済み#90コードを再利用し、
新たな環境構築・依存追加・モデル取得は行わなかった。オフラインモードで解析した。
初回の依存不足による27件未評価は履歴として保全し、最終的には27件すべて再解析に成功した。
GPU処理は終了済み。人手正解は追加しておらず、一致度は精度ではない。
