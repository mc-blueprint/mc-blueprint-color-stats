## Ubuntu接続先

| ホスト名 | 接続先 |
| --- | --- |
| ubuntu-0 | toumokorosi@192.168.1.46 |
| ubuntu-1 | toumokorosi@192.168.1.85 |
| ubuntu-2 | toumokorosi@192.168.1.86 |

## SSH運用
- グローバルAGENTS.mdの共通規約に従う。上表の接続先へのSSH・再接続・テスト・読み取り探索は追加確認不要。未登録の接続先と、周囲へ影響する破壊的変更は事前確認する。
- `python scripts/ssh.py --host ubuntu-0 --directory /絶対パス --command "pwd"`で接続する。--hostは上表の名前を指定し、--previewで接続せず確認できる。接続先定義は.ssh-targets.jsonにあり、変更時は上表と一緒に更新する。
- コマンド・作業場所・出力・終了コードは~/.codex/logs/commands/へ記録する。Ubuntuへの環境構築は依頼に含めない。
