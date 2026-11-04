# Issue #76 第2段階：固定全量レポートとM3判定

2026-11-05 JST。起点3bdde23からorigin/developをmerge。
ローカルmerge commitは `92c4edd2ef7153112f7c903b5470f6e08dd968ec`、競合なし。
完了前に再fetchしdevelop `41dc567575964bdbccbe3e09bd6df4228c9cfebb`を確認、再mergeはAlready up to date。
#77はPR #98として取り込み済み。rebase・reset・force push・push・PR作成は行っていない。
変更のcommitは作成せず、指定の公開文面を用意した。

## 正本と同一性

snapshot: `3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702`。
#74全量snapshotと#75の本番run `d7297e42-3b35-49e2-a0f8-903809a9af59`を使用。
登録済み全569行・入力辺4856件がREAD ONLY / REPEATABLE READで固定JSONに完全一致。
接続時にもdefault_transaction_read_only=onを設定した。[監査結果](db-audit.json)参照。

- [実レポートMarkdown](full-report.md)・[数値とartifact hash](full-summary.json)
- [外部監査を照合したM3判定](m3-assessment.json)・[コード内容hash](implementation.json)
- [G引継ぎ最終版](g-handoff.md)
- JSON正本: ubuntu-2 `/mnt/data/work/issue-76/review-20261104T2011/report-1/report.json`
- Windows複製: `H:/mc-blueprint/artifacts/issue76-full-report-conflict.json`
- 同じLinux環境の2回目はreview-20261104T2011/report-2。JSON/Markdownともcmpでバイト一致。
  JSONは約190 MBで、Gitへは数値要約・hash・再現手順とMarkdownを保存した。

全7607 asset、SHA異なり3575、重複行4032。
D15適格3076→必要解析あり3074→SHA代表1618、適格確定subject37。
層矛盾・対象外を除いた採用subjectは27（建築20・地形7）。
12層の所属質量合計27、目標合計1200、不足合計1173。
両立件数を加算して被覆としない。chinese-houseの所属質量は0。
10万枚目標は1618/100000（不足98382）、1万・3万も未達。

## M3条件判定

| 条件 | 判定 | 根拠 |
| --- | --- | --- |
| 1 | passed | #66/#74の全7607件監査。prep成功7603/失敗4、segment/shade各7603、color成功7601/失敗2、違反0。品質・速度・容量を追跡 |
| 2 | passed | #72/#79の全判定再実行差分0・誤結合検査0、#85のstate/根拠run接続。確定154 subject、候補/未知を別記 |
| 3 | passed | 固定snapshotの全hashと本番Linux再計算一致、DB569行・入力4856辺一致、全量CLI二重実行一致 |
| 4 | failed | wall 20 subject/n_eff17.824331、tree 7/7。treeの10/10未達 |
| 5 | passed | 全12層の不足・未知・D15・未支持、役割別D15前後と集合差を出力 |
| 6 | unverified | G引継ぎ文書は最終化・成果物として提示済み。実際の受領・利用確認は未実施 |

条件1・2は既存本番監査の証跡を照合した判定で、今回本番で解析・再推定を再実行していない。
自動reportは外部証跡を入力しないため条件1・2をunverifiedとする。外部確認後の判定は
m3-assessment.jsonへ分けて保存し、自動reportのバイト列は変更しない。
条件2の同定精度は人手正解による保証ではない。#79の旧確定保護2件の粒度注意も維持する。
M3全体は未完了。条件4の失敗を文書作成・内部ゲートの緩和で解消した扱いにはしない。

| 役割 | D15前の保存色subject | D15後 | 失ったsubject | 主結果subject | n_eff | 補正率 | 情報なし |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| wall | 135 | 30 | 105 | 20 | 17.824331 | 100% | 0% |
| tree | 18 | 7 | 11 | 7 | 7 | 0% | 100% |

率の分母は主結果の採用subject数。**passed は層補正の有効性を意味しない。**
treeはweak_correction。情報なし過半は注意フラグで、passedの追加閾値にはしない。
全569行unsupported、direct/smoothed各0。10/10ゲートと直接分布30/30を混同しない。
wallのstyle未知率100%、building_type95%、region10%、era65%。treeの層属性は全て100%未知。
D15前後の保存色支持と、品質・部分層補正後の採用支持は異なる。

## 実データ接続での変更

- #85のsubject.attribute_evidenceからregion/eraのstateを表示へ接続。
  保存済みstateはasset行分母でregion inferred659、era inferred431。
  subject単位の#85結果129/44とは分母が異なる（719関連画像のうち値ありの画像数）。
- 全量の不要な観測・関係JSON読込みを避け、件数・除外理由をDuckDBで集計。
- 必要解析なしの6件は色支持へ入れない。うち権利除外かつ解析なし4件を
  rights_excluded_without_analysisへ出す。解析のある画像の和集合色欠落は従来通りnull/unverified。
  明示された解析失敗を診断証跡欠落と誤認しない回帰を追加。
- #74追加列に合わせ旧fixtureのINSERTを列名指定へ修正。
- stats/snapshot・aggregate・weights・licenses・coverage、analyze/queueの直接編集なし。

## 実行・検証

- ruff check .、sdist/wheel build: 成功。
- Windows全体: 512 passed / 214 skipped（108.70秒）。最終の解析失敗区別追加後の
  report関連: 33 passed / 1 skipped（37.39秒）。Matplotlib任意API警告1件。
- 反証修正前のLinux/隔離PostgreSQL16.15全体: **726 passed / 1 skipped**（141.79秒）。
  スキップは既存GPU実機テスト。専用port5576・Unix socket、TCP無効、毎回新規DB。
  外部cwdのCLIも最終wheelを使って成功。専用PGは正常停止。
- 初回統合時の同じ全量入力のソース実行35.01秒、外部cwd/DBなし/wheel実行35.18秒。
  最大RSS4565508/4515736 KiB。共有負荷下の1回ずつであり高速化率を主張しない。
- Windowsの本番統計再計算は3行の診断delta_cに浮動小数点末尾差があり、
  reportの完全一致検査が拒否した。[OS間照合](cross-platform.json)へ記録。
  本番と同じLinuxでは完全一致。許容誤差や統計値の改変で回避していない。
- 初回隔離PGは専用起動オプションの不足で5432にbindしようとして失敗。専用socket/portとTCP無効を明示して解消。
  転送不足のfixture/opsと旧venv参照も修正し、最終全体を再実行した。
- #66既存実測: 成功stage累積94478.044秒、成功artifact4544948207 byte。
  snapshot自身は1716504436 byte。DB/WAL増分は並行書込みを含むため単純合算しない。

## 文書と次の手段

docs/design.md §12へ条件4・部分補正数式・report契約、docs/schema.mdへ出力契約、
docs/collection-bias.mdへ#76の偏り定義と#77の12層×2供給元実測・参考外挿を統合した。
#77は145 API/344 HTTP、19 SHA取得・適格8、確定subject0。固定snapshotへは追加していない。

原因はD15適格・解析・SHA代表の確定subject37という支持不足。
次の手段は[マイルストーン#7](https://github.com/mc-blueprint/mc-blueprint-color-stats/milestone/7)
「収集基盤拡張：解析専用入力と転送最適化」のIssue #87〜#94。
新収集・解析・同定後に新snapshotで条件4を再評価する。D15は今回緩めない。
配色パック生成・同梱、G受領、10万枚達成は残る。永続データ削除・本番DB書込み・pilot再開はない。

監査記録は%USERPROFILE%/.codex/logs/commands/に保存。
自動承認審査が接続補助ファイルと設定ファイルの無加工表示を秘密露出リスクで拒否したため、
これらは表示せず、専用READ ONLYコードと名前のみの確認で完了した。


## 反証修正：値なしconflictの保持（2026-11-05）

保存済みstate=conflictは値がなくても維持し、unknownへ置換しない。
全7607 asset行に対しbuilding_typeはinferred461・conflict4・unknown7142、
biome_likeはinferred373・conflict2・unknown7232へ訂正した。
修正前のunknown7146/7234に含まれていた矛盾を分離したものであり、
採用属性・主統計・補正率・役割支持・M3判定を変更していない。
[修正前後の機械照合](conflict-regression.json)ではattribute_states以外の全レポート内容が完全一致した。

- Windows関連pytest: 41 passed / DB1 skipped（72.66秒）。
- 隔離PG16込みLinux関連pytest: 42 passed（18.31秒）、専用PGは正常停止。
- ruff check .、sdist/wheel build: 成功。
- 本番READ ONLY再監査: 569行・入力辺4856件と統計hash不変。
- 値なし/空文字/unknown/既知値のconflictと、inferred/unknown/根拠なしとの8組合せを回帰確認。
- G引継ぎへ「条件2は同定精度保証ではない」「保護した旧確定2画像（Sahimeyama-jinja、1対象）の粒度注意」を追記。
  条件4の補正率・未知率とn_effの限界、passedは補正有効性を意味しない注意は維持した。

修正後の全量再生成は34.50秒／33.48秒、最大RSS4567284／4580672 KiB。
ソース実行と外部cwd・DBなしwheel実行のJSON/Markdownはcmpでバイト一致した。
旧実レポートはstage2-20261104T1944配下とWindowsの旧artifactに保全した。
