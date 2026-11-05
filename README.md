# mc-blueprint-color-stats

[mc-blueprint](https://github.com/mc-blueprint/mc-blueprint) 向けに、建築・地形の画像と資料から配色の統計を作り、mc-blueprint に同梱する配色パックを生成する。mc-blueprint が生成時に LLM を呼ばずに、建築の部位ごとの配色を決められるようにすることが目的。

設計は [docs/design.md](docs/design.md) を参照する。
ジョブの投入・ワーカーの起動と停止・保存先の契約は [docs/queue.md](docs/queue.md) を参照する。
Commons収集・ソースポリシーと後続アダプターの共有契約は [docs/collect.md](docs/collect.md) を参照する。
画像全体の主色・OKLab観測の抽出と登録は [docs/color.md](docs/color.md) を参照する。
画像の利用目的・保持期間・GitHub Issueによる削除受付は [docs/retention.md](docs/retention.md) を参照する。

## 構成

| パス | 内容 |
|---|---|
| `src/colorstats/` | 収集・解析・統計・配色パック生成の本体 |
| `taxonomy/` | 分類体系（部位・地形・シーン属性）の正本 |
| `configs/` | ノード・保存先・ソースポリシー・収集目標・モデルの設定 |
| `ops/` | 環境構築手順、監視・バックアップのスクリプト |
| `bench/` | ベンチマークの手順と集計 |
| `scripts/ssh.py` | 登録済み Ubuntu ノードへのログ付き SSH 実行 |
| `docs/` | 設計書、引継ぎ資料、ストレージ調査結果 |

## 開発環境

Python 3.12 と [uv](https://docs.astral.sh/uv/) を使う。

```bash
uv sync
```

```bash
uv run ruff check .
```

```bash
uv run pytest
```

## バージョン

パッケージ・分類体系・配色パックは SemVer で管理する（[docs/design.md](docs/design.md) §11.1）。

## ブランチ

`develop` が開発版、`main` がリリース版。通常の変更は `develop` から `feature/issue-<番号>` を作り、`develop` 宛ての PR にする。
