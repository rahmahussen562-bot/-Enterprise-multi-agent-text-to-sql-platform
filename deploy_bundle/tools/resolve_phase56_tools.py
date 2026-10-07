"""Resolve public release metadata; never read or print account credentials."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / '.runtime/phase56-tools'
directory.mkdir(parents=True, exist_ok=True)
session = requests.Session()
session.headers['User-Agent'] = 'SentinelSQL-release-validation'

def get(url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()

def action(item):
    repo, tag = item
    value = get(f'https://api.github.com/repos/{repo}/git/ref/tags/{tag}')['object']
    if value['type'] == 'tag':
        value = get(value['url'])['object']
    if value['type'] != 'commit' or len(value['sha']) != 40:
        raise ValueError('Invalid action reference.')
    return repo, {'tag':tag,'sha':value['sha']}

items = [('actions/checkout','v6'),('actions/setup-python','v6'),('actions/setup-node','v6'),
    ('actions/upload-artifact','v6'),('docker/setup-buildx-action','v3'),
    ('docker/login-action','v3'),('docker/build-push-action','v7'),('cloudflare/wrangler-action','v4')]
if '--images-only' in sys.argv:
    actions, packages = {}, {}
else:
    with ThreadPoolExecutor(max_workers=4) as executor:
        actions = dict(executor.map(action,items))
    packages = {name:get(f'https://pypi.org/pypi/{name}/json')['info']['version'] for name in ['PyYAML','cryptography','ruff']}
images = {}
for repo, tag in [('library/python','3.14.7-slim-bookworm'),('library/postgres','17.11-bookworm'),('cloudflare/cloudflared','2026.10.0')]:
    token = get('https://auth.docker.io/token?service=registry.docker.io&scope=repository:'+repo+':pull')['token']
    response = session.get(f'https://registry-1.docker.io/v2/{repo}/manifests/{tag}',headers={
        'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json'},timeout=30)
    response.raise_for_status()
    images[repo+':'+tag] = response.headers['Docker-Content-Digest']
result={'actions':actions,'packages':packages,'images':images}
(directory/'versions.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
