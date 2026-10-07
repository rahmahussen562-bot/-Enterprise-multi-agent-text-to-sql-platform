import os
import json
from pathlib import Path
import subprocess
import sys
root = Path('D:/BIRD-Interact/frontend')
for name,folder in {'TEMP':'tmp','TMP':'tmp','TMPDIR':'tmp','npm_config_cache':'npm-cache','PLAYWRIGHT_BROWSERS_PATH':'browsers'}.items():
    path=root/'.runtime'/folder;path.mkdir(parents=True,exist_ok=True);os.environ[name]=str(path)
os.environ['NODE_OPTIONS']='--max-old-space-size=768 --max-semi-space-size=2'
node=root/'.runtime'/'node'/'node.exe'
if '--audit' in sys.argv:
    audit=subprocess.run([str(node),str(root/'.runtime'/'node'/'node_modules'/'npm'/'bin'/'npm-cli.js'),'audit','--json'],cwd=root,capture_output=True,text=True)
    (root/'.runtime'/'dependency-audit.json').write_text(audit.stdout,encoding='utf-8')
    result=json.loads(audit.stdout)
    print(json.dumps(result.get('metadata',{}),indent=2))
elif '--dev' in sys.argv:
    subprocess.run([str(node),'tools/run.mjs','dev'],cwd=root,check=True)
else:
    subprocess.run([str(node),'tools/generate-api.mjs'],cwd=root,check=True)
    subprocess.run([str(node),'tools/generate-api.mjs','--check'],cwd=root,check=True)
    subprocess.run([str(node),'tools/verify-source.mjs'],cwd=root,check=True)
    subprocess.run([str(node),'tools/run.mjs','build'],cwd=root,check=True)
    subprocess.run([str(node),'tools/run.mjs','test'],cwd=root,check=True)
