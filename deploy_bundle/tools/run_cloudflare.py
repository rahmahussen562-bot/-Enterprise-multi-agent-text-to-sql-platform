"""Pinned Cloudflare CLI with local caches/configuration/logs confined to D:."""
import os
from pathlib import Path
import subprocess
import sys

front=Path('D:/BIRD-Interact/frontend')
if not front.is_dir() or front.drive.upper()!='D:':
    raise SystemExit('Provision the D: frontend workspace first.')
for key,folder in {'TEMP':'tmp','TMP':'tmp','TMPDIR':'tmp','npm_config_cache':'npm-cache',
        'npm_config_prefix':'npm-global','npm_config_logs_dir':'npm-cache/_logs',
        'XDG_CONFIG_HOME':'config','XDG_CACHE_HOME':'cache','WRANGLER_HOME':'wrangler'}.items():
    path=front/'.runtime'/folder
    path.mkdir(parents=True,exist_ok=True)
    os.environ[key]=str(path)
os.environ['WRANGLER_LOG_PATH']=str(front/'.runtime/wrangler/wrangler.log')
os.environ['PATH']=str(front/'.runtime/node')+os.pathsep+os.environ['PATH']
os.environ['npm_config_update_notifier']='false'
node=front/'.runtime/node/node.exe'
npm=front/'.runtime/node/node_modules/npm/bin/npm-cli.js'
if '--dry-run' not in sys.argv and '--version' not in sys.argv and (
        not os.getenv('CLOUDFLARE_API_TOKEN') or not os.getenv('CLOUDFLARE_ACCOUNT_ID')):
    raise SystemExit('Supply Cloudflare credentials through protected environment configuration first.')
subprocess.run([str(node),str(npm),'exec','--yes','--package=wrangler@4.136.3','--','wrangler',*sys.argv[1:]],cwd=front,check=True)
