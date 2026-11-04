# G 引継ぎ：M3固定統計と支持不足（2026-11-05）

本書はG担当へ渡す最終成果物。受領確認・Gでの利用・配色パック生成は未実施である。
M3全体は未完了。条件4はfailed、条件6は受領未確認のためunverifiedとする。
[完成条件判定](m3-assessment.json)・[実レポート](full-report.md)・[数値正本](full-summary.json)を併せて確認する。

## 固定入力と統計

- snapshot: `3e785e67c42f02a174c85a6f54e2c081447c8c784c912ee3b4c5e7a94cb45702`
- ubuntu-2: `/mnt/data/derived/stats/issue74-full-20261104T180829Z/snapshot`
- rule_stat run: `d7297e42-3b35-49e2-a0f8-903809a9af59`、aggregate-v2、569行。
- 登録行集合hash: `c5ed183f453fdcc4501a13654e2605cad08a12312cd730ed7b401cbba4b024dd`
- 元統計: `/mnt/data/derived/stats/issue75-full-20261104T190400Z/dry-1.json`。
  DB全569行・入力辺4856件をREAD ONLYで照合済み。[監査](db-audit.json)参照。
- 全量レポートJSONとMarkdownの場所・SHA-256はfull-summary.jsonへ固定。
  JSONは約190 MBのためGitへ複製せず、Windows artifactとubuntu-2の専用領域に保全した。

## 有用性と未達

| domain/役割 | 採用subject | n_eff | 補正率 | 情報なし割合 | 条件4の役割ゲート |
| --- | ---: | ---: | ---: | ---: | --- |
| real_building/wall | 20 | 17.824331 | 100% | 0% | passed |
| real_terrain/tree | 7 | 7 | 0% | 100% | failed / weak_correction |

率の分母は各行の採用subject数。**passed は層補正の有効性を意味しない。**
補正率は両立層を絞り込めた割合で、精度・改善率ではない。情報なし割合>0.5は注意フラグであり、
passedへの追加閾値にはしない。n_effは重みの集中度で、未知属性や欠測偏りの不確実性を含まない。
wallの未知率はstyle 100%、building_type 95%、region 10%、era 65%。
treeのbiome_like・season・time_of_dayは各100%未知。
unknownを検索意図・候補・他画像の撮影条件で埋めない。
全7607 asset行の保存stateではbuilding_typeにconflict4件、biome_likeにconflict2件がある。
値なしでもconflictをunknownへ置換せず、主結果の未知率とは分母・用途を分ける。

全569行unsupported（direct 0 / smoothed 0）。10/10の内部ゲートと30/30の直接分布閾値は別。
diagnostics.raw等を利用可能な主分布として代用せず、unsupportedの主分布を0色で埋めない。
親のCDFを借用しても観測subject数・n_effは増えない。

原因はD15・解析・SHA代表後の確定subjectが37件しかないことにある。
主統計の層矛盾・対象外除外後は27件（建築20・地形7）。
条件2のpassedは再実行・根拠追跡・矛盾検出の確認であり、同定精度の保証ではない。
#79で保護した旧確定2画像（Sahimeyama-jinja、1対象）の粒度注意も維持する。
旧確定の保持を、新しい粒度基準への適合と解釈しない。
wallの保存色支持はD15前135→後30（105減）、treeは18→7（11減）。
D15前後の保存色支持と、品質・部分層補正後の主結果は別の分母である。
必要解析の失敗6件も保持し、色の支持へ入れていない。
適格SHA画像1618枚で、1万・3万・10万の段階目標は未達（10万まで98382枚不足）。

## 分布と権利の契約

分布は既知属性によるsubject部分層補正の**外観色**であり、材質色や母集団への無偏推定ではない。
既知値と両立する層へ目標qに比例した所属質量m_shを配り、W_sとsubject基準n_effを使用する。
層の両立subject数は重複し得る。被覆・不足はm_shの和で読む。
色はOKLab、Δhはdegree、relation差はB-A、面積比はB/A。
domain、条件、役割/pair、親・λ、欠損目標質量、high_weight、感度を一緒に引き継ぐ。

D15のSA/NC/ND・由来未確認・非open重み等の除外を維持した。
出典URL・作者・帰属の正本はsnapshotのprovenance.parquet。
#85の属性根拠runのrestricted値を画像のD15条件へ伝播させない。
画像・分布の再配布許諾、DATA_LICENSE、パックスキーマ・同梱判断はG側で別途確認する。
Gのスキーマや配色選択APIを本レポートで先取りしない。

## 次の手段

[新マイルストーン #7「収集基盤拡張：解析専用入力と転送最適化」](https://github.com/mc-blueprint/mc-blueprint-color-stats/milestone/7)
のIssue #87〜#94へ引き継ぐ。解析専用入力と転送経路の拡張は次の設計・実装で行い、
今回のD15・固定snapshot・統計の閾値を遡って緩めない。
ユーザー決定の初期ソースLoC＋Mapillary、Openverse登録クライアント、保持期間の契約は次マイルストーンの正本に従う。

#77は145 API要求・344 HTTP要求で19 SHA取得、D15適格新規SHA8、取得byte186623050。
取得分の根拠付き確定subjectは0で、追加解析・同定は未実施。今回の固定snapshotにも足していない。
[追加収集の実測](../issue77/stage2-results.md)にある枠・停止理由・外挿の限界を維持する。
支持の拡大後は新しいsnapshot→rule_stat→偏りレポートの順で再評価する。
Gの受領と利用可否の判断後に条件6を更新する。条件4の再判定には新しい実データが必要。
