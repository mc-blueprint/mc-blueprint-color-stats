# 別ホスト復元試験（Issue #30）

実施日: 2026-11-02 JST（ホスト・監査ログは2026-11-01 UTC）。

## 対象と認証

- 元DB: ubuntu-2 (`192.168.1.86`) のPostgreSQL 16 `colorstats`。
- 最新の検証用バックアップ: `/var/lib/colorstats-backup/issue30/colorstats-latest.dump`。
  稼働中DBを `pg_dump --format=custom --no-owner --no-acl` で取得した。
- 保存先: ubuntu-0のWD、`/srv/colorstats/backup-wd750/issue30/colorstats-2026-11-02.dump`。
  health・mount UUID照合後に既存世代とは別に保存した。バックアップ削除・既存世代の上書きはない。
- 復元先: Windows上のWSL `Ubuntu-24.04`、独立PostgreSQL 16クラスタ
  `/tmp/issue30-postgres`、port `55430`、DB `issue30_restore`。
- 元ダンプ・転送後・WD保管後のSHA-256:
  `d7670bccd3d3a0589f8ec490d1040759a75b31040d04135280713b02ba02361e`。
- ダンプにロール定義や認証値は含めない。SSHの既存認証でダンプだけを転送し、復元先で一時ロール
  `issue30_worker` とランダムな秘密を生成した。秘密はWSLの検証プロセス内だけに保持し、
  コマンド引数・ログ・ホスト間へ出さない。Unix socketで管理操作し、ワーカー接続はlocalhost TCPの
  `scram-sha-256` で実際に認証した。本番の認証・DB・データは変更していない。

## 結果

`pg_restore --exit-on-error --no-owner --no-acl` が終了コード0。
Alembic `current` は `0003 (head)`、`check` は `No new upgrade operations detected.`。

| 復元テーブル | 件数 |
| --- | ---: |
| source | 380 |
| asset | 457 |
| subject | 377 |
| subject_candidate | 89 |
| color_observation | 2275 |
| processing_run | 1541 |
| processing_run_input | 455 |
| collection_reservation | 457 |
| job | 1578 |

元DBは試験中もパイロットが更新するため、復元後の件数を本番の後刻値と等しいとは扱わない。
転送の完全性はダンプのハッシュ、スキーマはAlembic headとmetadata比較で確認した。

一時ワーカーロールでQueueからreviewジョブを投入し、テスト用ハンドラーを使ってpendingから
succeededへ完了した。ジョブIDは `ec9ed0c8-0a37-4a74-b655-71446c0b4781`、試行数1。
ネットワーク取得や本番rawへの出力は行っていない。

さらにWSLの一時tmpfsを実際にroへremountし、保存先を指定したワーカーが取得しないことを
実DBで確認した（pending・attempts=0）。rwへ戻すと同じジョブがsucceeded・attempts=1となった。
試験mountは解除し、一時クラスタは検証終了後に停止する。復元DBとダンプは保全する。

追記: 後任の温度修正時にはWSLの `/tmp` の一時環境が消失していたため、全テスト用の
独立クラスタを再作成した。上記の復元成功は前任の監査ログに基づく実施記録であり、
復元DBが現在も残ることは保証しない。Windows側の元ダンプ
`C:/Users/ryuma/AppData/Local/Temp/issue30-colorstats.dump` とWD保管分は削除していない。

## 監査ログ

Windowsの `C:/Users/ryuma/.codex/logs/commands/` 配下:

- ダンプ生成: `20261101T151105Z-69595aad4dac42e8911942b119971906.jsonl`
- 別ホスト復元・SCRAM・マイグレーション・再開:
  `20261101T151420Z-5065f290f95549869b9486c5e1fde372.jsonl`
- 実readonly/rwでの取得停止・復旧:
  `20261101T151651Z-bf14671ffde746f8861c778cba2bde44.jsonl`
- WD保管後の照合: `20261101T152144Z-d7426a5d0e27453f9db9f17de9670564.jsonl`
