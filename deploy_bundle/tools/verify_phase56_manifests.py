"""Static manifest contract checks, distinctly separate from Docker/live validation."""
import ast
import json
from pathlib import Path
import tomllib
import yaml

ROOT=Path(__file__).resolve().parents[1]
compose=yaml.safe_load((ROOT/'docker-compose.prod.yml').read_text(encoding='utf-8'))
workflow=yaml.load((ROOT.parent/'.github/workflows/deploy.yml').read_text(encoding='utf-8'),Loader=yaml.BaseLoader)
services=compose['services']
assert set(services)=={'fastapi','fincore_postgres','cloudflared','private_ingress'}
assert not any(service.get('ports') for service in services.values())
assert services['fastapi']['user']=='10001:10001' and services['fastapi']['read_only']
assert services['fastapi']['cap_drop']==['ALL']
for name, service in services.items():
    for mount in service.get('tmpfs', []):
        assert isinstance(mount, str) and mount.split(':', 1)[0].startswith('/'), f'{name}: tmpfs entries must have absolute mount paths'
assert compose['networks']['database']['internal']
assert 'ssl=on' in services['fincore_postgres']['command']
assert '--token-file' in services['cloudflared']['command']
assert 'SENTINEL_SESSION_KEY_FILE' in services['fastapi']['environment']
assert 'pull_request' in workflow['on'] and 'main' in workflow['on']['push']['branches']
jobs=workflow['jobs']
assert jobs['container-tests']['needs']==['backend-tests','frontend-tests']
assert jobs['release']['needs']==['container-tests']
assert jobs['pages-deploy']['needs']==['backend-deploy']
assert jobs['backend-deploy']['runs-on']==['self-hosted','sentinelsql-production']
workflow_text=(ROOT.parent/'.github/workflows/deploy.yml').read_text(encoding='utf-8')
for secret in ['CLOUDFLARE_API_TOKEN','CLOUDFLARE_ACCOUNT_ID','TUNNEL_TOKEN']:
    assert 'secrets.'+secret in workflow_text
assert 'npm audit --audit-level=low' in workflow_text
assert 'run_ci_backend.py' in workflow_text and 'smoke_container.py' in workflow_text
worker=tomllib.loads((ROOT/'edge/wrangler.toml').read_text())
assert not worker['workers_dev'] and len(worker['ratelimits'])==2
pages=tomllib.loads((ROOT.parent/'frontend/wrangler.toml').read_text())
assert pages['name']=='sentinelsql-portal' and pages['pages_build_output_dir']=='dist'
assert (ROOT.parent/'frontend/public/_redirects').read_text().strip()=='/* /index.html 200'
for folder in ['api','core','agents']:
    for path in (ROOT/folder).glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'))
result={'yaml_and_toml':'passed','tmpfs_mount_paths':'passed','private_ports':'passed','secret_file_mounts':'passed',
    'release_gate_dependencies':'passed','pages_project':'sentinelsql-portal',
    'container_build':'not assessed by this static validator; run the container CI gate',
    'live_cloudflare_deployment':'not assessed by this static validator; run the live ingress/release gate',
    'private_ingress':'requires trusted institutional certificate and WARP hostname routing'}
(ROOT/'docs/PHASE56_MANIFEST_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
