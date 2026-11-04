# Issue #74 全量snapshotの検証

2026-11-05（JST）。最新develop `a6c1bff`（#66、PR #95）を
`feature/issue-74` へ取り込み、merge commitは `0b2a5af`。競合なし。
#85の属性根拠接続とschema統合は既存commit `640634a` を継承した。

## 不変artifact

- snapshot ID: `3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702`
- 正本: ubuntu-2 `/mnt/data/derived/stats/issue74-full-20261104T180829Z/snapshot`
- Windows複製: `H:/mc-blueprint/artifacts/issue74-full-20261104T180829Z/snapshot`
- 内容版: `0b2a5af+i74-stage2-6974ac5a11728555`。親ディレクトリの
  `implementation.json` に生成時のsrc各ファイルのSHA-256を固定した。
- 7 Parquet、manifest、executionの合計は1,716,504,436 byte。
  画像は含まない。既存artifactの削除・上書きは行っていない。

件数・ファイルhash・選択hash・監査結果の正本は
[full-summary.json](full-summary.json)。生成用コードと実行補助は
`/mnt/data/work/issue-74/stage2/` に保全した。

## 入力と一貫読取り

#66の固定7,607 assetと、成功prepを指定する既存
`/mnt/data/work/issue-66/production-v2/manifest.json` を使った。
暗黙の最新run選択は行わず、次の固定reportの成功job/run集合を照合して選択した。

- `/mnt/data/work/issue-66/production-v2/final-report-20261105.json`
- `/mnt/data/work/issue-66/retry-3713/final-report-20261105.json`
- `/mnt/data/derived/issue66-workers-20261104/ubuntu1-final-report.json`
- 同ディレクトリの `ubuntu1-smoke-final-report.json`、`ubuntu2-final-report.json`

各reportのviolationsと未終了attemptは0。選択・元report・コホートのhashは
artifact親の `selection.json` に固定し、照合済みコピー6件を
`input-evidence/` に保存した。成功runはstageごとに次の件数。

| stage | 成功 | 最終失敗 |
| --- | ---: | ---: |
| prep | 7,603 | 4 |
| segment | 7,603 | 0 |
| shade | 7,603 | 0 |
| color | 7,601 | 2 |

prep失敗はDecompressionBombError 2、SVGのUnidentifiedImageError 1、
math domain error 1。color失敗2件は有効画素なし。
失敗理由と選択をassets.data.selectionにも残し、失敗6件の適格観測・関係・union寄与は0。
回復済みの旧segment失敗や未claimの旧batch jobを最終失敗として重複計上しない。

本番接続はdefault_transaction_read_onlyをonにし、
snapshot自身のREPEATABLE READ / READ ONLY取引で12照会、読取り151.955秒。
取引snapshotは `168489:168489:`、read_only=on、isolation=repeatable read。
取引・接続を閉じてから集合結合とunion色抽出を実行した。
全生成1,499.767秒（約25分）、nice 19 / ionice c3、GPU不使用。
processing_run・job等のDB登録や本番書込みはなく、永続化はファイルだけである。

runs.parquetはprep 7,603・segment 7,603・color 7,601・subject 2の22,809行。
shade noneの独立runはpalette色の入力連鎖ではないため採用runへ含めず、
成功7,603件の根拠はselectionと#66 reportに保持した。

## ゲート・件数・帰属の照合

| 段階 | asset数 |
| --- | ---: |
| 全入力・全出典を保持 | 7,607 |
| SHA異なり（全入力） | 3,575 |
| D15適格 | 3,076 |
| D15適格かつ必要解析あり | 3,074 |
| SHA代表 | 1,618 |
| 採用入力の確定subject | 37 |

除外理由は重複を許す。SA等の条件付き表記4,531件に
license_conditionsとlicense_not_allowedが付く。
missing_attribution 23、missing_analysis 6、sha_duplicate 1,456。
理由別件数の合計を除外画像数として扱わない。

領域217,465、部位観測1,086,712、関係3,348,707は#66の固定report合計と一致。
全体色観測38,005を加え、観測は1,124,717行。適格な個別観測3,655・関係167。
UUID文字列最小のSHA代表、画像と観測の権利・品質判定、採用出典のURL・帰属を
DBなしで再照合し、違反はすべて0。

| union | D15前 | D15後 | SHA代表後 | SHA代表後subject |
| --- | ---: | ---: | ---: | ---: |
| real_building/wall | 4,357 | 1,555 | 869 | 30 |
| real_terrain/tree | 3,047 | 1,435 | 704 | 7 |

unionは7,404行、うち適格1,573行。D15前の色と除外理由も保持している。
このsubject数だけで条件別n_effやM3全体の達成を判定しない。

## 属性根拠とライセンス表記

属性run `80f5dbf3-f7b7-4115-bbcd-a3a4b81087a5` を明示選択し、
manifest.input_run_idsとruns.parquetへ含めた。
719画像・136 subjectにstate・理由・値・完全claim・元値/更新後値・run・設定hash・
根拠JSON hashを保持し、同一subjectの根拠も一致した。
固有subjectではregionのinferred 129 / unknown 7、eraのinferred 44 / unknown 92で、
#85の記録と一致する。

属性根拠runのrestricted固定値を画像のD15判定へ伝播させない。
接続画像中の権利適格147件を維持し、画像・解析モデル由来の既存制約は維持した。
licenses.pyと#85の固定値は変更していない。

#77の引継ぎに合わせ、照合済みOpenverseのby/by-saだけを、元ライセンス一致と
照合済みmetadataの版に基づいて判定時に正規化する。
未照合・版欠損・不一致は許可せず、SAは引き続き除外する。
元quality・出典を変更せず、assets.data.d15_licenseに判定表記を保持する。
今回の7,607件はすべて版付きCommons表記等で、短縮表記の該当は0件。

## 検証と再実行

- ruff check .、git diff --check: 成功。
- Windows Python 3.12 pytest: 445 passed / 183 skipped。
- 隔離PostgreSQL 16（専用socket・port5574、新規DB）pytest: 627 passed / 1 skipped。
  スキップ1件は既存のGPU実機テスト。専用PGは停止済み。
- uv build: sdistとwheel生成成功。
- fixture: SA/NC/評価重み/由来欠損/複数出典/成功run混在、
  hash改変拒否、同一入力hash再現、DB変更後の意味保持を検証済み。
- 属性run接続前後の適格性維持、restricted解析runの除外、
  属性3 stateの根拠・hash再現、短縮ライセンス5条件のDB回帰が成功。
- 全量独立監査: Linux約7.075秒、Windows約6.141秒。
  7 Parquetの全hash・件数・権利・帰属・SHA代表・属性根拠・失敗非算入が全項目一致。
  元DB・画像への接続なし。全量生成そのものの二重実行は行っていない。
  OS間Parquet読書きのfixture照合は[第1段階記録](results.md)を参照。

全量artifactを新たな出力ファイルで再監査する例（PYTHONPATH=srcで実行）:

```sh
python bench/issue74/full-audit.py /mnt/data/derived/stats/issue74-full-20261104T180829Z   --hash 3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702   --output /新規パス/audit.json
```

親ディレクトリのselection.json、input-audit.json、input-evidence/も使用する。
snapshotそのものの検証・再集計には7 Parquetとmanifestだけでよい。
execution.jsonは動的な取引・計測の補助記録で、snapshot IDへ含めない。

## 残存事項

#74の全量生成・完成条件の照合・schema統合・公開準備は完了。
tree unionの採用subjectは7で、M3条件4のsubject 10以上には未達。
n_eff・層補正・条件4の最終判定と不足の引継ぎは#75/#76の範囲であり、
snapshot作成の成功と混同しない。#75/#76/#77のworktreeは変更していない。
ubuntu-1 pilotは未起動。本番DB書込み・サービス再起動なし。
push・PR・Issue closeは行っていない。
