"""Run frontend release checks with explicit endpoints and all local artifacts on D:."""
import json
import os
from pathlib import Path
import subprocess

front=Path('D:/BIRD-Interact/frontend')
bundle=front.parent/'deploy_bundle'
node=front/'.runtime/node/node.exe'
for name,folder in {'TEMP':'tmp','TMP':'tmp','TMPDIR':'tmp','npm_config_cache':'npm-cache','npm_config_prefix':'npm-global','npm_config_logs_dir':'npm-cache/_logs','PLAYWRIGHT_BROWSERS_PATH':'browsers'}.items():
    directory=front/'.runtime'/folder
    directory.mkdir(parents=True,exist_ok=True)
    os.environ[name]=str(directory)
os.environ.update(VITE_API_BASE_URL='https://api.sentinelsql.internal/api/v1',VITE_WS_BASE_URL='wss://api.sentinelsql.internal/api/v1',SENTINEL_PRODUCTION_BUILD='1',VITE_ENABLE_VOICE_INPUT='false',NODE_OPTIONS='--max-old-space-size=768 --max-semi-space-size=2')
for arguments in [['tools/generate-api.mjs','--check'],['tools/verify-source.mjs'],['tools/run.mjs','test'],
        ['--test','tools/pages-security.test.mjs',str(bundle/'edge/gateway.test.mjs')],['tools/run.mjs','build']]:
    subprocess.run([str(node),*arguments],cwd=front,check=True)
audit=subprocess.run([str(node),str(front/'.runtime/node/node_modules/npm/bin/npm-cli.js'),'audit','--json'],cwd=front,capture_output=True,text=True)
result=json.loads(audit.stdout)
(front/'.runtime/phase56-dependency-audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result.get('metadata',{}),indent=2))
if audit.returncode or result.get('metadata',{}).get('vulnerabilities',{}).get('total',1)!=0:
    raise SystemExit('Frontend dependency audit did not pass.')
