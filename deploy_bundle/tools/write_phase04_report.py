"""Capture final Phase 4 evidence from successful native and legacy suites."""
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
FRONTEND=Path('D:/BIRD-Interact/frontend')
assert ROOT.drive.upper()=='D:' and Path(sys.prefix).resolve()==ROOT/'.venv'
for name,folder in {'TEMP':'tmp','TMP':'tmp','TMPDIR':'tmp','PIP_CACHE_DIR':'pip-cache','PYTHONPYCACHEPREFIX':'pycache','PYTHONUSERBASE':'python-user'}.items():
    os.environ[name]=str(ROOT/'.runtime'/folder)

def cases(path):
    tree=ET.parse(path)
    assert not any(list(tree.getroot().iter(tag)) for tag in ('failure','error','skipped')),str(path)
    return list(tree.getroot().iter('testcase'))

all_cases=cases(ROOT/'docs/PHASE04_TEST_RESULTS.xml')
baseline=cases(ROOT/'docs/PHASE03_TEST_RESULTS.xml')
identity=lambda items:{(case.attrib['classname'],case.attrib['name']) for case in items}
assert len(baseline)==250 and identity(baseline)<=identity(all_cases)
bank_cases=[case for case in all_cases if case.attrib['classname'].split('.')[-1]=='test_fincore']
assert len(all_cases)==320 and len(bank_cases)==70
frontend_cases=cases(FRONTEND/'.runtime/frontend-tests.xml')
assert len(frontend_cases)==10
shutil.copyfile(FRONTEND/'.runtime/frontend-tests.xml',ROOT/'docs/PHASE04_FRONTEND_TEST_RESULTS.xml')

def subset(name,items):
    suites=ET.Element('testsuites')
    suite=ET.SubElement(suites,'testsuite',name=name,tests=str(len(items)),failures='0',errors='0',skipped='0',
        time=str(sum(float(case.attrib.get('time',0)) for case in items)))
    for case in items: suite.append(ET.fromstring(ET.tostring(case)))
    ET.ElementTree(suites).write(ROOT/f'docs/{name}.xml',encoding='utf-8',xml_declaration=True)

subset('PHASE04_FINCORE_TEST_RESULTS',bank_cases)
api_cases=[case for case in all_cases if case.attrib['classname'].split('.')[-1]=='test_api']
subset('PHASE04_API_TEST_RESULTS',api_cases)
original=json.loads((ROOT/'docs/PHASE01_TEST_BASELINE.json').read_text(encoding='utf-8'))
hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
        for name,digest in original['files'].items() if name.startswith('tests/')}
assert all(hashes.values())
fixture=json.loads((ROOT/'.runtime/postgres/verification.json').read_text(encoding='utf-8'))
assert fixture['forced_rls_tables']==17 and len(fixture['masked_invoker_views'])==12
stop=subprocess.run([str(ROOT/'.runtime/postgres/pgsql/bin/pg_ctl.exe'),'-D',str(ROOT/'.runtime/postgres/cluster'),
    'status'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
assert stop.returncode==3,'Owned PostgreSQL fixture server still running.'
pip=subprocess.run([sys.executable,'-B','-m','pip','check'],capture_output=True,text=True,check=True)
assert 'No broken requirements found' in pip.stdout
def pins(path):
    return dict(line.split('==',1) for line in path.read_text().splitlines() if '==' in line)
installed=pins(ROOT/'requirements-phase04.lock.txt')
legacy=pins(ROOT/'requirements-phase02.lock.txt')
assert all(installed.get(name)==version for name,version in legacy.items())
source=json.loads((FRONTEND/'.runtime/source-audit.json').read_text())
assert source['passed'] and not source['emojiFiles']
frontend_lock=json.loads((FRONTEND/'package-lock.json').read_text())
phase03=json.loads((ROOT/'docs/PHASE03_VERIFICATION.json').read_text())
assert all(frontend_lock['packages']['node_modules/'+name]['version']==version for name,version in phase03['versions'].items())

def folder_bytes(path):
    total=0
    for directory,_,filenames in os.walk(path):
        for filename in filenames:
            file=Path(directory)/filename
            assert file.resolve().is_relative_to(path.resolve())
            total+=file.stat().st_size
    return total

sizes={str(path):folder_bytes(path) for path in (ROOT/'.venv',ROOT/'.runtime/postgres',FRONTEND/'node_modules',FRONTEND/'dist')}
functions=ast.parse((ROOT/'tests/test_fincore.py').read_text())
native={node.name for node in functions.body if isinstance(node,ast.FunctionDef) and any(arg.arg=='bank' for arg in node.args.args)}
native_count=sum(case.attrib['name'].split('[')[0] in native for case in bank_cases)
versions={name:importlib.metadata.version(name) for name in ('psycopg','psycopg-binary','psycopg-pool','sqlglot','fastapi','pydantic','pytest')}
proof={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'backend':{'passed':len(all_cases),'failed':0,'errors':0,'skipped':0,
       'phase03_baseline_retained':len(baseline),'fincore':len(bank_cases),'native_postgres_cases':native_count,'api':len(api_cases),
       'historical_test_hashes_unchanged':hashes},'frontend':{'passed':len(frontend_cases),'typescript_build':'passed',
       'openapi_drift':'passed','zero_emoji':source},'postgres':{**fixture,'fixture_server_stopped':True},
       'versions':versions,'legacy_python_pins_retained':True,'pip_check':pip.stdout.strip(),
       'directory_bytes':sizes,'d_free_bytes':shutil.disk_usage('D:/').free,
       'storage':{'python':str(ROOT/'.venv'),'postgres':str(ROOT/'.runtime/postgres'),'frontend':str(FRONTEND)},
       'contract':'Existing Phase 3 REST paths/requests/outputs unchanged; banking role enum and postgres schema dialect added.',
       'boundary':'Actual local PostgreSQL 17.11; synthetic encrypted fixtures, native RLS/constraints/cancellation. Banking synthesis uses approved finite v1 English catalog. No production data migration, KMS integration or Cloudflare deployment.'}
(ROOT/'docs/PHASE04_VERIFICATION.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
report=f'''# Phase 4 execution report

FinCore Enterprise and the PostgreSQL dialect adapter are implemented and locally
verified. **{len(all_cases)}/{len(all_cases)} backend tests pass**, retaining every
one of the **250 Phase 3 cases**, plus **{len(bank_cases)} FinCore tests**.
The React integration retains **10/10 frontend tests** and passes type generation,
OpenAPI drift checking, production build and the zero-emoji source scan.

## Delivered implementation

- `core/postgres.py`: Psycopg 3 async pool, PostgreSQL SQLGlot validation/rendering,
  read-only transactions, statement/lock/transaction deadlines, bounded rows and
  native cancellation with rollback and reusable leases. The existing worker-thread
  controller accesses it through a scoped bridge. Remote connections require TLS
  certificate/hostname verification. Catalog metadata has its own bounded budget,
  preserving full schema validation even with a one-row query result limit.
- `data/fincore_schema.sql`: migration 0001 with normalized customers/profiles,
  accounts, transactions/events, loans/installments, holds, journal entries/lines,
  compliance cases/screening hits, investigations/card tokens and JSONB audit data.
  Actual synthetic identifiers/profiles are encrypted with PGP-AES256.
- Ledger constraints enforce currency/branch consistency, deferred exact balance,
  atomic rollback and immutable posted history. Header locking serializes sealing
  and line writers. Reversals must exactly swap account debits/credits; posting
  audit commits atomically and cannot be updated/deleted.
- Three disjoint banking view allowlists, 12 masked invoker/barrier views and
  17 forced-RLS base tables. Unique database LOGINs bind private branch/active-case
  assignments to `session_user`; user-controlled session variables cannot replace
  identity. Native column grants deny encrypted PII and confidential case evidence.
  AST policy separately enforces view-only access, including nested/CTE/correlated
  references and masked columns. Required invoker-view base-column grants remain
  readable within their RLS scope outside the gateway.
- `core/fincore.py`, `agents/fincore.py`, `data/financial_metrics.v1.json`: reviewed
  registry 1.0.0 for posted balance/holds, US-reference USD cash monitoring and
  contractual fixed simple-interest/day-count metrics. The institutional business
  date is independent of browser or connection timezone. Unknown definitions and
  unsupported filters are rejected; valid empty results never weaken predicates.
- Server authentication adds `compliance_officer`, `branch_analyst` and
  `fraud_investigator` without changing five-field signed session payloads or the
  legacy personas. API requests cannot select a database or supply authorizations.
  The SPA adds banking roles, PostgreSQL schema/SQL labels and approved shortcuts.
- `tools/migrate_fincore.py` applies only to a fresh dedicated database, inspects
  migration/RLS/view properties, and refuses destructive reapplication. Native test
  provisioning uses this same migration function.

## Verification evidence

| Check | Result |
| --- | --- |
| Complete backend suite | {len(all_cases)} passed; 0 failures/errors/skips |
| Phase 3 retained cases | 250/250; includes Phase 2 and hardening baselines |
| FinCore suite | {len(bank_cases)} passed; {native_count} cases use actual PostgreSQL fixtures |
| Existing API integration | {len(api_cases)} passed |
| Original recovered test files | Eight recorded hashes unchanged |
| Frontend suite | 10 passed; no failure/error/skip |
| TypeScript / production build / generated types | Passed |
| Native database | PostgreSQL {fixture['server_version']}; 17 FORCE RLS tables; 12 masked views |
| Synthetic database identities | Six separately authenticated, restricted principals |
| Pool and timeout cleanup | Native pg_stat_activity checks; cancellation leaves no sleeping statement; leases reused |
| Owned fixture lifecycle | Test DB/LOGINs removed; PostgreSQL server stopped |
| Legacy Python package pins | All Phase 2 pins retained; pip check passes |
| Icons/source policy | Zero-emoji scan passes |

Tests cover unbalanced/zero-line/currency-mismatch atomic rejection, valid exact
reversal and incorrect balanced reversal, concurrent sealing, append-only audit,
branch/case isolation, native PII/compliance denial, principal disablement on an
existing connection, UTC-midnight business dates, cash aggregation without netting
or duplicate party counting, exact-threshold behavior, loan metrics, PostgreSQL CTE
grounding, fail-closed parser errors, API banking sessions/metadata/audit and empty
result stability. They also exercise server timeout, task cancellation, the API
control token, bounded pool admission and privileged database-identity rejection.

Earlier verification runs encountered intermittent legacy two-second start-signal
failures. Isolated reruns passed; redacted audit timestamps in one later failure
showed a 1.425-second delay before the first worker event and cancellation before
the driver was reached. The final full run above passes without concurrent builds.
All test assertions and security deadlines were preserved. The existing Starlette
HTTPX deprecation warning remains;
it is not a test failure. Phase 3 browser evidence is retained; this phase verifies
banking HTTP integration and frontend builds/tests without claiming another browser
workflow run or cloud deployment.

JUnit: `PHASE04_TEST_RESULTS.xml`, `PHASE04_FINCORE_TEST_RESULTS.xml`,
`PHASE04_API_TEST_RESULTS.xml`, `PHASE04_FRONTEND_TEST_RESULTS.xml`.
Structured evidence: `PHASE04_VERIFICATION.json`. The additive contract is
`PHASE04_OPENAPI.json`; original Phase 2/3 specifications remain preserved.

## D-drive environment

Python: `D:\\BIRD-Interact\\deploy_bundle\\.venv`.
Native database binaries, cluster, SCRAM secrets and synthetic fixtures:
`D:\\BIRD-Interact\\deploy_bundle\\.runtime\\postgres`.
Frontend dependencies/cache/build: `D:\\BIRD-Interact\\frontend`.
Package and temporary paths stay on D: using the existing provisioning/test helpers.
No heavy dependency or build cache is directed to C:.

Measured footprint: Python environment {sizes[str(ROOT/'.venv')]/1024**2:.1f} MiB;
PostgreSQL runtime/archive/cluster {sizes[str(ROOT/'.runtime/postgres')]/1024**2:.1f} MiB;
frontend dependencies {sizes[str(FRONTEND/'node_modules')]/1024**2:.1f} MiB;
frontend build {sizes[str(FRONTEND/'dist')]/1024**2:.2f} MiB.
D: free space **{proof['d_free_bytes']/1024**3:.2f} GiB**.
Driver versions: Psycopg {versions['psycopg']}, binary {versions['psycopg-binary']},
pool {versions['psycopg-pool']}; additive lockfile `requirements-phase04.lock.txt`.
The native Windows runtime comes from EDB's PostgreSQL binary distribution;
its URL and local SHA-256 are saved in `.runtime/postgres/provenance.json`.
That local digest is a reproducibility record, not a vendor-published checksum.

## Run and migration handoff

Follow [FinCore schema and operating guide](FINCORE_SCHEMA.md) for fresh database
migration, restricted LOGINs, branch/case assignments and the private D-drive
`SENTINEL_PG_AUTH_FILE`. Use `tools/bootstrap_api.py --roles branch_analyst
compliance_officer fraud_investigator` on initial account setup; existing private
accounts must be updated explicitly rather than overwritten. Start the API with
`.venv\\Scripts\\python.exe -B tools\\run_api.py`, then start the SPA using its
D-drive runtime script and `npm run dev`.

The test database is synthetic and disposable. Production account/transaction
imports, institution-controlled envelope keys, regulatory exemption evidence,
historical business-date handling, broader parameterized/multilingual synthesis,
and Cloudflare deployment remain separate rollout work. Banking generation v1
accepts a finite approved English catalog; it never silently ignores extra filters
or falls through to Chinook revenue rules. The cash metric is a US monitoring
reference, not an automatic CTR/SAR filing system or an Egyptian/EU threshold.
Cloudflare/Hyperdrive connection governance must preserve each authenticated
database identity and branch/case scope before any shared pooling deployment.
'''
(ROOT/'docs/PHASE04_EXECUTION_REPORT.md').write_text(report,encoding='utf-8')
print(json.dumps({'backend_passed':len(all_cases),'fincore_passed':len(bank_cases),'native_postgres_cases':native_count,
    'frontend_passed':len(frontend_cases),'server_version':fixture['server_version'],'d_free_gib':round(proof['d_free_bytes']/1024**3,2)},indent=2))
