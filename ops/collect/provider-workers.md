# provider別収集の運用（#114向け）

第1段階はubuntu-1だけで実行する。CLIはcollect専用handlerと`--provider`を必須にし、
実行hostがubuntu-1以外ならclaim前に拒否する。jobの保存先hostも実行hostと一致させる。
ubuntu-0/2はraw割当て・空容量・実path・DB/backup/GPUのI/O競合・replica/清掃責務の
保存契約が未確定なので、有効化しない。既存pilotサービスを再開する手順ではない。

1. 旧collect/pilotと他の同一provider収集を停止済みと確認する。実行コード・現行source policy・
   storage設定・measurementを固定し、jobに含まれるprovider・host・policyとstorage hashを確認する。
   #77-v1は専用単一workerのまま完了済み条件を維持し、並行収集は新measurementにする。
2. DB所有者が停止中に`alembic upgrade head`（0008）を適用する。
   既存`ops/deploy/worker_grants.sql`を再適用するか、追加表だけなら
   `GRANT SELECT, INSERT, UPDATE ON collection_limit TO colorstats_worker`を実行する。
   workerへDDL・superuser・migration書込み権限は付与しない。
3. 両workerで同じ運用者の共有DBを使う。CommonsとOpenverseが同じmedia hostを使う場合は
   `upload.wikimedia.org`の同一枠に入り、thumb hostも同じrate_groupへ入る。
   同時2・10秒25,000,000 byte・要求間1秒、Commons API同時1を守る。
   DBを分けることで枠を増やさない。隔離比較は事前予算内でのみ行う。
4. ubuntu-1の既存Python環境とDATABASE_URL注入を使い、別々のプロセスで起動する。
   実際の保存媒体2本を両方`--storage-path`へ指定する。秘密値は引数・ログへ書かない。

```sh
python -m colorstats.queue --handler collect=colorstats.collect.bias \
  --provider wikimedia_commons --stop-file /run/colorstats/collect-commons.stop \
  --storage-path collect=/srv/colorstats/raw-orico \
  --storage-path collect=/srv/colorstats/raw-suneast
python -m colorstats.queue --handler collect=colorstats.collect.bias \
  --provider openverse --stop-file /run/colorstats/collect-openverse.stop \
  --storage-path collect=/srv/colorstats/raw-orico \
  --storage-path collect=/srv/colorstats/raw-suneast
```

Openverseは現行policyのanonymousを維持する。登録値未配置でstandardへ切り替えない。
standardの有効化は#93のcredential注入・台帳条件に従う。元ページ・redirectへ認証を渡さない。
無効sourceの元host停止は全workerで現行policyを再確認する。

providerリースはjobリースと同じ期間で、待機中も更新する。二重起動・有効な旧jobがあれば
通信せず起動を拒否する。停止ファイルで子プロセスを先に止め、その後provider所有権を返す。
DB障害は送信・read前に伝播し、所有権喪失では未確定出力を登録しない。
通信リース120秒、socket timeout60秒で各read前に再確認する。DB障害で応答後の記録を
完了できなかった通信や強制終了した通信は、失効後もhostを停止する。不明なRetry-Afterを
期限だけで解除しない。#114の運用担当が旧process・接続の終了と応答ログ・待機期限を確認し、
byte/API台帳を保持したまま該当tokenだけを復旧する。確認できない場合は停止を維持する。
未完了byte予約は最大130秒保持し、強制終了を理由に払い戻さない。正常read後も予約byteを
10秒残すため、短い応答・EOFでは実受信量より保守的に待つことがある。
`collection_limit`を手作業で消して枠を回復しない。台帳が残る0008のdowngradeも拒否する。

監視はprovider別のjob状態・lease期限・失敗理由・HTTP/byte・DB待機を確認する。
停止後は両workerとprepare子processの終了を確認し、DB・raw・計測ログを保全する。
配置・サービスの常用化と本番開始は#114の担当範囲で行う。
