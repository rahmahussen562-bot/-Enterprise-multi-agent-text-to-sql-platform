"""Read deployment capabilities without displaying secret values."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit

ROOT=Path(__file__).resolve().parents[1]
for path in (Path('D:/AGENTS.md'),ROOT.parent/'AGENTS.md',ROOT/'AGENTS.md'):
    if path.exists():
        print('INSTRUCTIONS: '+str(path)+'\n'+path.read_text(encoding='utf-8'))
binary_names=('docker','podman','cloudflared','wrangler','gh','wsl','ssh')
presence={name:shutil.which(name) for name in binary_names}
known=[Path('C:/Program Files/Docker/Docker/resources/bin/docker.exe'),Path('D:/Docker'),Path('D:/BIRD-Interact/.github/workflows')]
git=subprocess.run(['git','remote','get-url','origin'],cwd=ROOT,capture_output=True,text=True)
remote=git.stdout.strip()
if '://' in remote:
    parts=urlsplit(remote)
    remote=urlunsplit((parts.scheme,parts.hostname or '',parts.path,'',''))
proof={'binaries':presence,'known_paths':{str(path):path.exists() for path in known},'repository_remote':remote if git.returncode==0 else None,
    'credentials_present':{name:bool(os.environ.get(name)) for name in ('DOCKER_HOST','CLOUDFLARE_API_TOKEN','CLOUDFLARE_ACCOUNT_ID','TUNNEL_TOKEN','GITHUB_TOKEN','GH_TOKEN','SENTINEL_DEPLOY_HOST')},
    'd_free_bytes':shutil.disk_usage('D:/').free}
(ROOT/'.runtime/phase56-environment.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
print(json.dumps(proof,indent=2))
