# Issue #104 再評価の記録

2026-11-05。担当は `feature/issue-104`、起点は `73d3c3d`。
本番対象は ubuntu-2 の固定M3コホート7,607件。新規収集・segment・colorは実行しない。

## 実装と対象

既存の `collect.policy`・`rights.analysis_review_reasons`・D15ゲートを再利用する。
再評価は `stats.reassess.execute`、本番用入口は `production.py`。
元licenseの完全一致、取得根拠、利用停止、既存確認情報との不一致を検査し、
READ ONLY計画のhashが一致した場合だけ、単一取引で区分と未設定の確認情報を追加する。
元license・URL・作者・日時・元quality・取得時設定・解析runは保持する。
旧画像には `retention_until` と保持台帳を追加しない。既存アーカイブを保持する。

Commonsで現れたSA表記5種類だけを設定へ追加した。
Openverseは固定コホートに0件。実測されていない短縮表記の許可は追加しない。
再評価実装は照合済みの元Commonsだけを受け、NC・未知表記・根拠欠落を除外する。
rights_reviewの根拠はIssue本文のユーザー判断。指定どおり外部再照会はしていない。
source_policyの変更は解析専用の許可表記と確認根拠一式で、hosts・レート・既存open表記は変更していない。

## 本番READ ONLY dry-run

正本：ubuntu-2 `/mnt/data/work/issue-104/results/dry-before.json`。
保存済みコピー：[dry-before.json](dry-before.json)。
選択は旧M3 artifactの `selection.json` をそのまま使用した。

| 区分 | 保存済み区分 | 再評価計画 |
| --- | ---: | ---: |
| open | 7,607 | 3,076 |
| analysis_only | 0 | 4,531 |
| NC / academic / restricted | 0 | 0 |
| 合計 | 7,607 | 7,607 |

除外理由はNC 0・根拠欠落0・未知表記0・その他0。変更予定4,531件。
[入力runの事前監査](input-runs-before.json)で選択済み22,809件をREAD ONLY照合し、
画像の解析入力22,808件はopen、残り1件は明示選択した属性根拠である。
NC・評価用・未知重みは0件。属性根拠を画像モデルの制約と混同しない。
これは区分の再評価であり、解析の有無・SHA重複・subject支持を適用したsnapshot適格数とは異なる。
DB全体7,626件と固定コホート7,607件を混同しない。
DB全体のSA4,542件に対し、対象コホートのSAは4,531件である。

## 旧版の事前監査

[old-snapshot-before.json](old-snapshot-before.json)で旧snapshotの全7 Parquetのhashを照合済み。
[old-db-before.json](old-db-before.json)で旧runの全569行・入力辺4,856件をREAD ONLY照合済み。
旧snapshot IDは `3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702`、
旧runは `d7297e42-3b35-49e2-a0f8-903809a9af59`。
登録行集合hashは `c5ed183f453fdcc4501a13654e2605cad08a12312cd730ed7b401cbba4b024dd`。

| 指標 | 旧版 | 新版 |
| --- | ---: | --- |
| D15適格画像 | 3,076 | 未作成 |
| SHA代表画像 | 1,618 | 未作成 |
| 適格確定subject | 37 | 未作成 |
| wall 採用subject / n_eff | 20 / 17.824331 | 未作成 |
| tree 採用subject / n_eff | 7 / 7 | 未作成 |
| supported / unsupported | 0 / 569 | 未作成 |
| M3条件4 | failed | 未判定 |

## 本番書込みの開始条件と残作業

1. #89のPRがdevelopへmerge済みであることを `gh pr list` で確認し、担当ブランチへmergeする。
2. 本番schemaは0005。#87の0006と#88の0007が必要。
   0007はsnapshotの停止・保持照会に必須だが、既存画像を台帳へ登録しない。
   migration適用と既存区分列への限定更新の確認は回答待ち。
3. 統合後のコードでdry-runを更新・保存し、同じhashで `production.py apply` を実行する。
   再実行で変更0件・同じhashを確認する。
4. 旧selectionで既存snapshot CLIを実行し、新しい未使用ディレクトリへ保存する。
   品質設定・解析run・属性根拠は旧M3と同じものを指定する。
5. `bench/issue75/production.py` のdry/registerで新しいrule_stat runを登録し、
   既存report CLIで条件1〜6を再判定する。旧版の監査を再実行してhash不変を照合する。
6. 比較値・新ID・テスト・公開文面を確定する。push・PR作成は行わない。

新snapshot・rule_statは未作成。本番区分更新・migration・アーカイブ操作は未実行。
条件4・条件6を達成扱いにしない。

## 検証と反証

- WSL Ubuntu 24.04、Python 3.12.3、専用PostgreSQL 16、クライアントも同じWSL環境。
- ruff check .、sdist/wheel build、wheelのインストール：成功。外部通信なし。
- 最終全pytest：845 passed / 1 skipped、163.52秒。skipは既存の明示GPUテストのみ。
  Matplotlib任意APIの警告1件は既存依存によるもの。
- READ ONLYで不変、計画不一致の拒否、冪等再実行で変更0件、元quality・出典保持、
  NC・根拠欠落・未知表記・停止・確認不一致・非Commons元ソースの除外を検証した。
- 再評価後の新版snapshotだけがSAを追加採用し、旧snapshotの全hashを維持するDB回帰に成功。
- 配布allowlistへ実assetの原meta・画像・個別出典を混入すると拒否されることを確認した。
- SA設定変更に伴う収集テストの期待値を更新し、計測回帰では旧D15と解析専用を両方保持した。
  collect/http.py・measurement.py・docs/collect.md・#89のhosts/レートは変更していない。
- 初回のruff行長、テスト用PGのroot起動、wheel未インストール、依存配置、再利用DBの管理表残存を
  修正した。失敗を成功扱いせず、毎回新規DBを使用した上記の最終全件結果を正とする。
- 検証コード・venv・DB：`/tmp/colorstats-issue104/`。専用PGは正常停止済み。
  本番再評価・新snapshot・新rule_statの実測検証は開始条件待ちで未実行。
