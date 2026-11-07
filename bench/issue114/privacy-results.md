# バッチ1：自動人物判定と目視サンプル（2026-11-07）

ユーザー決定に従い「自動判定＋一部目視」へ変更した。
方式・閾値・取込みの契約は[人物判定計画](privacy-plan.md)、全件集計は[集計JSON](privacy-summary.json)、
解析と保全の最終照合は[検証JSON](privacy-analysis.json)。
画像・個別の判定記録・目視結果はGitへ入れていない。

## 判定確定値

対象は今回収集した2,600枚だけ。採用1,607（人物検出なし1,279、人物maskあり328）、
自動不採用0、目視待ち993。目視待ちの内訳は主体混在660・主体不明1・人物面積超過332。
人物が検出されなかった全体1,700枚のうち、主体条件も満たした1,279枚だけを自動採用した。

人物単独SAM2/DINO補助検出は両hostで完了した。人物率の中央値0%、90%点9.4324%、95%点48.7528%。
高面積群を人物主体と断定せず保留にする。採用上限1%は膨張後maskの運用上限であり、
人物不在や識別不能を保証する検証済み精度ではない。目視サンプルの確認まで統計更新しない。

人物検出はscore 0.35 / text 0.25、maskを2px膨張、膨張後1%以下を少量とする。
主体は建物・地形のmask和集合の大きい方が5%以上、差が2ポイント以上の場合だけ固定する。
quality.privacy_reviewの全2,600件へ自動判定者・方式と版・閾値・主体・採否・mask/SHA・根拠を登録済み。
モデルの追加取得・外部API通信・取得画像保存先の変更は行っていない。

## 非公開の目視用データ

ユーザーがWindowsを操作できないため、現在の提示は[携帯端末用HTMLと会話の番号返信](mobile-review.md)を使う。
以下は従来の内部閲覧ツールの記録であり、ユーザーへJSONのダウンロード・返送は要求しない。

- Windows：`H:/mc-blueprint/private/issue114-review-20261107/review-v2/index.html`
- Ubuntu-2：`/mnt/data/work/issue-114/batch1-20261106/review-v2-ready/index.html`
- 無作為100枚（seed=11420261107）と閾値付近40枚、重複除去後の必須確認138枚。
- 目視待ち全件も含む一覧は1,074枚、取得画像・解析画像・mask重畳PNGは計3,222ファイル。
- 転送tarは2,838,507,520 byte、SHA256：
  `23d74a41363edbf0cf00a55efe9d59bdc1c7faece85faf997d88bdb447007c4a`。
  H:側で同じSHA、全画像参照の存在、外部URLなしを確認済み。
- 画像複製・HTML・manifest・共有tar・H:側コピーを保持台帳へ登録した。
  H:専用フォルダ内にGit除外を置き、画像をリポジトリ外へ分離した。

HTMLで「無作為」「閾値付近」を検索し、取得画像・解析画像・赤色maskを確認して判定欄を記入する。
確認者名を入力し、必要な138枚の確認後、誤りがなければ確認欄へチェックしてJSON保存する。
誤りがあれば該当欄に記入して保留・不採用にする。修正maskは解析画像と同寸のPNGを用意する。
`privacy-review-results.json`と必要なmaskを担当へ返す。取込みコマンドは人物判定計画に記載した。
取込みは過去記録を保全し、見落とし・判定変更・mask修正時は承認を出さず再解析へ戻す。

## 配備・実行枠

- 実装commit：f6cd346、取得画像replica対応：b42b5d1、目視承認・統計分母の照合：6d7c81b。
- 解析の実配備はb42b5d1のLF archive、SHA256：
  `f9fa261b0ea8dbb1d60da0a785d9e143412b7254921f44f025ea2891b1cfa196`。
- ubuntu-1：`/opt/colorstats/work/issue114-auto-v2-20261107-r2`
- ubuntu-2：`/mnt/data/work/issue-114/batch1-20261106/auto-v2-code-r2`
- 新実行枠：`/mnt/data/derived/issue114-batch1-20261106/auto-v2`。
  ubuntu-1 646枚／ubuntu-2 961枚。既存成功segmentを固定し、shade/colorだけを新規実行する。
- unit：`colorstats-issue114-auto-u1-r2` / `colorstats-issue114-auto-u2-r2`。
  両hostの3件smokeは三段階完了で成功し、全量も成功した。
- 目視取込み・統計承認用は`review-code-r3`（6d7c81b）へ別配備した。
  archive SHA256は`fda1d63a29100a9da729f1d30be2bb83d9d361a2043eda278205845ee133debf`。
  稼働中の解析実装が同一であることを照合し、実行中の配備は変更していない。

元の5200 job・5200 prep/segment runの行hashと、元manifest/reportの4ファイルSHAを実行前に固定した。
元の失敗shade jobを再試行可能へ戻していない。既存segment・旧統計を上書きしていない。
新しいsnapshot・rule_stat・report・#105訂正v2比較はユーザーの目視結果待ちで未実施。
Windows側の常駐監視processは作らず、短い記録付きSSH照会だけで監視する。

2026-11-07 10:01 JSTまでに解析・最終照合が終了した。
ubuntu-1 646枚・ubuntu-2 961枚、合計1,607枚のsegment再利用と新規shade/color完了を照合した。
新規shade/colorは各1,607 job成功・失敗0・再試行0、両段階とも328 jobで固定person_maskを使用した。
各payloadの入力SHAと現在のprivacy_review・mask/SHAも一致した。
shadeのpart_observationは42,428件、colorのpart_observationは212,129件・relationは599,977件。

元artifact 74,865ファイル・元job 5,200行・元prep/segment run 5,200行・元manifest/report 4ファイルは変更0。
収集前のasset 7,626行・run 42,314行も変更0。新aggregate jobは0件、目視承認ファイルは存在しない。
解析unit2つと最終照合unit `colorstats-issue114-auto-verify` は全てResult=success、MainPID=0、inactive。
目視結果待ちであり、新統計・旧版比較は未着手のまま保全した。
最終照合ログは`20261107T010102Z-5c53a5c57f664d3f870cd4b4850b14ea.jsonl`。

## 起動時の修正と保全

最初の補助検出は不要なduckdb importで起動失敗し、host別の接続と既存deps指定で修正した。
顔promptの大面積誤検出版privacy-v1は採用せず、全結果を保全して保持台帳に登録した。
最初の閲覧生成はubuntu-2に原画像mountがなく失敗した。原保存先は変更せず、
閲覧対象1,074枚・427,984,748 byteだけをubuntu-1から共有領域へ保持付きreplicaとして作成した。
複製元・複製後・閲覧時にAsset.sha256との一致を照合している。

WindowsのGit archiveはcore.autocrlfによりシェルをCRLF化するため、最初の解析unitはjob処理前に終了した。
`git -c core.autocrlf=false archive`でGit blobのLFを保持した別配備を作り、内容一致を検証して再開した。
Gitの保存設定、既存配備、失敗unit・部分出力を変更・削除していない。元のDBへ復元していない。

## 検証

最終WSL Ubuntu-24.04 / 隔離PostgreSQL16込み全pytestは **1,077 passed / 1 skipped、218.78秒**。
ruff、sdist/wheel build、解析シェルのbash構文確認が成功。
自動判定境界、目視上書き・承認取消し、mask伝播と既存segment再利用、
未mount取得画像の明示replica参照、閲覧複製の0600/0700・保持登録を検証した。
ログ `20261107T002209Z-2887508364084d52849869bd1d73cc9d.jsonl`、
artifact `/tmp/colorstats-issue114-2qm9Yh/`。隔離DB・検証processの終了を確認済み。
skipは実GPU条件付きのpytestで、今回の実GPU人物補助検出完了とは区別する。
