# クラウドVLM試行の実行契約（Issue #142）

#141の入力・結果・HTML契約は [vlm-trial.md](vlm-trial.md) を参照する。
本機能の完成検証は合成入力とスタブによる。実GPUの動作・速度・品質・課金・
削除成功・24時間連続稼働は、実行許可後の記録で確認する。

## 構成と再利用

- trial_runnerは実行状態・有効attempt・停止・回収確認を管理する。
- trial_runpodはRunPod Secure On-DemandのREST v2とSSHだけを扱う。
- trial_nativeはA/B/CのvLLMとSAM2.1 large、DのSa2VA、EのSAM3へ接続する。
- trial_costsは固定費込みの比較と予約、trial_ledgerは段階共通の私有USD台帳。
- trial_run_cliは起動窓口。trial_fakeは外部通信を行わない合成backend。
- #141の権利再確認、PNGパッケージ、逐次結果検査、受領確定、比較ページを再利用する。
  合成入力の生成だけを既存trial_cliから抽出した。新しい依存は追加していない。

実行側はLinuxまたはWSL Ubuntu-24.04を用いる。OSのflockでresult_rootとUSD台帳を
それぞれ排他にし、1つのrunnerが最大2構成を管理する。別rootから同じUSD台帳を同時に
使うことも拒否する。DBの操作は、実写真の権利再確認に必要な#141のREAD ONLY取引に限定する。

## CLI

以下は手順例。作成先の親は存在している必要がある。

```sh
python -m colorstats.trial_run_cli demo --result-root /private/new-synthetic-trial
python -m colorstats.trial_run_cli demo --result-root /private/new-synthetic-parallel --concurrency 2
python -m colorstats.trial_run_cli review --plan /private/execution.json --output /private/trial/review.json
python -m colorstats.trial_run_cli run --plan /private/execution.json --dry-run
python -m colorstats.trial_run_cli run --plan /private/execution.json --authorization /private/authorization.json
python -m colorstats.trial_run_cli run --plan /private/execution.json --authorization /private/authorization.json --resume
python -m colorstats.trial_run_cli run --plan /private/execution.json --authorization /private/authorization.json --cleanup
```

demoは30枚の合成入力から、5構成150件のダミー結果を回収・受領・HTML化し、
新設資源の終了相当まで同じrunnerで通す。dry-runは合成manifestだけを受け付ける。
秘密参照・実GPU・提供元APIの認証は不要。推定USDは形式検証用の時計見積で、
実請求を示さない。実接続扱いの実行は許可不足ならPod作成前に停止する。

reviewの出力はresult_root内の私有ファイルに限定する。対象件数・manifest SHA、
モデル版・提供元・地域・費用・保持期限・削除範囲・未検証事項・必要な許可をまとめる。
既存ファイルは上書きしない。実行の標準出力は状態・件数・推定費用・合成backendの区分だけ。

## 私有実行設定

execution.jsonはtrial-execution-v1。実行設定はGitへ保存しない。
synthetic_plan関数はテスト用の形式例であり、仮の重み・環境・containerと
未確認のライセンスを持つ。実接続設定へそのまま流用できない。

| 項目 | 条件 |
| --- | --- |
| result_root | #141で作った固定30件の私有絶対パス。回収先はこの1か所 |
| budget_ledger | Git外の私有USD台帳の絶対パス。smoke・測定・本体で同じ値 |
| provider / product / region | runpod / secure-on-demand / 固定データセンター。自動変更なし |
| purpose | smoke / measurement / trial |
| measurement | 測定を含む総枠かどうか。省略した5 USDを本体へ移さない |
| concurrency | 既定1、選択時2。A終了後B/C、その後D/E |
| configurations | #141のA～E固定参照 |
| deployments | A～Eそれぞれの下表の実行設定 |
| smoke_record | 実GPU合成smokeまたは測定の確定checkpointのfileとsha256。本体で必須 |
| measurement_record | 終了確認済み測定checkpointのfileとsha256。測定あり本体・smokeで必須 |
| api_key_file | 既存のRunPod専用秘密ファイルへの参照。要求時だけ読む |
| ssh_key_file / known_hosts | 専用SSH鍵・事前照合したhost keyの参照。値を設定・ログへ転記しない |
| billing_receipts | 私有の課金終了照合記録への参照。不存在・未確定は未完了 |

deploymentsの各構成は次を持つ。

| 項目 | 意味 |
| --- | --- |
| container | 配布物を含むcontainerの完全な@sha256参照 |
| gpu / gpu_count / disk_gb | 固定GPU種、同一Podの1または2GPU、ephemeral disk容量 |
| hf_secret_name | 必要時の既存RunPod Secret名。HF_TOKENへ名前で参照し、値をcontrollerへ取得しない |
| versions | native環境の依存名と正確な版の辞書。実行時にmetadataと照合 |
| model / segmenter | repo、40桁revision、files、license_ref、license_confirmed |
| files | 重み・processor設定・remote code等のfileと既知sha256の完全な必要一覧 |
| usd_hour | 全GPU・disk・CPU/RAM・税等を含む時間単価 |
| hourly_extras_usd | Podのcompute costに含まれないdisk・税・追加時間課金分。二重計上しない |
| fixed_usd / minimum_seconds | 転送等の定額と最低課金。起動・取得・ロード中も時計で加算 |
| time_seconds / cleanup_seconds | 構成の総秒上限と終了処理の余裕。再試行も同じUSD枠内 |
| prepare_timeout_seconds | 画像転送前の準備上限、最大1800秒 |
| image_timeout_seconds | 1画像の上限、最大120秒 |
| memory_fraction | vLLMの固定GPU割当率。A/B/Cは各GPUの4GiB余裕も検査 |
| measurement_evidence | 高単価採用時のbaselineとcandidateの測定checkpoint参照 |

filesのSHAを未取得物の初回算出値で補わない。公開照合値・固定revisionでの取得証跡と
算出値を区別し、containerと必要ファイルを別の準備段階で固定してから実行設定へ入れる。
環境SHAとコードSHAは後述のruntime全体の固定参照から作る。
重みSHAはdigest(files)、processor SHAはdigest(LIMITS)、指示SHAはPROMPTのUTF-8 SHA。
processorの実ファイルはmodelの固定一覧とrevisionにも含める。

初回実装の固定モデルは承認済み計画第3節に対応する。

| 構成 | 方式 | revision |
| --- | --- | --- |
| A | Qwen3-VL-8B-Instruct BF16 | 0c351dd01ed87e9c1b53cbc748cba10e6187ff3b |
| B | Qwen3-VL-32B-Instruct BF16 | 0cfaf48183f594c314753d30a4c4974bc75f3ccb |
| C | Qwen2.5-VL-72B-Instruct-AWQ、4bit＋FP16演算 | c8b87d4b81f34b6a147577a310d7e75f0698f6c2 |
| D | Sa2VA-8B BF16、内蔵分割器 | 902b049acb12eb68454abf4e51ab1e23d1bc9efa |
| E | SAM3 FP32、場面はunsupported | b7296bc5016065f0d6e772c058601de3da6e932b |
| A/B/Cの分割器 | SAM2.1 Hiera large FP32 | 665f8e2ad61cf5f53d65644ff27c8ee525124610 |

A/BはApache 2.0、Cは独自Qwen License、Dは基盤・内蔵分割器も含む確認、
EはSAM Licenseとアクセス同意、SAM2.1はApache 2.0を確認する。
license_refには確認記録のSHAを指定する。ライセンス未確認ならsmokeも拒否する。

## 許可と実行前の確認

authorization.jsonはユーザー原文と日時、plan_sha256、manifest_sha256、
provider・product・region、max_usd、expires_atを持つ。send_images、billing、
delete_new_resources、retention_confirmedが明示的にtrueである必要がある。
operationsにregion、checked_atとstatus_ref・maintenance_ref・capacity_ref・
data_terms_refのSHAを置く。実行前に公式status・予定保守・対象GPUの在庫と
同一ホスト配置・画像のログ/backupを含む保持条件を確認した記録へ結ぶ。
不明な条件を補完して送信許可にしない。

smoke・measurementは合成入力を用い、各構成3件で残りをmissingとして保存する。
実GPUのsmoke成功checkpointは、fakeでないこと、合成入力であること、
同じモデル・環境・GPU設定であること、完了とSHAを本体前に検査する。
同じUSD台帳へ費用を引き継いだことも照合する。実写真の許可はさらに別の記録が必要。

実写真の送信前と回収後は、既存のrecheckで元権利・停止要求・保持期限・元SHA・
入力PNGを読み取りで再確認する。ライセンス区分や過去のOpenAI同意だけで送らない。
許可の期限は起動・回収・終了を含む実行窓に合わせる。失効しても--cleanupは
起動時に記録した新設資源削除許可を使い、入力を再利用せず終了だけ進められる。

## native処理・送信と回収

RunPod REST v2で地域・GPU・container digest・ephemeral disk・SSHと空のmountsを指定する。
準備中の未割当地域は待機し、RUNNINGになってから固定地域と無添付storageを照合する。
Community、Spot、待ち行列、別地域、既存volume、公開HTTPへの切替は実装していない。
同じ名前の資源が複数ある場合は停止する。作成を拒否した4xxと応答不明を区別する。応答が失われてもPOSTを再送せず、
同名・同IDを一覧で照合するまで新規起動を止める。

重みは画像転送前に公式repoの固定revisionから専用領域へ取得し、既知SHAを照合する。
ゲート付き重みの認証はhf_secret_nameで既存のRunPod Secretを参照できる。
Pod起動時にHF_TOKENへ展開し、controllerは値を取得しない。専用containerは
SSHからのnative処理にもこの変数を渡す構成が必要。Secretの作成・変更は実行範囲へ含めない。native呼出しは固定したcontainerに
対応するvLLM、SAM2、Sa2VA、SAM3とコードがインストール済みであることを前提にする。
本リポジトリのCPU環境へGPU依存を混在させない。

写真は1枚ずつ番号だけのinput.pngとしてSSH転送する。送るrequestにはモデルの固定参照、
試行番号・入力SHA・期限だけを加え、元の内部対応・元URL・タイトルは渡さない。
StrictHostKeyCheckingとBatchModeを必須にする。認証値をログへ出さず、
実行操作・終了コード・出力SHAを私有checkpointへ記録する。

A/B/Cは同じ日本語の部位説明、batch 1、長辺1024、context 8192、
回答1536 tokens、最大24領域を使う。processorの画像token込み上限を確認し、
vLLMの箱を元座標へ変換してSAM2.1 largeへ渡す。VLMとSAM2は別プロセスで、
VLM終了後にSAM2をロードする。初回経路は写真ごとの別プロセスなので、
モデル再ロード時間もUSD/件の処理時間へ含む。常駐時の速度へ読み替えない。

Dは著者のpredict_forwardと内蔵maskを使い、生成の入力token数・回答上限を検査する。
EはSAM3単体の6部位照会とFP32を維持する。vLLMの子workerを含むGPU使用量は
nvidia-smiでも読み取り、GPUごとの余裕を確認する。OOM、token超過、
打切り、部位数超過、形式差は失敗として停止し、解像度や精度を変更しない。

回収では入力SHA・構成SHA・寸法・番号・実行識別を受信値と照合する。
maskを保存前にfile-ledgerへ登録し、#141のvalidate_resultへ渡す。
有効attempt表はrunnerが開始時に設定し、受信行から作らない。検証済み結果を
不変checkpointへ保存してから外部画像・maskを除去する。
回収確認が2分途切れたら新規入力を停止する。各backend操作には14秒の総枠を置き、
CLIは処理時間込みの10秒周期を目安に反復する。

外部期限は写真ごとに転送時から24時間か元・ローカル期限の早い方。
Pod内の期限処理は当試行の既知ファイルだけを対象とする補助策で、
provider障害中の消去やbackupの消去を保証しない。通常の回収後削除・Pod削除・
残存確認と併用し、保持条件や削除が確認できなければ未完了として報告する。
ローカル期限に達したコピーも、台帳SHAとroot内のパスが一致する画像・HTMLだけを
終了経路で除去する。元画像は対象にしない。自動schedulerを新設せず、
担当runnerの監視と、必要時の--cleanupを運用する。

## 費用・停止・中断と再開

既存OpenAIのapi_budget台帳と分け、trial-usd-v1のUSD台帳を使う。
起動要求時から時計で加算し、請求の方が大きければ請求額を採る。終了と最終請求の照合後は、
税・追加費用込みの確定USDへ置き換え、不課金だった停止時間を実費へ加算しない。
単調時計と保存UTCの大きい経過時間を使い、再開で時計をリセットしない。
同じUSD台帳のsmoke・測定・本体・再試行を合算する。fakeの台帳を実請求に流用しない。
中止した測定も、資源の終了を確認したcheckpointの費用を引き継ぐ。
高単価の採用根拠に使う測定は、正常3件以上を持つ完了記録に限定する。

| 区分 | 上限 |
| --- | --- |
| 測定あり全体 | hard 20 USD、soft 18 USD |
| 測定省略全体 | hard 15 USD、soft 13 USD |
| 測定だけ | 5 USD・全run合計40分・最大4 lease・1 lease 20分・6 USD/h以下。3.5 USDまたは30分で新規起動停止、4.5 USDで終了へ |
| A / B / C / D / Eのsmoke・本体・再試行の共有予約 | 1.45 / 3.55 / 4.95 / 1.45 / 1.45 USD |
| 同じ構成の再起動 | 旧資源の終了・請求確認後に最大1回、残USD・時間内 |
| 全体の設備障害 | 2回で新規処理停止 |
| 管理・回収監視失敗 | 2回で新規処理停止・終了へ |

共有予約の総和は12.85 USDで、測定省略時のsoft 13 USDを下回る。
A/D/EはA40 1台、B/Cは2台、200GB container diskと仮の税10%を含め、
全込み単価0.679556/1.328556 USD/hとした見積に基づく。
smoke各0.5時間と本体1.5/2/3/1.5/1.5時間の通算見積は、
A/D/E各1.359111、B 3.321389、C 4.649944 USD（計12.048667 USD）。
各枠には約6%以上の余裕を持たせる。時間・税は仮定であり完了保証ではない。
実際の単価・税・追加費用が変わる場合は開始前に再照合する。
既存runを異なる枠で再開せず、新規試行に適用する。

構成別の上限時間は元の1.5/2/3/1.5/1.5時間と、
(残USD予約－定額)/実単価から逆算した時間の短い方。終了余裕も差し引く。
高単価GPUへ元の時間上限をそのまま渡さない。soft到達後は終了用の残枠を使い、
料金遅延・通信障害下で請求上限を絶対保証できるとは扱わない。

1.5 USD/h超は同じ入力・構成の実GPU測定checkpointからmeasured_profileを作り、
固定費込みD(30)の費用区間が、1.5 USD/h以下の基準より安い場合だけ採用する。
候補のGPU・台数・地域・container・時間単価・定額・最低課金も測定記録と照合する。
同額なら速い候補、区間が重なれば基準を維持する。D(10000)は別に計算する。
fakeの観測を採用根拠にできない。summaryは予定30件あたりと、
実際に画素を持つmaskがある正常完了件数あたりのUSDを分け、失敗・再試行・固定費も含む。
公開incident件数を故障確率へ変換しない。24h確認・全量は別承認・別予算。

再開は入力・モデル版・精度・環境・指示・分割器・資源設定の一致が必須。
確認済み結果を保持し、未完了分だけ新attemptへ出す。旧attemptの遅延結果は拒否する。
管理APIに届かない場合はworker消失と断定せず、同名照合と終了確認を優先する。
不変checkpointの欠落・SHA差は拒否し、既存出力を上書きして復旧しない。
受領確定後の再開は#141記録を再照合し、完全な比較ページがあればSHAを照合する。
ページ生成途中の欠損は保全して報告する。

終了は当試行のname/IDが一致するPodのTerminateだけを実行する。
新設network volumeを作らない設計で、既存volumeには操作しない。
一覧の全ページと残存volumeを確認する。課金APIの時間bucketは確定印ではないため、
billing_receiptsに資源IDごとの全費用込みamount_usd、ended_at、evidence_sha256を記録し照合する。
請求確定・削除を確認できるまでは予約を解放せず、完了扱いにしない。
未確認なら--cleanupで再照合する。並列の一方が未確認でCLIを終了する場合も、
他方を含む全新設資源の終了を試み、未確認の資源を残して報告する。レシートは私有で、公開文面へ転載しない。

## 検証と未検証事項

合成30件の逐次・2構成並列、150結果、比較ページ、事前mask登録、
許可なし・ライセンス未確認・費用不足・価格差・時間切れ・未回収・失効、
参照差・旧attempt・管理不通・作成応答喪失・部分成功・再開上限・削除不能を検証する。
提供元REST/SSHと5モデルのnative接続はスタブで確認する。
WSL隔離PostgreSQLで既存の全pytest、ruff、uv buildも実行する。

実在のcontainer digest・依存lock・重みSHA・ライセンス確認・地域とデータ条件・
実GPU合成smoke・写真30件の最終確認は、実行準備段階に残る。
実装レビュー後に対象と費用・保持・削除の範囲を示して送信・課金の許可を得る。

一次資料は2026-11-17に確認した。REST v1の廃止に合わせv2を使う。
[RunPod v2](https://docs.runpod.io/api-reference-v2/overview)、
[Pod作成](https://docs.runpod.io/api-reference-v2/pods/create-a-pod)、
[請求](https://docs.runpod.io/api-reference-v2/billing/get-pod-billing-history)。
[Qwen3-VL](https://github.com/QwenLM/Qwen3-VL)、
[SAM2](https://github.com/facebookresearch/sam2)、
[Sa2VA](https://huggingface.co/ByteDance/Sa2VA-8B)、
[SAM3](https://github.com/facebookresearch/sam3)。

既存Secretの参照は [RunPod公式の秘密管理](https://docs.runpod.io/pods/templates/secrets) に従う。

### ファイル転送の接続条件

公開IPとTCP 22を備えたPodの `ssh.direct` を使い、既知のhost keyを厳密に照合する。
一覧APIには直接接続情報が出ないため、RUNNINGの当試行PodをIDで個別取得して同名・同IDを照合する。
接続先の準備・host keyの事前照合が済まなければ、写真は送らない。
専用コンテナはSSH daemonとSCPを含む。プロキシ経由の基本SSHはSCP/SFTP非対応のため使用しない。
接続情報が未準備の場合は監視未確認として扱い、2回続けば停止・清掃する。
[公式SSH接続条件](https://docs.runpod.io/pods/configuration/use-ssh)を確認した。

## 反証指摘への修正

清掃はPodごとの例外を集約し、全新設Podへの終了を試みてから失敗を記録する。
請求証跡の破損・形式差や他の清掃失敗があれば、未確認の資源と費用予約を残し、成功扱いにしない。

測定の時間・lease数は共通USD台帳の過去runを含める。並列資源の残り予約も差し引く。
合成入力の測定は起動・形状確認用で、高単価GPUの採用根拠にはしない。
このCLIの測定経路は合成入力だけであり、実写の測定証跡を生成する経路は今回追加していない。

権利再確認で得た最新の短い期限を実行状態と送信先へ反映する。
送信先では別ファイルへの転送後に期限ファイルを置き換え、独立監視が1秒以内の間隔で読む。
期限に達したら当該写真の専用プロセス群を終了してから既知ファイルを削除し、処理終了後の再書込みを防ぐ。
controller停止後も最後に確認・転送した期限に従う。停止後にDBだけでさらに変わった条件は自動取得できない。
期限の更新が確認できなければ停止・全新設資源の清掃へ進む。ローカルコピーも保存済みの最新期限で清掃する。

HTTPは接続・本文受信を含む14秒総枠をPOSIXタイマーで中断する。
低速で本文が届き続けても枠を延長せず、終了時に既存のsignal handlerを復元する。
controllerの主スレッドから呼び、既存の実時間タイマーがある場合は併用を拒否する。

## SAM3専用環境（Issue #145）

通常環境はNumPy 2系、SAM3専用環境はNumPy 1.26.4に固定する。
vLLM 0.20.0がOpenCV headless >=4.13を要求し、そのOpenCVがNumPy >=2を要求するため、
NumPy <2を要求するSAM3を別Pythonで実行する。
SAM3の処理はtrial_sam3へ移し、画像・ファイル検査・期限・phase保存を
DB依存のないtrial_native_commonで共有する。

### 配備と固定値

ops/vlm-trial/DockerfileはCUDA 13.0.2 / Ubuntu-24.04のamd64 base digestを固定する。
以下の3環境を同じPodのephemeral diskへ作る。

| 環境 | Python | lock |
| --- | --- | --- |
| 通常アプリ・vLLM・SAM2・Sa2VA | /opt/colorstats/controller/bin/python | /opt/colorstats/locks/controller.lock |
| SAM3 | /opt/colorstats/sam3/bin/python | /opt/colorstats/locks/sam3.lock |
| 配備用uv | /opt/colorstats/tools/bin/python | /opt/colorstats/locks/tools.lock |

requirements-controller.in、requirements-sam3.in、requirements-tools.inから、
uv 0.13.6 / Python 3.12 / Ubuntu-24.04向けに生成したlockを同梱する。
公開ソースのarchiveも固定commitとSHAで参照する。sources.jsonに照合値を置く。
source配布の依存宣言はuv.tomlへ公式の内容を記載し、解決時のbuildを避ける。
モデル重みは従来のprovisionで画像転送前に取得・照合する。

Dockerfileは環境別lockの配布物SHAを要求し、build用依存にもcontroller.lockを適用する。
通常アプリ本体のbuildは通常環境で行い、解決済み依存を両環境でuv pip checkする。
SSH公開鍵はPod側のPUBLIC_KEYまたは用意済みauthorized_keysを使い、host keyは起動時に生成する。
実行前に直接SSH接続とknown_hostsを別途確認する。

deploymentsの各構成にruntimeを追加する。

| 項目 | 条件 |
| --- | --- |
| runtime.code_files | trial_native.py、trial_native_common.py、trial_sam3.py、trial_paths.jsonのファイル名とSHAの辞書 |
| runtime.lock | 通常環境lockの固定fileとsha256 |
| runtime.sam3 | Eで必須。python、versions、lockを持つ |
| runtime.sam3.python | /opt/colorstats/sam3/bin/python |
| runtime.sam3.versions | SAM3環境の正確な配布名と版。NumPy 1.26.4、torch 2.11.0、torchvision 0.26.0、Transformers 4.57.6を含む |
| runtime.sam3.lock | /opt/colorstats/locks/sam3.lockのfileとsha256 |

code_sha256はdigest(runtime.code_files)とする。
environment_sha256はdigest(environment_reference(versions, runtime))とし、
通常環境の版・lockとE専用環境の版・lock・Pythonを参照に含める。
code_files()とenvironment_reference()はtrial_native_commonの関数を使う。
構成設定を作るときは、配備するコードとlockの実byteからSHAを算出する。

既存の私有execution.jsonはruntimeと構成SHAを再生成する。
旧設定の再開には固定参照不一致が生じるため、新しい設定・新しい試行として準備する。
#141の入力・結果の項目、mask保持期限、番号、受領条件は従来の契約を使う。

### 起動・期限・失敗

親は通常環境のコード・lock・版を検査してからE専用Pythonを明示して起動する。
E workerは通常アプリをimportせず、同じプロセスグループで動く。
自身を含む実行コード、専用lock、宣言した依存版、固定モデルと重み一覧、
入力SHA・長辺・保持期限を検査する。
保存前にもdeadline.jsonの短い期限を確認する。
OOM・期限切れ・例外は既存のfailure.jsonへ理由codeを保存し、親が失敗結果へ変換する。

画像の時間上限、GPU監視、期限の独立監視、費用上限、全新設Podの清掃は
#142の既存経路を使う。期限更新・旧attempt拒否・単一writerの条件も適用する。
再開時はworkerと環境別lockを含む構成参照の一致を要求する。

### 検証の範囲

合成入力と推論スタブで、専用workerの二値PNG出力から150結果の受領・
30件の比較ページまで検証する。入力・重み・worker・lock・依存版の差、
保存前の期限短縮、OOM・例外、並列D/Eの終了も検証する。

lock解決に加え、Issue #149で実install・コンテナbuildとGPU不要範囲のimportを検証する。
CUDA ABI・画像推論・GPUごとのVRAM余裕は実GPU smokeで確認する。
Dockerfile中の配備手順を実際に動かす段階でも、ユーザー許可の範囲を照合する。

公式依存宣言は2026-11-18に確認した。
[SAM3](https://github.com/facebookresearch/sam3/blob/31cb7e624e4fe95301b1be1d4e809111593d2e45/pyproject.toml)、
[SAM2](https://github.com/facebookresearch/sam2/blob/2b90b9f5ceec907a1c18123530e92e794ad901a4/setup.py)、
[iopath](https://github.com/facebookresearch/iopath/blob/v0.1.10/setup.py)、
[FlashAttention](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/setup.py)、
[vLLM 0.20.0](https://pypi.org/pypi/vllm/0.20.0/json)。


### SSH起動での環境指定

配備先のPythonとコード探索パスはsrc/colorstats/trial_paths.jsonへまとめる。
Dockerfileも同じJSONから通常環境・SAM3環境を作成し、依存検査へコード探索パスを渡す。
JSON自体もruntime.code_filesへ含める。

RunPodのprepare/start、通常側の子phase、SAM3 worker、独立した期限監視は、
python_command()が作る絶対Pythonと明示PYTHONPATHの引数で起動する。
OpenSSHがセッション環境を作り直した場合も、固定コードの探索先を指定して開始できる。
起動スタブで、両環境の絶対Python・探索パス・プロセス群・時間上限を照合する。


## containerの実buildと非公開registry（Issue #149）

SAM2の配布名は`sam-2`、Pythonのimport名は`sam2`である。
依存入力・uvの静的metadata・lock・依存版の照合には配布名を使い、
source archiveの実metadataと照合する。

各deploymentに`registry`と`min_cuda_version`を明示する。
`registry`は本人がRunPodへ登録したcredential ID、または公開image用のnull。
IDは空白を含まない空でない文字列とし、認証値は本人管理のRunPodへ登録する。
`min_cuda_version`はmajor.minor形式で、このimageでは13.0以上を指定する。
作成要求はIDをbodyの`registry`へ、CUDA下限を`gpu.minCudaVersion`へ渡す。
nullの場合はregistry項目を省略する。作成前のplan検査で不正値を拒否する。

両項目をdeployment_signatureへ含め、再開・高単価の採用根拠でも照合する。
未実行の私有planは両項目と修正後のlock・コード・環境参照を再生成し、
新しい試行として準備する。

Windows Docker Desktopで次の手順を使い、linux/amd64のimageを実buildする。

```sh
docker buildx build --platform linux/amd64 --load --progress plain -f ops/vlm-trial/Dockerfile -t colorstats-vlm-trial:local .
```

contextにはDockerfile・lock・src・project metadataだけを含める。
写真・モデル重み・秘密情報の混入を確認し、公式配布元の固定sourceと配布物SHAを照合する。
完成image IDとサイズを記録し、ネットワーク無効の検査container内で各Python環境の
`python -m pip check`、通常環境とSAM3環境のGPU不要範囲のimport、
ツール環境のuv起動を確認する。Python・コードパスはtrial_paths.jsonの定義を使う。
依存版とlock SHAを記録して構成参照へ結ぶ。
GHCRへのpush・可視性設定、Pod作成・実GPU試行はそれぞれの実行許可を得て行う。


FlashAttentionとSAM2の隔離buildにはtorchが必要なため、uv.tomlの
extra-build-dependenciesで通常環境と同じtorch 2.11.0を指定する。
Dockerfileは同じuv.tomlとhash付きbuild制約を使う。
BuildKitのcache mountで取得・build用cacheを保持し、完成imageへのsource cache混入を抑える。

今回のA40・L40S向けFlashAttentionはSM 8.0のcubinを生成する。
同じmajor revisionでminorが高いGPUへのcubin互換性を利用し、
MAX_JOBS=2・NVCC_THREADS=2で32GB程度のbuild環境の並列数を制限する。
実GPUでの動作・VRAM確認は合成smokeで行う。

[FlashAttentionの公式build手順](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/README.md)
[固定版のbuild設定](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/setup.py)
[NVIDIAのAmpere/Ada互換性](https://docs.nvidia.com/cuda/ada-compatibility-guide/index.html)


## 構成Dを省略する試行

実行planのconfigurationsとdeploymentsからDを共に除き、両集合を一致させる。
受領契約で認める集合・件数・匿名比較は[試行契約](vlm-trial.md#構成dを省略する試行)に従う。
起動順はA→B/C→Eとなり、Dを起動したりダミー結果を作ったりしない。

既存のplan SHA・model_settings_sha256には構成集合が含まれるため、集合を変えた
再開やsmoke記録の流用は拒否する。構成を変える場合は新規runと対応する記録を作る。
smoke・本試行・再試行の共通USD台帳は継続し、Dを省略しても過去runの支出は除外しない。
A/B/C/Eの共有枠は1.45/3.55/4.95/1.45 USD（計11.40 USD）で、
新規起動停止13 USD・全体上限15 USDと既存時間制限を変更しない。
