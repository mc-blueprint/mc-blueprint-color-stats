# Issue #105 訂正v2

2026-11-05、`4d9dcdb`起点。P2のUTC・撮影日・全組合せ不足と、先行推定の固定化を修正した。
初回#105・#104・M3のsnapshot/runは履歴として維持した。新規の外部API照会は行っていない。

## 訂正範囲と規則

所有元は初回#105のscene run `a1b2b69c-b063-4083-884c-92d41fee8e52` と
`4fba8d08-18da-40eb-825c-14ebdb90f8ce` に限定した。
成功runと保存計画の一致、属性単位の最初の値・所有run・現在値を照合して全根拠を再評価した。
その前の確定値・他runの値・subject関連付けは変更していない。#105のP17由来region 9件も
保存claimから再確認し、値は同じだった。

- GPS UTCと撮影日時＋時差を両方読める場合はUTCへ変換して照合する。
  丸め幅1秒を超える違いはunknown。GPS取得時刻の遅延を推測で補正しない。
  一方だけならその根拠を使い、片方が不正なら他方を選んで続行しない。
  撮影日時内に含まれる時差も照合する。該当EXIF2件を含め、最終規則の本番再計算は変更0件。
- 日が一意なEXIF/ISO撮影日時だけを受理する。期間・年/月だけ・近似・説明文から
  先頭の日付を抜き出さない。保存日時はsource=exif、またはEXIF撮影日との一致が必要。
  保存metaのDateTimeOriginalは7,315件すべてcommons-desc-pageであり、それだけで撮影日とは
  みなさない。候補日付とEXIFが異なる場合もunknownにする。
- 自分が推定した属性はpreservedで固定せず再評価する。矛盾・根拠不十分ならunknownへ戻す。
- 絵画・描画等の保存カテゴリは実景の撮影属性や地形属性の根拠にしない。

## 本番訂正

dry-runと同一hashの計画を1取引で反映した。581画像の583属性をunknownへ訂正した。
再実行の変更は0。属性の置換・撤回は許可された所有元だけで、旧値・他runの変更は0。

| 属性・理由 | 訂正件数 |
| --- | ---: |
| 季節：撮影日と確認できない保存日時 | 235 |
| 季節：保存候補日とEXIFの不一致 | 71 |
| 季節：期間・不確定・不正日付 | 40 |
| 季節：非写真の描写 | 7 |
| 季節：その他の根拠不足 | 7 |
| 時間帯：UTC二系統の不一致 | 221 |
| 時間帯：カテゴリと太陽高度の矛盾 | 1 |
| 時間帯：太陽高度の境界 | 1 |
| 合計 | 583 |

季節360・時間帯223。前回の2段階処理でpreservedになっていた値の訂正は359件で、
そのうち当時から複数の矛盾する根拠を保存していたものが10件あった。
同じ根拠をまとめて評価する場合と順次得た場合で、自己推定値が固定されない回帰テストを追加した。

## 決定的50画像のカテゴリ監査

カテゴリ起因の150画像からSHA重複を除き、
`sha256("issue105-category-audit-v2:" + image_sha)`順の先頭50件を選んだ。
既存原画像の内部縮小表示、保存済みの名称・説明・カテゴリ・EXIFを照合した。
原画像・監査用縮小画像・個別出典・EXIF台帳は公開記録へ含めていない。

実景写真か、カテゴリが描写対象に当たるか、季節・時間帯が可視情報に明白に反しないか、
保存説明・EXIFと整合するかを確認した。
誤りは3/50（6%）：冬景色の絵画、秋の森林の絵画、nightとされた朝の橋。
薄明とnightの境界が判断できない2件は保留し、正解に数えなかった。
残る45件は目視情報と整合したが、母集団全体の正確性を保証するものではない。
選択seed・入力hash・50件の判定は [category-audit-v2.json](../category-audit-v2.json) に記録した。
この3件は訂正の対象に含まれる。画像ごとの例外を推定器へ追加していない。

## 支持の比較

| 指標 | 前回#105 | 訂正v2 |
| --- | ---: | ---: |
| 適格画像 / SHA代表 / 確定subject | 7,607 / 3,570 / 154 | 同じ |
| wall subject / n_eff | 121 / 27.048481 | 同じ |
| wall 補正率 / 情報なし | 100% / 0% | 同じ |
| tree subject / n_eff | 14 / 9.681382 | 15 / 10.956522 |
| tree 補正率 / 情報なし | 57.14% / 42.86% | 53.33% / 46.67% |
| supported / 全統計行 | 0 / 569 | 0 / 569 |
| 条件4 | failed | passed |

誤推定をunknownに戻したことにより、対象層に両立するsubjectと重みが変わった結果である。
未知の層所属による不確実性はn_effへ含まれず、条件4のpassedを支持改善の保証とみなさない。
直接分布30支持は引き続き不足する。自動reportの条件1・2・6はunverifiedであり、M3全体は未完了。

## 全組合せ不足と収集目標

旧907行には地形relationがなかった。taxonomyの37建築役割・12地形役割を使い、
paletteと異なる2役割の全無向pairを条件別・12目標層別に列挙した。
未観測・未検証も含む15,621行となり、地形relationは726行。
37役割には建築の親グループ、12地形役割にはtree和集合を含む。

[前回版を新方式で測った不足](deficits-before.json) と [訂正後](deficits-after.json) は
ともに15,621行。重複を許す原因分類は両方とも属性不足5,320、subject不足15,615、
部位不足15,547、権利除外0。個別の支持数・n_eff・10/30までの不足値は各行に記録した。
閾値を下回る行の件数が同じでも、支持値が同じという意味ではない。

訂正後の主要役割（wall/tree）の30支持不足に従って残枠を再配分した。
既存の意図層画像数を5枚単位で切り上げた床を確保し、残枠を不足に比例配分した。
subject所属質量・役割のsubject/n_effが10未満の層を優先度1、30以上を優先度3とした。
部位名はwindow→window_frame/window_glass、rock→rock_face/rock_scree等、実taxonomy名へ揃えた。

総枠10,000枚、集中上限、統計のsubjects比率は不変。
中国住宅955・山岳925・平原885・砂漠935・雪景935・秋の森林755枚などとし、
LoC・Mapillary・Commonsへの対応付けは保持した。
各層のsupport_gapに不足subject・n_eff・未検証pair数を付けた。
未検証部位の不足は画像追加だけで解決せず、部位評価の改善も必要である。
[target-plan.json](target-plan.json) と [再生成スクリプト](../regenerate_targets_v2.py) が根拠となる。

## 保全・生成物

- 書込み前の新規完全pg_dump：
  `/mnt/data/work/issue-105/correction-v2/backup-20261105T105632Z/colorstats.dump`。
- 584,150,971 bytes、SHA-256
  `148715c6abc1516acdf451389b5a879ca5f73925fc38e40c268833cf295ed34d`。
  pg_restore目録・全SQLストリーム読取り成功、復元・上書き・削除なし。
- 訂正run：`58deac3d-192c-44d7-98d1-73c1547407e1`。
- 新snapshot：`a8384373192d930df952190433d5d346393549b87c941ef157ea93380c714864`。
- 新rule_stat run：`4dbbc2aa-d8a2-44cb-8764-0036837a9063`。
- 新job：`d9057e08-b86e-478f-a0c3-ab87be572539`。
- 正本：`/mnt/data/derived/stats/issue105-corrected-20261105T105836Z`。
- dry-run・apply・repeat・実行コード・個別根拠は `/mnt/data/work/issue-105/correction-v2/` に保全。
- 元subject・関連付け・source・原asset情報、M3・#104・前回#105のsnapshot/runのhashは不変。
- provenance・regions・observations・relations・groupsの5 Parquetは前回#105と完全一致。
- 新統計569行・10,715入力辺は固定計算と全量一致。

本番の比較・冪等・保全は [comparison.json](comparison.json)、
[preserved-before.json](preserved-before.json)、[preserved-final.json](preserved-final.json) に記録した。
snapshotはread only / repeatable read。収集・pilot・サービス・環境構築は行っていない。

## 検証と残り

WSL `wsl -d Ubuntu-24.04`、ext4一時コピー、Python 3.12.3・専用PostgreSQL 16で検証した。
UTC二系統・単一根拠、不確定日付、後から判明した矛盾、他runの保護、訂正の冪等、
全taxonomy pairと地形relation、収集部位名の回帰を含む。
最終のruff・全pytest（896 passed / 1 skipped）・sdist/wheel buildは
[verification.json](verification.json) に記録した。src・configs・tests・taxonomyは検証コピーとバイト一致。
本番で実際に生成したコード版・hashは [implementation.json](implementation.json) に固定し、
その後に再生成した収集枠を含む最終検証版と区別した。
専用DB・起動した本番処理は終了し、バックグラウンド処理は残していない。

反証指摘の修正・本番訂正・新規集計と収集目標の再生成は完了。
支持不足、未知属性、未検証部位、M3条件1・2・6の別途確認は残る。
push・PR作成は行わない。#90の後続4commitは未統合で、変更ファイルの重複はない。
