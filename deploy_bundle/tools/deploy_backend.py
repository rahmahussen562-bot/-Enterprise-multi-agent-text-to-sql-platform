"""Update a preprovisioned self-hosted Compose stack and roll back unhealthy API images.

Credentials/data remain on the runner. GitHub supplies only the tunnel token and
the tested immutable image. Never execute this script from pull request workflows.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def validate_image(value):
    if not re.fullmatch(r'ghcr\.io/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}',value or ''):
        raise ValueError('Deployment requires an immutable GHCR digest.')
    return value

def main():
    image = validate_image(os.environ['FASTAPI_IMAGE'])
    destination = Path(os.environ['SENTINEL_DEPLOY_DIR']).resolve()
    if not destination.is_absolute() or (os.name=='nt' and destination.drive.upper()!='D:'):
        raise ValueError('Use an absolute persistent deployment directory; Windows storage must remain on D:.')
    destination.mkdir(parents=True,exist_ok=True)
    env_file = destination/'.env.production'
    if not env_file.is_file():
        raise ValueError('Provision the private production environment first.')
    secret_dir = Path(os.environ['SENTINEL_SECRETS_DIR']).resolve()
    if not secret_dir.is_dir() or (os.name=='nt' and secret_dir.drive.upper()!='D:'):
        raise ValueError('Preprovision a private secrets directory on the deployment host.')
    token = os.environ.get('TUNNEL_TOKEN','').strip()
    if not token:
        raise ValueError('GitHub TUNNEL_TOKEN secret is required.')
    # Preserve the bind-mounted inode and its preprovisioned group/ACL permissions.
    token_path = secret_dir/'tunnel-token'
    if not token_path.exists():
        raise ValueError('Preprovision tunnel-token with read access for UID/GID 10001.')
    token_path.write_text(token,encoding='utf-8')
    shutil.copyfile(ROOT/'docker-compose.prod.yml',destination/'docker-compose.prod.yml')
    (destination/'ops').mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'ops/postgres-entrypoint.sh',destination/'ops/postgres-entrypoint.sh')
    shutil.copyfile(ROOT/'ops/private-ingress.conf',destination/'ops/private-ingress.conf')
    release = destination/'release.json'
    previous = json.loads(release.read_text())['image'] if release.exists() else None
    environment = dict(os.environ,FASTAPI_IMAGE=image,SECRETS_DIR=str(secret_dir))
    compose = ['docker','compose','--env-file',str(env_file),'-f',str(destination/'docker-compose.prod.yml'),'--profile','edge']
    def run(*args,env=environment):
        subprocess.run(compose+list(args),cwd=destination,env=env,check=True)
    run('config','--quiet')
    run('pull')
    try:
        run('up','--detach','--no-build','--wait','--wait-timeout','120')
        # Check schema through the restricted engine instead of treating /health
        # liveness as database readiness. No administrator credentials enter API.
        probe = "import json,os; from core.auth import load_accounts,session_for_role; from core.postgres import PostgresConfig,PostgresSyncBridge; records=load_accounts(__import__('pathlib').Path(os.environ['SENTINEL_AUTH_FILE'])); [(PostgresSyncBridge(PostgresConfig.for_session(session_for_role(user,record['role']))).get_table_names()) for user,record in records.items()]"
        run('exec','-T','fastapi','python','-c',probe)
        run('exec','-T','fastapi','python','tools/container_health.py')
        # A remotely managed connector is only ready after edge connections form.
        connector_probe = """import time,urllib.request
deadline=time.monotonic()+45
while True:
    try:
        with urllib.request.urlopen('http://cloudflared:2000/ready',timeout=3) as response:
            if response.status==200: break
    except OSError:
        if time.monotonic()>deadline: raise SystemExit('Tunnel readiness timeout.')
        time.sleep(1)
"""
        run('exec','-T','fastapi','python','-c',connector_probe)
        subprocess.run([sys.executable,str(ROOT/'tools/verify_edge.py')],env=environment,check=True)
    except subprocess.CalledProcessError:
        if previous:
            rollback_env = dict(environment,FASTAPI_IMAGE=validate_image(previous))
            run('up','--detach','--no-build','--wait','fastapi',env=rollback_env)
        raise
    release.write_text(json.dumps({'image':image,'commit':os.environ.get('GITHUB_SHA','')},indent=2)+'\n',encoding='utf-8')
    print('Backend released; restricted database schemas, API health and tunnel readiness verified.')

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('Backend deployment failed: '+type(error).__name__,file=sys.stderr)
        raise SystemExit(1) from None
