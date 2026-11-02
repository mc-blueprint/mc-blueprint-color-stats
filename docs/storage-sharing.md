# raw共有方式とNFS断・復帰試験（Issue #42）

2026-11-02。基準は`feature/issue-42` / `4e016c5`。
[設計 §4・§4.1](design.md)、[segmentの入力契約](segment.md)、
[媒体監視](../ops/storage/README.md)を前提とする。
恒久設定は適用せず、本番DBと停止中のパイロットには触れない。

## rawの選定

**ジョブに必要な原本だけを、監視確認・SHA-256検証付きで事前複製する方式を推奨する。**
全原本の常時ミラーは行わず、検証済みバッチのローカルパスをGPUワーカーへ渡す。
転送完了前にジョブをclaimしない。原本は再取得可能なキャッシュだが、
帰属・権利・assetとの対応の正本は引き続きDBとする。

| 候補 | 障害時の挙動 | 性能・容量 | 運用と既存実装への影響 |
| --- | --- | --- | --- |
| ubuntu-1からNFS読み取り専用export | hardでは原本の読取りも復旧まで待つ。exportのroは媒体故障や原本内容の健全性を通知しない | 必要な原本を直接読め、複製容量は不要。小さい画像の反復読取り・属性参照がLANへ出る | export・クライアントmount・UID/GID管理が必要。既存`storage_available`はreadonly rootを拒否し、segmentはraw停止記録を見ない。監視契約の変更が必要 |
| HTTPで画像バッチ取得 | 接続・読取りのtimeoutと再試行を転送層へ集約できる。取得中断をジョブ投入前に保留できる | バッチ化で往復を減らせるが、ローカルstagingと検証は必要 | 設計§4の方向に合うが、原本配信API・認可・パス制限・監視連携・配信サービスが未実装。既存HTTPは収集用クライアントで配信機能はない |
| 必要原本の事前複製（採用案） | 複製失敗は投入前に保留。複製後の推論はubuntu-1やLANの断から独立。SHA不一致は公開しない | 初回転送と対象分の追加容量が必要。反復推論はローカル読取り。全量複製はしない | 既存SSH/SCPと標準ライブラリで構成できる。元媒体の停止はubuntu-1側の既存監視で判定でき、GPU側へ物理UUIDを偽装する必要がない |

NFSの再試行・キャッシュの仕様は[nfs(5)](https://man7.org/linux/man-pages/man5/nfs.5.html)、
既存転送ツール候補の部分転送・検証は[rsync公式manual](https://download.samba.org/pub/rsync/rsync.1)を確認した。
今回は登録済みWindows→各UbuntuのSSH認証だけで試せるSCPと標準ライブラリを使った。
rsyncは両Ubuntuに導入済みだが、Ubuntu間の認証・manifestと原本SHAの対応は別途必要であり、
転送検証だけで既存の内容アドレス検証を代替しない。新規配信サービスや依存パッケージは追加しない。

## 配備案と監視の境界

`ops/deploy/raw-replica.py`は手動実行する案。恒久export・fstab・systemdは不要。
実行コマンドは`run_logged.py`、SSHは登録済み接続先を`ssh_logged.py`経由で記録する。

1. ubuntu-1で採用済みassetの原本**不変パス**を選ぶ。DBの参照を正本とし、媒体全体の走査結果をそのまま投入しない。
2. ubuntu-1の配備Pythonと`PYTHONPATH=<repo>/src`で
   `raw-replica.py stage --destination <新規の転送用ディレクトリ> <原本パス>...`を実行する。
   `storage_available("prep")`を再利用し、blocked・媒体欠落・readonlyなら保留する。
   原本名と内容SHA-256を照合し、コピー後も再照合・監視確認を行って最後にmanifestを作る。
3. manifestと選択画像だけを、監査付きSCPでGPUノードのstagingへ転送する。
   今回はWindowsの担当領域を経由した。SSH鍵やDB資格情報は転送しない。
   恒久運用ではSSHの接続・死活timeout（例: `ConnectTimeout=15,ServerAliveInterval=15,ServerAliveCountMax=2`）を指定し、
   転送失敗は投入前の保留にする。今回のSCPは正常転送だけを確認し、転送断の実機試験は行っていない。
4. GPUノードで`raw-replica.py publish --staging <転送先> --destination <新規バッチ公開先>`を実行する。
   内容と容量を検証後、ディレクトリrenameで公開する。両パスは同じfilesystemに置く。
   不完全な転送は公開せず、既存バッチを上書きしない。失敗時はジョブを投入せずstagingを保全する。
5. manifestのSHAをassetと突き合わせ、segmentの`input_path`へ公開済みローカル画像を渡す。
   `license_class`はassetの区分を保持する。prep runの画像ではないため、
   prepを指す`input_run_id`を流用しない。原本とrunの由来を恒久運用でどう記録するかは、
   #40/#45の担当と確認してからジョブ投入手順を確定する。

既存`Storage.resolve`のホスト・raw配列順、DBの原本パス、既存payload・保存形式は変更しない。
本番のcollect/prepはubuntu-1の監視を使い続ける。既に検証したキャッシュの推論は
元媒体が停止しても継続可能とし、追加の複製を止める。媒体停止の解除やreadonly解除は既存の手動復帰手順に従う。
複製中の停止・SHA不一致はこの配備案の呼出し元が「保留」として扱う。自動scheduler連携は今回追加しない。
stagingは対象バッチだけ再生成し、参照中の公開バッチは削除しない。容量上限・保持期間は恒久配備前に決める。

## rawの実機確認

ORICO・SUNEASTからJPEG各1枚、合計15,408,105 byteを、元媒体を変更せず複製した。
ubuntu-1の既存監視が利用可能を返した状態でstageし、ubuntu-2の
`/mnt/data/work/issue-42/raw-cache/batch-1`へ検証後に公開した。
原本・転送後のSHA-256は一致した。

| 媒体 | byte | SHA-256 |
| --- | ---: | --- |
| ORICO | 2,600,158 | `f2f11a4ca2f468b08be98dc3b5a9efc755aff95afd9a5359f5e82336c7be81be` |
| SUNEAST | 12,807,947 | `b07074bc30a80f98efc421bbd8a18df4d8e4506695a31bb411c864dc53a5e20f` |

GPUノードで既存segmentの`_hash`とPillowの`load`を呼び、
それぞれ2362×1780・5107×3405画素のJPEGとして復号できた。
ハッシュ読取りは0.00469秒・0.02234秒だったが、転送直後のキャッシュを含むローカル測定でありLANのスループットではない。
これは一時キャッシュでの到達確認であり、本番segmentジョブ・GPU推論・DB登録の確認ではない。
複数ノード同時転送や代表的スループットの比較は未実施。2枚の結果から方式間の速度差を主張しない。

## NFS試験の隔離と再実行手順

サーバーubuntu-2に`/mnt/data/work/issue-42/nfs-test`を作り、
`exportfs -i -o rw,sync,no_subtree_check,root_squash 192.168.1.85:<試験パス>`で一時exportする。
試験ファイルは所有者UID/GID 1000。baselineと未読のread-15・read-630にそれぞれ1MiBを用意する。
恒久`/etc/exports`・`exports.d`・fstabは変更しない。

サーバーでのファイル準備例（専用ディレクトリが未作成のときだけ実行）:

```sh
test ! -e /mnt/data/work/issue-42/nfs-test
mkdir -p /mnt/data/work/issue-42/nfs-test
python3 - <<'PY'
import hashlib
import os
from pathlib import Path
root = Path('/mnt/data/work/issue-42/nfs-test')
for name in ('baseline', 'read-15', 'read-630'):
    data = os.urandom(1024 * 1024)
    (root / name).write_bytes(data)
    print(name, hashlib.sha256(data).hexdigest())
PY
sudo -n exportfs -i -o rw,sync,no_subtree_check,root_squash \
    192.168.1.85:/mnt/data/work/issue-42/nfs-test
```

`ops/deploy/nfs-isolated-test.py`をubuntu-1の専用領域へ転送し、監査付きSSHでsudo実行する。
スクリプトは専用net/mount名前空間を作り、mount伝播をprivateにする。
実行例は`sudo -n python3 -u /var/tmp/issue-42/nfs-isolated-test.py --durations 15 630`。
名前空間内のloopback:20490を、名前空間作成前に確立した
ubuntu-1:742→ubuntu-2:2049の専用TCP接続へ中継する。
予約送信元portでsecure exportの条件を満たす。ホストの経路・firewall・NFS serviceを操作しない。
NFSクライアントを別ネットワーク名前空間に分け、本番との接続共有も避ける。

試験マウントは`/mnt/issue42-test`、
`vers=4.2,proto=tcp,hard,timeo=600,retrans=2,nconnect=1,nosharecache,port=20490`。
障害注入は**専用中継の転送だけを15秒・630秒止める**。
export解除やNFS service停止、ホスト全体の通信遮断は断の手段に使わない。
無応答の模擬であり、ホスト電源断・サーバー再起動を網羅しない。
サーバーが停止中の上流TCPを閉じた場合は、転送再開後に中継の専用接続だけを再確立する。
`setns`による切替は中継スレッド内だけで行い、元のホスト側ネットワーク名前空間で接続後、
試験用名前空間に戻る。本番の既存TCP接続は操作しない。

未読ファイルの読取りと、別ファイルへのwrite・fsync・rename・読戻しをUID/GID 1000の別プロセスで実行する。
復旧後は通常umountし、スクリプト終了で名前空間を破棄する。
最後にサーバーの**試験exportだけ**を`exportfs -u 192.168.1.85:<試験パス>`で撤去する。
試験生成ファイルだけを片付け、実測ログと原本キャッシュ・試験DBデータは証跡として保持する。

## 待機・復帰と10分リース

短時間の断では、読取りとwrite/fsync/rename/読戻しの両方が待機し、復帰後に終了コード0で完了した。
読取りのSHAはサーバーの事前値と一致した。hardでは`timeo=600`・`retrans=2`を過ぎても
エラー終了する保証はなく、復旧待ちのままになる。

再接続対応後の最終実測:

| 停止設定 | 読取りのI/O経過 | 書込み・fsync・rename・読戻しの経過 | 転送再開からの完了待ち | 結果 |
| --- | ---: | ---: | --- | --- |
| 15秒 | 15.008秒 | 15.051秒 | 読取り0.061秒・書込み0.104秒 | 両方exit 0・SHA一致 |
| 630秒（停止実測630.101秒） | 630.171秒 | 630.258秒 | 読取り0.104秒・書込み0.192秒 | 上流TCP再接続後、両方exit 0・SHA一致 |

長時間試験では600.088秒時点も両PIDが`rpc_wait_bit_killable`で待機し、終了していなかった。
読取りSHAは`b45d20d64284aa502d4d34fd1ee6b4a95d78d2f8ae0fbb165c2d8478db246f55`、
書込み・読戻しSHAは`a5e51e42f801cd6b8470db595808966c52e7dc0dee1a8edb7be1c3b8eea09cea`。
前者はサーバーの事前SHA、後者は既知の書込み内容と一致する。

初回の長時間断では、閉じた上流TCPを再接続しない中継の制約で復帰できなかった。
試験子プロセスだけを終了して通常umountし、中継を修正して上表の再試験を完了した。
初回長時間試験は成功に含めない。

リースはNFSの状態と別に扱う。既存Workerは子のprepareを待ちながら親が200秒ごとに更新する。
親のDB接続・監視が応答すれば、子が10分以上待ってもリースは継続し得る。
一方、親自身が`storage_available`内のstat/statvfsや、complete内のrenameで待つと、
親ループからの更新・停止フラグ確認も進まない。ここは実装からの判断であり、
今回のI/O子プロセス試験を本番Worker全体の停止応答確認とは扱わない。

`ops/deploy/nfs-lease-probe.py`は、localhost:55442のIssue42専用PostgreSQL 16を使う。
本番クラスタと分離し、実Queue・既定600秒のリースを短縮せずに測る。
片方だけを更新し、更新しない側を期限後に再claimして、旧所有者のcompleteを拒否することを確認する。
NFS試験と並行する独立のQueue試験であり、NFSによる親停止を直接注入する試験ではない。
実測では200.02秒・400.02秒・610.02秒で片方を更新し、未更新側を610.03秒で
attempt=2として回収した。更新側はattempt=1を維持し、旧所有権のcompleteは`LeaseLost`で拒否された。
`processing_run`は0件だった。

最初のprobeには`complete`のregister引数漏れがあり、リース更新・回収後の最終呼出しで失敗した。
事前保存した旧トークンを使って正しいAPI引数で拒否・run未確定を別途確認した。
保存した再実行用スクリプトは修正済み。旧probe全体を成功したものとは扱わない。

断時は対象ワーカーの新規投入を止め、PID・待機箇所・DBのリースを確認する。
本番mountを強制解除したりsoft化したりせず、サーバー・経路を復旧する。
復旧後も、ファイル存在だけで成功扱いせずDBの採用run・所有権を確認する。
更新が失われた試行は10分経過後のclaimで回収される。旧試行のファイルが残り得るため、
参照されていないことを確認せず削除しない。

## 完成条件と未適用範囲

rawの選定・配備案、一時複製による到達確認、隔離NFSの断・復帰記録を対象とする。
恒久設定の適用と本番ワーカーでの原本入力はユーザー確認後のため、Issue #42全体は未完了。
PRは`Refs #42`とし、自動closeさせない。

確認事項は採用方式、GPUノードの恒久キャッシュ配置・容量上限・保持期間、
assetと原本入力runの由来を保持する投入手順。適用とサービス起動は今回の範囲に含めない。

## 検証・証跡

- ruff 0.17.3: 追加Pythonスクリプト3本と新規テストで成功。中継修正後も対象ファイルだけ再確認した。
- pytest 9.2.0: `test_raw_replica.py`・`test_queue.py`・`test_worker_storage.py`の**30件成功**（17.14秒）。
  PostgreSQLを必要とするテストもlocalhost:55442の一時DB・一時schemaで実行した。
- `derived-client.sh`のbash構文確認成功。Windows作業コピーのCRLFをLinux試験コピーだけLFにして確認した。
- 原本2枚の転送前後のSHA一致、GPUノードでの画像復号成功。
- モデル重み・GPU推論・本番ジョブ投入・複数GPUの同時性能試験・ホスト再起動試験は未実施。

Ubuntu側の`/mnt/data/work/issue-42`にソース・試験DBデータ・原本キャッシュを保全し、
`/var/tmp/issue-42`にNFS試験のI/Oログを保全する。他Issue領域へ出力しない。
検証Pythonは既存#40環境を読取りだけに使用し、ruff/pytest・pip cache・pycache・pytest出力はIssue42領域に分離した。

Windowsの監査ログは`%USERPROFILE%/.codex/logs/commands/`。

| 内容 | ログ |
| --- | --- |
| 一時export追加・事前SHA | `20261102T034703Z-fdb4cad7236e4f719b1e042f6a0b9de6.jsonl` |
| 最初のNFS試験（15秒成功、長時間復帰は中継切断で中断） | `20261102T034707Z-5fe96930df9a41efb948a0abae0bd53c.jsonl` |
| 再接続対応後のNFS試験 | `20261102T040100Z-3df20ac3154849b3a558c6ea7d761666.jsonl` |
| 原本stage | `20261102T035141Z-6ce67f0516d2437fa350b5d0f80076b6.jsonl` |
| 原本publish | `20261102T035154Z-757847c230df4b69882394d95f90bf6b.jsonl` |
| 原本復号・シェル構文 | `20261102T035839Z-e45074abf3a04430be1f3721cd4aa304.jsonl` |
| ruff・30テスト | `20261102T035727Z-38dc3405792641b8979485f61a4172c2.jsonl` |
| 中継修正後のruff | `20261102T040138Z-4bda1be9840b4ab9bdd2d9181735c9c8.jsonl` |
| 600秒リース更新・失効回収（最終API呼出しの引数漏れあり） | `20261102T034925Z-48fb3adc6d4443a999677371ec013c16.jsonl` |
| 旧所有権の拒否・更新側非回収・run未確定 | `20261102T040057Z-9d077208737f492f8ffadfaeac12a0f2.jsonl` |
| 一時PostgreSQL停止 | `20261102T040146Z-18fc3328848d472d932b6bae2329ff5b.jsonl` |
| クライアント撤去・本番mount・停止状態 | `20261102T041200Z-584d0fa985564ff7a2f4854aab5721e7.jsonl` |
| 試験export・生成ファイル撤去、恒久設定照合 | `20261102T041203Z-3da157f4d10d46eb88854edd6831fac3.jsonl` |

終了時、試験mountpoint・試験export・export内の生成ファイルは撤去済み。
サーバーのexportは元のderivedだけ。本番derivedは`hard,timeo=600,retrans=2`を維持し、
パイロット3サービスはinactive、3停止フラグも維持した。一時PostgreSQLの55442待受もない。
恒久設定のSHA-256は事前値と一致した:

- ubuntu-1 `/etc/fstab`: `29057994d689fea9aac8917ca9fa4d739d13a3c612f6eedb1feec8bc15a7de11`
- ubuntu-2 `/etc/fstab`: `6ebebe179691f23a2528f1e05bc07d815ef575a91858b4dd537fc8682f0dc007`
- ubuntu-2 `/etc/exports`: `3f95c811c082f8c8a0cfda159146c0ce388a37248fe173907a5cb57c98f2fee3`

最初の全追跡ファイルarchiveのSCPは、秘密を含む可能性とpayloadの明示承認不足を理由に
自動権限審査で拒否され、実行していない。設定・データを含まないPythonソースと
確認済み試験ファイルだけへ限定して審査を受け直し、許可された転送で検証した。
