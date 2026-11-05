# Issue #89 小規模比較計画

## 固定条件と予算（2026-11-05、実行前記録）

- #77 `bench/issue77/targets.yaml` の `japanese-castle` 層から日本語・英語の固定検索語と `Himeji Castle` カテゴリを使い、Commons のみ、各検索1ページ・最大10件。Openverse は匿名枠保護のため対象外。
- 旧・新は独立 PostgreSQL 16.15、measurement ID、job hash、保存先で順次実行する。#77-v1、M3 cohort、本番DBは変更しない。
- 初期予算はAPI60・画像40要求。先行した旧v1でAPI30・画像11を消費し、帯域制限未設定のため比較から除外した。ユーザーは追加枠を明示許可し、旧v2・新v1それぞれAPI35・画像15を上限として実行することを指定した。
- 今回の比較予算はAPI70・画像30（旧v2 API35/画像15、次いで新v1 API35/画像15）。失敗・redirectも要求数に含め上限到達時停止。過去の旧v1要求数は別記し、比較結果に混ぜない。

## 共通の公開安全条件

- 固定User-Agent、maxlag=5、同時1、Retry-After、再試行上限・backoff、WikimediaのAction API規則に従う。
- 両条件にAPI応答が1秒超なら5秒待機、API 199/60秒、media 25,000,000 byte/10秒の安全上限を適用する。旧v2のAPI/media間隔は1秒、新v1は0.5秒。API実測で改善しなければ新設定を既定にしない。
- 2026-11-05のユーザー決定により、公式 Robot policy「Action API rules」および「Rate limits」に従いCommons Action APIの利用を継続する。robots.txtの`Disallow: /w/`は動的ページ巡回crawler向けと解釈し、動的HTMLページは巡回しない。`upload.wikimedia.org/archive/`は取得しない。
- 一時環境 `/tmp/colorstats-issue89/` の隔離 PostgreSQL 16.15と一時保存先を使用する。取得画像は残し、削除しない。

## 比較記録

各measurementでID・job hash・HTTP/API要求、成功/失敗byte、timeout、総時間とAPI/page/media/wait/backoff/帯域/DB lock wait・processing・commit内訳、成功・失敗・適格新規SHAを記録する。完了後、同じ入力の旧v2と新v1を比較し、改善しない場合は候補の間隔を既定値に採用しない。
