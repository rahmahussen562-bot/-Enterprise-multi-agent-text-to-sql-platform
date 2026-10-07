"""Produce the requested hardening diff and evidence-based execution report."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
DOCS = ROOT / "docs"
environment = json.loads((DOCS / "PHASE01_ENVIRONMENT.json").read_text(encoding="utf-8"))
baseline = json.loads((DOCS / "PHASE01_TEST_BASELINE.json").read_text(encoding="utf-8"))
source_sync = json.loads((DOCS / "PHASE01_SOURCE_SYNC.json").read_text(encoding="utf-8"))
results = ET.parse(DOCS / "PHASE01_TEST_RESULTS.xml").getroot()
suites = list(results.iter("testsuite"))
counts = {name: sum(int(suite.get(name, "0")) for suite in suites)
          for name in ("tests", "failures", "errors", "skipped")}
if any(counts[name] for name in ("failures", "errors", "skipped")):
    raise RuntimeError(f"A passing, unskipped verification run is required: {counts}")
legacy_names = {Path(file).stem for file in baseline["files"] if file.startswith("tests/")}
legacy_count = sum(
    1 for case in results.iter("testcase")
    if any(name in case.get("classname", "").split(".") for name in legacy_names)
)
if legacy_count != 44:
    raise RuntimeError(f"Expected 44 preserved historical cases, found {legacy_count}")
for path, expected in source_sync.items():
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"Source synchronization drifted: {path}")

patch = []
paths = [
    "deploy_bundle/agents/guardian.py", "deploy_bundle/agents/critic.py",
    "deploy_bundle/core/database.py", "deploy_bundle/core/sql_validation.py",
    "deploy_bundle/core/config.py",
    "deploy_bundle/agents/orchestrator.py",
    "agents/guardian.py", "agents/critic.py", "agents/orchestrator.py",
]
for path in paths:
    previous = subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=REPOSITORY,
        capture_output=True, text=True, encoding="utf-8",
    )
    if previous.returncode:
        tracked = subprocess.run(
            ["git", "ls-files", "--", path], cwd=REPOSITORY,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if tracked:
            raise RuntimeError(f"Cannot retrieve tracked baseline: {path}")
        original = ""
    else:
        original = previous.stdout
    revised = (REPOSITORY / path).read_text(encoding="utf-8")
    difference = list(difflib.unified_diff(
        original.splitlines(keepends=True), revised.splitlines(keepends=True),
        fromfile=f"a/{path}" if original else "/dev/null", tofile=f"b/{path}",
    ))
    if difference:
        patch.append(f"diff --git a/{path} b/{path}\n")
        if not original:
            patch.append("new file mode 100644\n")
        patch.extend(difference)
(DOCS / "PHASE01_HARDENING.patch").write_text("".join(patch), encoding="utf-8")

MiB = 1024 ** 2
GiB = 1024 ** 3
dependency_rows = "\n".join(
    f"| `{name}` | {info['version']} |"
    for name, info in environment["dependency_locations"].items()
)
report = f"""# SentinelSQL Phase 0/1 execution report

Verified at {environment['verified_at_utc']}.

Phase 0/1 core hardening is implemented. The local regression gate passes with
**{counts['tests']}/{counts['tests']} tests, zero failures, zero errors, and zero skips**.
All **44 original cases** pass; {counts['tests'] - 44} additional adversarial and resource-lifecycle cases pass.
The eight recovered historical test modules and their seeder are byte-for-byte
unchanged from revision `{baseline['source_revision']}`; SHA-256 values are recorded
in [PHASE01_TEST_BASELINE.json](PHASE01_TEST_BASELINE.json).

## D-drive runtime and footprint

| Item | Verified location or usage |
|---|---|
| Project virtual environment | `{environment['environment']}` |
| Python runtime and standard library | `{environment['base_interpreter']}` |
| Interpreter version | CPython {environment['python']} |
| Installed environment | {environment['venv_bytes'] / MiB:.1f} MiB |
| Copied Python runtime | {environment['python_runtime_bytes'] / MiB:.1f} MiB |
| Runtime, caches, fixtures, and temporary files, including Python | {environment['runtime_bytes'] / MiB:.1f} MiB |
| Combined environment and runtime footprint | {(environment['venv_bytes'] + environment['runtime_bytes']) / MiB:.1f} MiB |
| Available D: space at verification | {environment['d_free_bytes'] / GiB:.2f} GiB |

All installed third-party dependencies resolve inside the D: virtual environment.
The Python runtime was copied from the existing installation and the virtual
environment rebased to D:, so its base interpreter and standard library also reside
on D:. New package downloads, pip/uv caches, temporary files, bytecode, user-package
directories, npm caches, and future frontend/build workspaces are directed to D:.
The existing C: installation was read during relocation and was not removed.

| Dependency | Verified version |
|---|---|
{dependency_rows}

`pip check`: **{environment['pip_check']}**

[PHASE01_ENVIRONMENT.json](PHASE01_ENVIRONMENT.json) records exact import paths,
disk measurements, and cache locations. The exact dependency snapshot is
[`requirements-phase01.lock.txt`](../requirements-phase01.lock.txt), verified on
Windows x64 / CPython 3.14. Revalidate before selecting another platform/interpreter.
`tools/provision_phase01.py` automatically uses this lock when present.

## Implemented safety behavior

- **Guardian:** missing/broken parser and malformed SQL deny with
  `AST_PARSER_FAILURE`; the compatibility fallback also denies. Physical relations
  resolve in their lexical scopes, so CTE shadowing and nested queries cannot hide
  unauthorized tables. Catalog/schema names remain part of authorization. Bare
  physical T-SQL relations are rewritten to explicit `dbo` names before
  execution, preventing connection-default-schema substitution; CTE names remain
  scoped aliases. Matched whitelist spellings are canonicalized and conflicting
  identifiers fail closed. Only read-only roots and approved analytical functions
  are accepted; dynamic sources,
  writes, external/system functions, and qualified UDF calls are denied. Outer row
  ceilings apply even with nested TOP, OFFSET, oversized limits, PERCENT, or WITH TIES.
- **Critic:** table aliases bind to their own verified column metadata; CTE/derived
  outputs and correlated references follow local scopes. Unqualified ambiguous
  columns, aliases borrowed from unrelated scopes, unavailable metadata, and
  metadata identity mismatches deny execution. Metadata refreshes for each audit.
  Valid empty results succeed immediately with no filter-relaxation advice.
- **Database:** the background query thread is removed. ODBC statement timeouts and
  explicit cursor cancellation replace orphaned execution; SQLite deadlines use
  its progress handler and interrupt. Transactions roll back and cursors/connections
  close on completion and failure. Result materialization has row/byte budgets,
  and qualified metadata lookups preserve schema/catalog identity. The SQLite
  adapter maps the approved `dbo` schema explicitly to `main` rather than stripping
  arbitrary schema names.
  SQLite fallback requires explicit `SENTINEL_DEMO_MODE=1`; the default production
  configuration fails readiness on live database failure instead of switching data.
- **Controller:** DATA_QUERY requires an identity before exploration/generation.
  Parser, authorization, catalog, unsupported-source/function, mutation, and timeout
  failures terminate the attempt. Verified ordinary column mistakes retain bounded
  repair. Legitimate empty results finish on the first attempt without SQL mutation.
  HELP remains available without a session.

Existing source Guardian, Critic, and controller files under
`D:\\BIRD-Interact\\agents` are synchronized with the deployment copies.
[PHASE01_SOURCE_SYNC.json](PHASE01_SOURCE_SYNC.json) records matching hashes.
The deployment bundle is the runnable workspace; its `core` package supplies shared
validation. Previously deleted parent application/core files were not recreated.

The requested unified diff is [PHASE01_HARDENING.patch](PHASE01_HARDENING.patch).
It includes Guardian, Critic, Database, shared validation, controller, and synchronized
original agent sources and explicit demo configuration. No deployment or repository
commit was performed.

## Verification and practical limits

Run from `D:\\BIRD-Interact\\deploy_bundle`:

```powershell
. .\\tools\\use_d_runtime.ps1
.\\.venv\\Scripts\\python.exe -B .\\tools\\run_phase01_tests.py
.\\.venv\\Scripts\\python.exe -B .\\tools\\check_phase01_runtime.py
```

The runner explicitly places test artifacts on D:. Historical seeds use a vendored,
integrity-checked Chinook SQL fixture; tests do not download data or call LLM providers.
The test fixture enables the explicit offline demo mode; launch the Streamlit demo
with `SENTINEL_DEMO_MODE=1` as well. Production leaves this flag disabled.
Spy-based adversarial cases assert no database execution after parser/authorization
failure and no regeneration after a valid zero-row answer. Native-driver failures
use mocks; SQLite timeout interruption also executes a real long-running query.
Machine-readable results: [PHASE01_TEST_RESULTS.xml](PHASE01_TEST_RESULTS.xml).

SQL Server's live cancellation behavior still requires integration validation on
the production driver and server. The host exposes the legacy `SQL Server` ODBC
driver; Microsoft ODBC Driver 18 is absent. Python ODBC/PostgreSQL drivers are installed.
No system driver installer was run against C:. ODBC deadlines have integer-second
granularity and connection/login timeouts are distinct. Result byte budgets measure
returned content, not total process RSS. Unapproved functions and recursive CTE
output policies require explicit review rather than implicit acceptance. Identifier
matching retains the legacy case-insensitive SQL Server convention; production
identifier collation must be verified before supporting case-sensitive catalogs.

This report verifies local Phase 0/1 checks. CI/container parity and banking/RLS
isolation gates belong to the subsequent adapter and domain deployment work.

## Immediate Phase 2 transition

1. Add a FastAPI adapter with typed login, classify, execute, and audit-log contracts;
   preserve controller/result interfaces and return stable denial codes. Map legacy
   intent names explicitly at the transport boundary.
2. Replace demo login with verified signed sessions and server-derived role scope.
   Validate issuer/audience/expiry and require identity on execution, telemetry, and
   WebSocket subscriptions. Never accept client-supplied table entitlements.
3. Run the synchronous controller/database path in a bounded executor with explicit
   worker/connection budgets. Add query IDs, deadlines, cooperative cancellation,
   disconnect handling, event sequencing, and reconnect/replay contracts. Cancellation
   of an async await must not be mistaken for native database cancellation.
4. Store query status and redacted audit events durably; filter every telemetry read
   by the authenticated scope. Add exact decimal/date serialization and payload limits.
5. Keep all {counts['tests']} current tests as a gate, then add REST/WS transport parity,
   spoofing/expired-session, concurrent-role isolation, saturation, cancellation, and
   event-replay tests. Establish locked container/CI environments before deployment.
"""
(DOCS / "PHASE01_EXECUTION_REPORT.md").write_text(report, encoding="utf-8")
print(f"Verified tests: {counts['tests']} (44 baseline + {counts['tests'] - 44} additional)")
print(f"Unified diff: {DOCS / 'PHASE01_HARDENING.patch'}")
print(f"Execution report: {DOCS / 'PHASE01_EXECUTION_REPORT.md'}")
