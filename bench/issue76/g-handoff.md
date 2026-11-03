# G 引継ぎ下書き（合成fixtureのみ）

前提: #74 第1段階2ea1ea5、#75 第1段階57178b6。
実snapshotと本番rule_stat登録後に、対象commit・snapshot_id・aggregate run ID・
統計JSON hash・設定hash・artifactパスを記入し、Gと照合する。
第1段階のfixtureは本番の支持を証明しない。

- 分布はsubject事後層化による外観色。材質色や現実母集団への無偏推定ではない。
- OKLab、Δh degree、relation B-A、面積比B/A。役割／pairとdomainを保持する。
- direct／smoothed／unsupportedを保持する。smoothedは親CDF混合で、
  観測subject数・subject基準n_effは増えない。親・λ・欠損目標質量・品質フラグを渡す。
- 未知subject、未分類、属性競合、目標層の空白とD15除外を除去・隠蔽しない。
- D15のSA／NC／ND・未確認由来・非open重み等の除外を維持する。
  provenanceのURL・作者・帰属を保持する。パック同梱・DATA_LICENSEはG側の別判断。
- モデル未検証の部位・対象外ラベルは成功率へ含めない。
- 10万枚は段階目標。パック生成／同梱とM3内部統計DBの完成は別状態。

本番後に必要な確認:
1. #66の全7,607件の成功・失敗・除外、品質、速度・容量の実測根拠。
2. #72の再実行不変性・誤結合・未分類の監査根拠。
3. #74と#75と本レポートのsnapshot_idが一致し、DB登録対象JSONと同じであること。
4. 建築・地形の役割別直接観測subject数>=10、n_eff>=10とモデル品質のゲート。
5. 全12層の支持不足・未知・除外と、Gの受領確認。
6. 必要なdocs追記を各ownerと統合し、M3最終結果を報告する。

正本: Issue #76、docs/design.md §12、docs/schema.md、#74/#75の実装。
本書は引継ぎ内容の下書きであり、受領済み・本番検証済みとは扱わない。

追加の引継ぎ事項（反証4）:
#74の和集合色は適格assetだけで生成される。除外前の壁／樹木の和集合支持差を
確定するには、同じsnapshotに結び付くD15除外前の診断根拠が別途必要。
report-v2は不足をnullと条件5のunverifiedで出し、個別部位の損失とは分けて報告する。
