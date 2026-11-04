# Issue #75 全量snapshotの統計登録

2026-11-05（JST）。#75基準b16dd69へorigin/develop
66cdbdf50c1d9097956d6506d0d199f019f98156（#74 PR #96）をmerge。
競合なし。rebase・reset・force pushは行っていない。
内容版は `b16dd69+develop66cdbdf+issue75-stage2-fbcb8e2749ad4d16`。
全srcの内容hashを[implementation.json](implementation.json)に固定した。

## 入力・不変artifact

- snapshot ID: `3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702`
- 正本: ubuntu-2 `/mnt/data/derived/stats/issue74-full-20261104T180829Z/snapshot`
- 入力監査: [#74全量検証](../issue74/full-results.md)。
  全7,607 asset、D15・解析・SHA代表1,618画像、確定subject37。
- 集計成果物root: `/mnt/data/derived/stats/issue75-full-20261104T190400Z`
- 登録された不変JSON: `/mnt/data/derived/stats/issue75-full-20261104T190400Z/.output-8ecaa23e-f587-40b1-a5a9-9f4281534e1b-0df4251c-5c1f-4a07-bc99-145dfa6e4d91/statistics.json`
- 同rootのdry-1.json・dry-2.json・dry-summary.json・registration.json・implementation.jsonを保持。
  sourceは `/mnt/data/work/issue-75/stage2-20261104T190400Z/code`。
- #77共用DBへ負荷をかけないよう、nice 19 / ionice c3 / CPU一スレッド。
  dry-runはDBへ接続せず、登録前の再計算もDB取引外で行った。

## 登録と再実行監査

- job ID: `86312097-f9fa-4635-8c52-9eae982f75fd`
- run ID: `d7297e42-3b35-49e2-a0f8-903809a9af59`、aggregate-v2、license_class=open、attempts=1。
- rule_stat登録: **569行**。既存rule_statは0行。
  既存行の削除・更新、スキーマ変更はしていない。
- supported（directまたはsmoothed）: **0**、
  unsupported: **569**。
- 入力辺: **4856件**。
  #85の属性根拠run `80f5dbf3-f7b7-4115-bbcd-a3a4b81087a5` も保持。
- 全入力runの成功・設定・コード・モデル・制約・入力辺を256件ずつ照合。
  #85として明示された属性根拠だけを画像の制約と区別し、
  解析のrestrictedや別methodへの例外は設けていない。
- 同じQueue.completeを再度呼んでも同じrunを返し、登録callbackは再実行されなかった。
  同じCLI/payloadを再投入しても同じjob・run・attempts・行数・入力辺を維持した。
- 2回のREAD ONLY / REPEATABLE READ監査で、DBの全569行を
  固定計算結果と照合し、信頼区間がSQL NULLであることも確認。
- 登録統計の正規JSON hash（行集合）:
  `c5ed183f453fdcc4501a13654e2605cad08a12312cd730ed7b401cbba4b024dd`

数値の正本は[full-summary.json](full-summary.json)。
全条件・役割/pairのsubject数、n_eff、sample_count、重み、状態、
補正率・情報なし割合・属性別未知率をsupport配列へ保存した。
dry-run二重計算も一致（全結果hashは[full-dry-summary.json](full-dry-summary.json)）。

## M3条件4に関係する実測値

| domain/役割 | SHA画像 | 採用subject | n_eff | 総重み | 補正率 | 情報なし | 欠損目標質量 | 10/10役割ゲート |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| real_building/wall | 48 | 20 | 17.824331 | 17.142857 | 100.0% | 0.0% | 0.142857 | passed |
| real_terrain/tree | 7 | 7 | 7.000000 | 7.000000 | 0.0% | 100.0% | 0.000000 | failed |

**M3条件4は未達**。treeは7 subjectで10に届かない。
wallの元union subject30のうち20を採用し、10は属性矛盾・対象外として未割当に残る。
建築の属性未知率はstyle 100%・building_type 95%・region 10%・era 65%。
地形のbiome_like・season・time_of_dayはすべて100%未知。

30/30の直接分布閾値は別の条件であり、今回の主分布は全569行unsupported。
実測分布はdiagnostics.raw等に残すが、主分布を0色で埋めず、使える直接統計と称しない。
wallの10/10ゲートpassedは親から借用した数ではなく、実測subject/n_effによる。
補正率100%でもstyleが判明した意味ではない。
treeの目標被覆1も、全層両立の所属質量に由来するため、層属性の観測が揃った意味ではない。
n_effはsubject重みの集中度であり、未知の層所属・欠測の偏りの不確実性を含まない。
条件4・G引継ぎには補正率・情報なし割合・未知率を併記し、閾値を追加・緩和しない。

## 修正・検証

- #85のstate・根拠runをsnapshot→aggregate→processing_run_inputへ接続。
  inferredは品質フラグに反映し、支持の解釈をJSON・run.parameters・schemaに明記。
- 全量dry-runで独立shade参照によるKeyErrorを検出（本番DB書込み前）。
  選択記録の独立shade noneを解析入力根と誤認しないよう修正。
  実際にcolor入力辺にあるshadeは維持する両条件を回帰テストに追加した。
- docs/schema.mdのrule_stat節を統合し、#74の新列・#85根拠接続と整合させた。
- ruff check .・sdist/wheelビルド: 成功。
- Windows全体: 471 passed / 192 skipped（73.31秒）。
  shade接続修正後の最終集計fixture: 28 passed（39.35秒）。
- 隔離PostgreSQL 16の最終全体: **664 passed / 1 skipped**（111.22秒）。
  1 skipは既存GPU実機テスト。#85 metadata/解析制約の境界、
  リース喪失・rollback・二重登録の回帰も含む。
- 専用PG16は正常停止。#77・ubuntu-1 pilot・本番サービスは操作していない。

dry-runは18.534秒・17.671秒、二重計算と記録を含む全体37.153秒。
登録・再計算・二重完了/再投入・DB監査の全体は25.202秒。
本番での全量snapshot再生成は行っていない。

## 残存事項

#75の登録・検証・公開準備は完了。push・PR作成・merge・Issue closeは行っていない。
#76の最終報告・条件4の未達/G引継ぎと、支持不足の扱いを後続へ渡す。
D15・品質ゲートを緩めたり、既存データを削除して達成扱いにはしない。
