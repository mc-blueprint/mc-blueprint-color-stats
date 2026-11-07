# 画像の利用目的・保持と削除受付

建築・地形の非表現的な色分布・比率・共起の統計作成だけに画像を利用します。
原画像・縮小画像・マスク・CVAT注釈は公開しません。人物・要配慮情報が主体の画像は
対象外です。内部確認者が原画像と縮小画像を確認し、人物の写り込みは人物画素の除外maskを
固定して色集計から外します。顔認証・人物属性推定は行いません。

新規収集分の画像は取得から30日以内、不採用は7日以内に削除します。
削除要求は受付時に新規利用・再取得・配布を停止し、7日以内に画像を削除します。
ソース条件が短い場合は短い期限を優先します。バックアップ残留は30日以内です。
これは2026-11-04承認の運用値です。既存7,607件の一括削除は行いません。
画像期限の清掃だけでは完成済み数値統計を失効させません。画像削除後の再現対象は
保存済み数値入力からの再集計です。画像・maskを使う新たな和集合計算はできません。

削除・利用停止の窓口は
[本リポジトリのGitHub Issue](https://github.com/mc-blueprint/mc-blueprint-color-stats/issues/new)
です。対象の出典ページURL、またはproviderとnative ID、または原画像URLを記載してください。
個人名を検索キーにしません。公開Issueへ氏名・精密位置・画像・認証情報を添付しないでください。
管理者は対象確認後すぐに以下の受付操作を実行し、受付時刻と期限を監査します。

## 管理手順

既存のSQLAlchemy・不変出力パス・Storageを再利用し、追加依存はありません。
`alembic upgrade head`で0007を適用します。過去行の登録・移行は行いません。
新規collectだけがretentionとretention_fileへ登録されます。
`DATABASE_URL`は既存の認証注入を利用し、コマンド引数・ログへ出しません。

```sh
python -m colorstats.retention_cli stop --source-url https://example.test/item/1 --request-url https://github.com/mc-blueprint/mc-blueprint-color-stats/issues/123 --ledger /private/deletion-ledger.json
python -m colorstats.retention_cli audit
python -m colorstats.retention_cli cleanup --host ubuntu-2
python -m colorstats.retention_cli export-stops --output /private/deletion-ledger.json
```

`--url`、または`--provider`と`--native-id`でも指定できます。native IDは
`asset.quality.metadata.native_id`です。source URL指定は出典全体、原画像URL/native ID指定は
該当画像だけを停止します。不採用は指定範囲の現在の画像だけを停止します。
不採用は`--reason rejected`、根拠失効は`--reason rights_revoked`を指定します。
受付と収集確定・画像参照登録・集計登録はPostgreSQL取引ロックで直列化します。
実収集は`stage.prepare(..., database_url=...)`で取得直前にも停止を照会します。
標準Workerはこれを注入します。独自収集入口は同じ確認を必須とします。
DB未指定時は収集を開始しません。`prepare-draft`もDATABASE_URL（APIではdatabase_url）を
必須とし、XMLを読む前に停止・期限を確認して生成XML/JSONを保持台帳へ登録します。

画像処理は認可された内部worker/管理者のOSアカウントだけで実行してください。
新規の一時ファイル・確定ファイルは0600、確定ディレクトリは0700です。
保存root・NFS・CVATは公開HTTPへマウントせず、既存の内部専用権限で利用します。
WindowsのACL・既存NFS設定・CVAT認証は変更しません。POSIX modeだけでWindows ACLや
NFSサーバーの認可を代替できません。画像パスを外部利用者へ返すAPIはありません。

`retention.review_privacy`で自動判定または目視結果、採否、building/terrainの主体を記録します。
自動判定は版を含むmethod、閾値、固定入力の根拠とauto:方式名のreviewerを保存します。
目視による上書きはprivacy_review_historyへ前の記録を保全します。不採用・目視待ちは色処理しません。
人物画素がある場合は解析画像と同寸の非ゼロ人物PNGを渡し、color payloadの`person_mask`へ
同じパスを指定します。採用判定なし・不一致・変更済みmaskはcolor処理を拒否します。
shadeにも同じperson_maskを渡し、人物をWB推定・色観測・部位面積から除外します。
自動判定を使う統計は固定seedの目視サンプル確認後に作成します。
具体的な判定・非公開HTML・記入結果取込みは[バッチ1人物判定](../bench/issue114/privacy-plan.md)を参照します。
CVAT・replica・cache・backupを作成する処理は同じ取引ロック内で
`retention.register_file(session, asset_id, host, absolute_path, kind)`を必ず呼びます。
新規ファイルを保持期限の外へ複製しないでください。CVATのタスク・ZIPを外部共有しません。
保持期限付きの新規画像と旧画像が混在するCVAT draft生成・取込みは、出力前に拒否します。
新旧は別のCVATタスク・出力へ分けて実行してください。新規画像だけの共有物は保持台帳へ
登録し、旧画像だけの処理は従来どおり保持台帳へ登録しません。Jobを持たない旧runや
所有者を特定できないrunの共有参照も保護します。既存共有物の削除は本タスクの対象外です。
CVATのdraft・maskは既存ディレクトリの権限やumaskにかかわらず、作成時から0600とします。
解析出力のhostはpayload.host（省略時は実行host名）、CVATと人物maskは呼出し時のhost
（省略時は実行host名）です。NFSの別名を使う場合は清掃hostと同じ名前を明示してください。

cleanupは登録された通常ファイルのみを対象にします。未参照ファイル清掃とは別処理です。
参照解除時刻と物理削除時刻を分け、I/O失敗はerrorへ記録します。途中停止後も再実行できます。
通常の共有パスの有効な別参照と既存asset参照は保護し、最後の参照解除後に削除します。
複数画像を埋め込む閲覧HTMLとその番号表は`image_bundle`として全構成assetの参照を登録します。
構成assetのどれかが画像期限切れ・停止・削除受付等で利用不可になった場合、次回cleanupは
同じhost/pathの全参照を解除して束全体を削除対象にします。ほかの画像のrawや別ページの期限は変えません。
物理削除の失敗は通常どおりerrorへ記録し再実行できます。新種別は既存のText列で扱い、migrationは不要です。
生成側とcleanup側はこの種別に対応した版へ揃えて配備してください。既存cache行の種別は自動変更しません。
旧snapshotは不変のまま内部に保管し、停止台帳で採用を拒否します。
`rebuild-selection --input <旧selection.json> --output <新版selection.json>`で
依存索引から停止入力を除外し、既存snapshot CLIで新規出力先にsnapshotを生成して集計します。
全件が停止された場合は空のselectionをビルダーへ渡さず、配布を取り止めます。

## バックアップと復元

backup種別にも依存する全assetを登録します。DB dump・世代archiveはファイル全体を単位とし、
保持対象以外の永続データを混載しません。既存backup retentionの世代上限だけでは期限を
保証できないため、監査台帳のbackup_untilまでに専用世代を除去・確認します。
受付台帳はDB backupと別の内部保存先を`--ledger`へ指定します。受付取引のcommit前に
最新版を原子的に保存し、保存できなければ受付操作自体を失敗させます。復元時はこの最新版を
用います。管理APIを直接呼ぶ運用も同じ保存・commit順序を守る必要があります。

1. 復元DB・画像はworker/HTTP/CVATから隔離する。
2. 0007までmigrationし、最新の別保管台帳を準備する。取得できなければ開放しない。
3. `python -m colorstats.retention_cli restore-stops --input /private/deletion-ledger.json`を実行する。
4. 全hostでcleanupとauditを行い、期限超過・I/O失敗・未確認backupを解消する。
5. 停止入力の再取得・再解析・旧snapshot採用拒否を確認してから内部処理へ開放する。

M4ビルダー接続は対象外です。[配布契約](pack-contract.md)と
`colorstats.pack_boundary.validate_public`が公開前検査の受け口です。
