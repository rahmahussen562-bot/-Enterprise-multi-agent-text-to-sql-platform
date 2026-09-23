# Enterprise Multi-Agent Text-to-SQL Platform — Deployment Bundle

This repository bundle contains the standalone, production-hardened source code for deploying the Enterprise Multi-Agent Text-to-SQL Platform with Microsoft SQL Server (T-SQL) integration, Role-Based Access Control (RBAC), and AST-based SQL Injection quarantine firewall.

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

| Role ID | Username | Password | Authorized Table Scope |
| :--- | :--- | :--- | :--- |
| **Commercial Sales** | `sales_analyst` | `Sales@2026!` | `Customer`, `Invoice`, `InvoiceLine` |
| **Catalog & Operations** | `inventory_lead` | `Ops@2026!` | `Track`, `Album`, `Artist`, `Genre`, `MediaType` |

All cross-boundary queries are blocked deterministically by the AST Guardian Firewall before database runtime.
