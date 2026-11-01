import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.home()/'.codex/scripts'))
import ssh_logged
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--host',required=True);p.add_argument('--directory',required=True);p.add_argument('--command',required=True);p.add_argument('--preview',action='store_true')
a=p.parse_args();targets=json.loads((root/'.ssh-targets.json').read_text(encoding='utf-8'))
if a.host not in targets:p.error('登録されていないホスト名です。AGENTS.mdと接続先を確認してください。')
args=['--target',targets[a.host],'--directory',a.directory,'--command',a.command,'--project',str(root)]
if a.preview:args+=['--preview']
raise SystemExit(ssh_logged.main(args))
