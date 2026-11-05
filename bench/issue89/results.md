# Issue #89 比較結果

## 許可判断

2026-11-05のユーザー決定：Commons Action APIは公式[Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy)のAction API rules（未認証同時1、5 req/s未満、1秒超の要求後5秒待機、batch推奨）とRate limits（識別User-Agentで200 req/min）に従って利用を継続する。[Commons robots.txt](https://commons.wikimedia.org/robots.txt)の`Disallow: /w/`は動的ページを巡回するcrawler向けと解釈し、HTML動的ページは巡回しない。`upload.wikimedia.org/archive/`は巡回しない。この判断はIssue #104にも記録済み。

## 初期予備計測（比較対象外）

初期予算API60・画像40に対して旧v1がAPI30・画像11を消費。旧v1はmedia byte rate limit未設定のため比較から除外し、履歴と画像を保持する。measurement `issue89-old-v1`、一時DB `i89_old`、保存先 `/tmp/colorstats-issue89/raw-old`（画像11点、80,587,190 byte、削除しない）。3 job成功、HTTP41（API30・画像11）、timeout/backoff 0、download 11/80,587,190 byte、合計bytes 80,753,594、適格新規SHA7（新SHA11）、elapsed78.394秒、API network17.511秒、media network19.038秒、wait36.176秒、DB lock wait0.232秒・processing3.412秒・commit0.708秒。

## 追加許可枠での比較

ユーザーの追加許可は旧v2・新v1それぞれAPI35・画像15まで。両測定とも同じ固定入力、Commonsのみ、固定UA、隔離PostgreSQL 16.15、一時保存先で旧v2→新v1の順に実行。Openverseなし。各3 job成功。両方ともHTTP33（API33・画像0）、responses33、timeout/backoff0、候補30・verified29、response bytes209,185、download bytes0、eligible new SHA0・new SHA0。全job committedでHTTP retry・timeoutがなく、本文byteは成功209,185・失敗0。今回の候補は全てauthor limit等で除外され、画像取得・新規SHA効果は発生しなかった。

| measurement | job ID / SHA-256 hash (順に対応) | elapsed合計 | API network | 通常wait | DB lock wait | DB processing | DB commit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `issue89-old-v2` | `ea254bf0-c596-4645-8e26-b34e1410490c` / `4c20cdec33fe3a24a365a401cba8b4c9180f820e059aba318b5b696d5cf6b189`; `977fbf0e-20af-4bcf-b5f4-60449cf517d9` / `22cf5c51878372a409e6300374a9afe17ab09b92b18cc609e01af455f571e14f`; `9966c161-8ac6-44cb-a251-be5be5371628` / `33ccd50aa808f1681102ef9c2eba8ce374aaffecf1314f132012d649bd2ab23f` | 46.813秒 | 11.064秒 | 31.489秒 | 0.204秒 | 3.012秒 | 0.514秒 |
| `issue89-new-v1` | `8974f7ab-bf8a-4d81-b0e1-4b5509c4a8a9` / `541b5f477c21b69c90a9c4a667bc6e1803d3a7f2ad3a1cbf1b33383c3e163473`; `3c8df545-f5e0-49d7-a448-2110876dc1b0` / `1439bb0b73f7e48e90a91e69504eaf924ff5e53899a83a52b0b7d48d123f8a15`; `6c6b3fb8-18e8-47bd-b6cd-33e4df567dff` / `b135e6dd681970aebfbcb5ad59587ea637429a39214fac60d0dbb027d9470a8b` | 29.342秒 | 10.080秒 | 14.962秒 | 0.209秒 | 3.030秒 | 0.510秒 |

新条件は総elapsedが17.471秒（37.3%）、API networkが0.984秒（8.9%）、通常waitが16.526秒（52.5%）短縮。DB処理・commit時間はほぼ同じ、lock wait差+0.005秒。小規模測定の範囲で改善したため新しいAPI/media間隔を既定に採用する。画像が取得されずmedia間隔の効果・新規SHAの改善は未測定。
