# ADE20Kと部位候補の親対応表 v2

正本は[`region-parents-v2.json`](../src/colorstats/analyze/region-parents-v2.json)。
版は`ade-role-parents-v2`、正規化JSONのSHA-256は
`9657fe1c90fae5ea3b87eca49b3b84a91d57d1287dae1a81db519cdd76acc21b`。
対応IDは[固定checkpointのconfig](https://huggingface.co/shi-labs/oneformer_ade20k_swin_large/blob/4a5bac8e64f82681a12db2e151a4c2f4ce6092b2/config.json)
のモデルID（0始まり）で、`oneformer-labels.json`と照合する。

屋外外観の粗い`building`等を、部位候補を絞るための親として許容する。
有効領域は必ず**既存候補maskと親semantic領域の積**であり、building全体をwall等へ変換しない。
専用クラスがある場合も粗い建物親を併用し、細部が粗いクラスに含まれた場合の全欠測を防ぐ。
sky=2、person=12は全41部位で許容しない。
同親和集合・異role交差をvoidにする契約は変えず、独立scoreで勝者を決めない。

## 建物の部位

表中の**B**は`1 building / 25 house / 48 skyscraper / 51 grandstand /
79 hovel / 84 tower / 88 booth`。**W**は`0 wall`。
文脈の異なるbridgeやpier、物品一般を建物親へ一括追加していない。
8はこのcheckpointの`window `で、ADEのwindowpane相当として扱う。

| 部位 | 許容親（B/W以外はモデルID） | 根拠 |
| --- | --- | --- |
| plinth | W+B+40 base | 建物の基部・台座 |
| stairs_entry | B+53 stairs+59 stairway+121 step | 建物に含まれる入口階段、専用階段クラス |
| wall_main / wall_secondary / gable_wall | W+B | 外観の壁候補が粗い建物クラスに含まれるため |
| column | W+B+42 column | 建物内部の柱候補と専用柱クラス |
| beam / corner_quoin / half_timber | W+B | 専用クラスがない構造部材。候補形状が部位の前提 |
| window_glass | B+8 window | 窓が粗い建物クラスに含まれる場合を許容 |
| window_frame | W+B+8 window | 枠と周囲の壁、窓の粗分割 |
| door | B+14 door+58 screen door | 建物に含まれる戸と専用戸クラス |
| shutter | B+8 window+63 blind | 窓付属の戸・日除け |
| arch | W+B+14 door+42 column+58 screen door | 開口・柱・壁をまたぐアーチ候補 |
| roof_surface / eave | B+86 awning+106 canopy | roof専用クラスは150クラスにない。建物・覆いを親にする |
| ridge | B | 専用クラスなし。建物内の棟候補だけに限定 |
| gable_trim / chimney | W+B | 壁・建物として粗分割される細部。室内fireplaceは追加しない |
| dormer | B+8 window | 建物・窓として粗分割される屋根窓 |
| cornice / band_course | W+B | 壁・建物に含まれる装飾候補 |
| railing | B+32 fence+38 rail+95 bannister | 建物付属または専用柵クラス |
| relief / accent_other | W+B+132 sculpture | 建物表面の彫刻・装飾 |
| path | 3 floor / 6 road / 11 sidewalk / 52 path | 歩行面。建物全体は許容しない |
| fence | 32 fence / 38 rail / 95 bannister | 柵の専用クラス |
| vegetation_attached | 4 tree / 17 plant / 66 flower / 72 palm | 付着植物候補の植生親 |
| light_fixture | B+36 lamp+82 light+85 chandelier+87 street lamp+134 sconce | 建物付属または照明の専用クラス |
| floor_visible | 3 floor / 11 sidewalk / 13 earth / 52 path / 94 land | 可視床・地面としての歩行面 |

## 地形の部位

| 部位 | 許容親（モデルID） | 根拠 |
| --- | --- | --- |
| ground_soil | 13 earth / 29 field / 52 path / 91 dirt track / 94 land | 裸地・耕地・土の道として粗分割される地面 |
| ground_grass | 9 grass / 17 plant / 29 field | 草地・低い植物・耕地 |
| rock_face | 16 mountain / 34 rock / 68 hill | 岩面候補が山・丘に含まれる場合も許容 |
| rock_scree | 13 earth / 16 mountain / 34 rock / 68 hill / 94 land | 岩屑が地面・山に含まれる粗分割 |
| sand | 13 earth / 46 sand / 94 land | 砂地が一般地面に含まれる場合も許容 |
| snow_ice | 13 earth / 16 mountain / 34 rock / 68 hill / 94 land | snow/ice専用クラスはない。地表・山にある雪候補の積だけを許容 |
| water | 21 water / 26 sea / 60 river / 109 pool / 113 falls / 128 lake | 水域の専用・粗いクラス |
| vegetation_low | 9 grass / 17 plant / 29 field / 66 flower | 草・低木・花の候補 |
| vegetation_tree_canopy / tree_trunk | 4 tree / 72 palm | treeを山・岩・雪へ拡張しない |
| path_natural | 13 earth / 52 path / 91 dirt track / 94 land | 自然の道候補と地表の粗分割 |

snow/iceの親許容は雪の意味的な正しさを保証しない。地面全体を雪へ変換せず、
sky/person/treeを雪の親としても許容しない。競合は他roleと同様にvoidになる。
親クラスは部位の正解ラベルではなく粗い制約であり、部位精度の採否は後続Dで確認する。

## 版・不変性

region-policy-v1の共有payload形式を維持し、`parent_table.version`と`parent_table.sha256`を
segmentパラメータ・role契約へ追加する。policy hashはこの参照を含み、
対応表変更はconfig hashも変える。旧hashの有効maskや色観測を現行へ流用しない。
旧版はcommit `922d88b`と既存private成果物に保全し、新run・別の出力先へ保存する。
旧`sam2-dino`経路、stage/schema、migration、採用設定は変更しない。
