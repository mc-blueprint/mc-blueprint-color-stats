# 建物正面の支配色 v3

壁の画素を厳密に切り出す方式から独立させ、建物正面の最大面積の色クラスタを
壁の観測色として返す。旧領域policy・旧評価・既存の色stageは変更しない。
色のまとまりを推定するものであり、可視壁mask・材質色・照明補正値ではない。

`colorstats.analyze.dominant_wall.estimate(image, front, clusters=K)`を使う。
`front`は画像と同寸のbool mask。正面の入力元とKは固定された評価・設定に従って
呼出し側が渡す。正解maskで正面を作らず、空の場合に画像全体等へfallbackしない。

既存`color.extract_colors`のOpenCV k-means++・OKLab変換を再利用する。
seed0、1試行、100反復以内、epsilon1e-6。不透明画素は黒白も含める。
元の色stageの黒白除外は既定で有効のまま。
最大クラスタの画素平均を`color=[L,a,b]`、面積比を`dominant_area_ratio`、
実クラスタ数を`cluster_count`、正面の有効画素数を`front_pixels`として返す。

正面なし、不透明画素なし、最大クラスタが同面積の場合は`color=None`と
`missing_reason`を返す。色差や面積を0として成功扱いしない。
入力画像・maskは変更せず、不正な寸法・dtype・Kは例外にする。
結果を保存するときはVERSION、正面の由来、K、入力SHAと同じrunの参照を付け、
旧Region/role maskの観測として再解釈しない。

評価は[支配色v3の事前設計](../bench/issue130/dominant-plan.md)を参照。
GTの壁画素平均と画像別ΔOKを比較し、確認用の中央値<=0.02・欠測率<=20%を要求する。
p90は報告するが追加の合格条件にはしない。既知公開GTの結果を所有画像の独立保証へ拡張しない。
本番DB・統計・既存default設定は、このAPI追加だけでは更新しない。

[固定評価結果](../bench/issue130/dominant-v3-results.md)は色差基準未達。
調整で選ばれたraw壁候補union＋K=2も本番採用済みの設定とは扱わない。
