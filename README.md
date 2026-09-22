# Enterprise Multi-Agent Text-to-SQL Platform (Microsoft SQL Server / T-SQL)

A production-grade, corporate-hardened conversational Text-to-SQL platform built in Python using **Streamlit**, **Microsoft SQL Server (T-SQL)**, **Vanna AI**, and **sqlglot**.

---

## Architectural Upgrades & Enterprise Capabilities

This architecture addresses the failure modes of the state-of-the-art **BIRD-Interact** benchmark and introduces corporate-grade governance:

1. **Microsoft SQL Server (T-SQL) Dialect Standard:**
   - Full T-SQL compliance with bracket quoting `[Table].[Column]`, `TOP N` row restrictions, and ANSI Common Table Expressions (CTEs).
   - Dynamic schema inspection via `INFORMATION_SCHEMA.COLUMNS` and `INFORMATION_SCHEMA.TABLE_CONSTRAINTS`.
   - Native integration with Microsoft ODBC Driver for SQL Server (`pyodbc`) and resilient local T-SQL execution fallback.
2. **Multi-User Role-Based Access Control (RBAC) & Row/Table-Level Control (RLC):**
   - Session-based corporate authentication isolating user authority by business domain:
     - **Commercial Scope (`sales_analyst`):** Whitelisted exclusively for `[Customer]`, `[Invoice]`, and `[InvoiceLine]`.
     - **Catalog Scope (`inventory_lead`):** Whitelisted exclusively for `[Track]`, `[Album]`, `[Artist]`, `[Genre]`, and `[MediaType]`.
3. **Deterministic AST SQL Injection Quarantine & Policy Firewall:**
   - Pre-runtime AST traversal using `sqlglot` (`dialect="tsql"`).
   - Strict read-only enforcement: blocks all non-`SELECT` statements and destructive AST nodes (`DROP`, `DELETE`, `UPDATE`, `ALTER`, `TRUNCATE`, `INSERT`, `EXEC`, stored procedures).
   - Multi-statement injection defense: detects and rejects stacked queries separated by semicolons.
   - Table-Level Privilege Enforcement: extracts all referenced tables from the AST and verifies them against the active user's authorization whitelist before database runtime.
   - Defensive T-SQL Safeguard: automatically injects `TOP 100` into root `SELECT` queries if omitted.
   - Cartesian Defense: detects unconditioned joins (`ON TRUE` or missing join predicates) to prevent table explosion.
4. **Active Data Reconnaissance:**
   - Dynamically probes categorical values (`SELECT DISTINCT TOP 5 [col] FROM [table] WHERE ...`) prior to query synthesis, eliminating casing and format mismatches.
5. **Execution-Guided Self-Healing:**
   - Closed-loop retry state machine diagnosing zero-result sets (`len(df) == 0`) and runtime errors, providing automated query refactoring and diff visualization.
6. **Corporate Industrial Design System:**
   - 100% de-emojified professional UI adhering to enterprise styling standards (Dark Slate `#0f172a`, Corporate Navy `#1e293b`, Off-White `#f8fafc`).
   - Clean industrial ASCII nomenclature (`[AUTH]`, `[EXPLORER]`, `[CODER]`, `[GUARDIAN]`, `[EVALUATOR]`).

---

## Multi-Agent Topology (4-Agent State Machine)

```
                       +-----------------------------------+
                       |    Corporate User Authentication  |
                       |    (sales_analyst/inventory_lead) |
                       +-----------------+-----------------+
                                         |
                                         v
                       +-----------------------------------+
                       |    User Natural Language Query    |
                       +-----------------+-----------------+
                                         |
                                         v
                       +-----------------------------------+
                       |   Central Controller (State Mach) |
                       +-----------------+-----------------+
                                         |
         +-------------------------------+-------------------------------+
         |                                                               |
         v                                                               |
+-------------------------------+                                        |
|  Agent 1: Explorer            |                                        |
|  - RBAC-Scoped Schema Pruning |                                        |
|  - T-SQL Distinct Value Probe |                                        |
|  - Context Packing            |                                        |
+---------------+---------------+                                        |
                | (Schema Card + Grounded Values)                        |
                v                                                        |
+-------------------------------+                                        |
|  Agent 2: Coder               |<-------------------+                   |
|  - T-SQL Dialect Optimization |                    |                   |
|  - [Table].[Column] Brackets  |                    |                   |
|  - CTE-First Architecture     |                    |                   |
|  - Critique-Aware Refactoring |                    |                   |
+---------------+---------------+                    |                   |
                | (Raw T-SQL Draft)                  |                   |
                v                                    |                   |
+-------------------------------+                    |                   |
|  Agent 3: Guardian            |                    |                   |
|  - sqlglot AST Parsing (tsql) |                    |                   |
|  - SQL Injection Quarantine   |---[AST Failure]----+                   |
|  - Strict RBAC Whitelist Check|    (Critique & Diff)                   |
|  - Cartesian Join Prevention  |                                        |
|  - Defensive TOP 100 Injection|                                        |
+---------------+---------------+                                        |
                | (Sanitized T-SQL)                                      |
                v                                                        |
+-------------------------------+                                        |
|  Agent 4: Evaluator           |                                        |
|  - Sandbox Timeout Execution  |                                        |
|  - Zero-Result Diagnosis      |---[Zero Rows/Anomaly]                  |
|  - Domain Sanity Checks       |    (Relax Filters & Diff)              |
|  - Formal Narrative Synthesis |                                        |
+---------------+---------------+                                        |
                | (Tabular DataFrame + Narrative)                        |
                v                                                        |
+---------------------------------------------------------------+        |
|                  Streamlit Corporate UI                       |        |
|  - Live Status Handoffs [Explorer -> Coder -> Guard -> Eval]  |        |
|  - Self-Healing Diff Display (Failed vs Corrected T-SQL)      |<-------+
|  - Autonomous Visual Analytics (Plotly Line/Bar/Donut/Scatter)|
|  - Enterprise Data Export (CSV / Excel)                       |
|  - Active Learning: [Record Verified Query] -> vn.train()     |
+---------------------------------------------------------------+
```

---

## Directory Structure

```text
├── app.py                      # Main Streamlit UI with RBAC login and industrial layout
├── core/
│   ├── __init__.py
│   ├── auth.py                 # Multi-user authentication & table authorization whitelists
│   ├── config.py               # Environment variables, T-SQL dialect, and pyodbc settings
│   ├── vanna_client.py         # Vanna initialization (ChromaDB + LLM provider)
│   └── database.py             # MS SQL Server engine (pyodbc) & RBAC INFORMATION_SCHEMA
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py         # Pipeline coordinator & retry loop state machine
│   ├── reconnaissance.py       # Agent 1: RBAC schema retrieval & T-SQL value probe
│   ├── coder.py                # Agent 2: T-SQL generator (TOP N, brackets, CTEs)
│   ├── guardian.py             # Agent 3: sqlglot T-SQL AST parser, injection & RBAC firewall
│   └── critic.py               # Agent 4: Execution evaluator & formal analytical narrative
├── utils/
│   ├── __init__.py
│   ├── visualizer.py           # Adaptive Plotly chart generator
│   └── db_seeder.py            # Automated Chinook or E-commerce SQLite DB downloader
├── tests/
│   ├── test_auth.py            # Authentication, session security & table whitelist tests
│   ├── test_database.py        # T-SQL DB engine, INFORMATION_SCHEMA & probe tests
│   ├── test_guardian.py        # AST injection quarantine, TOP 100 & RBAC firewall tests
│   ├── test_reconnaissance.py  # RBAC-filtered reconnaissance & T-SQL value probing tests
│   ├── test_orchestrator.py    # 4-Agent state machine execution under corporate personas
│   └── test_visualizer.py      # Plotly recommendation & visualization tests
├── requirements.txt            # streamlit, pyodbc, vanna, pandas, plotly, sqlglot, openpyxl
└── README.md                   # Architecture diagram, setup guide, and usage instructions
```

---

## Quickstart & Installation

### 1. Environment Setup
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Corporate Authentication Credentials
The platform includes two pre-configured corporate personas:

| Corporate ID / Username | Password | Role Title | Authorized Table Whitelist | Scope |
| :--- | :--- | :--- | :--- | :--- |
| `sales_analyst` | `Sales@2026!` | Sales Analyst | `[Customer]`, `[Invoice]`, `[InvoiceLine]` | Commercial Domain |
| `inventory_lead` | `Ops@2026!` | Inventory Lead | `[Track]`, `[Album]`, `[Artist]`, `[Genre]`, `[MediaType]` | Catalog Domain |

### 3. Launch the Application
```bash
streamlit run app.py --server.port 8502
```
Access the application at `http://localhost:8502`.

---

## Running the Verification Suite

Execute the automated test suite across all modules:
```bash
python -m unittest discover -s tests -p "test_*.py"
```
Result: **28 unit tests passing (100% pass rate)**.
