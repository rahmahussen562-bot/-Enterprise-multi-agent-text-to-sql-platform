# SentinelSQL FastAPI adapter

The API runs the existing hardened T-SQL controller in bounded AnyIO worker threads. REST and WebSocket transports share the same signed identity, native cancellation token, deterministic Guardian/Critic checks, and durable job records. Streamlit remains available as a separate client.

## Run locally on D:

Use PowerShell in the approved workspace:

```powershell
Set-Location D:\BIRD-Interact\deploy_bundle
. .\tools\use_d_runtime.ps1
.\.venv\Scripts\python.exe -B .\tools\install_phase02.py
.\.venv\Scripts\python.exe -B .\tools\bootstrap_api.py
.\.venv\Scripts\python.exe -B .\tools\run_api.py
```

Bootstrap prompts for two distinct corporate IDs and private passwords, creates a random 32-byte signing key, and writes only salted PBKDF2 password hashes. It restricts the private folder ACL and refuses to overwrite existing accounts. There are no built-in or published credentials. Do not point a running service at the test account directory.

For local Chinook evaluation, run `.\.venv\Scripts\python.exe -B .\tools\prepare_api_demo.py` once to provision the vendored fixture offline, then set `$env:SENTINEL_DEMO_MODE = '1'` before starting the process. The tool refuses to overwrite an existing database. Production requires the SQL Server settings in `.env` or process environment and a functioning Microsoft ODBC driver. SQLite emulation is disabled by default. Configure production SQL Server with a least-privilege read-only account, validated TLS certificates, `MSSQL_ENCRYPT=yes`, and `MSSQL_TRUST_SERVER_CERTIFICATE=no`.

`run_api.py` binds to `127.0.0.1:8000`, redirects temporary files and package/provider caches to D:, and starts one ASGI process. Open `http://127.0.0.1:8000/docs` for the typed contract. An equivalent command after dot-sourcing the runtime setup is:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 16384 --timeout-graceful-shutdown 20
```

For Command Prompt, use `cd /d D:\BIRD-Interact\deploy_bundle` and `.venv\Scripts\python.exe -B tools\run_api.py`; the helper applies the D-drive runtime settings itself.

## Signed sessions

`POST /api/v1/auth/login` accepts exactly `user_id` and `password`. It returns `access_token`, `token_type: bearer`, and a session profile with exactly five claims: `user_id`, `role`, `allowed_tables`, `issued_at`, and `expires_at`. JWT signing is fixed to HMAC-SHA256. Tokens are signed, so their payload can be read by their holder; they contain no credentials.

The account directory assigns each corporate ID exactly one server role. Clients cannot select roles or submit scopes. The server policies are:

| Role | Authorized physical tables |
| --- | --- |
| `sales_analyst` | Customer, Invoice, InvoiceLine |
| `inventory_lead` | Track, Album, Artist, Genre, MediaType |

Every protected route verifies signature, TTL, account existence, current role, and the exact current server table policy. Role changes and account deletion revoke existing tokens. Rotating the signing key invalidates all tokens. Password changes alone do not revoke existing stateless tokens; delete/disable the identity or rotate its role/key when immediate revocation is required. The default TTL is 900 seconds.

Private defaults are `.runtime/api-private/session.key`, `accounts.json`, and `jobs.sqlite`. Environment overrides are `SENTINEL_SESSION_KEY`, `SENTINEL_AUTH_FILE`, `SENTINEL_API_STATE`, `SENTINEL_SESSION_TTL`, `SENTINEL_API_WORKERS`, `SENTINEL_JOB_TIMEOUT`, and `SENTINEL_ALLOWED_ORIGINS`. Set overrides before process startup. Windows account/state paths must reside on D:. API startup fails if private configuration or mandatory AST validation is unavailable.

## REST contracts

Send `Authorization: Bearer <access_token>` on all routes below.

| Route | Request | Result |
| --- | --- | --- |
| `POST /api/v1/query/classify` | `{"question":"List customers in Brazil"}` | HELP, DATA_QUERY, OUT_OF_SCOPE, or SECURITY_ATTACK; no database execution |
| `POST /api/v1/query/execute` | Same question contract | Waits for bounded execution; returns job ID, status, typed output with SQL, columns, rows, narrative, latency, and retry diffs |
| `GET /api/v1/query/jobs/{job_id}` | Owned job ID | Durable status/output or structured failure |
| `POST /api/v1/query/jobs/{job_id}/cancel` | Owned job ID | Requests native cancellation; status may remain running until resource cleanup completes |
| `GET /api/v1/telemetry/audit-logs?job_id=<id>&after_sequence=0&limit=100` | Owned job ID, pagination | Redacted AST traces, hallucination verdicts, stage durations, and a replay cursor |

Execute failures return `detail`, `error_code`, `ast_trace`, and `job_id`. Validation errors never echo passwords or submitted payloads. Unauthorized sessions return 401; Guardian/RBAC denial returns 403; overload returns 503; query deadline returns 408; oversized requests/results return 413. Other identities receive 404 for private jobs, including users with the same role.

Decimal values are exact strings and dates are ISO strings. Non-finite values become null. Legitimate empty results succeed immediately; the API never weakens filters or invents rows.

## WebSocket protocol

Connect to `/api/v1/query/stream` with a bearer header. Browser clients send `{"token":"<access_token>"}` as their first frame within five seconds. Tokens never belong in URLs. Origins must match the configured allowlist.

After `{"type":"ready"}`, send one of:

```json
{"action":"start","question":"List customers in Brazil"}
{"action":"subscribe","job_id":"<owned UUID>","after_sequence":4}
{"action":"cancel","job_id":"<owned UUID>"}
```

Start returns a `job` frame, followed by durable `event` frames numbered from one: admission, agent stage status, AST/schema verdicts, redacted unified diffs when a bounded retry occurs, and terminal cleanup. These messages describe observable agent operations. Sensitive grounded values, SQL literals/comments, arbitrary exceptions, and result cells are excluded from ordinary audit logs.

Successful jobs then stream authorized `rows` frames in batches of at most 100 with `columns`, `offset`, and a sequence following the durable events; the final `result` frame contains the complete typed job response. Row frames are generated from the owned result rather than persisted in audit logs. Reconnect cursors apply to durable events; replace row batches by offset when replaying a completed result. Rows become available after database evaluation, not while an unaudited query is executing.

A stream supports one active start/subscription. Closing the initiating connection cancels its active query; disconnecting a replay observer does not cancel someone else's initiation. Session validity is checked repeatedly during execution and before result/row delivery. Clients receive a structured `error` frame followed by close code 1008 on protocol/session denial.

## Resource and persistence boundaries

The default limit is four simultaneous engine operations, with no unbounded admission queue. Questions are limited to 4,000 characters, HTTP request bodies to 16 KiB, WebSocket commands to 8 KiB, results to 1,000 rows/2 MiB, and each job to 256 audit events. The total query deadline is 60 seconds; database driver timeouts retain their Phase 1 limits. LLM calls remain synchronous within bounded worker threads; cancellation prevents further stages after an in-flight provider call returns.

HTTP disconnects, task cancellation, WebSocket disconnects, explicit cancellation, deadlines, and shutdown all use the same cancellation context. An independent control thread invokes active ODBC cursor cancellation or SQLite interruption. Jobs become cancelled only after worker cleanup and transaction rollback/connection closure. Cancellation depends on driver cooperation; live SQL Server integration must verify the deployed ODBC driver's behavior. A driver cancellation failure is reported explicitly.

SQLite WAL persists jobs/results and sequenced records across restarts. An exclusive owner lease enforces one ASGI process per state file; a second process fails startup. Previously running jobs become interrupted after a restart. Protect this private store like its source database and apply organizational backup/retention rules. Per-principal, per-role retrieval namespaces prevent concurrent sessions from sharing learning memory. Multi-replica execution, distributed scheduling, shared retention, and enterprise identity federation require a shared storage/coordination adapter in a later phase.

## Verification

```powershell
.\.venv\Scripts\python.exe -B .\tools\run_phase01_tests.py -q --junitxml=docs/PHASE02_TEST_RESULTS.xml
```

Tests retain the 207-test hardening baseline and cover signed sessions, tampering, exact server entitlements, strict input validation, real Guardian/Critic enforcement, empty results, durable owner isolation, WebSocket sequencing/replay/diffs/rows, workload admission, session revocation, and native cancellation/cleanup. Provider generation and native ODBC execution are controlled test doubles; actual SQLite query evaluation is exercised.
