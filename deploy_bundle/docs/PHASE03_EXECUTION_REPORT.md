# Phase 3 execution report

The enterprise React workspace is implemented at `D:\BIRD-Interact\frontend`. It connects to the hardened FastAPI service and preserves all 248 Phase 2 tests and its existing REST/component contracts. Verification completed w
ith **250/250 backend tests**, **10/10 frontend tests**, **zero dependency vulnerabilities**, and successful real-browser workflows in English and Arabic.

## Delivered experience

- Obsidian/slate/navy landing page with high-contrast typography, locally hosted Inter fonts, restrained cyan accents, Lucide icons, and no emojis. Its four sample security scenarios and interactive SVG architecture diagram expose the deterministic policy boundary. The simulator is explicitly illustrative; the status strip polls actual API health and measures round-trip latency.
- Accessible Radix role-selection dialog exchanges private credentials for the server-owned signed session. Selecting a different persona cannot change RBAC. Tokens/results stay in memory; only the language preference persists. Expiry, logout and rejected sessions clear the workspace.
- Authorized schema explorer reads actual tables, columns, primary keys and relationships from the server. Both relationship endpoints must be visible. New protected metadata inspection uses bounded workers, cancellation cleanup and driver query timeouts.
- Natural-language query studio supports classification, role-specific shortcuts, optional browser dictation, REST or WebSocket execution, syntax-highlighted verified SQL and server-provided unified diffs.
- Virtualized results grid includes exact decimal-string sorting, 100-row pages, CSV and XLSX export. CSV neutralizes formula-like strings; XLSX stores strings literally and preserves decimal precision. The lazily loaded Recharts panel uses actual numeric results, with an explicit approximation note for chart values.
- Live inspector displays owned agent stages, actual timings, AST/schema verdicts and ordered audit events. WebSocket queues and send buffers are bounded; reconnect resumes an acknowledged job without resubmitting execution. Missing durable events are recovered from the audit endpoint before final output is accepted. Unresolved gaps are rejected.
- English LTR and Arabic RTL apply to document layout and Radix controls. SQL remains LTR. Technical database identifiers, server messages and approved English sample prompts retain their source language.

## API compatibility and additions

`docs/PHASE03_OPENAPI.json` is an additive export. Every Phase 2 REST path definition and component schema remains identical; `docs/PHASE02_OPENAPI.json` is preserved. `src/api/generated.ts` derives from that export through openapi-typescript and its drift check passes.

New routes are `GET /api/v1/health` and signed-session-protected `GET /api/v1/schema`. Health describes API/AST readiness and worker occupancy. Schema metadata derives from the server's verified role policy, rather than client-selected claims. Native foreign-key discovery restricts both tables to the authorized `dbo` schema; metadata operations inherit the configured driver timeout.

## Verification

| Check | Result |
| --- | --- |
| Backend regression and integration | 250 passed; 0 failed/errors/skipped; all 248 Phase 2 cases retained |
| API integration subset | 43 passed, including role-filtered metadata and native cancellation |
| Historical recovered test modules | All eight recorded hashes unchanged |
| TypeScript and production build | Passed |
| Generated API contract drift | Passed |
| Frontend transport/export tests | 10 passed; 0 failed/errors/skipped |
| npm dependency audit | 0 vulnerabilities across all severity levels |
| Zero-emoji source scan | Passed |
| Actual Edge browser | Both roles; live WebSocket and REST; schema isolation; simulator; memory-only session; exports |
| Responsive and Arabic verification | Desktop and 390px mobile landing/workspace; no horizontal page overflow |
| Browser runtime errors | 0 uncaught errors |
| Actual downloaded XLSX | Reopened successfully: 5 data rows, 5 columns, no formulas |
| Preview backend shutdown | Graceful cleanup completed |

JUnit evidence: `docs/PHASE03_TEST_RESULTS.xml`, `docs/PHASE03_API_TEST_RESULTS.xml`, `docs/PHASE03_FRONTEND_TEST_RESULTS.xml`. Machine-readable evidence: `docs/PHASE03_VERIFICATION.json`, `docs/PHASE03_BROWSER_RESULTS.json`. Desktop/Arabic/mobile screenshots are in `D:\BIRD-Interact\frontend\.runtime\screenshots`.

Browser checks used the actual FastAPI entry point, ephemeral private hashed credentials, the existing offline coder and vendored Chinook SQLite fixture. The Sales account remained Sales-authorized even when Inventory was selected in the portal; Customer/Invoice metadata remained hidden from the actual Inventory account. Browser storage contained only the language preference. Native ODBC/provider behaviors remain covered by controlled test doubles. No live SQL Server, external LLM or Cloudflare deployment was exercised. The installed Starlette HTTPX adapter emits one existing deprecation warning; it does not fail the baseline.

## D-drive runtime and build

Self-contained Node 24.19.0 and npm 11.17.0 are under `frontend\.runtime\node`; Python remains `deploy_bundle\.venv`. Frontend dependencies, npm cache/prefix/logs, Vite cache, temporary files, browser profiles and build artifacts are configured under the frontend directory. No dependency installation or build cache is directed to C:.

Measured frontend footprint: dependencies 182.7 MiB; runtime/cache/verification artifacts 503.5 MiB; production output 0.94 MiB. D: free space: 109.34 GiB. The production entry JavaScript is about 359 kB (114 kB gzip); charts are a separate 358 kB chunk (104 kB gzip), and Excel compression is loaded only for export. All versions are reproducibly pinned in `package-lock.json`.

```powershell
Set-Location D:\BIRD-Interact\frontend
. .\tools\use-d-runtime.ps1
npm install
npm run dev
# Production build
npm run build
```

Open `http://localhost:5173`. Start the backend in a second terminal using `deploy_bundle\tools\run_api.py`; provision private operator credentials with `tools\bootstrap_api.py` once if needed. Vite proxies HTTP and WebSocket requests to `127.0.0.1:8000`. Full setup, API generation and runtime details are in `D:\BIRD-Interact\frontend\README.md`. For CI, use `npm ci` with the lockfile. Test preview accounts are ephemeral verification fixtures and are not operator credentials.

## Next transition

The SPA build includes Cloudflare Pages `_redirects` and security `_headers`. The next deployment phase should bind the frontend origin and API gateway, enforce HTTPS/WSS and the exact CORS/WebSocket allowlist, tighten the CSP API origin, deploy the Python container/Tunnel or Workers gateway, and verify native database/provider behavior. Multi-replica coordination still needs shared job/audit storage and admission governance from the approved roadmap. FinCore/PostgreSQL migration remains planned; the active backend is T-SQL/Chinook, and the frontend labels that boundary explicitly.
