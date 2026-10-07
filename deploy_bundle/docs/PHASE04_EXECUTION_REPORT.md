# Phase 4 execution report

FinCore Enterprise and the PostgreSQL dialect adapter are implemented and locally
verified. **320/320 backend tests pass**, retaining every
one of the **250 Phase 3 cases**, plus **70 FinCore tests**.
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
| Complete backend suite | 320 passed; 0 failures/errors/skips |
| Phase 3 retained cases | 250/250; includes Phase 2 and hardening baselines |
| FinCore suite | 70 passed; 36 cases use actual PostgreSQL fixtures |
| Existing API integration | 43 passed |
| Original recovered test files | Eight recorded hashes unchanged |
| Frontend suite | 10 passed; no failure/error/skip |
| TypeScript / production build / generated types | Passed |
| Native database | PostgreSQL 17.11; 17 FORCE RLS tables; 12 masked views |
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

Python: `D:\BIRD-Interact\deploy_bundle\.venv`.
Native database binaries, cluster, SCRAM secrets and synthetic fixtures:
`D:\BIRD-Interact\deploy_bundle\.runtime\postgres`.
Frontend dependencies/cache/build: `D:\BIRD-Interact\frontend`.
Package and temporary paths stay on D: using the existing provisioning/test helpers.
No heavy dependency or build cache is directed to C:.

Measured footprint: Python environment 347.9 MiB;
PostgreSQL runtime/archive/cluster 515.6 MiB;
frontend dependencies 182.7 MiB;
frontend build 0.94 MiB.
D: free space **108.66 GiB**.
Driver versions: Psycopg 3.3.6, binary 3.3.6,
pool 3.3.3; additive lockfile `requirements-phase04.lock.txt`.
The native Windows runtime comes from EDB's PostgreSQL binary distribution;
its URL and local SHA-256 are saved in `.runtime/postgres/provenance.json`.
That local digest is a reproducibility record, not a vendor-published checksum.

## Run and migration handoff

Follow [FinCore schema and operating guide](FINCORE_SCHEMA.md) for fresh database
migration, restricted LOGINs, branch/case assignments and the private D-drive
`SENTINEL_PG_AUTH_FILE`. Use `tools/bootstrap_api.py --roles branch_analyst
compliance_officer fraud_investigator` on initial account setup; existing private
accounts must be updated explicitly rather than overwritten. Start the API with
`.venv\Scripts\python.exe -B tools\run_api.py`, then start the SPA using its
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
