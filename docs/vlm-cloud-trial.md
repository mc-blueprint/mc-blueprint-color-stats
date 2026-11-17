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
環境SHAはdigest(versions)、重みSHAはdigest(files)、processor SHAはdigest(LIMITS)、
指示SHAはPROMPTのUTF-8 SHA、コードSHAはtrial_native.pyのbytesのSHA。
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
| A / B / C / D / Eの本体予約 | 1.05 / 2.80 / 4.20 / 1.05 / 1.95 USD |
| 同じ構成の再起動 | 旧資源の終了・請求確認後に最大1回、残USD・時間内 |
| 全体の設備障害 | 2回で新規処理停止 |
| 管理・回収監視失敗 | 2回で新規処理停止・終了へ |

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
