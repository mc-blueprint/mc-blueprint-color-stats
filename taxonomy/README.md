# taxonomy

部位・地形・シーン属性の分類体系の正本（YAML）。初版は `taxonomy_version: 0.1.0`。

- `parts.yaml`: 第1階層をキー、第2階層を値とする建築部位。集計は第2階層が基本。
- `terrain.yaml`: 地形ラベル、画像内の相対高度帯・勾配区分。深度推定由来は `estimated: true` とする。
- `scene.yaml`: 様式20種、用途、規模、バイオーム相当、季節、天候、時間帯。未判定の属性は省略し、推測で既定値を入れない。
- `mcblueprint.yaml`: 固定版 `6ece64a` の `designs/medieval.md`・`japanese.md`・`modern.md` のPaletteにある全役割と、候補部位・地形ラベルの対応。

mc-blueprintには配色パック用の語彙定義がまだないため、対応表は本リポジトリの**暫定対応**であり、パックの公開契約ではない。契約の正本はmc-blueprint側に置く（設計書§7）。対応表にない様式・ラベルをパックへ自動的に出力しない。modernの `floor` は陸屋根にも使われるため複数の候補部位を持つ。素材が同一という意味ではなく、後続の選択処理で用途を区別する。

検証例（作業ディレクトリはリポジトリルート）:

```python
from pathlib import Path
from colorstats.schema.taxonomy import load_taxonomy

taxonomy = load_taxonomy(Path("taxonomy"))
```

`schema.json`（JSON Schema Draft 2020-12）で構造を検証し、ローダーで版の一致、部位の親の一意性、親子・地形間の重複、対応先の存在を検証する。YAMLはリポジトリ管理の入力であり、wheelには同梱しない。インストール先へ自動探索せず、呼び出し元が正本のディレクトリを渡す。

ラベル削除・統合・意味変更はMAJOR、追加はMINOR、説明修正はPATCHを上げ、全YAMLの版を揃える。既存レコードの版を書き換えず、非互換変更では再解析する。
