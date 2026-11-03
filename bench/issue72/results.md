# Issue #72 対象推定の本番実測

2026-11-03。基準は#71 merge後の`origin/develop`
`6e312464fb77137d242b1a916531aa5c73d8c19b`（開始時にfetch）。
担当worktreeは`H:/mc-blueprint/worktrees/colorstats-72/mc-blueprint-color-stats`、
ブランチは`feature/issue-72`。commit・push・PR作成は未実施。

## 反証3件の修正

1. 既存subjectの再利用を名称一致から成功runの対象キー対応へ変更した。
   domain・対象キー・subject IDをprocessing_run.parameters.subject_keysに保存する。
   旧根拠の利用も対象キーの決定的UUID、成功runと設定hash、名称＋固有カテゴリが
   一致する場合に限定し、旧方式の名称再利用が作った任意IDは確認済みとみなさない。
   キーを確認できない決定的UUIDの衝突は失敗とし、別subjectへ結合しない。
2. 同一domain・SHA群内の弱い対象名や固有カテゴリも競合に含めた。
   別対象の根拠があれば群の新規確定を抑止し、sha_conflictsに対象と元assetを保存する。
   ファイル名だけの旧subjectとpHash候補は対象名の証明として使わない。
3. betweenの年代範囲と窓・柱等の構造説明を多対象から除外し、対象間の位置関係は残した。
   Glessner Houseの窓間説明とミュンスター大聖堂の年代説明を実メタデータfixtureに固定した。
   ミュンスターの既存キーへ独立に確認したExterior viewカテゴリを追加し、
   #41の誤った候補期待値を修正した。一般カテゴリの許容範囲は広げていない。

既存SQLAlchemy/PostgreSQL・prepのImageHash重複グラフ・標準ライブラリとPyYAMLを使用。
新規依存・テーブル・Enum変更はない。検索意図を確定属性へ昇格させていない。

## 実行条件・成果物

ubuntu-2、PostgreSQL 16.15。既存issue-46検証venvを再利用し、
専用領域`/mnt/data/work/issue-72/code`から固定スナップショットをロードした。
接続はpostgresのpeer認証で、認証情報・接続URLを表示していない。
ubuntu-1のpilotを再開せず、サービスの配備先も切り替えていない。

最終コード内容版: `6e31246+i72-review-ab889e537543e9d3`。
`src/colorstats/stats/*.py`と`configs/subject_rules.yaml`をパス順に並べ、
各パス文字列とファイル内容を順番にSHA-256へ投入した先頭16桁を使う。
規則版は2、taxonomy版は0.1.0。
規則hash: `86e2a4eeab4af82889bb70cdb35d091af594ef30b72c835d9448fcc0ba85f014`。

最終成功run: `b5ad2583-fcb2-4ffe-a43f-ab9028729852`。
完全スナップショットはubuntu-2の
`/mnt/data/work/issue-72/production-results/review-applied-02.json`。
Gitには全量メタデータを入れず、[production.json](production.json)へ
hash・run ID・件数・時間・検査結果を保存する。修正前の実測も同JSONに保全した。

## 本番件数・時間

| 項目 | 修正前 | 修正後 |
| --- | ---: | ---: |
| 全asset / SHA異なり | 7,607 / 3,575 | 7,607 / 3,575 |
| 確定asset | 54 | 144 |
| 候補asset | 1,784 | 1,694 |
| 未同定asset | 5,769 | 5,769 |
| 確定assetのSHA異なり | 28 | 104 |
| 確定subject | 8（建築7・地形1） | 10（建築9・地形1） |

今回根拠を保存したsubject_candidateは2,076辺。
候補表には確定への根拠も入るため、候補asset数とは区別する。

| 実行 | 秒 |
| --- | ---: |
| 修正ルールdry-run | 27.631 |
| 修正ルール本実行 | 30.382 |
| 最終コードdry-run | 28.759 |
| 最終コード本実行 | 30.966 |

dry-run後に本実行し、1取引で全件・候補・取消判定・属性・成功runを確定した。
最終コードの再実行で全7,607件の状態・subject・属性・候補IDは不変。
独立したSQLでも件数、成功runと全件の最終run参照を照合し、不一致は0件。

## 取消範囲

`--reconsider-run 376fcdcc-4f47-43d0-ac33-c6e30c55f5ed`を指定した。
スナップショットの更新前値、現在のrun・subject参照を照合し、
そのrunが新規に付けた関連付けだけを再評価する。更新後に別のsubjectへ差し替えない。

**取り消し0件**。指定runは再実行であり、その54件はすべて既存確定の引継ぎだった。
それ以前の初回run `28d633d3-3aca-4ad7-8329-eec4976b9ab4`由来の54件は保護した。
対象runの新規関連付け0件・以前の確定の保護54件を初回修正実行に記録し、
前回の確定54件すべてのIDが維持されていることを独立に比較した。
最終再実行ではrun参照が既に更新済みのため、その値を再び取消対象には含めていない。
新規関連付けを実際にNULLへ戻す場合、取消後の再実行、途中失敗のrollbackはDBテストで検証した。

## 属性と反証

| 属性 | 推定 | 矛盾（未分類） | 未知 |
| --- | ---: | ---: | ---: |
| style | 44 | 0 | 7,563 |
| building_type | 461 | 4 | 7,142 |
| biome_like | 373 | 2 | 7,232 |
| season | 244 | 0 | 7,363 |
| time_of_day | 35 | 0 | 7,572 |
| weather | 32 | 0 | 7,575 |

SHA内の確定subject競合、domain混同、根拠なし確定、多対象・位置矛盾を無視した
新規確定、#41の異なる同名群の結合はいずれも0件。
#41の6群13枚は全件確定し、名前null同士を成功に含めていない。
モデル判定の同名群は人手正解ではなく、検査結果だけで同定精度を保証しない。
再集計: `python bench/issue72/audit.py <スナップショットJSON>`。

## 検証

- Python 3.12のworktree外venv、既存lock。依存変更なし。
- 最終コードのPostgreSQL 16.15全件pytest: **471 passed, 1 skipped**。
  スキップは既存GPUテスト（公式重み・CUDA・一時DBの明示指定が必要）。
  #72の30テストはすべて成功。
- 同名別地点・旧ファイル名subject、未確認UUID、旧方式の誤再利用根拠、
  弱い別名のSHA競合、年代・構造・位置のbetween、実メタデータを回帰検証。
- dry-run無更新、既存確定保持、限定取消、取消途中失敗のrollback、取消後の再実行、
  出力作成失敗・DBエラー後の再実行、外部根拠保持を検証。
- `ruff check .`成功、`uv build`でsdist・wheel生成成功。
- テスト専用PostgreSQLクラスタは停止し、データとログを保全した。

## 維持した制約と未対応理由

- 位置判定の建築4km・地形40km、基準点からその半分を使う保守的な範囲は維持した。
  Habitat 67の108件・Sossusvleiの110件は引き続き候補。
  撮影GPSだけでは対象の中心・境界を確定できないため、件数を増やす目的で半径を広げない。
  対象範囲や基準位置の独立した根拠が得られた場合に再検討する。
- 姫路城天守等のカタログ外の固有カテゴリを自動登録する拡張は行わない。
  カテゴリ名だけでは地域・施設全体・別棟の粒度が確認できず、今回3件の修正範囲を越える。
  追加対象も名称・場所・対象粒度を確認して個別キーを定める必要がある。
- 確定subjectは建築9・地形1であり、M3後続の「各10 subject以上」の条件には不足する。
  D15・解析品質ゲート後の採用数ではない。M3全体の有用性達成とは区別する。

実行・保存契約の正本は[設計 M3-A](../../docs/design.md)と[スキーマ](../../docs/schema.md)。
