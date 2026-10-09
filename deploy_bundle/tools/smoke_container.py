"""Test the built API image with actual TLS PostgreSQL/RLS; never reuse production data."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def certificate(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'SentinelSQL ephemeral CI CA')])
    now = datetime.now(timezone.utc)
    ca = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=2)).add_extension(x509.BasicConstraints(ca=True,path_length=0),True).sign(key,hashes.SHA256())
    server_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'fincore_postgres')])
    server = x509.CertificateBuilder().subject_name(server_name).issuer_name(name).public_key(server_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=2)).add_extension(x509.SubjectAlternativeName([x509.DNSName('fincore_postgres')]),False).sign(key,hashes.SHA256())
    (directory/'postgres-ca.crt').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (directory/'postgres-server.crt').write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (directory/'postgres-server.key').write_bytes(server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    (directory/'postgres-server.key').chmod(0o600)

def run(*arguments,**kwargs):
    return subprocess.run(list(arguments),check=True,**kwargs)

def api_request(container, path, payload=None, token=None):
    # Internal Docker networks intentionally prevent host port probes. Exercise
    # the real API over its container loopback; credentials travel only on stdin.
    script = '''import json,sys,urllib.request,urllib.error
config=json.load(sys.stdin)
headers={"Content-Type":"application/json"}
if config["token"]:
    headers["Authorization"]="Bearer "+config["token"]
data=None if config["payload"] is None else json.dumps(config["payload"]).encode()
request=urllib.request.Request("http://127.0.0.1:8000/api/v1"+config["path"],data=data,headers=headers)
try:
    with urllib.request.urlopen(request,timeout=20) as response:
        sys.stdout.write(response.read().decode())
except urllib.error.HTTPError as error:
    print(json.dumps({"http_status":error.code}),file=sys.stderr)
    sys.exit(1)
except urllib.error.URLError as error:
    print(json.dumps({"transport_error_type":type(error.reason).__name__}),file=sys.stderr)
    sys.exit(1)
'''
    result = subprocess.run(['docker','exec','--interactive',container,'python','-c',script],
        input=json.dumps({'path':path,'payload':payload,'token':token}),capture_output=True,text=True)
    if result.returncode:
        # The probe emits only status/type metadata on stderr. Responses and
        # credentials remain captured, including failed login/query payloads.
        try:
            diagnostic = json.loads(result.stderr)
        except ValueError:
            diagnostic = {}
        safe = {key: value for key, value in diagnostic.items()
                if (key == 'http_status' and isinstance(value, int)) or
                   (key == 'transport_error_type' and isinstance(value, str) and value.isidentifier())}
        print('Container API probe failed: '+path+' '+json.dumps(safe),file=sys.stderr)
        raise RuntimeError('Container API probe failed.')
    return json.loads(result.stdout)

def main():
    if os.name == 'nt' and ROOT.drive.upper() != 'D:':
        raise ValueError('Container fixtures must remain on D:.')
    from core.auth import password_hash
    directory = ROOT / '.runtime' / ('container-smoke-'+secrets.token_hex(6))
    directory.mkdir(parents=True)
    private = directory/'secrets'
    private.mkdir(mode=0o700)
    certificate(private)
    password = secrets.token_urlsafe(32)
    user = 'ci_branch_'+secrets.token_hex(4)
    key = secrets.token_bytes(32)
    (private/'session.key').write_bytes(key)
    (private/'accounts.json').write_text(json.dumps([{'user_id':user,'role':'branch_analyst','password_hash':password_hash(password)}]),encoding='utf-8')
    (private/'postgres-password').write_text(secrets.token_urlsafe(32),encoding='utf-8')
    (private/'postgres-identities.json').write_text('{}',encoding='utf-8')
    (private/'tunnel-token').write_text('',encoding='utf-8')
    for path in private.iterdir():
        if path.name not in {'postgres-server.key'}:
            path.chmod(0o644)  # Ephemeral CI only: directory 0700 protects host access.
    api_data = directory/'data/api'
    api_data.mkdir(parents=True)
    if os.name != 'nt':
        run('docker','run','--rm','--user','0:0','--mount',f'type=bind,source={api_data},target=/state',
            '--entrypoint','python',os.environ.get('FASTAPI_IMAGE','sentinelsql-api:ci'),
            '-c',"import os; os.chown('/state',10001,10001)",stdout=subprocess.DEVNULL)
    environment = dict(os.environ,FASTAPI_IMAGE=os.environ.get('FASTAPI_IMAGE','sentinelsql-api:ci'),
        FRONTEND_ORIGIN='https://sentinelsql-portal.pages.dev',DATA_ROOT=str(directory/'data'),SECRETS_DIR=str(private),
        POSTGRES_DB='fincore',POSTGRES_ADMIN_USER='sentinel_admin',COMPOSE_PROFILES='')
    project = 'smoke-'+secrets.token_hex(6)
    compose = ['docker','compose','--project-name',project,'-f',str(ROOT/'docker-compose.prod.yml')]
    try:
        run(*compose,'up','--detach','--no-build','--wait',env=environment,cwd=ROOT)
        cid=run(*compose,'ps','--quiet','fastapi',env=environment,cwd=ROOT,capture_output=True,text=True).stdout.strip()
        assert run('docker','inspect','--format','{{.Config.User}}',cid,capture_output=True,text=True).stdout.strip()=='10001:10001'
        assert run('docker','inspect','--format','{{.HostConfig.ReadonlyRootfs}}',cid,capture_output=True,text=True).stdout.strip()=='true'
        # Provision a synthetic fixture through the container network using TLS.
        script = '''import json,os,secrets,sys
sys.path.insert(0,"/app")
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from tools.migrate_fincore import apply_schema
dsn=make_conninfo(host="fincore_postgres",dbname="fincore",user="sentinel_admin",password=open("/fixture/postgres-password").read(),sslmode="verify-full",sslrootcert="/fixture/postgres-ca.crt")
with psycopg.connect(dsn,autocommit=True) as c:
    assert c.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()").fetchone()[0]
    inspection=apply_schema(c)
    login="ci_branch_login"; password=secrets.token_urlsafe(32)
    c.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(sql.Identifier(login),sql.Literal(password)))
    c.execute("GRANT fincore_branch TO ci_branch_login")
    c.execute("INSERT INTO security.principals(db_login,persona) VALUES(%s,%s)",(login,"branch_analyst"))
    user=json.load(open("/fixture/accounts.json"))[0]["user_id"]
    conninfo=make_conninfo(dsn,user=login,password=password,sslrootcert="/run/secrets/postgres-ca.crt")
    json.dump({user:{"role":"branch_analyst","db_login":login,"conninfo":conninfo}},open("/fixture/postgres-identities.json","w"))
    assert inspection["forced_rls_tables"]==17
'''
        setup_script = directory/'setup.py'
        setup_script.write_text(script,encoding='utf-8')
        network = project+'_database'
        run('docker','run','--rm','--user','0:0','--network',network,'--mount',f'type=bind,source={private},target=/fixture',
            '--mount',f'type=bind,source={setup_script},target=/setup.py,readonly','--entrypoint','python',environment['FASTAPI_IMAGE'],'/setup.py',stdout=subprocess.DEVNULL)
        assert api_request(cid,'/health')['status']=='ready'
        token = api_request(cid,'/auth/login',{'user_id':user,'password':password})['access_token']
        def query(path,payload=None):
            return api_request(cid,path,payload,token)
        schema=query('/schema')
        assert schema['dialect']=='postgres' and all(table['name'].startswith('branch.') for table in schema['tables'])
        result=query('/query/execute',{'question':'Show daily balances'})
        assert result['status']=='completed' and result['output']['row_count']==0
        run(*compose,'stop','--timeout','40','fastapi',env=environment,cwd=ROOT,stdout=subprocess.DEVNULL)
        run(*compose,'up','--detach','--no-build','--wait','fastapi',env=environment,cwd=ROOT,stdout=subprocess.DEVNULL)
        cid=run(*compose,'ps','--quiet','fastapi',env=environment,cwd=ROOT,capture_output=True,text=True).stdout.strip()
        assert api_request(cid,'/health')['status']=='ready'
        print('Container gate passed: non-root API, TLS PostgreSQL, 17 FORCE RLS tables, masked schema, clean empty result and graceful stop.')
    finally:
        subprocess.run(compose+['down','--remove-orphans'],env=environment,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        # Keep public evidence; remove ephemeral secrets without deleting data recursively.
        for path in private.iterdir():
            if path.is_file(): path.unlink()

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('Container gate failed: '+type(error).__name__,file=sys.stderr)
        raise SystemExit(1) from None
