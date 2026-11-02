# MCBlueprint配色統計 設計書

作成日：2026-11-01  
状態：**設計確定（初版）**。  
前提資料：[引継ぎ資料](handoff-2026-11-01.md)、[ストレージ調査結果](storage-audit-2026-11-01.md)（11/1最終更新）。要件は両資料に従い、本書では再掲しない。

## 1. 位置付けと責務分担

| リポジトリ | 役割 | 公開 |
|---|---|---|
| `rs0325/MCBlueprint` | AIエージェント向けの配布ツールキット（Blueprint JSON → `.schem`）。MIT、Python 3.11以上 | 公開・GitHubで無料配布 |
| `rs0325/mc-blueprint-color-stats`（本リポジトリ） | 画像・資料の収集、解析、統計、**配色パックの生成** | private |

- 本リポジトリは配布物を直接持たない。成果は**配色パック**（バージョン付きJSON、§7）として出力し、MCBlueprintへ同梱する。
- 生成時の配色選択（パック参照→役割ごとのPalette生成）は**MCBlueprint側に実装**する。MCBlueprintの利用者は本リポジトリなしで動作でき、LLMを呼ばない。MCBlueprint側の変更は同リポジトリのIssueとして別途起票する（M4）。
- 配色パックの役割名はMCBlueprintのPalette役割（壁・柱・床・屋根・妻壁・土台。`designs/*.md`、`mcblueprint design`の出力）と対応させる（§6.2）。
- 本リポジトリではMCBlueprintをライブラリとして参照し、Palette検証・プレビュー生成に再利用する（ブロックID検証や`colors.json`を再実装しない）。

## 2. 要件・アーキテクチャ整合性レビュー

| # | 論点 | 判断 |
|---|---|---|
| R1 | ホスト対応 | 2026-11-01の読み取り確認で確定（§3）。ubuntu-0は別用途PC、ubuntu-1＝i5-8400、ubuntu-2＝i7-8700K。**ubuntu-1/2はGPUを認識しているがNVIDIAドライバー未導入**のため、M0で導入する |
| R2 | ジョブキューの置き場所 | Windowsは停止し得るため、キューとメタデータDBはUbuntu側に置く。SQLiteはLAN越しの複数ライターに不向きなので不採用。**PostgreSQLをubuntu-2のNVMeに置く** |
| R3 | 両1TB SSD | SUNEAST／ORICOは監視付きの暫定候補なので、**再取得可能な原本キャッシュ専用**とし、DB・正解データ・集計結果は置かない |
| R4 | Windowsの使用範囲 | **H:のみ**使用（空き769GB）。WSL2のディストリビューション、集計用Parquet、CVAT、パックのビルドをH:に置く。C・F・Gは使わない |
| R5 | 処理順序 | 分類体系とスキーマを先に確定し、収集は1,000枚MVPに限定。大量取得は品質・権利ゲートとベンチマーク後 |
| R6 | ライセンス | MCBlueprintはMITで無料公開されるため、同梱パックは**商用利用も許すライセンスと両立する入力だけ**から作る（§8） |
| R7 | 統計の単位 | 画像単位ではなく`subject`（同一建築・場所・作品）単位で重み付けする。収集時に撮影地点・タイトル・作者・作品ページを必ず保存 |
| R8 | ブロック色 | MCBlueprintの`colors.json`はプレビュー用のキーワード単位の代表色で粒度が足りない。本リポジトリで、ユーザーが所有するバニラjarから面ごとのOKLab分位点をローカル抽出し、テクスチャ画像は保存・配布しない |

## 3. 実機構成（2026-11-01 読み取り確認）

| ホスト | CPU | RAM | GPU（ドライバー） | OS | 保存（空き） |
|---|---|---:|---|---|---|
| Windows（メイン） | Ryzen 7 5700X | 64GB | RTX 4070 SUPER（導入済み） | Windows 11 | **H: NVMe 769GB（使用）** |
| ubuntu-0（別用途） | 8スレッド | 31GiB | ドライバー不通・使用しない | Ubuntu 24.04.4 | OS CT500MX500 410GB、HDD：WD 750GB（ext4）、ST3500 500GB×2（NTFS） |
| ubuntu-1（収集） | i5-8400 | 15GiB | RTX 4060（未導入） | Ubuntu 24.04.5 | OS CSSD 200GB、ORICO 1TB（ext4・未マウント）、SUNEAST 1TB（NTFS・未マウント）、TOSHIBA 240GB（NTFS・未マウント） |
| ubuntu-2（GPU推論） | i7-8700K | 31GiB | RTX 4070（未導入） | Ubuntu 24.04.5 | OS 980Plus 210GB、NVMe `/mnt/data` 891GB |

全UbuntuでPython 3.12.3、Docker未導入。

## 4. システム構成

```
            ┌──────────── ubuntu-1（収集） ─────────────────────┐
 Web/API ─▶ │ collector ─▶ blob store（ORICO+SUNEAST, 原本キャッシュ）│
            │ cpu-worker（重複・品質・色抽出）、RTX4060 軽量推論     │
            └──────────────▲───────────────────────┬──────────────┘
                           │ ジョブ取得/結果登録   │ 画像バッチ取得(HTTP)
            ┌──────────────┴─────────┐ ┌──────────▼──────────────┐
            │ ubuntu-2                │ │ Windows H:（WSL2）       │
            │ PostgreSQL・モデル重み  │ │ gpu-worker（任意参加）   │
            │ gpu-worker 分割・陰影   │ │ 集計(DuckDB)・CVAT       │
            └──────────┬──────────────┘ │ 配色パックのビルド       │
                       │                └──────────┬──────────────┘
                       ▼ 日次バックアップ          ▼
            ubuntu-0 HDD（DB・正解・集計）   配色パック → MCBlueprint
```

### 4.1 保存先の割当て

| 論理名 | 実体 | 内容 | 失った場合 |
|---|---|---|---|
| `db` | ubuntu-2 `/mnt/data/postgres` | メタデータ・ジョブ・小さい解析値 | バックアップから復元 |
| `models` | ubuntu-2 `/mnt/data/models`（各GPUノードへ複製） | モデル重み | 再取得 |
| `raw` | ubuntu-1 ORICO・SUNEAST（ext4） | 原本画像（SHA-256で内容アドレス） | URLから再取得。消失ソースは欠損として記録 |
| `derived` | ubuntu-2 `/mnt/data/derived` | マスク・縮小画像・特徴量・Parquet | 再計算 |
| `work` | Windows H: | 集計用Parquetの複製、CVAT、パックのビルド | `derived`から再生成 |
| `backup` | ubuntu-0 HDD | DBダンプ、正解データ、分類体系、集計結果、パック | — |

- `raw`の論理パスは`raw/<sha256[0:2]>/<sha256>.<ext>`。ORICO／SUNEASTへの振り分けは設定で行い、媒体の交換・追加時に設定だけ変える。
- 正解データ（CVAT）と評価セットの原本は再取得できない可能性があるため、`backup`にも置く。
- M1パイロットはubuntu-1からrawを読み、ubuntu-2のderivedをNFS共有している暫定配置。
  M2で複数GPUノードの入出力を測定し、derivedのNFS共有の継続とrawの共有・複製方式を決める。
  再取得・再計算と障害時の制御は[配備手順](../ops/deploy/README.md)に従う。

### 4.2 バックアップ

- ubuntu-0のHDD3台を使う。WD 750GBを主バックアップ、ST3500 500GB×2を世代バックアップとし、**同じデータを2台以上のHDDに置く**（500GB×2は高温・長時間稼働のため単独では信頼しない）。
- 日次：`pg_dump`（カスタム形式）、正解データ、集計結果をrsyncで転送し、7日分＋週次4世代を保持。
- 月次で別ホストへの復元試験を行い、結果を記録する。
- HDDのSMART温度・代替セクタを監視し、閾値超過で書込みを止めて通知する。バックアップは監視状態・異常記録により転送先を除外し、健全な媒体が2台未満ならserviceの失敗状態とjournalに残す（外部通知は未実装）。
- 温度は60°C以上で転送・保持を停止し、55°C未満で自動復帰する。過去の温度超過・温度属性だけのしきい値履歴は恒久除外しない。CRC・代替セクタ・保留セクタの増分、I/Oエラー、SMART健康異常は履歴を残し、手動解除まで除外する。
- ST3500×2は2026-11-01にユーザーが既存データの消去を承認し、Issue #23でserial照合後にext4化した。UUIDと保存先は `configs/storage.yaml` を正本とする。

### 4.3 ストレージ監視と停止条件

- 各ホストで5分ごとにSMART（CRC・代替セクタ・温度）とkernelログ（BadCRC・EIO・reset）の増分を記録する。
- `raw`の媒体で異常の増分を検知したら、その媒体を`readonly`にして書込みジョブを止め、処理中のジョブはキューへ戻す。復帰は手動。
- 起動時に媒体をシリアル番号で照合し、`/dev`名に依存しない（マウントはUUID指定）。

## 5. ジョブキュー設計

### 5.1 採用方針

- PostgreSQL 16をubuntu-2に置き、ジョブは**`FOR UPDATE SKIP LOCKED`＋リース期限**で取得する。
- Procrastinateの適合性はIssue #6で確認済み。旧試行による結果更新を防ぐ所有権境界に別のjob行が必要になるため、既存SQLAlchemyとPostgreSQLによる単一の`job`テーブルを採用した（[調査と選定](queue.md)）。Ray Dataは、実測でスループットが足りないと判明した場合だけ検討する。

### 5.2 キュー

| queue | 単位 | 実行ノード | 出力 |
|---|---|---|---|
| `collect` | 検索クエリ／ソースページ1件 | ubuntu-1 | `source`, `asset`, `raw` |
| `prep` | 1 asset／job（実装済み） | ubuntu-1 CPU | SHA-256、pHash、品質指標、縮小画像 |
| `segment` | M2で決定（当初目標16件バッチ） | GPU（12GB優先） | `region`、マスク |
| `shade` | M2で決定（当初目標16件バッチ） | GPU | 陰影推定、補正の信頼度 |
| `color` | 1 asset／job（実装済み） | CPU | `color_observation`, `relation` |
| `review` | 低信頼度サンプル | 人手（CVAT）／VLM（任意・明示時のみ） | ラベル修正、教師データ |
| `aggregate` | 統計バージョン1件 | Windows | `rule_stat` |

現行ワーカーは1スロットで、jobごとに計算用プロセスをspawnする。
prep/colorの64件バッチは投入目標であり、M2で速度・メモリとモデル常駐方式を実測して採否を決める。

### 5.3 冪等性と障害時の挙動

- ジョブキーは`(stage, asset_id, stage_config_hash)`。同じキーの結果があればスキップする。
- 出力は一時パスに書き、取引外で試行・公開ごとに固有の不変パスへrenameする。
  採用するファイル参照・結果・成功を所有権付きDB取引で確定する（[詳細](queue.md)）。
- リース期限（既定10分）切れで`pending`へ戻す。3回失敗したら`failed`にして理由を保存する。
- 保存先異常中は対象stageの取得を止め、処理中の試行は回数を消費せず保留する（Issue #30）。
- Windowsワーカーは停止フラグで即時停止でき、残りのジョブは他ノードが引き継ぐ。

## 6. データスキーマと分類体系

### 6.1 エンティティ

引継ぎ資料§6のエンティティを採用し、次を追加・明確化する。

| エンティティ | 追加・変更 |
|---|---|
| `subject` | 同一建築・場所・作品の集約単位。統計の重みの基準。`asset.subject_id`は不確実ならNULLとし、候補を別表に持つ |
| `asset` | `domain`（`mc_vanilla`／`mc_modded_or_shader`／`mc_unknown`／`real_building`／`real_terrain`／`text`）、`license_class`（§8） |
| `region` | 部位ラベル、`instance_id`、マスク参照、bbox、正規化高さ（0=接地、1=頂部）、面方向の推定、`label_source`（model／human／vlm／schematic） |
| `color_observation` | `observed_oklab`（主色・分位点）、`material_oklab`（推定、NULL可）、`material_confidence`、面積比 |
| `relation` | `(region_a, region_b, type)`、ΔL・ΔC・Δh（OKLCh）、ΔE_ok、面積比 |
| `processing_run` | モデル名、重みハッシュ、`license_class`、設定ハッシュ、ノード、日時 |
| `block_color` | Minecraft版、ブロックID、面（top／side／bottom）、OKLab分位点、材質タグ |

色空間は**OKLab／OKLChに統一**する（統計キー・ブロック照合とも）。CIELABは比較評価にだけ使う。

### 6.2 部位ラベル（建築）

2階層。統計は第2階層を基本とし、データが不足するときは第1階層へ平滑化する。右端はMCBlueprintのPalette役割との対応。

| 第1階層 | 第2階層 | MCBlueprintの役割 |
|---|---|---|
| `foundation` | `plinth`, `stairs_entry` | 土台 |
| `wall` | `wall_main`, `wall_secondary`, `gable_wall` | 壁・妻壁 |
| `frame` | `column`, `beam`, `corner_quoin`, `half_timber` | 柱 |
| `opening` | `window_glass`, `window_frame`, `door`, `shutter`, `arch` | （部品） |
| `roof` | `roof_surface`, `eave`, `ridge`, `gable_trim`, `chimney`, `dormer` | 屋根 |
| `ornament` | `cornice`, `band_course`, `railing`, `relief`, `accent_other` | 帯・装飾 |
| `context` | `path`, `fence`, `vegetation_attached`, `light_fixture`, `floor_visible` | 床・照明 |

### 6.3 地形ラベル

`ground_soil`, `ground_grass`, `rock_face`, `rock_scree`, `sand`, `snow_ice`, `water`, `vegetation_low`, `vegetation_tree_canopy`, `tree_trunk`, `path_natural`。付随属性は画像内の相対高度帯と勾配区分（深度推定に由来するものは`estimated`フラグ付き）。

### 6.4 シーン属性

- 建築：`style`は閉じた語彙で、MCBlueprint同梱プリセット（`medieval`／`japanese`／`modern`）を含む15〜25種から始める。`building_type`（house／tower／temple／castle／shop／bridge／other）、`scale`（small／medium／large）。
- 地形：Minecraftのバイオームに対応させた`biome_like`、季節、天候・時間帯（照明条件）。
- 語彙の正本は`taxonomy/*.yaml`。変更するときは`taxonomy_version`を上げる。

## 7. 配色パック（MCBlueprintへの出力）

- 形式：`colorpack.json`。MCBlueprintの`src/mcblueprint/data/`に同梱し、標準ライブラリだけで読める。サイズが数MBを超える場合はgzipを検討する。
- **契約の正本はMCBlueprint側に置く**：JSON Schema（`schema/colorpack.schema.json`）、役割名、条件の語彙（style・building_type・biome_like）、対応するMinecraftバージョンはMCBlueprintが定義する。読み込む側が形式を決め、本リポジトリはそれに合わせて出力する。
- 本リポジトリはMCBlueprintをバージョン固定で参照し、ビルドしたパックをそのスキーマで検証する。語彙はMCBlueprintの定義と`taxonomy/`の対応表で変換し、対応のないラベルはパックに出さない。
- 契約の変更手順：MCBlueprint側でスキーマ・語彙を変更するPRを先にmerge → 本リポジトリの参照バージョンを上げて出力を合わせる。本リポジトリからスキーマを変更しない。
- 内容：
  - `palette_prior`：条件（style・building_type・biome_like）→役割ごとのベース色分布（OKLab分位点）とサンプル数
  - `relation_rule`：役割の組→ΔL／ΔC／Δhの分布
  - `accent_rule`：アクセントの役割と面積比の上限
  - `block_color`：対応するMinecraft版ごとのブロック面のOKLab分位点・材質タグ
  - `provenance`：統計バージョン、入力件数、`subject`数、使用ソースとライセンスの集計、帰属表示の一覧
- 選択アルゴリズム（MCBlueprint側）：条件でベースパレットをサンプル→役割間の関係制約で整合を確認→ブロック色距離と材質制約で重み付きPaletteに割り当てる→`seed`で再現する。出力は既存の`palettes`形式なので、Blueprint JSONとValidatorは変更しない。
- 本リポジトリは、パックの検証（MCBlueprintのスキーマ、ブロックID、サンプルBlueprintのプレビュー生成）までを担う。

## 8. ライセンス方針

MCBlueprintはMITで公開・無料配布される。MITは利用者の商用利用を妨げないため、同梱パックは次の区分で管理する。

| `license_class` | 例 | 同梱パックへの使用 |
|---|---|---|
| `open` | CC0、CC BY、CC BY-SA、Public Domain、Apache-2.0／MITの重み | 可（帰属表示を`provenance`に記載） |
| `noncommercial` | CC BY-NC系画像、Depth Anything V2 Base以上の重み | **不可**。内部の比較・評価にだけ使う |
| `academic_only` | `compphoto/Intrinsic` | **不可**。評価専用 |
| `restricted` | ND、規約で自動取得を禁止するソース、独自ライセンスの重み（未確認） | 取得しない、または使用前に個別確認 |

- 統計値のみを同梱し、画像・切り抜き・テクスチャは含めない。
- SAM 2（Apache-2.0）は`open`の想定。SAM 3.1・DINOv3・Grounding DINOの重みのライセンスは採用Issueで一次情報を確認して区分する。
- パックのビルド時に、`noncommercial`／`academic_only`／`restricted`の`processing_run`や`asset`に由来するレコードを除外し、除外件数を`provenance`に記録する。

## 9. データソース

| 優先 | ソース | 確認事項 | MVPでの扱い |
|---|---|---|---|
| 1 | Wikimedia Commons API | ファイルごとのライセンス・作者、APIの利用規約・User-Agent・レート | 実建築・地形の主ソース |
| 1 | Openverse API | 匿名・認証時のレート、元サイトでのライセンス照合 | Commonsの補完 |
| 2 | Minecraft画像 | mc_vanillaの扱いは後続で必要になった時点で再検討する | M2の色推定誤差評価には使用しない |
| 2 | ライセンスが明記されたSchematic | 配布サイトの規約・再利用可否 | 部位推定の検証用の正解。`mcblueprint import`で読む |
| 3 | 建築色彩の文献 | 著作権・引用範囲 | 後期。ルールの根拠付けのみ |
| 保留 | SNS・画像共有サイトのMinecraft作品 | 規約上の自動取得可否 | 規約確認まで取得しない |

各ソースは`source_policy`（取得可否、レート、帰属表示、再配布可否、`license_class`の判定方法）を設定に持ち、ポリシーのないソースからは取得しない。

### 9.1 収集の偏り制御

検索結果の上位や取得しやすいソースをそのまま集めると、有名建築・特定地域・特定作者・晴天の昼間などに統計が偏る。**収集の段階で偏りを抑え、残った偏りを統計の段階で補正する**。

- **層（strata）を先に定義する**：建築は`domain × style × building_type × 地域 × 年代`、地形は`biome_like × 季節 × 照明条件`。層ごとに目標件数（`subject`数）を`configs/collection_targets.yaml`に定める。
- **目標に基づいて収集する**：collectorは、目標に対して不足している層の検索語・ソースを優先してジョブを投入する。目標に達した層の取得は止める。人気順の上位だけを取らず、検索結果の複数ページ・ランダムなオフセットから取る。
- **集中の上限**：1`subject`あたりの画像数、1作者・投稿者あたり、1ソースサイトあたり、1地域あたりの割合に上限を設ける（初期値はパイロットで決め、設定に置く）。
- **検索語の偏りを避ける**：様式ごとの語彙を複数言語で用意し、特定の言語圏・有名建築名に依存しない。
- **選ばれ方を記録する**：検索語、ソース、結果の順位・ページ、取得日時を`asset`に保存し、後から偏りの分析と補正ができるようにする。
- **網羅率レポート**：層ごとの画像数・`subject`数・作者数・ソース数、集中度（上位作者の占有率、エントロピー）を定期出力する。目標未達や集中度の高い層を一覧にする。
- **統計での扱い**：`subject`単位の重み、層ごとの重み（目標分布に対する逆確率）で補正する。サンプル不足の層は全体平均で埋めず、上位の層への平滑化と品質フラグで示す。Minecraft・実建築・地形は別ドメインとして集計する。
- **バニラMinecraft**：作者・サーバー・作品ごとの上限を設け、少数の作者の作風が様式の統計を支配しないようにする。

## 10. 1,000枚ベンチマーク

目的：1枚あたりの時間・容量・精度を実測し、10万枚／100万枚の所要時間と容量を試算する。

| 項目 | 方法 |
|---|---|
| 構成 | 実画像600（Commons・Openverse）、地形200。Minecraft画像200は廃止し、M1の実画像予算1,000枚には含めない |
| 正解セット | M2で100枚をCVATで部位ポリゴン付け（建築70・地形30）。M1の完成条件には含めない |
| 比較対象 | 分割：SAM 2＋Grounding DINO／SAM 3.1（テキスト指定）。補正：補正なし／Gray-World WB／Intrinsic（評価専用） |
| 精度 | 部位別IoU・適合率・再現率（細部装飾は別集計）、同一建築の複数画像間での推定材質色の一致度（subject内ばらつき） |
| 速度 | ノード×stage別の枚/秒、GPU使用率・VRAM最大値、CPU待ち、ディスクI/O |
| 容量 | 原本・縮小画像・マスク・Parquetの1枚あたりのバイト数 |
| 合格条件 | 全指標が記録され、決定的なstageは再実行で同じ結果になること。精度の閾値は初回結果を見て決める |

## 11. リポジトリ構成

`rs0325/mc-blueprint-color-stats`（private）。Python 3.12、`uv`でロック、ruff・pytest、GitHub Actions。デフォルトブランチは`develop`、リリースは`main`。

```
mc-blueprint-color-stats/
  pyproject.toml / uv.lock
  src/colorstats/
    schema/        # DBモデルとマイグレーション
    store/         # 論理パス→実保存先の解決
    queue/         # ジョブの投入・取得・リース
    collect/       # ソース別アダプター
    analyze/       # prep・segment・shade・color の各stage
    stats/         # Parquet→DuckDB集計、重み付け、平滑化
    blocks/        # バニラjarからのブロック面色抽出
    pack/          # 配色パックの生成・検証
  taxonomy/        # 分類体系の正本（YAML）
  configs/         # ノード・保存先・ソースポリシー・モデル設定
  ops/             # 監視・バックアップのスクリプトとsystemd unit
  bench/
  tests/
  docs/
```

既存の`scripts/ssh.py`・`.ssh-targets.json`・`AGENTS.md`・引継ぎ資料を含む。

### 11.1 バージョン表記

すべて**SemVer（`MAJOR.MINOR.PATCH`）**を採用する。

| 対象 | MAJOR | MINOR | PATCH |
|---|---|---|---|
| 本パッケージ（`pyproject.toml`、Gitタグ`vX.Y.Z`） | CLI・設定・DBスキーマの非互換変更 | 互換を保つ機能追加 | 不具合修正 |
| 分類体系`taxonomy_version` | ラベルの削除・統合・意味変更（再解析が必要） | ラベル・属性の追加 | 説明文の修正 |
| 配色パック`pack_version` | パックの互換性を壊す変更（MCBlueprintのスキーマのMAJOR変更に追従） | 条件・役割・ブロック・Minecraft版の追加 | 同じ形式での統計の再計算 |

- 1.0.0までは開発版（0.y.z）とし、最初の配色パックをMCBlueprintへ同梱する時点で1.0.0にする。
- パックには`schema_version`（準拠したMCBlueprintのスキーマのバージョン）、`taxonomy_version`、生成した本パッケージのバージョンを記録する。

## 12. マイルストーンとIssue案

### M0 基盤

| Issue | 内容 | 完成条件 |
|---|---|---|
| 1 | リポジトリ雛形 | 上記構成、uv・ruff・pytest、CIが通る、READMEと本設計書 |
| 2 | ubuntu-1/2のGPU環境 | NVIDIAドライバー・CUDA・PyTorchで両GPUの推論が動く。WSL2（H:）の4070 SUPERも確認 |
| 3 | 保存領域とストレージ監視 | ORICOをUUIDでマウント、SUNEASTをext4化、`raw`の設定、監視と停止条件が動く |
| 4 | PostgreSQLとバックアップ | ubuntu-2にPostgreSQL、ubuntu-0のHDDを確認・整備して日次バックアップ、復元試験に成功 |

### M1 スキーマ・収集MVP（1,000枚）

| Issue | 内容 |
|---|---|
| 5 | 分類体系v1（YAML）とDBスキーマ・マイグレーション |
| 6 | ジョブキュー（Procrastinateの適合確認を含む）とワーカー基盤 |
| 7 | `source_policy`とWikimedia Commonsアダプター |
| 8 | Openverseアダプター |
| 9 | 収集の偏り制御（層・目標件数・集中上限・網羅率レポート） |
| 10 | prep stage（重複・品質・縮小画像） |
| 11 | ブロック面色の抽出（`block_color`） |
| 12 | color stageのベースライン（部位なしの主色・OKLab） |

### M2 解析検証（1万枚）

自作Minecraft基準画像200枚は廃止する。統計の入力ではなく色推定誤差の基準用だったため、M2の色評価には使わない。mc_vanillaの扱いは後続で必要になった時点で再検討する。色推定誤差は、同一建築の複数画像間における推定材質色の一致度（subject内ばらつき）で評価する。正解セットはモデル下書きを人手で修正し、修正前後と修正量を記録する。

| Issue | 内容 | 依存 |
|---|---|---|
| #38 | M2の設計を本節・§9・§10へ反映 | なし |
| #39 | prep/colorのバッチ・常駐方式を実測して採否を決める | なし（本番DB・パイロットサービス不使用） |
| #40 | segment stageを実装し分割手法・重みライセンスを比較 | なし。原本入力は#42 |
| #41 | CVATで部位ポリゴン付き正解セット100枚を作成 | CVAT構築は即時可。下書き生成は#40 |
| #42 | raw共有方式を決めNFS断・復帰を実機確認 | #37完了後 |
| #43 | Openverseの不通原因とライセンス照合の歩留まりを実測 | #37完了後 |
| #44 | 収集を1万枚規模へ拡大 | #37、#43、#39の採否（未決なら現行方式） |
| #45 | 部位別の色観測と部位間の関係を抽出 | #40 |
| #46 | shade stageを比較し同一建築の一致度で評価 | #45、#41（同定付き画像群） |
| #47 | M2のベンチマークを集計し採用手法を決定 | #39〜#46 |

着手順：即時に#38〜#41（#41の下書き生成は#40後）。#37完了後に#42・#43。その後、依存を満たした#44〜#47を進める。


### M3 統計DB初版（10万枚）

`subject`の推定と重み付け／条件付き分布と平滑化／偏りレポート。

### M4 MCBlueprint接続

`rs0325/MCBlueprint`（先行）：配色パックのスキーマ・語彙の定義。  
本リポジトリ：スキーマに沿った配色パックの生成・検証（SemVerで版付け）。  
`rs0325/MCBlueprint`（後続）：パックの同梱と配色選択コマンド。生成結果のプレビューで人手評価する。

### M5 拡張（数十万枚〜）

ワーカー追加・例外キュー・網羅率の追跡。
