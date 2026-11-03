# Issue #79 Commonsカテゴリ・Wikidata対象キーの本番実測

2026-11-03。fetchで確認した起点は `69ebe7cdb81bcf5c5d6d6efed377be4c63b19359`
（#72 merge後）。担当は `feature/issue-79`、
`H:/mc-blueprint/worktrees/colorstats-79/mc-blueprint-color-stats`。
commit・push・PR作成は未実施。継続開始時のローカルorigin/developは起点より2 commit先で、
本作業ではmerge・rebase等を行っていない。

## 完成条件と反証4件

| 対象 | 最終結果 |
| --- | --- |
| P1 対象の粒度 | 道路・街路・建築群・城郭・寺社全体と、P527/P2670の建物部分を意味的に検査。候補に止め、SHA継承からの再確定も抑止 |
| 本番3例の回帰 | df9fa207 → Q20971160、Eihoji Hondo.JPG → Q3049365、Q28233040を公式応答からfixture化。すべて未確定 |
| P2 複数対象カテゴリ | 対象domainの複数物理対象へ結び付くカテゴリをambiguous_categoriesへ保持。単独カテゴリが併存してもmultiple_targetsで抑止 |
| P2 応答欠損 | 各要求カテゴリの正規化・redirect後の応答、各要求QIDを検査。実通信・キャッシュ双方の欠落を失敗にし、DBテストで既存確定とrunの保持を確認 |
| P3 GPS説明 | docs/design.md §12の該当GPS段落だけを実装に合わせて修正 |
| 本番dry-run → 本実行 | 実施。元の#79 run由来だけを取り消し、#72以前の144確定を保持 |
| 再現性・誤結合検査 | 同一入力の全判定一致、offline再実行差分0、独立DB照合0、同名群・SHA競合・不正な新規確定0 |
| テスト・ruff・ビルド | 506 passed / 1 skipped、Windows関連fixture54成功、ruff・sdist・wheel・差分検査成功 |

カテゴリの全主題はcategory_itemsに残す。カメラ等のメタデータ主題は建築・地形の複数対象と区別する。
Commonsがタイトルを伴って明示的missingを返す場合は「応答済み・対象情報なし」であり、
空pages・要求項目の脱落・Wikidata項目のmissingとは区別する。応答脱落を黙って対象なしにしない。

## 最終本番件数

| 項目 | #72 | #79 修正前 | #79 反証修正後 |
| --- | ---: | ---: | ---: |
| 全asset / SHA異なり | 7,607 / 3,575 | 7,607 / 3,575 | 7,607 / 3,575 |
| 確定asset | 144 | 877 | 784 |
| 候補asset | 1,694 | 2,073 | 2,166 |
| 未同定asset | 5,769 | 4,657 | 4,657 |
| 確定SHA異なり | 104 | 441 | 385 |
| 建築の確定対象 | 9 | 184 | 136 |
| 地形の確定対象 | 1 | 18 | 18 |

確定assetの由来は手作業キー144・自動キー640。
建築136対象は手作業9・自動127、地形18対象は手作業1・自動17。
建築は719 asset / 366 SHA、地形は65 asset / 19 SHA。
subject_candidateの根拠は3,595辺で、候補asset数とは区別する。

## 元runに限定した取消と修正過程

対象runは `ac88d4ae-ec77-40a3-8988-8ff31cacbbc4`。
そのrunが新規に付けた733件だけを再評価し、run以前の144件を保護した。
最終差分は **93 asset・48対象の取消、すべて建築**。

| 重複しない主要根拠 | 取消asset | 取消対象 |
| --- | ---: | ---: |
| 道路・街路 | 3 | 3 |
| 複合施設クラス | 2 | 1 |
| 寺社全体クラス | 76 | 39 |
| 別の建物を部分に持つ施設 | 12 | 5 |
| 合計 | 93 | 48 |

QID別件数・対象asset・理由は[audit.json](audit.json)のrevocationsに保存した。
指定例のQ20971160は1件、Q3049365は同じ本堂画像の2件、Q28233040は1件を取り消した。

修正初回の本実行run `70f97262-9160-4974-b064-467b2f3beabd` で106件を取り消した。
その後の点検で、広い構造物クラスをP527/P2670の建物とみなす過剰抑止を確認したため、
建物・建築群のクラスへ絞り、柱・身廊等の建築要素を建物群として数えないよう修正した。
最終実行で13件・4対象を元と同じsubject IDへ復元し、元runとの差分93件・48対象を確定した。
このため最終実行自身のrevoked_assignmentsは0、元runからの最終取消数は93である。
途中run・出力は保全し、元の成功runやスナップショットを書き換えていない。
[production.json](production.json)のreview_historyとverificationに経過を記録する。

#72成功run `b5ad2583-fcb2-4ffe-a43f-ab9028729852` の144確定IDは全件不変。
#72と元#79成功runのparameters・出力参照・設定hash・終了日時・失敗理由・コード版の署名も不変。
旧確定のうちSahimeyama-jinjaの2件・1対象は新しい粒度フラグが付くが、
ユーザーの明示した保護範囲なので取り消していない。保持は新基準への適合保証とは区別する。

## 粒度・根拠と実装の再利用

CommonsAdapter / HttpClientのUser-Agent、min_interval、maxlag、Retry-Afterを再利用。
bot判定回避の変更や新規依存・表・Enum・旧形式の移行は追加していない。
P31/P279でdomainと除外クラスを確認し、P527の部分項目とP2670のクラスを必要な範囲だけ追加取得する。
対象の名前や本番の問題QIDを直接除外する実装ではない。元応答のrevision・クラス・
部分構造・要求hashと応答hashを成功runとsnapshotへ残す。

固有カテゴリ＋名称、または固有対象キー＋P625と撮影GPSの整合が必要。
建築4km・地形40kmの撮影範囲と、その半分の基準距離は維持する。
名称＋固有カテゴリで支持された撮影点を、追加キーやGPSで候補を除外しても範囲検査から捨てない。
既存確定保持・1取引反映・run単位取消・SHA競合・pHash候補は#72を再利用した。
同じQIDは手作業キーとUUIDへ統合し、名称一致だけでは再利用しない。

手作業カテゴリに直接リンクがない4対象は公式項目の名称・P373・P625を確認してQIDを明示済み
（Strasbourg Q745460、León Q175874、Münster Q708532、Dülmen Q348707）。
一般カテゴリから親を探索して対象へ昇格させる処理はない。

## 実行・計測と保存先

最終成功run: `7edc8dde-03b5-4b0a-8892-c497c1ba1fda`。
コード内容版: `69ebe7c+i79-review-4e3387e85b4a7a81`。
内容版はsrc/colorstats/stats/*.pyとconfigs/subject_rules.yamlをパス順に並べ、
パス文字列と内容をSHA-256へ投入した先頭16桁。
設定hash: `a1320336eb21a6b458dd3b90eaff67dc8a974f0533a8f639a32deb55be7e5423`。

| 実行 | 秒 |
| --- | ---: |
| 最終カタログoffline生成 | 2.985 |
| 最終dry-run | 106.949 |
| 最終本実行 | 111.834 |
| 最終CLI offline再実行 | 107.770 |

保存カテゴリ9,112件、カタログは手作業12・自動343の355対象。
粒度不適合はcandidate_onlyとして候補に残すため、カタログ件数を確定対象数と解釈しない。
最終規則が参照する取得結果は301要求分で、途中検証を含むキャッシュ387応答を保全した。

ubuntu-2の専用領域 `/mnt/data/work/issue-79/`:

- `code/`: 最終実行コード
- `i79-review-corrected-code.tar.gz`: 最終コードの保全アーカイブ
- `i79-review-corrected-rules.json`: 最終の追加済み規則
- `review-evidence/cache/`: 要求hash別のAPI応答。offlineで再利用
- `results/production/review-corrected-dry-01.json`: 最終dry-run
- `results/production/review-corrected-applied-01.json`: 最終成功snapshot
- `results/production/review-corrected-replay-01.json`: 最終offline再実行
- `results/production/review-corrected-verification.json`: 独立DB照合
- `i79-review-corrected-verify.py`: 接続情報を表示しない読み取り専用の照合スクリプト
- `results/production/applied-01.json`: 修正前の元#79 runのsnapshot（不変）

最終snapshotは19,916,128 byte、
SHA-256は `dd1023240edf3a37a23257966433d6e8498f801d116f158e6c2a708713aa723f`。
本番接続はpostgresのpeer認証。認証ファイル・本番接続URIを表示していない。
ubuntu-1のpilotやサービス配備先は変更していない。

## 検証と残存制約

Python 3.12、worktree外venv、#72と同じUbuntu検証venvを使用した。
最終の専用PostgreSQL 16全件pytestは **506 passed / 1 skipped**（76.98秒）。
スキップは既存GPUテスト。Windowsのsubject関連fixture54件も成功。
ruff check .、python -m buildによるsdist・wheel、git diff --checkが成功。
専用PostgreSQLは停止し、データ・ログを保全した。

独立照合でdry-runと本実行の全assets判定が一致し、offline再実行の
状態・subject・属性・候補IDの差分0件。全7,607件のDB subjectと成功run参照も一致した。
元の2成功runの署名は不変、取消は元#79 runが新規に付けた範囲だけ、
復元13件はその途中取消から元の同じsubjectへ戻ったものだけと確認した。
本番3例はすべて未確定。#41の6群13枚は同じIDを保持し、異なる名称群の結合0件。
抜き取り根拠と検査の正本は[audit.json](audit.json)・[regression.json](regression.json)。

preferred座標が一つでも通常rankの有効P625が併存する5項目は今回も除外を維持した。
preferredというランクだけでは、他座標が同じ対象・粒度・時点を指すかを確認できず、
通常座標を捨てても同一性を緩めない根拠が不足するためである。
全座標の用途・粒度・時点を一次根拠で確認できた場合に再検討する。

メタデータとWikidataの誤り・欠損、画像が主対象を十分写すかは別の品質課題として残る。
今回の建築136・地形18はD15・役割品質ゲート前の値で、役割別n_effは未計測。
#76へ最終到達数と旧確定2件の粒度フラグを引き渡し、M3完成条件4の達成とは扱わない。
保存契約は[docs/schema.md](../../docs/schema.md)のIssue #79節、
GPS説明は[docs/design.md](../../docs/design.md) §12へ反映済み。
