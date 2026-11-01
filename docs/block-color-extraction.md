# バニラjarのブロック色抽出

`python -m colorstats.block_colors <jar> <Minecraft版> [--output <JSON>]` で、jar内のblockstates、モデルと親モデル、テクスチャをたどり、`block_color`レコードを生成する。既定のJSON出力先は `data/block-colors/<版>.json`。抽出結果は`write_block_colors`で保存し、DB登録は`register_block_colors(session, records, processing_run_id)`で行う。トランザクションと抽出runの作成は呼び出し側が担う。

ブロックIDはMCBlueprintの同じMinecraft版のブロックデータに存在するものだけを出力する。バリアントはその版の既定block stateに一致するモデルを選び、multipartは全適用モデルを集約する。モデル要素の上端・下端・側面を`top`・`bottom`・`side`として分類する。各テクスチャの不透明画素をsRGBからOKLabへ変換し、チャンネルごとの5/25/50/75/95パーセンタイルと中央値を保存する。完全透明画素は除外する。

blockstateやmodel elementの回転は面分類へ反映しない。jar内にないテクスチャ参照と、不透明画素がない面はスキップし、その面のレコードは出力しない。テクスチャ定義は文字列と26系の`{"sprite": "block/...", "force_translucent": true}`形式の両方を解決する。`force_translucent`は描画設定なので色抽出には反映せず、元画像のアルファ値255の画素だけを使用する。

grass、leavesなどモデル面にtint indexがあるテクスチャも、バイオーム既定色やtintを掛けず、jarに格納された元の不透明RGB画素を使う。よって出力はテクスチャ素材色であり、特定バイオームの描画色ではない。テクスチャ画像自体は保存・配布しない。material_tagsは現時点では空配列。

手動抽出例:

```powershell
uv run python -m colorstats.block_colors H:\MCBlueprintColorStats\work\jars\26.3.jar 26.3 --output H:\MCBlueprintColorStats\work\issue-11-extraction\26.3.json
```

## 全対応版の実jar検証（2026-11-01）

MCBlueprintの固定依存commit `6ece64ae40b5b2e3b23e0b566135eb0d7c8d5774` が返す全4版で抽出が完走した。ブロック数は出力レコードの一意な`block_id`数、面数はレコード数である。1.21.11の引継ぎ値1,005ブロックは再現せず、以下の966ブロックが実測値となる（面数2,634は一致）。

| Minecraft版 | 出力ブロック数 | 出力面数 | モデル面なし | 不透明画素なし | MCBlueprint未収録 | 画像参照先なし |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.21.11 | 966 | 2,634 | 160 | 39 | 2 | 1 |
| 26.1.2 | 968 | 2,638 | 160 | 39 | 2 | 1 |
| 26.2 | 1,060 | 2,912 | 96 | 39 | 2 | 1 |
| 26.3 | 1,150 | 3,177 | 96 | 39 | 2 | 1 |

未出力件数はjarのblockstatesを母集団として調べた。モデル面なしには空気や専用描画のブロック、不透明画素なしには色付きガラスなどが該当する。MCBlueprint未収録は`item_frame`と`glow_item_frame`。`heavy_core`はモデルの面が`#all`ではなく`all`を参照しており、解決先の`textures/all.png`がjarに存在しないためスキップする（`textures/block/heavy_core.png`自体は存在する）。これらは全版で例外なくスキップされ、モデル面から色を得られないブロックへ代替色は補完しない。

代表ブロックのOKLab中央値（`dominant`）は全4版・top/side/bottomで一致した。小数点以下6桁へ丸めた値を示す。石レンガのa・bはほぼ0で無彩色、木材はbが正で黄味があり、ホワイトテラコッタ > オーク > ダークオークの明度順を実測値で確認した。

| ブロックID（minecraft:省略） | L | a | b |
| --- | ---: | ---: | ---: |
| stone_bricks | 0.596490 | 0.001678 | -0.001201 |
| white_terracotta | 0.785032 | 0.029013 | 0.032665 |
| oak_planks | 0.666804 | 0.015793 | 0.080043 |
| dark_oak_planks | 0.330797 | 0.022829 | 0.046728 |

26系のjarは各版のローカルランチャーJSONの`downloads.client.url`（`https://piston-data.mojang.com/v1/objects/<SHA-1>/client.jar`）から取得し、`size`・`sha1`と一致することを確認した。ランチャー配下には書き込んでいない。

| 版 | サイズ（bytes） | SHA-1 |
| --- | ---: | --- |
| 26.1.2 | 38,113,927 | `4e618f09a0c649dde3fdf829df443ce0b8831e65` |
| 26.2 | 39,193,383 | `2dc72797acbc1b63fc16a11c4ac393605f453754` |
| 26.3 | 41,483,720 | `e877b6a07acd633fb3bb475002175cec036e7b87` |

jarは`H:\MCBlueprintColorStats\work\jars\`、全レコードと分位点・未出力ブロックの監査結果は`H:\MCBlueprintColorStats\work\issue-11-extraction\`に保持する。jar・テクスチャ画像・実測JSONはリポジトリに含めない。
