"""Actual isolated PostgreSQL fixture; binaries/data/secrets stay on D:."""
from contextlib import contextmanager
from datetime import date, timedelta
import getpass
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from core.fincore import PG_GROUPS
from tools.migrate_fincore import apply_schema

class PrivateFixture(dict):
    def __repr__(self):
        return '<FinCore native fixture; credentials redacted>'


def uid(number):
    return UUID(int=number)

def restricted(path):
    if os.name == 'nt':
        subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r',getpass.getuser()+':(OI)(CI)F'],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)

@contextmanager
def postgres_fixture():
    external_file = os.getenv('SENTINEL_TEST_PG_DSN_FILE')
    if external_file:
        with external_postgres_fixture(Path(external_file)) as fixture:
            yield fixture
        return
    if ROOT.drive.upper()!='D:':
        raise RuntimeError('Native fixtures must remain on D:.')
    runtime = ROOT/'.runtime/postgres'
    binaries = runtime/'pgsql/bin'
    if not (binaries/'postgres.exe').exists():
        raise RuntimeError('Provision the D-drive native runtime with tools/install_phase04.py first.')
    private = runtime/'private'
    private.mkdir(parents=True,exist_ok=True)
    restricted(private)
    admin_file = private/'admin.json'
    if admin_file.exists():
        admin = json.loads(admin_file.read_text())
    else:
        admin = {'user':'sentinel_fixture_admin','password':secrets.token_urlsafe(32)}
        admin_file.write_text(json.dumps(admin),encoding='utf-8')
    password_file = private/'initdb-password'
    password_file.write_text(admin['password'],encoding='utf-8')
    cluster = runtime/'cluster'
    assert cluster.resolve().is_relative_to(runtime.resolve())
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    environment = dict(os.environ)
    environment['PATH'] = str(binaries)+os.pathsep+environment.get('PATH','')
    environment['TEMP'] = environment['TMP'] = str(ROOT/'.runtime/tmp')
    if not (cluster/'PG_VERSION').exists():
        initialized = subprocess.run([str(binaries/'initdb.exe'),'-D',str(cluster),'-U',admin['user'],'--pwfile='+str(password_file),
            '--auth-host=scram-sha-256','--auth-local=scram-sha-256','--encoding=UTF8','--locale=C'],env=environment,
            creationflags=flags,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        if initialized.returncode:
            raise RuntimeError('Native initdb failed: '+initialized.stdout[-4000:])
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    options = f'-h 127.0.0.1 -p {port} -c max_connections=24 -c shared_buffers=16MB -c log_statement=none -c log_min_error_statement=panic'
    # A Windows daemon can inherit a pipe and keep communicate() waiting for
    # EOF after pg_ctl exits. Use D-drive files for detached process output.
    with (runtime/'pg_ctl.log').open('a',encoding='utf-8') as output:
        start = subprocess.run([str(binaries/'pg_ctl.exe'),'-D',str(cluster),'-l',str(runtime/'server.log'),'-o',options,'-w','start'],
            env=environment,creationflags=flags,stdout=output,stderr=subprocess.STDOUT,text=True,timeout=75)
    if start.returncode:
        raise RuntimeError('Native pg_ctl start failed; inspect the D-drive fixture logs.')
    database = 'fincore_test_'+secrets.token_hex(6)
    admin_dsn = make_conninfo(host='127.0.0.1',port=port,dbname='postgres',connect_timeout=5,**admin)
    created_roles=[]
    database_created=False
    try:
        print('Native PostgreSQL ready; applying FinCore migration.',flush=True)
        with psycopg.connect(admin_dsn,autocommit=True) as connection:
            # Rotate private administrator credentials every fixture run.
            admin['password']=secrets.token_urlsafe(32)
            connection.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(admin['user']),sql.Literal(admin['password'])))
            admin_file.write_text(json.dumps(admin),encoding='utf-8')
            password_file.write_text(admin['password'],encoding='utf-8')
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
            database_created=True
        admin_dsn = make_conninfo(admin_dsn,dbname=database,password=admin['password'])
        with psycopg.connect(admin_dsn,autocommit=True) as connection:
            inspection=apply_schema(connection)
            print('FinCore migration applied; seeding synthetic banking records.',flush=True)
            principals={}
            suffix=secrets.token_hex(4)
            for key,role in [('branch_a','branch_analyst'),('branch_b','branch_analyst'),('compliance','compliance_officer'),('fraud_a','fraud_investigator'),('fraud_b','fraud_investigator'),('branch_empty','branch_analyst')]:
                login='fc_'+key+'_'+suffix;password=secrets.token_urlsafe(32)
                connection.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Identifier(login),sql.Literal(password)))
                connection.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(PG_GROUPS[role]),sql.Identifier(login)))
                connection.execute('INSERT INTO security.principals(db_login,persona) VALUES(%s,%s)',(login,role))
                created_roles.append(login)
                principals[key]={'role':role,'db_login':login,'conninfo':make_conninfo(admin_dsn,user=login,password=password)}
            seed(connection,principals)
            print('Balanced synthetic ledger and restricted principals seeded.',flush=True)
            version=connection.execute('SHOW server_version').fetchone()[0]
        (runtime/'verification.json').write_text(json.dumps({**inspection,'synthetic_principals':len(principals),
            'fixture_kind':'native PostgreSQL with encrypted synthetic banking records','storage_root':str(runtime)},indent=2)+'\n',encoding='utf-8')
        fixture=PrivateFixture(admin_dsn=admin_dsn,principals=principals,server_version=version,database=database)
        (private/'fixture.json').write_text(json.dumps(fixture),encoding='utf-8')
        yield fixture
    finally:
        try:
            if database_created:
                with psycopg.connect(make_conninfo(admin_dsn,dbname='postgres',password=admin['password']),autocommit=True) as connection:
                    connection.execute(sql.SQL('DROP DATABASE {} WITH(FORCE)').format(sql.Identifier(database)))
                    for login in created_roles:
                        connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(login)))
        finally:
            subprocess.run([str(binaries/'pg_ctl.exe'),'-D',str(cluster),'-m','fast','-w','stop'],env=environment,
                creationflags=flags,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True)

@contextmanager
def external_postgres_fixture(path):
    """Use an ephemeral CI administrator; never skip native RLS tests on Linux."""
    from psycopg.conninfo import conninfo_to_dict
    path = path.resolve()
    if os.name == 'nt' and path.drive.upper() != 'D:':
        raise RuntimeError('CI credentials must remain on D:.')
    dsn = path.read_text(encoding='utf-8').strip()
    options = conninfo_to_dict(dsn)
    if options.get('host') not in {'127.0.0.1','localhost','::1'} and options.get('sslmode') != 'verify-full':
        raise ValueError('Remote CI databases require verified TLS.')
    database = 'fincore_test_' + secrets.token_hex(6)
    created_roles = []
    created = False
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
            created = True
        database_dsn = make_conninfo(dsn, dbname=database)
        with psycopg.connect(database_dsn, autocommit=True) as connection:
            inspection = apply_schema(connection)
            principals = {}
            suffix = secrets.token_hex(4)
            for key, role in [('branch_a','branch_analyst'),('branch_b','branch_analyst'),
                    ('compliance','compliance_officer'),('fraud_a','fraud_investigator'),
                    ('fraud_b','fraud_investigator'),('branch_empty','branch_analyst')]:
                login = 'fc_' + key + '_' + suffix
                password = secrets.token_urlsafe(32)
                connection.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Identifier(login),sql.Literal(password)))
                created_roles.append(login)
                connection.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(PG_GROUPS[role]),sql.Identifier(login)))
                connection.execute('INSERT INTO security.principals(db_login,persona) VALUES(%s,%s)',(login,role))
                principals[key] = {'role':role,'db_login':login,
                    'conninfo':make_conninfo(database_dsn,user=login,password=password)}
            seed(connection, principals)
            version = connection.execute('SHOW server_version').fetchone()[0]
        runtime = ROOT / '.runtime/postgres'
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime/'verification.json').write_text(json.dumps(inspection,indent=2)+'\n',encoding='utf-8')
        yield PrivateFixture(admin_dsn=database_dsn,principals=principals,server_version=version,database=database)
    finally:
        if created:
            with psycopg.connect(dsn,autocommit=True) as connection:
                connection.execute(sql.SQL('DROP DATABASE {} WITH(FORCE)').format(sql.Identifier(database)))
                for login in created_roles:
                    connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(login)))


def posting(connection,entry,branch,currency,account,contra,amount,debit=False,transaction=None,reversal=None):
    connection.execute('INSERT INTO fincore.journal_entries(entry_id,branch_id,currency,business_date,transaction_id,reversal_of) VALUES(%s,%s,%s,fincore.business_date(),%s,%s)',
                       (uid(entry),uid(branch),currency,uid(transaction) if transaction else None,uid(reversal) if reversal else None))
    for number,acc,is_debit in [(1,account,debit),(2,contra,not debit)]:
        connection.execute('INSERT INTO fincore.journal_lines VALUES(%s,%s,%s,%s,%s,%s,%s)',
                           (uid(entry),number,uid(acc),uid(branch),currency,amount if is_debit else 0,0 if is_debit else amount))
    connection.execute("UPDATE fincore.journal_entries SET status='posted' WHERE entry_id=%s",(uid(entry),))

def seed(connection,principals):
    with connection.transaction():
        key=secrets.token_urlsafe(32)
        for number in [1,2]:
            connection.execute('INSERT INTO fincore.branches VALUES(%s,%s,%s)',(uid(number),f'BR-{number}','US'))
            connection.execute("INSERT INTO fincore.customers VALUES(%s,fincore_crypto.pgp_sym_encrypt(%s,%s,'cipher-algo=aes256'),%s,'PGP-AES256','US',now())",
                               (uid(10+number),'SYNTHETIC-ID-'+str(number),key,'fixture-key-v1'))
            connection.execute("INSERT INTO fincore.customer_profiles VALUES(%s,fincore_crypto.pgp_sym_encrypt(%s,%s,'cipher-algo=aes256'),%s,'verified',now(),'high',80,now())",
                               (uid(10+number),'Synthetic profile '+str(number),key,'fixture-key-v1'))
        for number,customer,branch,kind,currency,side in [(101,11,1,'checking','USD','credit'),(102,11,1,'savings','USD','credit'),
              (103,11,1,'loan','USD','debit'),(104,None,1,'settlement','USD','debit'),(105,11,1,'savings','EUR','credit'),
              (201,12,2,'checking','USD','credit'),(204,None,2,'settlement','USD','debit'),(205,12,2,'savings','EGP','credit')]:
            connection.execute('INSERT INTO fincore.accounts VALUES(%s,%s,%s,%s,%s,%s,\'open\')',
                               (uid(number),uid(customer) if customer else None,uid(branch),kind,currency,side))
        for key,branch in [('branch_a',1),('branch_b',2)]:
            connection.execute('INSERT INTO security.branch_assignments VALUES(%s,%s)',(principals[key]['db_login'],uid(branch)))
        for tx,account,branch,amount,direction,channel,flag in [(301,101,1,6000,'in','cash',True),(302,102,1,4100,'in','cash',False),
                (303,101,1,1000,'out','cash',False),(304,201,2,10000,'in','cash',True),(305,101,1,50,'out','card',True),
                (306,201,2,100,'out','card',True)]:
            connection.execute('INSERT INTO fincore.transactions VALUES(%s,%s,%s,\'USD\',%s,%s,%s,fincore.business_date(),\'posted\',NULL,%s)',
                               (uid(tx),uid(account),uid(branch),amount,direction,channel,flag))
            for party in ['conductor','beneficiary']:
                connection.execute('INSERT INTO fincore.transaction_parties VALUES(%s,%s,%s)',(uid(tx),uid(11 if branch==1 else 12),party))
            posting(connection,tx+1000,branch,'USD',account,104 if branch==1 else 204,amount,direction=='out',tx)
        posting(connection,1400,1,'USD',103,104,10000,True)
        connection.execute('INSERT INTO fincore.account_holds VALUES(%s,%s,100,now()-interval \'1 hour\',now()+interval \'1 day\',NULL)',(uid(401),uid(101)))
        connection.execute("INSERT INTO fincore.loans VALUES(%s,%s,0.18,'ACT/360',fincore.business_date()-30,fincore.business_date()+365)",(uid(501),uid(103)))
        connection.execute('INSERT INTO fincore.loan_installments VALUES(%s,1,fincore.business_date()-10,100,0)',(uid(501),))
        connection.execute("INSERT INTO fincore.compliance_cases VALUES(%s,%s,'SAR','review',now(),90,'{\"private\":\"withheld\"}')",(uid(601),uid(11)))
        connection.execute("INSERT INTO fincore.screening_hits VALUES(%s,%s,%s,'synthetic-list',85,'pending',now())",(uid(701),uid(11),uid(601)))
        for case,tx,user in [(801,301,'fraud_a'),(802,305,'fraud_a'),(803,306,'fraud_b')]:
            connection.execute("INSERT INTO fincore.investigation_cases VALUES(%s,'active',now(),'SYNTHETIC_FLAG')",(uid(case),))
            connection.execute('INSERT INTO fincore.case_transactions VALUES(%s,%s)',(uid(case),uid(tx)))
            connection.execute('INSERT INTO security.case_assignments VALUES(%s,%s)',(principals[user]['db_login'],uid(case)))
            connection.execute("INSERT INTO fincore.card_events VALUES(%s,%s,%s,'authorization',now(),'review')",(uid(case+100),uid(tx),uid(case+200)))

if __name__=='__main__':
    with postgres_fixture() as fixture:
        print('Native FinCore fixture validated: PostgreSQL '+fixture['server_version'],flush=True)
