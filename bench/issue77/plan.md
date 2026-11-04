# Issue #77 追加収集測定計画（第1段階で固定）

基準は #74 の `2ea1ea59008664b3ecf8906bb0b14f3963791539`。
第1段階ではHTTP fixtureと隔離PostgreSQL 16だけを使用する。
本番測定は #66 完了後の第2段階とし、本計画の作成を実行許可へ読み替えない。

## 固定条件

- 設定は `bench/issue77/targets.yaml`。測定IDは `issue77-v1`、seedは77。
- 全12層、taxonomy 0.1.0、既存画像を含む全体10,000枚の枠を維持する。
- japanese-castle・gothic-temple・forest-autumn-day・modern-house・medieval-house・
  japanese-temple・islamic-temple・chinese-houseは各835枚、残る4地形層は各830枚。
  各層100 subject、source_share=.8、author_share=.05、region_share=.4、
  subject_share=.003、subject_images=3を維持する。層は検索意図であって真の分類ではない。
- 各層で再試行込みAPI要求20回、全HTTP要求40回。両providerの合計であり、
  Commonsのメタデータ・カテゴリ継続もAPI枠を消費する。失敗した要求の枠は返却しない。
  内訳はCommonsがAPI14回／HTTP22回、OpenverseがAPI6回／HTTP18回に固定する。
  リダイレクトの各追従要求も枠を消費し、待機と宣言済みUser-Agentを適用する。
  余った供給元枠を他方へ転用しない。Commons先行でもOpenverseのAPI枠は残る。
  層・集中枠の満了で通信できなかった供給元は未測定とし、歩留まり0とは扱わない。
- Commonsの多言語検索と `incategory:"Himeji Castle"` によるカテゴリ内候補検索、
  Openverse補助検索。カテゴリ内候補も既存Search APIを使い、categorymembers全件列挙はしない。
  新規アダプター・依存を追加せず、既存の継続位置とページ上限を再利用するための選択である。
- 各言語は既存検索語からseedで選択。各言語先頭ページのみを初期投入し、
  成功runのnext_offsetを順に再計画する。最大3ページ、max_offset=500、1ページ10候補。
- source_policyと宣言済みUser-Agent・待機・負荷制限・元画像の作者完全照合を維持する。
  Openverseのby/by-saは、元画像で照合した選択値・版から測定時にcc-by-版／cc-by-sa-版へ
  正規化して既存D15ゲートへ渡す。保存値・source_policyは変更せず、SA等の除外は維持する。

## 開始条件と停止条件

開始直前にREAD ONLY取引でpending/running collectのbias設定と未完了測定runを確認する。
残存する別設定や未完了runがあれば削除せず停止し、担当メインへ判断を返す。
#66の完了・旧収集ワーカー停止・保存領域の利用可能性を確認する。
測定中は専用collectワーカー1個だけを使用し、他のcollectと並行させない。

層の画像／subject枠、全体予算、provider集中枠の満了は検索前に止める。
作者／地域／subject集中枠は候補の予約時に止める。URL再発見は原本取得前に除外する。
API／HTTP枠はDBで直列予約し、枠超過時は通信せずstop_reasonを残す。
原本取得途中の正常な枠停止では取得成功分を確定する。通常の失敗時は従来どおり清掃する。
失敗・枠停止でも検索条件、受信済みapi_next_offset、候補と除外URL・理由を試行runへ残す。
検索終端・3ページ・offset上限でも継続しない。timeoutは既存キューの最大3試行に従う。
全ジョブが終端になったらワーカーを停止する。障害・空き容量不足でも上限を増やさない。

## 時間・byteの事前見込み

通信は最大480回、うちAPIは最大240回。正常時は概ね10〜60分を予想するが、
全通信が60秒待機となる場合は約8時間＋既存の待機／バックオフ／DB時間。
これは強制wall-time上限ではない。カテゴリ継続・429も同じ通信枠を消費する。
既存Commons集中枠の多くは満了済みなので、追加取得0枚も結果として受け入れる。
rawは既存M2の約6MB/取得の参考係数で0〜300MB程度を想定する。
極端に全480要求を取得と仮定した感度値は約2.88GBであり、ファイルサイズの保証上限ではない。
body byte、取得成功byte、保存新規SHA数を別々に記録し、DB/WALやwire byteへ読み替えない。

## 第2段階の実行手順

以下は準備済みコードを ubuntu-1 の `/opt/colorstats` に配置した後のコマンド例。
rawはconfigs/storage.yamlでubuntu-1だけに割り当てられているため、手動collectも同ホストで行う。
停止済みpilotサービスは再開しない。
接続情報は既存の環境注入を使い表示しない。保存設定は既存のものをそのまま指定する。
code-versionは公開担当が作成した本実装のcommitを指定する。初期・継続計画を同じ設定で行う。

```sh
cd /opt/colorstats
python -m colorstats.collect.bias_cli --targets bench/issue77/targets.yaml plan --storage configs/storage.yaml --host ubuntu-1 --code-version <実装commit> --seed 77
python -m colorstats.queue --handler collect=colorstats.collect.bias --stop-file /opt/colorstats/data/issue77.stop --storage-path collect=/srv/colorstats/raw-orico --storage-path collect=/srv/colorstats/raw-suneast --once
python -m colorstats.collect.bias_cli --targets bench/issue77/targets.yaml plan --storage configs/storage.yaml --host ubuntu-1 --code-version <実装commit> --seed 77
python -m colorstats.collect.bias_cli --targets bench/issue77/targets.yaml report --measurement-id issue77-v1 --output /opt/colorstats/data/issue77-yield.json
```

`--once` は1ジョブだけ実行する。返されたjob_idsの終端と台帳を確認し、上記workerと継続計画を
順に繰り返す。job_idsには既存成功ジョブも含むため、配列の非空だけを継続条件にしない。
API上限到達後のジョブは通信せず終了する。継続先がなく全対象が終端なら終了する。
本段階ではprep/subject推定を追加実行しない。第2段階で#72の根拠付き同定後に同じreportを
再生成し、確定subject異なり数・測定前からの新規subject数を確認する。

## 検証と解釈

要求は実送信前の予約回数、応答はHTTPヘッダーを受けた回数（429/503も含む）、timeoutは
クライアントのTimeoutError（URLErrorの原因も含む）。HTTP要求とAPI要求を混同しない。
candidateはアダプターが返せる形へ変換した候補数。途中失敗までの候補も台帳に残る。
verifiedはCommonsの帰属情報充足、Openverseは元画像の作者・ライセンス完全照合であり、
両providerの照合強度が同一とは解釈しない。search_responsesは候補一覧処理が完了したページ数。
取得成功数には、後続失敗でDB登録されなかった取得も含める。
適格新規SHAは完了取引時に既存全Assetと同バッチのSHAを除き、#74の権利ゲートを通った数。
解析可能性・品質・統計採用の保証ではない。既存SHAの新しい権利経路は新規SHAへ算入しない。
失敗／未完了試行も通信の分母へ含める。確定subjectは#72のconfirmed根拠を必要とする。
検索意図とタイトル一意一致だけの既存収集関連付けは確定subject数へ昇格しない。

## 1万行枠と適格SHAの段階目標・外挿

本計画の10,000は既存Asset込みの行数上限であり、適格・重複除外後1万枚の到達枠ではない。
開始時の行数をN0、#74で確認した適格SHA数をE0とすると、本測定後の楽観上限も
E0 + max(0, 10,000 - N0)枚である。設計時のN0=7,607、E0の上限1,620が同じなら、
追加行は最大2,393、適格SHAの合計も最大4,013で、適格1万枚へ届かない。
第2段階は実際の開始snapshotのN0/E0を報告し、この設計時の値を現在値へ流用しない。

層・供給元ごとにΔE=適格新規SHA、A=API要求（timeout・リダイレクト・再試行込み）、
R=新規登録行、B=取得byte、t=経過時間として、r=ΔE/A、q=ΔE/Rを測る。
参考外挿は目標Tに対して、残りG=max(0,T-E0)、必要API≈ceil(G/r)、
必要追加行≈ceil(G/q)、raw byte≈G×B/ΔE、時間≈G×t/ΔEで示す。
分母0や未測定の層・供給元では算出せず、0%や到達不能と断定しない。
層別値を混ぜる場合は予定配分も示す。別設定・検索深度でも歩留まりが一定と仮定した
感度試算に限定し、集中上限・候補の枯渇・subject支持・解析品質を満たす到達保証にしない。
1万→3万→10万SHAの実収集には、新しい行予算・供給元構成・容量を別計画で確定する必要がある。

## 第2段階の実行記録への参照

本番測定は2026-11-05 JSTに本書の枠・seed・source_policyを維持して実行した。
実行コードはdevelop a6c1bffをmergeした5c6c626を基準とする。配置は
`/opt/colorstats/work/issue77-20261105/code`、既存Pythonと`ops/deploy/launch.py`を使用した。
`bench/issue77/production.py`は収集前のREAD ONLY確認を行い、既存Queueのjob_ids制限で
この測定だけを1ワーカーで実行した。pilotサービスは再開していない。
結果と残る制約は `stage2-results.md`、設定・コードhashと保全先は `stage2-artifacts.json`。
`issue77-v1`は使用済みIDとして保持し、同じ測定を新規実行するために既存runを削除しない。
