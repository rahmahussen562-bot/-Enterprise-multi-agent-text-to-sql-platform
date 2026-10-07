# Phase 2 execution report

The hardened SentinelSQL controller is available through a decoupled FastAPI adapter in `api/`. All 248 tests pass: the complete 207-test Phase 0/1 baseline plus 41 API integration/contract tests. No tests fail, error, or skip. The eight recovered historical test modules retain their recorded SHA-256 hashes.

## Delivered behavior

- `api/main.py`: application factory, strict startup, lifecycle cleanup, CORS, bounded request bodies and unified errors.
- `api/auth.py`: fixed HS256 signed sessions, exactly five claims, server-owned table policy, account/role revocation, constant-time signature checks and private hashed credentials.
- `api/schemas.py`: Pydantic v2 typed request, response, session, telemetry and stream contracts; client-supplied scopes/roles are rejected.
- `api/routes.py`: protected login/classify/execute/audit routes, owned job status/cancellation, authenticated WebSocket streaming/replay and row batches.
- `api/runtime.py` / `api/store.py`: bounded AnyIO workers, private per-principal retrieval namespaces, native cancellation control, durable SQLite WAL job/event records and an exclusive service-owner lease.
- `core/cancellation.py` / `core/database.py`: cancellation context reaches active ODBC cursors and SQLite connections; worker cleanup precedes terminal cancellation status.
- Controller/Critic cancellation propagates without self-healing. Existing AST checks, exact RBAC qualification, defensive row limits and legitimate empty-result success remain intact.
- Published credential hints are removed from the UI, runtime directory and English/Arabic documentation. Production has no built-in passwords. Test-only historical credentials are derived from unchanged test source to preserve existing contracts.

## Verification evidence

JUnit report: `docs/PHASE02_TEST_RESULTS.xml`; machine-readable results: `docs/PHASE02_VERIFICATION.json`; exported typed REST specification: `docs/PHASE02_OPENAPI.json`.

Test coverage includes tampered/expired tokens, current server entitlements, role revocation/deletion, unauthorized inventory access through the real Guardian, strict request validation, valid empty results, owner-scoped persisted results/audits, stage latency/verdicts, WebSocket lifecycle/order/replay/SQL diffs/rows, workload saturation, in-flight revocation, financial decimal/date precision, result budgets, and HTTP/WebSocket/deadline/shutdown cancellation with native rollback/cursor/connection cleanup. Cancellation also reaches the default controller's database readiness query and survives an unavailable audit lookup.

Final test run: **248 passed**, **0 failures**, **0 errors**, **0 skipped**, 167.19 seconds. One installed Starlette deprecation warning concerns TestClient's httpx adapter; dependencies remain pinned to preserve the approved baseline. `pip check`: No broken requirements found.

Provider synthesis and native ODBC execution use controlled doubles. SQLite evaluation uses the actual vendored Chinook fixture. No live SQL Server or external LLM provider was connected; deployed ODBC cancellation and provider behavior still require an integration smoke test.

A separate live Uvicorn smoke test used the production `api.main:app` entry point, private temporary hashed credentials, the real deterministic offline coder and actual SQLite. Login, classification and execution succeeded over local HTTP; both REST and WebSocket returned 5 rows, streamed event/row sequences were ordered, and the server shut down gracefully with exit code 0. Evidence: `docs/PHASE02_LIVE_SMOKE.json`.

## D-drive environment and startup

Verified virtual environment: `D:\BIRD-Interact\deploy_bundle\.venv`; CPython 3.14.3. Runtime/dependency footprint: `.venv` 347.6 MiB and `.runtime` 580.0 MiB; D: free space 110.10 GiB. Installation, test, launch and provider cache helpers write under D:. Phase 2 adds httpx/httpcore without changing the Phase 1 core dependency versions.

```powershell
Set-Location D:\BIRD-Interact\deploy_bundle
. .\tools\use_d_runtime.ps1
.\.venv\Scripts\python.exe -B .\tools\install_phase02.py
.\.venv\Scripts\python.exe -B .\tools\bootstrap_api.py
.\.venv\Scripts\python.exe -B .\tools\run_api.py
```

Bootstrap prompts for private account passwords. It has deliberately not been run with invented operator credentials. Existing `.runtime/test_auth` fixtures are unsuitable for a running service. The demo database has been provisioned offline at `data/chinook.db`; for local demo mode only, set `SENTINEL_DEMO_MODE=1` before launching. Fresh workspaces can run `tools/prepare_api_demo.py` once. Otherwise configure the production SQL Server connection. Full contracts and operating instructions are in `api/README.md`.

## Operating boundaries and next phase

Use one ASGI process per local durable state file. The default service admits four simultaneous engine operations, bounds row/byte/event workloads and requires signed sessions across query/telemetry transports. Ordinary audit records redact SQL literals/comments and exclude financial/customer row values; row batches use the authenticated result channel.

Cancellation stops database work through the driver and prevents subsequent pipeline stages. An in-flight synchronous LLM call returns before its worker can finish cooperative cancellation. A non-cooperating driver cannot be forcibly terminated safely inside a Python thread. The shutdown path requests driver cancellation and waits for cleanup within its configured budget.

The immediate transition is to generate the decoupled frontend client from the exported contract, connect the role portal and analytics panels to these routes, replace local coordination/storage for multi-replica operation, and validate the backend container/Tunnel or Workers gateway against the real SQL Server deployment. PostgreSQL/FinCore dialect migration and Cloudflare deployment remain later roadmap phases.
