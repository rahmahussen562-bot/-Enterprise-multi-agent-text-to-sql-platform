"""
Microsoft SQL Server Connectivity Diagnostic & Health Check Utility.
Inspects ODBC drivers, tests live connectivity, measures query latency,
and scans for common enterprise database misconfigurations.
"""
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import get_config, resolve_best_odbc_driver


def run_diagnostics():
    print("=" * 70)
    print(" [MICROSOFT SQL SERVER ENTERPRISE CONNECTIVITY DIAGNOSTICS] ")
    print("=" * 70)

    # 1. Inspect Installed ODBC Drivers
    print("\n[STEP 1: HOST ODBC DRIVER DISCOVERY]")
    try:
        import pyodbc
        installed_drivers = pyodbc.drivers()
        print(f"pyodbc Version: {pyodbc.version}")
        print("Installed ODBC Drivers on Host:")
        for idx, d in enumerate(installed_drivers, 1):
            marker = " *" if "SQL Server" in d else ""
            print(f"  {idx}. {d}{marker}")

        best_driver = resolve_best_odbc_driver(installed_drivers)
        print(f"\nResolved Priority Driver: [{best_driver}]")
    except ImportError:
        print("CRITICAL: 'pyodbc' library is not installed in the active environment.")
        print("Remediation: Run 'pip install pyodbc'")
        return
    except Exception as e:
        print(f"Warning: Driver introspection error: {e}")
        installed_drivers = []

    # 2. Parse Active Configuration
    print("\n[STEP 2: CONFIGURATION & CONNECTION STRING]")
    cfg = get_config().db
    sanitized_str = cfg.get_sanitized_connection_string()
    raw_str = cfg.get_odbc_connection_string()

    print(f"Target Server   : {cfg.server}")
    print(f"Target Database : {cfg.database}")
    print(f"Auth Mode       : {'Windows Authentication (Trusted)' if cfg.trusted_connection else 'SQL Server Authentication'}")
    if not cfg.trusted_connection:
        print(f"User Identity   : {cfg.username or 'Not Provided'}")
    print(f"Active Driver   : {cfg.driver}")
    print(f"Sanitized String: {sanitized_str}")

    # 3. Connection Test & Benchmark
    print("\n[STEP 3: LIVE SERVER CONNECTION TEST]")
    print(f"Attempting connection with {cfg.connection_timeout_sec}s timeout...")

    t_start = time.perf_counter()
    try:
        conn = pyodbc.connect(raw_str, timeout=cfg.connection_timeout_sec)
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION, DB_NAME(), CURRENT_USER, @@SERVERNAME;")
        row = cursor.fetchone()
        query_ms = (time.perf_counter() - t_start) * 1000 - elapsed_ms

        raw_ver = row[0].split("\n")[0] if row else "Unknown"
        db_name = row[1] if row and len(row) > 1 else cfg.database
        user_name = row[2] if row and len(row) > 2 else "Unknown"
        srv_name = row[3] if row and len(row) > 3 else cfg.server

        print("\n[STATUS: LIVE CONNECTION SUCCESSFUL]")
        print(f"  Connection Handshake Latency : {elapsed_ms:.1f} ms")
        print(f"  Query Round-Trip Latency     : {query_ms:.1f} ms")
        print(f"  Connected Server Name        : {srv_name}")
        print(f"  Active Database              : {db_name}")
        print(f"  Session Current User         : {user_name}")
        print(f"  Server Build Version         : {raw_ver}")

        cursor.close()
        conn.close()

    except Exception as err:
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        err_str = str(err)
        print(f"\n[STATUS: CONNECTION FAILED after {elapsed_ms:.1f} ms]")
        print(f"Error Diagnostic: {err_str}")

        print("\n[ACTIONABLE REMEDIATION GUIDELINES]:")

        # Diagnosis A: SSL Certificate Failure on Driver 18
        if "SSL" in err_str or "certificate" in err_str.lower() or "08001" in err_str:
            if "ODBC Driver 18" in cfg.driver:
                print("  • Issue: ODBC Driver 18 mandates encryption by default and rejects untrusted certs.")
                print("    Remediation: Ensure 'TrustServerCertificate=yes;Encrypt=optional;' is present.")
                print("    In .env: Set MSSQL_TRUST_SERVER_CERTIFICATE=yes and MSSQL_ENCRYPT=optional")

        # Diagnosis B: Named instance / SQL Browser failure
        if "\\" in cfg.server or "08001" in err_str or "server was not found" in err_str.lower():
            print("  • Issue: Named instance resolution failure (e.g. SQLEXPRESS).")
            print("    Remediation: 1. Verify SQL Server service is running: Run 'services.msc'.")
            print("                 2. Verify 'SQL Server Browser' service is Started.")
            print("                 3. Open SQL Server Configuration Manager -> SQL Server Network Configuration.")
            print("                    Ensure 'TCP/IP' and 'Named Pipes' are set to Enabled.")

        # Diagnosis C: Authentication Failure
        if "28000" in err_str or "18456" in err_str or "Login failed" in err_str:
            print("  • Issue: Authentication rejected by SQL Server.")
            print("    Remediation: Verify credentials in .env. If using SQL Auth (MSSQL_USER/MSSQL_PASSWORD),")
            print("                 ensure SQL Server is set to 'SQL Server and Windows Authentication mode'")
            print("                 (Server Properties -> Security -> Mixed Mode Authentication).")

        # Diagnosis D: Port / Firewall
        print("  • General: Verify port 1433 (TCP) and port 1434 (UDP for Browser) are allowed in Windows Firewall.")
        print("  • Local Emulation Note: The platform will automatically fall back to its internal T-SQL emulation")
        print("    engine to allow offline query development and evaluation without interruption.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_diagnostics()
