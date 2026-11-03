# design.md §12 追記案（第1段階・未統合）

report(snapshot, snapshot_id, statistics, settings)はDB・元画像へ接続せず、
snapshotと登録対象統計JSONの同一性を検証して偏り報告を返す。
snapshot-v1・既存DuckDB／SQLAlchemy・標準ライブラリ・既存属性一致を利用し、
新しい依存や保存形式、共有APIの変更はない。
改変・別設定／別snapshotの統計はValueError。CLIは失敗時に終了コード1を返す。
出力ディレクトリは新規のみ。書込み失敗時の部分出力は再利用しない。
成功表示がなく、JSONとMarkdownが揃わない出力は完成レポートとして扱わない。

M3条件1〜6をそれぞれpassed／failed／unverifiedで表示する。
条件3はhash検証と#75の再計算一致を確認する。条件5は全対象層に加えて
層・条件と役割別のD15前後支持を確認し、和集合色等の根拠が不足すればunverifiedとする。
条件4はreal_building・real_terrain各1役割以上でモデル品質が検証済み、
直接観測の確定subject数>=10かつsubject n_eff>=10を要求する。
#75のdirect_min=30という配布支持ラベルとは異なる内部有用性ゲートであり、
10〜29件でも直接観測の閾値を満たせるが、親からの借用のみでは達成しない。
条件1（#66の固定7,607件の全件・品質・性能監査）、
条件2（#72の再実行・誤結合監査）、条件6（Gへの引継ぎ確認）は
snapshot単独からは証明できないためunverifiedとする。
実データのM3結果報告で対応する監査と引継ぎの根拠を追補し、最終判定する。
m3_completeはこの自動確認の全条件がpassedの場合だけtrueとなり、
本番結果報告による外部確認を勝手に代入しない。

実行例（DB不要、出力は未使用ディレクトリ）:

~~~sh
python -m colorstats.stats.report_cli --snapshot /path/snapshot --snapshot-id <hash> --statistics /path/aggregate.json --config configs/stats.yaml --targets configs/collection_targets.yaml --taxonomy taxonomy --output /path/new-report
~~~

コード版・taxonomy・設定hash・snapshot hash・統計JSON hashを保存する。
同一入力からJSON／Markdownのバイト列を再現する。実行時間は再現対象のJSONと分けて計測する。

## 反証2・3・4への修正

subject属性はcollect.coverage.subject_attributesを再利用し、location→region・eraを含める。
Noneは未知として層照合から外す。同じ正規化属性をweights.assign_strataへ渡し、
適格SHA代表画像の同一subjectの層矛盾をsubject全体の未割当とする。
画像の属性一致件数と採用subject数は別表示し、目標への不足は採用数から算出する。
#75の同時修正も同じ属性読取りへ揃える前提で、同担当ファイルは変更しない。

D15診断は保存済み個別部位色を持つ確定subjectの集合差で計算する。
D15以外の解析不足・SHA重複、未分類、モデル未検証を混同しない。
和集合色が未保存の場合、構成領域の存在を色観測支持へ代用せず、前後数と差をnullにする。
条件5はunverifiedとし、#74にD15除外前の和集合色の診断根拠が必要なことを示す。
