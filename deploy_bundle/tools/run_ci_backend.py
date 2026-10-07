"""Linux CI: run every native PostgreSQL test using an owned ephemeral container."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def main():
    directory = ROOT / '.runtime/ci-postgres'
    directory.mkdir(parents=True,exist_ok=True)
    password = secrets.token_urlsafe(32)
    env_file = directory / 'postgres.env'
    env_file.write_text('POSTGRES_USER=sentinel_ci\nPOSTGRES_PASSWORD='+password+'\nPOSTGRES_HOST_AUTH_METHOD=scram-sha-256\n',encoding='utf-8')
    env_file.chmod(0o600)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        port = probe.getsockname()[1]
    name = 'sentinel-ci-' + secrets.token_hex(8)
    dsn_file = directory / 'admin.conninfo'
    from psycopg.conninfo import make_conninfo
    import psycopg
    dsn_file.write_text(make_conninfo(host='127.0.0.1',port=port,dbname='postgres',user='sentinel_ci',password=password,connect_timeout=2),encoding='utf-8')
    dsn_file.chmod(0o600)
    image = os.getenv('POSTGRES_IMAGE','postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826')
    try:
        subprocess.run(['docker','run','--detach','--name',name,'--env-file',str(env_file),
            '--publish',f'127.0.0.1:{port}:5432',image,'postgres','-c','log_statement=none','-c','log_min_error_statement=panic'],check=True,stdout=subprocess.DEVNULL)
        deadline = time.monotonic()+90
        while True:
            try:
                with psycopg.connect(dsn_file.read_text()) as connection:
                    assert int(connection.execute('SHOW server_version_num').fetchone()[0]) >= 170000
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('CI PostgreSQL readiness timeout.') from None
                time.sleep(1)
        environment = dict(os.environ,SENTINEL_TEST_PG_DSN_FILE=str(dsn_file))
        result = subprocess.run([sys.executable,'tools/run_phase01_tests.py','-q','--junitxml=docs/PHASE56_TEST_RESULTS.xml'],cwd=ROOT,env=environment)
        return result.returncode
    finally:
        subprocess.run(['docker','rm','--force','--volumes',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        env_file.unlink(missing_ok=True)
        dsn_file.unlink(missing_ok=True)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('CI database gate failed: '+type(error).__name__,file=sys.stderr)
        raise SystemExit(1) from None
