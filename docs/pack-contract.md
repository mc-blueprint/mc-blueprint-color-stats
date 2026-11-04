# M4向け配布契約

Issue #87のD15-v2をM4パックビルダーへ接続するための契約。ビルダー自体はM4の対象とする。
入力は適格openまたは確認済みanalysis_onlyから得た非表現的統計に限る。
モデル重みはopen必須。NC/academic/restricted・不明・利用停止・根拠失効は除外し件数を残す。

配布物は次のallowlistから新規生成し、内部artifactをコピーして作らない。

- 配色データ：集計色分布・比率・共起と必要な品質フラグ。原画像の表現を再構成するデータを含めない。
- 最小provenance：provider別件数、適用方針版、除外理由別件数、ビルド版。
- 条件上必要な最小限の帰属・通知。帰属不要なら作者・個別URLは配布しない。
- DATA_LICENSE：生成配色データに適用するMIT本文。元写真をMITと表示しない。

原本・取得縮小画像・切抜き・テクスチャ・座標マスク・CVAT画像/注釈/manifest/ZIP・内部snapshot、
source/asset/runの詳細、座標・自由文・検索履歴・署名URLは配布入力と区別し、混入時はビルドを失敗させる。
新規統計利用停止は削除要求受付時に反映する。内部入力索引と削除・除外台帳を使い再ビルド可能にする。
原画像の期限清掃だけでは完成済みの非表現的統計を一律失効させない。

M4の必須回帰は同じD15ゲート、NC重み・根拠欠落の拒否、画像・マスク・個別追跡情報の混入拒否、
必要最小帰属、失効後の再ビルド。

#88の受け口は`colorstats.pack_boundary.validate_public(payload, session=..., selection=...)`。
固定キーの数値統計・provider別件数・policy/build版・MIT識別子だけを許可し、未知キーや
自由文・画像・個別追跡情報を拒否する。`tests/test_retention.py`のPUBLICと混入fixtureを
M4の回帰に引き継ぐ。selectionは非公開の依存索引とし、受付と同じDBロック内で
現行停止台帳を確認して公開を確定する。実ビルダーの接続と必要帰属の公開schemaはM4で行う。
必要帰属がある候補はschema確定まで保留する。
目的・保持期間・GitHub Issue窓口と管理手順は[保持・削除](retention.md)を参照する。
