# CVAT ローカル環境

既存WSL2ディストリビューション `Ubuntu-24.04`（`H:\WSL\colorstats`）を使う。
Docker Engine・CVATソース・volume・検証用Python環境はすべてそのLinux filesystem内に置く。
Docker Desktopは使わない。既存ディストリビューションの再登録・VHDXの置換は行わない。

## Docker Engine

PowerShellから次で既存環境へ入る。以下の構築コマンドはrootで実行する。

```powershell
wsl -d Ubuntu-24.04 -u root
```

systemdは既存の `/etc/wsl.conf` で有効。Dockerは[公式apt手順](https://docs.docker.com/engine/install/ubuntu/)を使用する。
既存の競合パッケージがある場合は、公式手順に従って影響を確認してから対応する。
WSLは使用中のセッションがなくなると停止するため、CVATを利用する間はこのWSL端末を開いておく。
API検証もDBの起動からテスト終了まで同じWSLプロセス内で実行する。
今回の環境では非表示の `wsl.exe ... --exec /usr/bin/sleep infinity` で稼働を維持している。
そのWindows PIDは担当worktreeの `data/issue41/wsl-keepalive.pid` に保存した。
終了時はCVATをstopした後、このPIDが該当wsl.exeであることを確認してから停止する。

```sh
apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
/usr/bin/docker info --format '{{.DockerRootDir}}'
```

確認値は `/var/lib/docker`。Docker 29のcontainerdイメージ保存先 `/var/lib/containerd` も同じWSL内にある。
WindowsのC:などへデータを移さない。

## CVAT起動・停止

[公式Compose構成](https://docs.cvat.ai/docs/administration/community/basics/installation/)を使い、自作の構成や依存追加を避ける。
確認済み版は `v2.81.0`（commit `fcd72d43ad5f791974d6d1e57ee9d0d9886a2a51`）。
新規構築時だけcloneし、既存 `/opt/cvat` を上書きしない。

```sh
cd /opt
git clone --depth 1 --branch v2.81.0 https://github.com/cvat-ai/cvat.git cvat
cd /opt/cvat
export CVAT_VERSION=v2.81.0
export COMPOSE_FILE=/opt/cvat/docker-compose.yml:/mnt/h/MCBlueprintColorStats/worktrees/issue-41/mc-blueprint-color-stats/ops/cvat/docker-compose.override.yml
docker compose config
docker compose up -d
docker compose ps
curl --fail http://localhost:8080/api/server/about
curl --fail -o /dev/null -w '%{http_code}\n' http://localhost:8080/
```

初回はmigration完了までAPIが応答しないことがある。`docker logs --tail 30 cvat_server` で確認し、完了後にcurlを再実行する。
再起動直後はAPIが200でも認可ポリシーが準備中の場合がある。書込み前に次も成功することを確認する。

```sh
docker exec cvat_server python3 -c "import urllib.request; urllib.request.urlopen('http://cvat_opa:8181/health?bundles', timeout=5)"
```

overrideの `ports: !override` で公式の8080・8090待受を置換する（Compose 2.24.4以降が必要）。
公開ポートが `127.0.0.1:8080` だけであることを確認する。公式定義へportを追加するだけでは全インターフェース待受が残る。

以降も同じ `CVAT_VERSION` と `COMPOSE_FILE` を設定して操作する。
停止は `docker compose stop`、再開は `docker compose up -d`。volumeを削除する `down -v` は使わない。
更新時は公式手順を確認し、DB・volumeをバックアップしてから行う。

## 処理環境と認証

Python 3.12の既存環境 `/opt/colorstats/venvs/issue41` を使う。Windowsの `.venv` は共有しない。

```sh
cd /mnt/h/MCBlueprintColorStats/worktrees/issue-41/mc-blueprint-color-stats
export PATH=/opt/colorstats/venvs/issue41/bin:$PATH
export UV_PROJECT_ENVIRONMENT=/opt/colorstats/venvs/issue41
export UV_CACHE_DIR=/opt/colorstats/venvs/issue41/uv-cache
export TMPDIR=/opt/colorstats/venvs/issue41
uv sync --locked
```

ローカル管理者の認証値はWSL内 `/opt/colorstats/issue41/cvat-admin.json`（0600）に保存済み。
会話・Git・ログ・コマンド引数へ転記しない。ブラウザでのログインにはローカル管理者が安全な方法で入力する。
検証スクリプトはファイルをプロセス内で読み、認証値を出力しない。
今回確認したのはAPIによる操作であり、Windowsブラウザでのログイン・実画面編集はユーザー作業として残る。

## 100枚の準備（担当者）

以下はまだ未実施。最初に候補画像と#40の成功segment出力を揃える。
正解候補は建築70枚・地形30枚、同一作者は全体で最大5枚とする。
同一建築の複数画像は建物名・Commonsカテゴリなどの根拠を併記し、#46で照合できるようにする。
taxonomyの41ラベル（部位30・地形11）を使い、親分類名をラベルにしない。

候補CSVの必須列と例:

```csv
asset_id,author,stratum,filename,sha256,segment_xml,original_width,original_height,building_id,building_evidence
<DBのUUID>,<作者>,building,<一意な縮小画像名>.png,<原画像のSHA256>,<segment.xmlのパス>,<原画像幅>,<原画像高さ>,<同一建築の識別子>,<建物名や出典URL>
```

`stratum` はこの作業では `building` / `terrain` とし、建築は建物の根拠を必須にする。
地形はbuilding_id・building_evidenceを空欄にできる。必要なら選定理由へ構図や地域も補記する。
SHAはCVATに渡す縮小画像のSHAではなく、DBのassetに対応する原画像のSHA。
`segment_xml` はmanifestのある場所からの相対パスまたはWSLの絶対パス。
寸法はDBのassetから転記する。XMLの寸法は#40の入力である縮小画像の寸法を使う。
CVATには#40が実際に推論した縮小画像を渡し、filenameに合わせて複製・改名する。
crop・回転した画像にはこの幅高さ比の変換を使えない。対応を確認してから候補にする。
画像、XML、JSON、manifestはH:の担当データ領域またはH:上のWSLに保存する。

作者上限を全体で5枚以内にするため、建築候補では3枚、地形候補では2枚まで選ぶ。
この配分で件数を満たせない場合は候補を増やすか、担当者が全体上限を確認して配分を調整する。

```sh
work=/opt/colorstats/issue41/gold100
mkdir -p "$work"
python -m colorstats.cvat labels --taxonomy taxonomy --output "$work/labels.json"
python -m colorstats.cvat select --input "$work/building-candidates.csv" --output "$work/building.csv" --count 70 --seed issue-41-building --author-limit 3
python -m colorstats.cvat select --input "$work/terrain-candidates.csv" --output "$work/terrain.csv" --count 30 --seed issue-41-terrain --author-limit 2
```

次でmanifestを結合して件数・作者・同一建築の根拠を点検する。選定コマンドは追加列、seed、選定理由を保持する。
候補CSVは同じ列順にし、segment_xmlを絶対パスにするか、結合後も参照できる場所に置く。

```sh
python - <<'PY'
import csv
from collections import Counter
from pathlib import Path
work = Path('/opt/colorstats/issue41/gold100')
rows = []
for name in ('building.csv', 'terrain.csv'):
    with (work / name).open(newline='', encoding='utf-8') as file:
        rows.extend(csv.DictReader(file))
assert Counter(row['stratum'] for row in rows) == {'building': 70, 'terrain': 30}
assert len({row['asset_id'] for row in rows}) == len({row['filename'] for row in rows}) == 100
assert max(Counter(row['author'] for row in rows).values()) <= 5
assert all(row['building_id'] and row['building_evidence'] for row in rows if row['stratum'] == 'building')
with (work / 'selection.csv').open('w', newline='', encoding='utf-8') as file:
    writer = csv.DictWriter(file, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
PY
python -m colorstats.cvat prepare-draft --manifest "$work/selection.csv" --output "$work/draft.xml"
```

`draft.xml` は#40のRLEマスクを変えずに結合したCVAT 1.1 XML。
併せて生成する `draft.json` は `label_source=model` として元RLE、ラベル、面積比、
画像対応、縮小・原画像寸法、入力XMLと下書きXMLのSHAを保持する。両方を修正前の状態で保全する。
既存出力は上書きしない。再選定時は新しい作業ディレクトリを使う。
元の#40のrun・PNG・XML・model領域は保持し、人手登録では変更しない。

## CVATへの登録（担当者）

1. `http://localhost:8080` で新しいProjectを作成する。ラベルのRaw定義へ `labels.json` の `labels` 配列を設定する。
   41ラベルと各ラベルのtext属性 `draft_id` があることを確認する。形状typeは `any`（maskとpolygonの両方）とする。
2. 同Projectに100枚の縮小画像を含むTaskを作成する。画像名はmanifestのfilenameに一致させる。
   Advanced configurationのSegment sizeを10枚にすると、Jobごとに修正・保存・進捗を管理できる。
3. Taskの **Upload annotations** から **CVAT 1.1** を選び、`draft.xml` を取り込む。
   画像自体のUploadと注釈Uploadを混同しない。成功後、画像数100と地形を含むラベルを確認する。
4. 編集前のTaskも **CVAT for images 1.1** でexportして保全する。
   CVAT v2.81.0ではXMLに `source=auto` を指定してもimport後のsourceは `file` になる。
   model由来の判定と差分の正本はCVATのsourceでなく `draft.json` と `draft_id` を使う。

## 修正・承認（ユーザー、100枚）

実画面の修正はユーザーが行う。今回AIがAPIで編集した検証Taskは正解100枚に数えない。
一括の [Shapes converter](https://docs.cvat.ai/docs/annotation/manual-annotation/utilities/shapes-converter/)
はCommunity版の対象外なので、この構成で利用できる前提にしない。

1. Project → Task → Jobを開き、画像と下書きマスクを確認する。
   Objects欄で対象マスクのラベルと `draft_id`（例 `0:0`）を控える。
2. 左のpolygon描画を選択し、対象部位の輪郭に沿って頂点を置き、描画を終了する。
   マスクをガイドとして使い、見えている部位の境界を修正する。必要に応じて頂点を移動・追加・削除する。
3. 作成したpolygonに正しい部位・地形ラベルを設定し、Attributes欄の `draft_id` に対応するIDを入れる。
   ラベルを変更すると属性が初期化される場合があるので、ラベル変更後にIDを確認する。
   新しく追加した部位はIDを空欄にする。元マスクが誤検出なら削除だけ行う。
4. 元のマスクを削除する。対応するIDは残したpolygonで一度だけ使う。
   1マスクを複数polygonに分割するときは代表の1つだけに元IDを付け、残りは空欄にする。
   複数マスクを統合するときも代表のIDだけを保持する。差分は他を追加・削除として記録する。
5. 穴や離れた領域は、穴を塗りつぶさない複数の単純polygonとして描き分ける。
   辺の自己交差や非隣接辺の接触・重なりは取込みエラーになる。CVATで頂点を修正して再exportする。
   全領域のラベル・頂点を確認し、mask・boxなどpolygon以外を残さない。不要な下書きは全て削除する。
6. **Save** して次の画像へ進む。10枚ごとに保存を確認し、別の進捗表へ確認日・承認者・画像名を記録する。
   無注釈が正しい画像も「領域なし」と承認した根拠を残す。
7. 全100枚について見落とし・重複・誤ラベル・同一建築の根拠を確認し、Jobを完了状態にする。
   最後に担当者へ「全100枚の修正・承認済み」と伝える。

所要時間は未計測。目安は1枚10〜25分で約17〜42時間、選定・最終照合を含め約20〜50時間。
まず5枚を修正して実測し、残りの見積りを更新する。形状の複雑さや下書きの誤検出数で大きく変わる。

## 修正後のexport・DB取込み（担当者）

承認後、Taskの **Export task dataset** から **CVAT for images 1.1** を選び、画像を含めてZIPを取得する。
元のmanifest・draft.jsonと同じ100枚のTask全体をexportする。選別した一部だけのexportは拒否される。
API実往復は成功済みだが、ブラウザでの操作・ユーザーによる承認はまだ未実施。

```sh
# DATABASE_URLは許可された専用DBに設定する。本番DB・パイロットDBは今回の対象外。
python -m colorstats.cvat import-cvat --export /opt/colorstats/issue41/gold100/edited.zip --manifest /opt/colorstats/issue41/gold100/selection.csv --draft /opt/colorstats/issue41/gold100/draft.json --mask-dir /opt/colorstats/issue41/gold100/human
```

入力は画像を含むZIPだけとし、XML・ZIP内images・manifest・下書きの画像集合、asset UUIDと原画像SHA、
縮小画像寸法、原画像寸法とDB、taxonomyの41ラベルを照合する。
ZIP画像のバイト列を原画像SHAとは比較しない（縮小・CVAT再圧縮で異なるため）。
CVATへ渡す画像を取り違えないよう、担当者が画像・XML・manifestの対応を準備時に照合する。
`draft_id` の不明・重複は拒否する。空欄は新規領域として扱う。

原画像座標は左上原点で `x原=x注釈×原幅/注釈幅`、`y原=y注釈×原高さ/注釈高さ`。
humanの `bbox`・polygon JSONは原画像座標、`area_ratio` はpolygonの幾何面積÷原画像面積。
`polygon-pixels-v1` JSONを `<asset UUID>/<region UUID>.json` に保存し、mask_pathはrunの `output_paths.masks` からの相対パスとする。
成功runをライセンス区分ごとに作り、既存regionを上書きしない。DB列・migrationの追加はない。
同じZIPの再登録はSHAで拒否する。SHAごとのトランザクション単位advisory lockで並行取込みも排他する。
DB接続はPostgreSQLのREAD COMMITTEDを使用する。失敗時はこの操作で作ったJSONとDB変更を戻す。

`output_paths.draft` に比較用下書きJSONのコピー、`parameters.draft_sha256` にその入力SHA、
`parameters.annotation_diff` に画像別・ID別の比較結果を保存する。
各行に追加・削除・対応あり、修正前後のラベル、ラベル変更の有無、面積比、
面積比の符号付き差と原画像換算の画素面積差を記録する。削除はafter=0、追加はbefore=0。
beforeはRLEの実画素数、afterはpolygonの幾何面積なので、描画形式の差も面積差に含まれる。
同面積の移動や輪郭の変更量・IoUを表す値ではない。下書きRLEと修正後polygonの両形状も保持する。
分割・統合は上記のID運用で対応し、1対多の自動対応付けはしない。

取込み後に担当者がmanifestの100 asset、各画像の承認領域数、human領域数と差分件数を照合する。
run数やregion総数だけで100枚完了とは判断しない。差分の空画像・追加削除も確認する。
本番への登録を進める場合は別途そのDB操作の許可が必要。

## 検証と残作業（2026-11-02）

- 反証対応後は全pytest 353件成功、DBテストのskipは0件。既存GPUテストのみ1件skip。
  自己交差・非隣接辺の接触や重なりの拒否、凹形状などの受入れ、同一ZIPの並行取込みを追加検証。
  ruff、sdist/wheelビルド、Windows側のgit diff --checkも成功。新規依存・migrationの追加はない。
- origin/develop `7a0f1c8` を担当ブランチへfast-forward統合。
- ローカルCVAT v2.81.0、Docker Engine 29.9.2 / Compose 5.6.1。公開はlocalhost:8080のみ。
- ubuntu-2 `/mnt/data/work/issue-40/review-gpu-run/test_gpu_worker0` から、画像・実RLE XML・計測JSONを読み取りコピー。
  自作CC0画像512×384の6モデル領域をProject 5・Task 5へ取込み、APIで6polygonへ修正相当編集。
  先頭のラベルをdoor→ground_grassへ変更してexportし、専用PostgreSQL 16の `issue41_segment_roundtrip_3` にhuman 6領域を登録。
  頂点・bbox・面積、元RLEの全6面積比、下書き保持と差分を照合。先頭の原画像換算面積差は約362画素。
  この画像では縮小前後が同寸法。幅2倍・高さ3倍の変換は単体・一時DB回帰テストで検証する。
- 検証データはH:の担当worktree `data/issue41/segment40` とWSL `/opt/colorstats/issue41/segment40/run3` に保全。
  誤検出を残すAPI編集なので正解セットには使わない。画面上のユーザー編集は実施していない。
- 編集前のTask 4も保持し、元の全6件のRLE配列・境界・draft_idがCVAT取込み後も完全一致することを確認した。
- 最終のruff成功、全pytest 345件成功。DBテストのskipは0件。
  公式重み・CUDA指定が必要な既存GPUテストだけ1件skip（今回GPU推論は再実行していない）。
  幅2倍・高さ3倍への変換、差分、下書きID重複、不正RLE、再登録拒否と失敗時の巻戻しを検証。
  sdist/wheelビルド成功。Matplotlib未導入による既存の任意機能警告が1件ある。
- テストDB用コンテナは外部ネットワーク・公開ポートのない `issue41_test_postgres`（PostgreSQL 16）。
  socketは `/opt/colorstats/issue41-postgres`。全pytestにはスキーマ検証のため毎回空の専用DBを用意する。
  既存のDB・volumeを削除して空にしない。
  検証後はこのコンテナを停止し、DBとvolumeを保持する。CVATは稼働を維持する。

Issue #41は未完了。実100枚（建築70・地形30）の選定・同一建築の根拠付け、
ユーザーの修正・承認、100枚の差分とhuman登録・件数照合が残る。PRは `Refs #41` とする。
