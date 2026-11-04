# mc-blueprint配色統計 設計書

作成日：2026-11-01  
状態：**設計確定（初版）**。  
前提資料：[引継ぎ資料](handoff-2026-11-01.md)、[ストレージ調査結果](storage-audit-2026-11-01.md)（11/1最終更新）。要件は両資料に従い、本書では再掲しない。

## 1. 位置付けと責務分担

| リポジトリ | 役割 | 公開 |
|---|---|---|
| `mc-blueprint/mc-blueprint` | AIエージェント向けの配布ツールキット（Blueprint JSON → `.schem`）。MIT、Python 3.11以上 | 公開・GitHubで無料配布 |
| `mc-blueprint/mc-blueprint-color-stats`（本リポジトリ） | 画像・資料の収集、解析、統計、**配色パックの生成** | public |

- 本リポジトリは配布物を直接持たない。成果は**配色パック**（バージョン付きJSON、§7）として出力し、mc-blueprintへ同梱する。
- 生成時の配色選択（パック参照→役割ごとのPalette生成）は**mc-blueprint側に実装**する。mc-blueprintの利用者は本リポジトリなしで動作でき、LLMを呼ばない。mc-blueprint側の変更は同リポジトリのIssueとして別途起票する（M4）。
- 配色パックの役割名はmc-blueprintのPalette役割（壁・柱・床・屋根・妻壁・土台。`designs/*.md`、`mcblueprint design`の出力）と対応させる（§6.2）。
- 本リポジトリではmc-blueprintをライブラリとして参照し、Palette検証・プレビュー生成に再利用する（ブロックID検証や`colors.json`を再実装しない）。

## 2. 要件・アーキテクチャ整合性レビュー

| # | 論点 | 判断 |
|---|---|---|
| R1 | ホスト対応 | 2026-11-01の読み取り確認で確定（§3）。ubuntu-0は別用途PC、ubuntu-1＝i5-8400、ubuntu-2＝i7-8700K。**ubuntu-1/2はGPUを認識しているがNVIDIAドライバー未導入**のため、M0で導入する |
| R2 | ジョブキューの置き場所 | Windowsは停止し得るため、キューとメタデータDBはUbuntu側に置く。SQLiteはLAN越しの複数ライターに不向きなので不採用。**PostgreSQLをubuntu-2のNVMeに置く** |
| R3 | 両1TB SSD | SUNEAST／ORICOは監視付きの暫定候補なので、**再取得可能な原本キャッシュ専用**とし、DB・正解データ・集計結果は置かない |
| R4 | Windowsの使用範囲 | **H:のみ**使用（空き769GB）。WSL2のディストリビューション、集計用Parquet、CVAT、パックのビルドをH:に置く。C・F・Gは使わない |
| R5 | 処理順序 | 分類体系とスキーマを先に確定し、収集は1,000枚MVPに限定。大量取得は品質・権利ゲートとベンチマーク後 |
| R6 | ライセンス | mc-blueprintはMITで無料公開されるため、同梱パックは**商用利用も許すライセンスと両立する入力だけ**から作る（§8） |
| R7 | 統計の単位 | 画像単位ではなく`subject`（同一建築・場所・作品）単位で重み付けする。収集時に撮影地点・タイトル・作者・作品ページを必ず保存 |
| R8 | ブロック色 | mc-blueprintの`colors.json`はプレビュー用のキーワード単位の代表色で粒度が足りない。本リポジトリで、ユーザーが所有するバニラjarから面ごとのOKLab分位点をローカル抽出し、テクスチャ画像は保存・配布しない |

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
                           │ ジョブ取得/結果登録   │ 必要原本の事前複製
            ┌──────────────┴─────────┐ ┌──────────▼──────────────┐
            │ ubuntu-2                │ │ Windows H:（WSL2）       │
            │ PostgreSQL・モデル重み  │ │ gpu-worker（任意参加）   │
            │ gpu-worker 分割・陰影   │ │ 集計(DuckDB)・CVAT       │
            └──────────┬──────────────┘ │ 配色パックのビルド       │
                       │                └──────────┬──────────────┘
                       ▼ 日次バックアップ          ▼
            ubuntu-0 HDD（DB・正解・集計）   配色パック → mc-blueprint
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
  M2でrawは必要原本の検証付き事前複製を採用し、derivedのNFS共有は継続している。
  再取得・再計算と障害時の制御は[配備手順](../ops/deploy/README.md)に従う。
  Issue #42の[方式比較・隔離試験と本番配備記録](storage-sharing.md)に従い、
  転送・SHA-256検証・GPUノードへの公開と読取り、保持削除の手順は配備・確認済み。
  HTTP原本配信APIは採用・実装していない。本番GPUジョブの投入・推論と自動scheduler連携は未実施で、
  原本入力の後段DB登録契約はIssue #66で扱う。

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
| `segment` | 1 asset／job・batch=1（[実装・計測](segment.md)） | GPU（12GB優先） | `region`、マスク、CVAT XML |
| `shade` | 1 asset／job、通常は`none`（補正なし） | CPU（Intrinsic比較のみGPU） | 部位ごとの観測色・材質色の領域平均、有効画素率 |
| `color` | 1 asset／job（実装済み） | CPU | `color_observation`, `relation` |
| `review` | 低信頼度サンプル | 人手（CVAT）／VLM（任意・明示時のみ） | ラベル修正、教師データ |
| `aggregate` | 統計バージョン1件 | Windows | `rule_stat` |

現行ワーカーは1スロットで、計算子プロセスを常駐させてjobを1件ずつ処理する。
prep/colorの16件・64件一括処理は採用せず、キューのclaim・完了は個々のjob単位で行う。
採否の実測値は[Issue #39ベンチマーク](../bench/issue39-report.md)に記録する。

M2の分割は`sam2-dino`（SAM 2.1 hiera tiny＋Grounding DINO tiny）を採用する。
M2時点で実装・評価済みの唯一の手法であり、CMP平均IoU 0.1988、ADE 0.1494、
CMP細部装飾3ラベル平均IoU 0.0728という低精度を受容したモデル候補として扱う。
人手修正は前提にしない。M3では装飾・壁の過剰検出を改善し、調整用と評価用の集合を分け、
公開正解と自前写真で改善を確認してから採用を見直す。数値の合格閾値はM3の設計で先に決める。
マスク・由来・失敗時の契約は[segment](segment.md)に従う。

通常の陰影補正は`none`を維持する。Gray-Worldはsol-correctで約5.08%改善するが、
model全体では約3.53%悪化するため一律採用しない。Intrinsicは§8の評価専用とする。
shadeの領域平均とcolorの最大クラスタ主色は異なる観測であり、同一指標へ混ぜない。
採用変更には建築・部位・日照条件を広げた共通集合での比較と利用条件の適合が必要。
根拠・母数・限界・未計測項目は[M2集計 §1〜§6](m2-report.md)、入出力は[shade](shade.md)を参照する。

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
| `region` | 部位ラベル、`instance_id`、マスク参照、bbox、正規化高さ（0=接地、1=頂部。接地・頂部が不明ならNULL）、面方向の推定、`label_source`（model／human／vlm／schematic） |
| `color_observation` | `observed_oklab`（主色・分位点）、`material_oklab`（推定、NULL可）、`material_confidence`、面積比 |
| `relation` | `(region_a, region_b, type)`、ΔL・ΔC・Δh（OKLCh）、ΔE_ok、面積比 |
| `processing_run` | モデル名、重みハッシュ、`license_class`、設定ハッシュ、ノード、日時 |
| `block_color` | Minecraft版、ブロックID、面（top／side／bottom）、OKLab分位点、材質タグ |

色空間は**OKLab／OKLChに統一**する（統計キー・ブロック照合とも）。CIELABは比較評価にだけ使う。

### 6.2 部位ラベル（建築）

2階層。統計は第2階層を基本とし、データが不足するときは第1階層へ平滑化する。右端はmc-blueprintのPalette役割との対応。

| 第1階層 | 第2階層 | mc-blueprintの役割 |
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

- 建築：`style`は閉じた語彙で、mc-blueprint同梱プリセット（`medieval`／`japanese`／`modern`）を含む15〜25種から始める。`building_type`（house／tower／temple／castle／shop／bridge／other）、`scale`（small／medium／large）。
- 地形：Minecraftのバイオームに対応させた`biome_like`、季節、天候・時間帯（照明条件）。
- 語彙の正本は`taxonomy/*.yaml`。変更するときは`taxonomy_version`を上げる。

## 7. 配色パック（mc-blueprintへの出力）

- 形式：`colorpack.json`。mc-blueprintの`src/mcblueprint/data/`に同梱し、標準ライブラリだけで読める。サイズが数MBを超える場合はgzipを検討する。
- **契約の正本はmc-blueprint側に置く**：JSON Schema（`schema/colorpack.schema.json`）、役割名、条件の語彙（style・building_type・biome_like）、対応するMinecraftバージョンはmc-blueprintが定義する。読み込む側が形式を決め、本リポジトリはそれに合わせて出力する。
- 本リポジトリはmc-blueprintをバージョン固定で参照し、ビルドしたパックをそのスキーマで検証する。語彙はmc-blueprintの定義と`taxonomy/`の対応表で変換し、対応のないラベルはパックに出さない。
- 契約の変更手順：mc-blueprint側でスキーマ・語彙を変更するPRを先にmerge → 本リポジトリの参照バージョンを上げて出力を合わせる。本リポジトリからスキーマを変更しない。
- 内容：
  - `palette_prior`：条件（style・building_type・biome_like）→役割ごとのベース色分布（OKLab分位点）とサンプル数
  - `relation_rule`：役割の組→ΔL／ΔC／Δhの分布
  - `accent_rule`：アクセントの役割と面積比の上限
  - `block_color`：対応するMinecraft版ごとのブロック面のOKLab分位点・材質タグ
  - `provenance`：統計バージョン、入力件数、`subject`数、使用ソースとライセンスの集計、帰属表示の一覧
- 選択アルゴリズム（mc-blueprint側）：条件でベースパレットをサンプル→役割間の関係制約で整合を確認→ブロック色距離と材質制約で重み付きPaletteに割り当てる→`seed`で再現する。出力は既存の`palettes`形式なので、Blueprint JSONとValidatorは変更しない。
- 本リポジトリは、パックの検証（mc-blueprintのスキーマ、ブロックID、サンプルBlueprintのプレビュー生成）までを担う。

## 8. ライセンス方針

mc-blueprintはMITで公開・無料配布される。MITは利用者の商用利用を妨げないため、同梱パックは次の区分で管理する。

| `license_class` | 例 | 同梱パックへの使用 |
|---|---|---|
| `open` | CC0、CC BY、Public Domain、Apache-2.0／MITの重み | D15の単一選択権利・帰属・全入力runを満たす非表現的統計のみ。SA/NC/NDは除外 |
| `analysis_only` | 取得経路と情報解析目的の根拠を確認した画像 | D15の解析専用経路を満たす非表現的統計のみ。画像の利用許諾は変更しない |
| `noncommercial` | CC BY-NC系画像、Depth Anything V2 Base以上の重み | **不可**。内部の比較・評価にだけ使う |
| `academic_only` | `compphoto/Intrinsic` | **不可**。評価専用 |
| `restricted` | ND、規約で自動取得を禁止するソース、独自ライセンスの重み（未確認） | 取得しない、または使用前に個別確認 |

- 統計値のみを同梱し、画像・切り抜き・テクスチャは含めない。
- M2採用のSAM 2.1 hiera tiny・Grounding DINO tinyの重みはApache-2.0で`open`と確定する（2026-11-02確認の[一次情報](segment.md#重みのライセンス)を再利用）。帰属・通知条件を保持し、runには入力asset・由来runの制約も伝播する。SAM 3.1は独自SAM Licenseで`restricted`、ユーザー判断により未評価（ゲート付き）・実行経路なしとして比較から除外する。DINOv3は採用Issueで確認する。
- 通常採用の補正なしと、不採用のGray-Worldには重みがなく、runの区分は入力から継承する。Intrinsic v2.0の`stage_0.pt`〜`stage_3.pt`は`academic_only`を維持し、通常処理・同梱パックへ採用しない（[利用条件と比較結果](shade.md)）。
- パックのビルド時に、`noncommercial`／`academic_only`／`restricted`の`processing_run`や`asset`に由来するレコードを除外し、除外件数を`provenance`に記録する。

### 8.1 D15の二経路と配布境界（2026-11-04ユーザー決定）

`open`経路は選択済みの元licenseとsourceの一致、SA/NC/ND除外、帰属、全runの制約を保持する。
`analysis_only`経路はsource/assetがともに同区分で、元license表示と固定確認記録が一致し、
出典・原画像識別子・provider・取得日時を追跡できる場合だけ許可する。
規約未確認・禁止・根拠失効・利用停止・削除要求は理由付き除外とする。
SA/NC/NDの既存画像を自動昇格せず、モデル重みは両経路ともopen必須とする。
非享受目的・必要な限度・権利者の利益を不当に害しないことを確認する内部区分であり、
法的適用を全件保証する判断ではない。海外処理や写真の表現再現へ流用しない。

区分は`rights.combine_license`で合成する。openのみはopen、openとanalysis_onlyはanalysis_only。
同じ非open制約は保持し、異なる非open制約の混在はrestricted。
prep、segment、shade、color、queue、CVAT、aggregateへ伝播する。
sourceはURLで共有する初回情報を保持し、後日の不一致はD15で止める。

| 内容 | 内部保存 | MIT配色パック |
| --- | --- | --- |
| 集計済み色分布・比率・共起・必要な品質フラグ | 可 | 非表現的な集計値のみ可 |
| 原本・取得縮小画像・切抜き・テクスチャ・座標マスク | 必要期間のみ非公開 | 不可 |
| CVAT画像・注釈・manifest・エクスポートZIP | 承認済み内部作業のみ | 不可 |
| source/asset詳細・作者・座標・自由文・検索履歴・署名URL | アクセス制限 | 必要最小の法定・契約上の帰属以外は不可 |
| 内部snapshot（原画像を含まない場合も同じ） | 内部再現用 | そのまま配布不可 |

M4の出力契約は[配布契約](pack-contract.md)。allowlistで新たに配布物を生成し、
provider別件数・適用方針版・除外件数・ビルド版と必要最小の帰属・通知だけを付ける。
DATA_LICENSEのMITは生成された配色データに適用し、元写真のlicense・作者・URLは改変しない。
削除・除外台帳から再ビルドできる内部入力索引を保持する。パックビルダーへの接続はM4で検証する。

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

### 9.0 取得経路と保持条件

確認基準日は2026-11-04。規約禁止をAPIやrobotsのAllowで上書きせず、未確認を許可にしない。
SNS一般を一律に許可しない。API・CDNの各hostの条件も有効化前に確認する。

| ソース | 経路・判断 | 開始条件 |
| --- | --- | --- |
| Commons / Openverse | 現行API経路、元サイトの権利確認を維持 | 既存設定を使用。登録クライアントは#93 |
| Library of Congress | JSON API、建築・地形のカラー写真候補 | collection別Rights and Access・各host確認、#88・#92 |
| Mapillary | API候補。規約全文・用途・大量保存条件は未確認 | ユーザー確認、#88・#94完了まで無効 |
| Flickr | HTML scraping禁止、認可APIのみ条件付き | 保存・削除要求・用途条件未充足のため保留 |
| Geograph | HTML/live bulkは禁止、小規模API・公式bulkのみ条件付き | 公式bulkの条件確認まで保留 |
| Reddit / X / Instagram / Pinterest / 500px | 無承認自動取得禁止、本用途は未承認 | 取得対象外 |
| Unsplash / Pexels / Pixabay | 本用途の自動取得・大規模保存条件が不適合または未確定 | 取得対象外 |

規約の根拠URL・確認日・要約・用途・判断者・policy版を固定source_policyに記録する。
既存ライブラリ（dataclass、PyYAML、SQLAlchemy、Alembic）と既存収集器を再利用し、依存は追加しない。
新規収集分は取得から30日、不採用7日以内、削除受付時に新規利用を停止して7日以内、
バックアップ残留30日以内。ソース条件が短ければ短い期限を採用する。
既存7,607件は削除しない。原画像の期限清掃だけでは完成済みの非表現的統計を失効させない。
統計利用根拠の失効と保存期限は別に扱う。清掃・公開境界と運用窓口は#88で完成させ、
それまで新ソースを有効化しない。確認キーと取得時JSONは[収集契約](collect.md#解析専用入力issue-87)参照。

### 9.1 収集の偏り制御

検索結果の上位や取得しやすいソースをそのまま集めると、有名建築・特定地域・特定作者・晴天の昼間などに統計が偏る。**収集の段階で偏りを抑え、残った偏りを統計の段階で補正する**。

- **層（strata）を先に定義する**：建築は`domain × style × building_type × 地域 × 年代`、地形は`biome_like × 季節 × 照明条件`。層ごとに目標件数（`subject`数）を`configs/collection_targets.yaml`に定める。
- **目標に基づいて収集する**：collectorは、目標に対して不足している層の検索語・ソースを優先してジョブを投入する。目標に達した層の取得は止める。人気順の上位だけを取らず、検索結果の複数ページ・ランダムなオフセットから取る。
- **集中の上限**：1`subject`あたりの画像数、1作者・投稿者あたり、1ソースサイトあたり、1地域あたりの割合に上限を設ける（初期値はパイロットで決め、設定に置く）。
- **検索語の偏りを避ける**：様式ごとの語彙を複数言語で用意し、特定の言語圏・有名建築名に依存しない。
- **選ばれ方を記録する**：検索語、ソース、結果の順位・ページ、取得日時を`asset`に保存し、後から偏りの分析と補正ができるようにする。
- **網羅率レポート**：層ごとの画像数・`subject`数・作者数・ソース数、集中度（上位作者の占有率、エントロピー）を定期出力する。目標未達や集中度の高い層を一覧にする。
- **統計での扱い**：subject単位で寄与を正規化し、目標分布に合わせた事後層化で補正する。これは真の包含確率によるIPWではない。サンプル不足の層は全体平均で埋めず、上位の層への平滑化と品質フラグで示す。Minecraft・実建築・地形は別ドメインとして集計する。
- **バニラMinecraft**：作者・サーバー・作品ごとの上限を設け、少数の作者の作風が様式の統計を支配しないようにする。

## 10. 1,000枚ベンチマーク

目的：1枚あたりの時間・容量・精度を実測し、10万枚／100万枚の所要時間と容量を試算する。

| 項目 | 方法 |
|---|---|
| 構成 | 実画像600（Commons・Openverse）、地形200。Minecraft画像200は廃止し、M1の実画像予算1,000枚には含めない |
| 正解セット・補助判定 | 人手正解は作らない。CMP606枚・ADE617枚の公開正解で画素評価し、自前100枚（建築70・地形30）はgpt-6.1-solで領域判定・10枚を二重判定する。モデル判定は人手正解ではない |
| 比較対象 | 分割：SAM 2.1 tiny＋Grounding DINO tinyのみ実装・評価済み。SAM 3.1はユーザー判断により未評価・比較除外（§8）。補正：補正なし／Gray-World WB／Intrinsic（評価専用） |
| 精度 | 部位別IoU・適合率・再現率（細部装飾は別集計）、同一建築の複数画像間での推定材質色の一致度（subject内ばらつき） |
| 速度 | ノード×stage別の枚/秒、GPU使用率・VRAM最大値、CPU待ち、ディスクI/O |
| 容量 | 原本・縮小画像・マスク・Parquetの1枚あたりのバイト数 |
| 合格条件・到達点 | 全指標が記録され、決定的なstageは同条件の再実行で同じ結果になること。M2の採用判断は§5.2・§8、実測と未計測・未充足は[M2集計](m2-report.md)へ記録する。現時点で精度の合格閾値や全ノードの性能を達成したとは扱わない |

## 11. リポジトリ構成

`mc-blueprint/mc-blueprint-color-stats`（public）。Python 3.12、`uv`でロック、ruff・pytest、GitHub Actions。デフォルトブランチは`develop`、リリースは`main`。

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
| 配色パック`pack_version` | パックの互換性を壊す変更（mc-blueprintのスキーマのMAJOR変更に追従） | 条件・役割・ブロック・Minecraft版の追加 | 同じ形式での統計の再計算 |

- 1.0.0までは開発版（0.y.z）とし、最初の配色パックをmc-blueprintへ同梱する時点で1.0.0にする。
- パックには`schema_version`（準拠したmc-blueprintのスキーマのバージョン）、`taxonomy_version`、生成した本パッケージのバージョンを記録する。

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

自作Minecraft基準画像200枚は廃止する。統計の入力ではなく色推定誤差の基準用だったため、M2の色評価には使わない。mc_vanillaの扱いは後続で必要になった時点で再検討する。色推定誤差は、同一建築の複数画像間における推定材質色の一致度（subject内ばらつき）で評価する。ユーザー決定により人手正解は作らず、公開正解の画素評価と自前100枚のモデル判定へ置き換える（§10）。採用手法・ライセンスは§5.2・§8で確定し、1万枚規模の検証と未計測項目の到達点は[M2集計 §7](m2-report.md)で区別する。

| Issue | 内容 | 依存 |
|---|---|---|
| #38 | M2の設計を本節・§9・§10へ反映 | なし |
| #39 | prep/colorのバッチ・常駐方式を実測して採否を決める | なし（本番DB・パイロットサービス不使用） |
| #40 | segment stageを実装し分割手法・重みライセンスを比較 | なし。原本入力は#42 |
| #41 | CMP/ADE公開正解の画素評価と自前100枚のsol領域判定・建築同定・二重判定（人手正解ではない） | 分割推論は#40 |
| #42 | raw共有方式を決めNFS断・復帰を実機確認 | #37完了後 |
| #43 | Openverseの不通原因とライセンス照合の歩留まりを実測 | #37完了後 |
| #44 | 収集を1万枚規模へ拡大 | #37、#43、#39の採否（未決なら現行方式） |
| #45 | 部位別の色観測と部位間の関係を抽出 | #40 |
| #46 | shade stageを比較し同一建築の一致度で評価 | #45、#41（同定付き画像群） |
| #47 | M2のベンチマークを集計し採用手法を決定 | #39〜#46 |

着手順：即時に#38〜#41（#41の下書き生成は#40後）。#37完了後に#42・#43。その後、依存を満たした#44〜#47を進める。


### M3 統計DB初版

2026-11-03のユーザー決定により、現7,607 assetを固定コホートとして、subject推定・重み付き条件分布・平滑化・偏りレポートを完成させる。10万枚はM3の必須件数にせず、D15適格かつSHA重複除外後の解析可能画像について、1万→3万→10万の段階目標とする。取得レコード・SHA異なり・確定subject・D15適格数・統計採用数は区別して報告する。

M3完成条件：
1. 固定7,607 assetの解析成功・失敗・除外・品質・速度・容量を追跡できる。
2. subjectとシーン属性の確定・候補・未知を分けて再実行でき、誤結合・分類矛盾を検出する。
3. D15適格入力から統計を生成し、同じ固定snapshotから再現可能に再集計できる。
4. 実建築・地形の各1役割以上で、既知属性による部分層補正の主結果の確定subject数10以上かつsubject基準n_eff 10以上を満たし、ラベル品質ゲートを通る。親借用で実測支持を増やさない。判定役割ごとの補正率・属性別未知率・情報なし割合と分母subject数を併記する。passed は層補正の有効性を意味しない。情報なし割合>0.5はweak_correctionとするが、passedの追加閾値にはしない。
5. すべての対象層について不足・未知・D15除外・平滑化・未支持を含む偏りレポートを出力する。
6. 分布の単位・品質・支持範囲・権利制約をGへ引き継ぐ。配色パック生成・同梱と10万枚目標の達成は別状態として扱う。

| Issue | 内容 | 依存 |
|---|---|---|
| #71 | M3設計を設計書へ反映 | なし |
| #72 | subjectと根拠付きシーン属性を推定 | #71 |
| #73 | 部位統計へ採用する分割設定と品質ゲートを固定 | #72 |
| #66 | 収集全量にsegment以降を適用し全量の速度・容量を記録 | #73の採用設定commit |
| #74 | D15適格入力の固定スナップショットを作成 | #72、#73、#66 |
| #75 | subject重み付き条件分布と階層平滑化を登録 | #74 |
| #76 | 偏り・支持範囲を報告しM3完成を検証 | #75 |
| #77 | 重複排除・権利条件を保った追加収集の歩留まりを測定 | #72、#74 |

着手順：#71 → #72 → #73 → #66 → #74 → #75 → #76。#77は#74以降に#75・#76と並行可能。coverage／collection-bias.mdの編集は#76と直列にする。


### M3-A: subject推定の実行契約（Issue #72）

実装は`stats/subjects.py`、CLIは`python -m colorstats.stats.subject_cli`。
`configs/subject_rules.yaml`の固有対象カテゴリと名称別名を組み合わせ、両根拠が一意で
矛盾しない場合に確定する。初版は保存済みメタデータで確認した明示カタログを使用する。
一般カテゴリから対象を自動生成する方式は、対象粒度と別棟の混同を避けるため採用しない。
既存SQLAlchemy/PostgreSQL・重複グラフと標準ライブラリを再利用し、新規依存を追加しない。

domainを分離し、強い対象キーから決定的UUIDを作る。
既存subjectの再利用には成功runに保存されたdomain・対象キー・subject IDの対応を要求し、
名称一致だけで既存IDを採用しない。旧実行の根拠を使う場合も、決定的UUID・成功runの
設定hash・独立した名称と固有カテゴリを確認する。対応を確認できないID衝突は失敗とする。
名前だけ・カテゴリだけ・pHashだけは候補、近接座標だけでは候補対象も生成しない。
SHA完全一致群では一意の確定値を継承するが、弱い対象名を含む別対象の根拠との競合・
複数対象・位置矛盾では新規確定を抑止し、競合対象と元assetを保存する。
betweenの年代範囲と窓・柱などの構造説明を多対象判定から除外し、対象間の位置関係は除外しない。
pHashはprepがImageHashの既存閾値で作ったasset_duplicateだけを候補生成に使い、
全画像ペアを再走査しない。撮影GPS単独では確定せず、Wikidataで分類・粒度を検証した
固有対象キーと、P625からの距離の整合を組み合わせた場合は確定根拠に使う。
固定基準点からの撮影範囲による矛盾検出も維持する。建築4km・地形40kmの最大撮影範囲に別設定を持ち、
基準点から最大撮影範囲の半分を越える群は全体を候補へ戻す（距離連鎖で対象を拡大しない）。

シーン属性は明示カテゴリの語彙規則と確定対象の恒久属性を使用する。
対象の季節・天候・時刻を別画像へ伝播せず、検索語・収集層は参照しない。
矛盾は未分類にし、既存確定値を維持する。#41は限定回帰資料であり人手正解ではない。

実行例（接続情報は環境から渡し、表示しない）:

```sh
python -m colorstats.stats.subject_cli --snapshot /新規パス/dry.json --code-version <コード内容版> --dry-run
python -m colorstats.stats.subject_cli --snapshot /新規パス/applied.json --code-version <コード内容版>
```

dry-runはREPEATABLE READ/READ ONLY。本実行はprepと同じadvisory lockと対象表の
書込み排他を取得し、全件・候補・runを1取引で確定する。既存確定subjectは上書きしない。
明示的に`--reconsider-run <成功run UUID>`を渡した場合だけ、そのrunが新規に付け、
現在も同じrun・subjectを参照する関連付けを再評価する。修正規則で同じ対象へ確定できなければ
NULLへ戻し、取消件数を保存する。指定run以前の確定、その後の別処理による変更は保持する。
指定runの成功スナップショットで更新前値を確認し、読めない・runが一致しない場合は反映しない。
設定・taxonomyが不正、DBエラー、出力ファイル作成失敗の場合はrollbackし、
CLIは接続情報を含み得る例外本文を表示しない。失敗した出力パスは再利用せず、
成功runと照合したスナップショットだけを後続の正本にする。
カタログ外・欠損・過度な撮影範囲は未確定として残るため、件数を精度保証と解釈しない。

### M3-D: 部分層補正（Issue #75、2026-11-04ユーザー決定A）

完全一致・一意層割当を既知属性による部分補正へ置き換える。D15・SHA代表・ラベル品質ゲートは維持する。
全層両立でも主結果で条件4を判定し、補正率0・情報なし割合1を隠さない。
補正率は偏りの改善率ではなく、両立層を絞り込めたsubjectの割合である。

#### 共通の判定契約

- `asset_attributes(asset) -> (attributes, conflicts)`：
  snapshotのsubject確認済み属性とasset実属性を、既存coverageの地域・年代読取りで統合する。
  収集意図や候補値は使わない。scene_attributesに保持された確認済み・根拠付き推定値という
  従来のstate基準を維持する。欠損・None・空文字・unknownは既知値を上書きしない。
- `compatible_strata(attributes, strata) -> list[str]`：
  domainを必須とし、そのdomainの目標層の属性だけで既知値の一致を調べる。
  unknownの属性は周辺化する。両立層IDを設定順で返し、対象外は空配列。
  #76もこの関数を使用し、別の完全一致・両立判定を実装しない。
  層にないweather等は照合対象にしない。
- `assign_strata(assets, strata) -> (assigned, reasons)`：
  assignedはsubject ID→既知層属性の辞書、矛盾・対象外の場合はNone。
  reasonsはsubject ID→理由配列。適格画像間の既知値を統合し、
  unknownと既知値の混在は矛盾にしない。層属性の既知値が競合する場合は
  subject_stratum_conflict、subject/asset内の競合はattributes_conflict、
  両立層なしはoutside_target。
  従来の「subject ID→一意な層ID」という戻り値は使用しない。

条件生成は引き続き実際に分かる条件属性だけから行う。
unknownを特定style等の直接観測に補完しない。条件が不足した子には既存の親CDF借用を使う。
同じsubjectの別画像から季節・時刻を画像の条件属性へ補完する処理も追加しない。

#### 推定量

各domain・条件・役割/pairごとに、条件と両立する目標層へsubjects目標を限定し、
q_hを合計1へ再正規化する。属性が目標層にない条件成分はqを狭めない。
両立する確定subjectが当該セルのNを構成する。未知subjectは主結果へ入れない。

```
m_sh = q_h * 1[両立] / Σ_{両立 h'} q_h'
p_h  = Σ_s m_sh / N
r_h  = q_h / p_h                    （p_h > 0のみ）
W_s  = Σ_h m_sh * r_h
n_eff = (Σ_s W_s)^2 / Σ_s W_s^2
```

subject内は有効SHA画像へ等配分し、画像内は役割領域の面積比、
pairは領域面積積で正規化した重みにW_sを乗じる。
同じ画像・subjectの観測行数を、Nやp_hの独立標本として数えない。
p_h=0の層はmissing_strataに残し、r_h=0等で埋めない。
支持された目標質量だけでCDFを正規化し、欠損目標質量を明示する。

qualityの追加出力：

| 項目 | 意味 |
| --- | --- |
| target_probabilities | 当該セルの再正規化済みq_h |
| memberships | subject ID→層ID→m_sh（非両立層は省略） |
| stratum_probabilities | 層ID→p_h（0の層も含む） |
| stratum_weights | 支持された層ID→r_h |
| subject_weights | subject ID→W_s |
| max_stratum_weight / max_weight | 最大r_h / 最大W_s |
| correction_rate | 両立層を1つ以上かつ全適用層未満へ絞り込めたsubject数 / N |
| attribute_unknown_rates | 層属性ごとの未知subject数 / N。domainは含めない |
| no_information_rate | 全適用層と両立するsubject数 / N |

割合の分母は当該条件・役割で採用した確定subject N。
矛盾・対象外はunassigned_subjects/reasons、未知subjectはunknown_imagesに別記する。
N=0では割合を0、空の支持・欠損質量1を保存する。
情報なし割合は条件で限定した後の適用層に対する値であり、
適用層が1つなら絞込みの余地がなく全採用subjectが情報なしに該当する。

全層両立のsubjectだけならm_sh=q_h、p_h=q_h、r_h=1、W_s=1となる。
これは情報が増えたことではなく、no_information_rate=1・未知率で明示する。
M3条件4はユーザー決定に従ってこの主結果の実測支持とn_effで判定する。

high_weight（従来どおり最大r_h>5）、層比r_hの上限5、補正なし、未知SHAを別subjectとする無補正感度、
円周Δh・経験CDF混合・30/10の支持閾値は維持する。
補正なし感度は対象外・矛盾の確定subjectも含む従来の診断として区別する。


### M3-E: 固定snapshotの偏り・完成条件レポート（Issue #76）

report CLIはDBや元画像へ接続せず、全Parquet hashと同じ設定によるaggregate-v2の再計算を検証する。
入力JSON全体が一致しなければ拒否する。全量の完全一致再計算は本番と同じLinux環境で行う。
Windowsでは診断delta_cの浮動小数点末尾差が出るため、OSを跨ぐバイト一致は保証しない。

12層の意図／実属性、全体／層別のasset行・SHA・重複、確定／候補／未知、
作者・provider・地域等の集中、除外理由と分母を分ける。
層の両立件数は重複し得る。被覆は所属質量m_shの和／目標subject数、
不足はmax(0,目標-所属質量)であり、未知を各層へ1 subjectずつ足さない。
条件・役割/pairのn_eff・補正率・未知率は#75主結果をそのまま渡す。
条件4のJSON・Markdownに判定役割別の率と注意文を必ず添える。

D15前後の役割支持は保存済み色を持つsubjectの集合差で報告し、採用所属質量とは区別する。
必要解析の失敗が明示される画像はmissing_analysisとして数え、色の支持へ足さない。
解析のある画像で和集合色が未保存なら前後差をnullとし、条件5をunverifiedとする。
#85の属性state・根拠runはsnapshotから追跡する。

自動レポートの条件1・2は外部監査待ち、条件6はGへの実際の引継ぎ確認待ちとする。
外部証跡を照合した判定はbench/issue76/m3-assessment.jsonへ別記し、自動判定と混同しない。
実結果・再現手順は[全量結果](../bench/issue76/full-results.md)、
単位・支持範囲・権利制約は[G引継ぎ](../bench/issue76/g-handoff.md)を参照する。
2026-11-05の固定snapshotは条件4未達であり、M3完成扱いにしない。

### M4 mc-blueprint接続

`mc-blueprint/mc-blueprint`（先行）：配色パックのスキーマ・語彙の定義。\
本リポジトリ：スキーマに沿った配色パックの生成・検証（SemVerで版付け）。  
`mc-blueprint/mc-blueprint`（後続）：パックの同梱と配色選択コマンド。生成結果のプレビューで人手評価する。

### M5 拡張（数十万枚〜）

ワーカー追加・例外キュー・網羅率の追跡。
