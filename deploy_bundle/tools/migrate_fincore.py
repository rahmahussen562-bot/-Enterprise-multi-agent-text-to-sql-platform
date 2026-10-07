"""Apply migration 0001 to a fresh PostgreSQL 17+ database; no destructive reset.

Read administrator conninfo from a private D: file named by
SENTINEL_PG_MIGRATION_DSN_FILE. Never pass passwords on the command line.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]


def inspect_schema(connection):
    version = connection.execute("SELECT current_setting('server_version')").fetchone()[0]
    migration = connection.execute('SELECT version FROM fincore.schema_versions ORDER BY version').fetchall()
    tables = connection.execute("""SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='fincore' AND c.relkind='r' AND c.relname IN
        ('customers','customer_profiles','accounts','transactions','transaction_parties','transaction_events',
         'journal_entries','journal_lines','account_holds','loans','loan_installments','compliance_cases',
         'screening_hits','investigation_cases','case_transactions','card_events','audit_logs') ORDER BY c.relname""").fetchall()
    views = connection.execute("""SELECT n.nspname||'.'||c.relname,c.reloptions FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('branch','compliance','fraud') AND c.relkind='v' ORDER BY 1""").fetchall()
    roles = connection.execute("""SELECT rolname FROM pg_catalog.pg_roles
        WHERE rolname IN ('fincore_owner','fincore_branch','fincore_compliance','fincore_fraud')
        AND NOT (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb)""").fetchall()
    if migration != [('0001',)] or len(tables)!=17 or not all(rls and force for _,rls,force in tables):
        raise ValueError('FinCore migration/RLS inspection failed.')
    if len(roles)!=4 or len(views)!=12 or not all({'security_invoker=true','security_barrier=true'}<=set(options or []) for _,options in views):
        raise ValueError('FinCore role/view inspection failed.')
    return {'server_version':version,'migration':'0001','forced_rls_tables':len(tables),
            'masked_invoker_views':[name for name,_ in views],'restricted_groups':len(roles)}


def apply_schema(connection):
    if int(connection.execute("SELECT current_setting('server_version_num')").fetchone()[0])<170000:
        raise ValueError('FinCore requires PostgreSQL 17+ for transaction_timeout.')
    existing = connection.execute("""SELECT count(*) FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
        AND n.nspname NOT LIKE 'pg_temp%' AND c.relkind IN ('r','v','m','S','f')""").fetchone()[0]
    if existing:
        raise ValueError('Apply requires a fresh dedicated database; use --check for an installed schema.')
    try:
        connection.execute((ROOT/'data/fincore_schema.sql').read_text(encoding='utf-8'))
    except BaseException:
        connection.rollback()
        raise
    return inspect_schema(connection)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--apply',action='store_true')
    action.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if os.name=='nt' and (ROOT.drive.upper()!='D:' or Path(sys.prefix).resolve()!=ROOT/'.venv'):
        raise ValueError('Use the project D: virtual environment.')
    path=Path(os.environ['SENTINEL_PG_MIGRATION_DSN_FILE']).resolve()
    if os.name=='nt' and path.drive.upper()!='D:':
        raise ValueError('Private migration configuration must remain on D:.')
    if path.stat().st_size>16384:
        raise ValueError('Unexpected migration configuration size.')
    conninfo=path.read_text(encoding='utf-8').strip()
    options=conninfo_to_dict(conninfo)
    if options.get('host') not in {'127.0.0.1','localhost','::1'} and options.get('sslmode')!='verify-full':
        raise ValueError('Remote migrations require sslmode=verify-full.')
    with psycopg.connect(conninfo,autocommit=True,connect_timeout=5) as connection:
        print(json.dumps(apply_schema(connection) if args.apply else inspect_schema(connection),indent=2))


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        # Driver exceptions may contain connection details. Print only type/state.
        print(f'Migration failed: {type(error).__name__}; SQLSTATE={getattr(error,"sqlstate",None)}',file=sys.stderr)
        raise SystemExit(1) from None
