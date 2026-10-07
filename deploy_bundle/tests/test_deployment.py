"""Exercise mounted secrets, release rollback and the actual Linux-CI fixture path."""
import json
import os
from pathlib import Path
import secrets
import subprocess

import pytest
import psycopg
from api.auth import SessionAuthority
from api.settings import APISettings
from core.auth import password_hash
from tools import deploy_backend
from tools.postgres_fixture import postgres_fixture, external_postgres_fixture


def mounted_settings(tmp_path,monkeypatch):
    key=secrets.token_bytes(32)
    key_file=tmp_path/'session.key'
    key_file.write_bytes(key)
    accounts=tmp_path/'accounts.json'
    password=secrets.token_urlsafe(24)
    accounts.write_text(json.dumps([{'user_id':'branch_test','role':'branch_analyst','password_hash':password_hash(password)}]))
    monkeypatch.delenv('SENTINEL_SESSION_KEY',raising=False)
    monkeypatch.setenv('SENTINEL_SESSION_KEY_FILE',str(key_file))
    monkeypatch.setenv('SENTINEL_AUTH_FILE',str(accounts))
    monkeypatch.setenv('SENTINEL_API_STATE',str(tmp_path/'jobs.sqlite'))
    return key,password,APISettings.from_environment()


def test_mounted_binary_key_issues_verifiable_sessions(tmp_path,monkeypatch):
    key,password,settings=mounted_settings(tmp_path,monkeypatch)
    authority=SessionAuthority(settings)
    token,claims=authority.login('branch_test',password)
    assert settings.signing_key==key
    assert authority.verify(token)==claims


def test_ambiguous_session_key_sources_fail_startup(tmp_path,monkeypatch):
    mounted_settings(tmp_path,monkeypatch)
    monkeypatch.setenv('SENTINEL_SESSION_KEY',secrets.token_urlsafe(32))
    with pytest.raises(ValueError,match='one session key source'):
        APISettings.from_environment()


def test_short_mounted_key_fails_closed(tmp_path,monkeypatch):
    mounted_settings(tmp_path,monkeypatch)
    Path(os.environ['SENTINEL_SESSION_KEY_FILE']).write_bytes(b'short')
    with pytest.raises(ValueError,match='at least 32'):
        APISettings.from_environment()


def test_backend_release_rolls_back_failed_image_without_deleting_data(tmp_path,monkeypatch):
    destination=tmp_path/'deployment'
    destination.mkdir()
    (destination/'.env.production').write_text('FRONTEND_ORIGIN=https://sentinelsql-portal.pages.dev\n')
    previous='ghcr.io/test/sentinelsql-api@sha256:'+'a'*64
    current='ghcr.io/test/sentinelsql-api@sha256:'+'b'*64
    (destination/'release.json').write_text(json.dumps({'image':previous}))
    data=destination/'customer-data'
    data.write_text('preserve')
    secret_dir=tmp_path/'secrets'
    secret_dir.mkdir()
    (secret_dir/'tunnel-token').write_text('old')
    marker=secrets.token_urlsafe(24)
    monkeypatch.setenv('FASTAPI_IMAGE',current)
    monkeypatch.setenv('SENTINEL_DEPLOY_DIR',str(destination))
    monkeypatch.setenv('SENTINEL_SECRETS_DIR',str(secret_dir))
    monkeypatch.setenv('TUNNEL_TOKEN',marker)
    calls=[]
    def execute(arguments,**kwargs):
        calls.append((arguments,kwargs))
        assert marker not in ' '.join(arguments)
        if 'up' in arguments and kwargs['env']['FASTAPI_IMAGE']==current:
            raise subprocess.CalledProcessError(1,arguments)
        return subprocess.CompletedProcess(arguments,0)
    monkeypatch.setattr(subprocess,'run',execute)
    with pytest.raises(subprocess.CalledProcessError):
        deploy_backend.main()
    assert any('up' in args and options['env']['FASTAPI_IMAGE']==previous for args,options in calls)
    assert json.loads((destination/'release.json').read_text())['image']==previous
    assert data.read_text()=='preserve'
    assert not any('down' in args for args,_ in calls)


def test_release_rejects_mutable_image_tag():
    with pytest.raises(ValueError,match='immutable'):
        deploy_backend.validate_image('ghcr.io/test/sentinelsql-api:latest')


def test_external_ci_fixture_preserves_native_server_and_row_security(tmp_path):
    with postgres_fixture() as outer:
        credentials=tmp_path/'admin.conninfo'
        credentials.write_text(outer['admin_dsn'])
        with external_postgres_fixture(credentials) as inner:
            with psycopg.connect(inner['principals']['branch_a']['conninfo']) as connection:
                assert connection.execute('SELECT count(*) FROM branch.account_summaries').fetchone()[0]>0
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute('SELECT * FROM compliance.compliance_cases')
        with psycopg.connect(outer['admin_dsn']) as connection:
            assert connection.execute('SELECT 1').fetchone()[0]==1
