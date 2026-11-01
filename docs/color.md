# color stage のベースライン

Issue #12。画像全体から最大5色を抽出し、色ごとの観測をassetへ直接登録する。
region・relation・材質色の推定は行わない。DBスキーマの変更はない。

## 採用した処理

- `colorstats.colors.rgb_to_oklab`へ#11の変換を移し、ブロック色と共用する。
  colour-scienceのsRGB伝達関数の復号→XYZ→OKLabを使う。ブロック色の選別・中央値は維持する。
- クラスタリングは[OpenCVのk-means](https://docs.opencv.org/4.x/d5/d38/group__core__cluster.html)
  を採用する。既存のcolour-scienceは変換に使い、k-meansを自作しない。
  k-means++、seed=0、1試行、最大100反復、中心移動の許容誤差1e-6。
  クラスタ数は最大5、有効画素のRGB種類数が少なければその数とする。
- GUIを使わないため`opencv-python-headless`を追加した。
  [公式配布情報](https://pypi.org/project/opencv-python-headless/)ではWindows/Linuxのwheelを提供し、
  GUI依存を含まない。Python 3.12・既存NumPyで動作確認する。
  PythonパッケージはMIT、OpenCV本体はApache-2.0、同梱ライブラリの通知は配布物に従う。
  別のcv2パッケージとの重複導入を避ける。追加サービスやGPUは不要。

## 有効画素と面積比

入力はsRGBとして読む。ICC変換・露出補正は行わない。
RGBAへ変換し、alpha=255の画素だけを採用する。透明画素の隠れたRGBや
半透明画素の合成先背景が主色へ混入するのを避けるため、alphaによる重み付けはしない。

全RGB成分が5以下の黒付近、全成分が250以上の白付近を除外する。
8bit端点から約2%だけを対象にする保守的なヒューリスティックで、
黒つぶれ・白飛びや余白の影響を減らす。単一成分が飽和した赤・青などは除外しない。
真の黒・白の材質も除外されるため、露出不良の判定や材質の真値とは扱わない。
この閾値の妥当性はM1パイロット・M2の正解データで評価する。

任意のマスクと上の条件の積集合が有効画素となる。面積比は
**クラスタ画素数 / マスク適用後の有効画素数**で、合計は1（浮動小数点誤差を除く）。
画像全体の面積比や除外画素を含む比とは区別する。
有効画素が0ならValueErrorで失敗し、空の観測で成功確定しない。

`observed_oklab.dominant`はクラスタ内OKLabの平均、`quantiles`は
各チャンネルの5・25・50・75・95%点。面積降順、同面積なら主色の辞書順に並べる。
結果JSONとDBは同じ観測を持つ。材質色・信頼度はNULL。
固定seedにより同じ入力・同じ依存環境で再実行結果を固定する。
ライブラリ版・CPU実装をまたぐビット単位の一致は保証しない。

## APIとキュー接続

`extract_colors(image, mask=None, *, clusters=5)`はPillow画像を変更せず観測辞書の配列を返す。
maskは入力と同じ高さ・幅の2次元bool NumPy配列。形状・型の不一致はValueError。
M2ではこの入力へ部位マスクを渡せる。regionへの登録はM2側で実装する。

`colorstats.analyze.color`は既存の`prepare` / `register`契約に従う。
colorのjobにはasset_idが必要。payload例:

```json
{
  "input_path": "/derived/.output-prep-token-uuid/asset.jpg",
  "input_run_id": "00000000-0000-0000-0000-000000000001",
  "output_path": "/derived/color/asset.json",
  "license_class": "open",
  "taxonomy_version": "0.1.0"
}
```

`input_path`はローカルに到達可能な確定画像。prepの
`run.output_paths[derived_path]`を指定し、prepのrun IDを`input_run_id`へ渡す。
後者は`processing_run_input`へ保存する。原本を直接処理するときは省略可能。
prepはJPEG化でalphaを失うため、透明画像の選別が必要ならRGBAを保持する原本を入力する。
`mask_path`は省略可能。指定時は同寸のマスク画像をLへ変換し、非ゼロ画素を採用する。
画像・マスク・ファイルの読込み失敗はキューの通常失敗として再試行される。

設定ハッシュにはコード版・抽出設定と入力画像／マスクの識別情報・入力runを含める。
画像・マスクはジョブ投入後に変更しない。再計算は新しい設定ハッシュで投入する。
ライセンス区分・taxonomy_versionは入力assetと一致する値を呼出し元が指定する。

```sh
uv run python -m colorstats.queue --handler color=colorstats.analyze.color --stop-file /tmp/color.stop
```

prepareは試行トークン付き一時JSONのみを書き、registerはDB登録だけを行う。
キューが不変パスへの公開・`run.output_paths`・観測・job成功を所有権付きで確定する。
成功済みの同じジョブを再投入・再確定しても観測を追加しない。

設計§5.2の64件は投入側のバッチ目標。現行#6のAPIは1 asset / 1 jobの取得・確定であり、
本stageもその境界を維持する。64件の投入でも各assetの失敗と再試行は独立する。
64画像を一つのclaimへ詰めたり、assetなしcolorジョブへ契約を変更したりしない。

## 検証範囲

`tests/test_color.py`は合成画像の既知色・75:25の面積比、透明・半透明・端点の除外、
マスク、単色・1画素、有効画素なし、多色画像の再現性、一時JSONを検証する。
`tests/test_color_db.py`は`TEST_DATABASE_URL`のPostgreSQL 16へ専用schemaを作り、
prep→colorの実ワーカー、asset直結、由来、JSON公開、再確定の重複防止、失敗時の未登録を検証する。
既存キューのリース喪失・ロールバック検証も全体テストに含める。

1,000枚の保存確認は、ユーザー指定どおりubuntu-1のrawを使うM1締めのパイロットで実施する。
本Issueでは合成画像と少数のCommons実画像をローカルの一時rawで確認し、実画像はGitへ追加しない。

2026-11-01の検証結果:

- Windows / Python 3.12.15、OpenCV 4.14.0.94、WSLの一時PostgreSQL 16.15で全174テスト成功。
  DB専用テストもスキップなし。ruff checkとuv build（sdist・wheel）も成功。
- Commonsの[姫路城](https://commons.wikimedia.org/wiki/File:Himeji_Castle,_November_2016_-02.jpg)
  と[富士山付近の写真](https://commons.wikimedia.org/wiki/File:Grumman_E-2C_Hawkeyes_of_VAW-115_fly_past_Mount_Fuji_on_15_February_2007_(070215-N-2604L-024).jpg)
  の2枚を既存アダプターで取得。縮小後の再抽出結果は一致し、
  実ワーカーのprep→colorで各5観測をassetに登録、面積比合計1、不変JSONの存在を確認した。
  raw・出典／帰属・結果・DB検証記録はGit対象外の`data/issue12-commons/`に保持。
- 重点反証では、単色・1画素、除外境界、マスクの形状・型、無効画素のみ、
  旧ブロック色の挙動、キューの再確定・失敗時の未登録を確認した。
  1画素のOpenCV入力形状の問題は修正し、回帰テストへ追加した。
- 実機Ubuntuへの変更は行っていない。1,000枚のパイロットは未実施。
