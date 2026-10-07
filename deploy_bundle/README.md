# Enterprise Multi-Agent Text-to-SQL Platform — Deployment Bundle

This repository bundle contains the standalone, production-hardened source code for deploying the Enterprise Multi-Agent Text-to-SQL Platform with Microsoft SQL Server (T-SQL) integration, Role-Based Access Control (RBAC), and AST-based SQL Injection quarantine firewall.

Phase 2 provides a decoupled FastAPI service. Follow [api/README.md](api/README.md) for private account provisioning, D-drive startup, REST contracts, and WebSocket streaming. The verified runtime is the self-contained D-drive environment; use its installer rather than the historical generic commands below.

Phase 4 adds FinCore Enterprise on PostgreSQL 17+: asynchronous Psycopg pooling
and cancellation, a balanced immutable ledger, native branch/case RLS, masked
views, and registry-controlled financial metrics. The original two roles retain
the legacy engine. See [FinCore schema and operating guide](docs/FINCORE_SCHEMA.md)
for migration and private principal provisioning. The React workspace at
`D:\BIRD-Interact\frontend` supports all five server-governed personas.

---

## 1. Directory Structure

```text
deploy_bundle/
├── app.py                  # Main Streamlit corporate gateway & UI
├── requirements.txt        # Production Python dependencies
├── packages.txt            # Linux OS packages (ODBC headers for cloud deploy)
├── .env.example            # Environment template for MS SQL Server
├── .gitignore              # Production git staging exclusions
├── README.md               # Deployment and operational documentation
├── core/                   # Security, configuration, and database engines
│   ├── __init__.py
│   ├── auth.py             # User authentication & RBAC table filtering
│   ├── config.py           # Dynamic ODBC driver resolution & connection settings
│   ├── database.py         # Thread-safe pyodbc adapter & resilient local engine
│   └── vanna_client.py     # Semantic store & retrieval module
├── agents/                 # Autonomous 4-Agent Topology
│   ├── __init__.py
│   ├── reconnaissance.py   # Active schema explorer & Top-5 value prober
│   ├── coder.py            # Pure T-SQL code generator with TOP N restrictions
│   ├── guardian.py         # AST sqlglot firewall (injection, RBAC, Cartesian)
│   ├── critic.py           # Sandbox evaluator & zero-result anomaly diagnosis
│   ├── orchestrator.py     # Central controller & self-healing state machine
│   └── visualizer.py       # Autonomous Plotly data analytics generator
├── utils/                  # Utility packages
│   ├── __init__.py
│   └── visualizer.py       # Re-export for standard utility imports
└── tools/                  # Diagnostics & Maintenance
    ├── __init__.py
    └── diagnose_mssql.py   # Standalone CLI MS SQL connection & latency benchmark
```

---

## 2. Installation & Prerequisites

### Windows Environments
1. Ensure Python 3.10+ is installed.
2. Ensure Microsoft ODBC Driver 17 or 18 for SQL Server is installed on the host.
3. Install required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

### Linux / Container / Cloud Environments (e.g. Streamlit Cloud, HF Spaces)
1. Install system ODBC dependencies (handled automatically by `packages.txt` on Streamlit Community Cloud):
   ```bash
   sudo apt-get update && sudo apt-get install -y unixodbc unixodbc-dev
   ```
2. Install Python packages:
   ```bash
   pip install -r requirements.txt
   ```

---

## 3. Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Configure target Microsoft SQL Server parameters:
   - For **Windows Integrated Authentication**:
     ```env
     MSSQL_SERVER=localhost\SQLEXPRESS
     MSSQL_DATABASE=YourDatabase
     MSSQL_TRUSTED_CONNECTION=yes
     MSSQL_TRUST_SERVER_CERTIFICATE=yes
     ```
   - For **SQL Server Authentication**:
     ```env
     MSSQL_SERVER=sqlserver.corp.local,1433
     MSSQL_DATABASE=YourDatabase
     MSSQL_TRUSTED_CONNECTION=no
     MSSQL_USER=your_user
     MSSQL_PASSWORD=YourPassword!
     MSSQL_TRUST_SERVER_CERTIFICATE=yes
     MSSQL_ENCRYPT=optional
     ```

---

## 4. Connectivity Diagnostics

Verify network reachability, ODBC driver detection, and round-trip query latency before launching the service:
```bash
python tools/diagnose_mssql.py
```

---

## 5. Launching the Corporate Platform

Start the Streamlit application:
```bash
streamlit run app.py
```
Or with custom network parameters:
```bash
streamlit run app.py --server.port 8502 --server.headless true
```

---

## 6. Access Control & Security Personas

| Role ID | Account Provisioning | Authorized Table Scope |
| :--- | :--- | :--- |
| **Commercial Sales** | Private account assigned `sales_analyst` by the server | `Customer`, `Invoice`, `InvoiceLine` |
| **Catalog & Operations** | Private account assigned `inventory_lead` by the server | `Track`, `Album`, `Artist`, `Genre`, `MediaType` |

Run `tools/bootstrap_api.py` in the D-drive virtual environment to choose credentials. Only salted password hashes are stored. There are no published or built-in demo passwords.

All cross-boundary queries are blocked deterministically by the AST Guardian Firewall before database runtime.


## Phase 5/6 production package

The decoupled API and React portal now have a parameterized Cloudflare deployment package. See [the deployment runbook](docs/CLOUDFLARE_DEPLOYMENT.md) for private `.internal` routing, public-zone alternatives, Docker/TLS/secret provisioning, Pages builds and CI/CD. The root workflow is `../.github/workflows/deploy.yml`; build contexts are `deploy_bundle/` and `frontend/`.

Verification: 326 backend tests, 20 frontend tests and 14 edge/header tests passed, with zero npm vulnerabilities. [Execution report](docs/PHASE56_EXECUTION_REPORT.md). Docker/live Cloudflare deployment remains pending a provisioned engine, runner and protected credentials.
