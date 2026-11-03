### 固定統計スナップショット（Issue #74、schema.md 追記案）

形式版は1、権利ゲート版はD15-v1。画像を含まないParquetとmanifest.jsonを、
未使用の出力ディレクトリへ作る。既存出力へ上書きしない。
本節は#79との編集競合を避けた下書きであり、docs/schema.mdは未変更。

実行入口は `python -m colorstats.stats.snapshot_cli`。
`--selection <JSON>`、`--code-version <固定コード版>` を必須とし、
通常実行では `--output <未使用ディレクトリ>` も指定する。
`--quality` は既定で configs/segment_stats.yaml。
`--dry-run` は永続artifactを作らず、一時領域で同じ件数・除外を検査する。
DATABASE_URLは環境から渡し、例外本文・接続情報をCLIへ表示しない。

選択JSONは次の形。全件のasset IDと採用する成功runを呼出し側で明示し、
DBの最新runを自動選択しない。失敗・欠測もコホートへ残す場合はrunを省略する。

```json
{
  "taxonomy_version": "0.1.0",
  "assets": [
    {
      "asset_id": "<UUID>",
      "prep_run_id": "<UUID>",
      "segment_run_id": "<UUID>",
      "color_run_id": "<UUID>"
    }
  ]
}
```

- 1つのREPEATABLE READ / READ ONLY取引で必要列を256件ずつ読む。
  選択asset欠損・重複、未成功run、別asset・異taxonomy・異stage、
  選択prep/segmentとcolorの直接入力不一致、入力循環、採用分割設定不一致は全体失敗。
- processing_run_inputを再帰的に辿り、全解析入力runの制約を確認する。
  subject/scene_inferenceが参照する成功subject runも取り込む。
  subjectと属性・候補・推定根拠は現在値をコピーし、再読取り時にDBへ参照しない。
- asset.quality.licenseとsource.licenseの選択値を照合する。
  PD/PDM・CC0・版付きCC BYだけを許容し、SA/NC/ND・制限付きrun・
  評価専用重み・権利不明・由来/帰属不足を理由別に除外する。
  カテゴリ上の複数ライセンスから選び直さず、別出典による再許諾を推測しない。
  原本や除外された出典を削除しない。
- 権利と必要解析が適格なassetの中で、SHAごとにUUID文字列最小の代表を採る。
  全別出典とその個別の除外理由を残す。D15除外・解析欠測・SHA重複を区別する。
- 画像全体観測はwhole_image、未支持の個別ラベルはunvalidated_labelとして保持する。
  shade平均をcolorの主色に置き換えない。
- #81の評価artifactはUTF-8/LFでhash照合し、支持済み和集合のメンバーを固定する。
  real_building/wallとreal_terrain/treeは、選択colorの画像・マスクの設定hashを照合後、
  既存color処理で画素和集合から主色を再抽出する。重なる画素は一度だけ数える。
  個別ラベルの支持も評価資料のdomain別に適用し、建築のdoorを地形へ転用しない。
  個別ラベルの観測を足した結果や親からの平滑化を直接支持にしない。
  画像・マスクは生成時だけ必要で、値を固定した後の再集計では不要。
  入力ファイルの欠損・改変・抽出失敗も全体失敗。

Parquet一覧:

| ファイル | 主な列と意味 |
| --- | --- |
| assets | id、sha256、domain、subject_id、representative_id、eligible、reasons、data（選択run・属性・subject・候補・根拠・収集意図） |
| provenance | asset_id、source_id、data（元URL・サイト・作者・選択ライセンス・帰属・収集時点） |
| runs | id、stage、data（設定・コード・重みhash・制約・成功時点・input_run_ids） |
| regions | id、asset_id、run_id、label、data（領域面積比・信頼度・位置等） |
| observations | id、asset_id、region_id、run_id、eligible、reasons、data（主色・クラスタ分位点・面積比） |
| relations | id、asset_id、run_id、eligible、reasons、data（順序付き領域参照・B−Aの差・B/A面積比） |
| groups | id、asset_id、run_id、role、eligible、data（構成領域・画素和集合面積比・主色・由来hash） |

data/reasons列はParquetのJSON文字列。ID・参照・ゲートは独立した型付き列。
assets.eligibleは権利・必要解析・SHA代表の入口ゲートであり、
subject・属性・有効標本数の支持条件を満たしたという意味ではない。
観測と関係のeligibleはさらに個別ラベル品質を要求する。
groupsは明示的な粗い役割だけの支持。後続#75で確定subject・根拠ある属性を
選び、未知subjectの診断分布と主統計を分離する。

manifestは選択集合とhash、taxonomy/コード版、固定品質設定とhash、
DB取引snapshot・分離レベル、段階別件数、複数該当を許す除外理由の件数、
全ParquetのSHA-256と行数、DuckDB版、snapshot_idを持つ。
rights_eligibleは権利ゲート後、analysis_eligibleは必要解析・domainの確認後、
representativesはさらにSHA代表選択後のasset件数。
sha_distinctは入力全体、confirmed_subjectsは代表の非NULL subject異なり数。
*_rowsは保存行数、*_eligibleは入口・品質ゲート後の行数。
クラスタ行数を画像数・subject数へ読み替えない。
除外理由の合計は複数該当があるため除外asset数とは限らない。

全Parquetのhashと件数を照合してからmanifestを最後に作る。
失敗した出力ディレクトリは成功artifactとして採用せず、新しい出力先で再試行する。
snapshot_idはsnapshot_id自体を除くmanifestの正規JSONのSHA-256。
正規JSONはUTF-8、キー順・区切りを固定しNaNを禁止する。
`verify(path, expected_hash)`へ信頼済み呼出し元が保持したsnapshot_idを渡し、
manifest・ファイル集合・全ファイルhash・行数を照合してから読む。
同じDB状態・入力集合ではParquet内容と代表が同じになる。
DB取引識別子が異なる再生成はsnapshot_idまで同一とは約束しない。

後続aggregateは成功snapshotのhashと固定設定をQueueのキーへ含め、
runs.parquetの入力runをprocessing_run_inputへ結ぶ。
Queue.completeの所有権確認・取引境界を経て統計を採用する。
snapshot作成自体はDB無更新で、aggregate登録やrule_stat生成は#75の責務。

既存データの移行・削除は不要。実7,607件からの生成は#66完了・#79 merge後の
第2段階とし、第1段階のfixture成功を実データの支持数の達成とは扱わない。
