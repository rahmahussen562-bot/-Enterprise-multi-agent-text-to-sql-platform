"""
Enterprise Microsoft SQL Server (T-SQL) Database Engine via pyodbc.
Implements dynamic driver discovery, live schema introspection via INFORMATION_SCHEMA,
safe parameterized T-SQL value probing, and resilient local emulation fallback.
"""
import contextlib
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.config import DatabaseConfig, get_config, resolve_best_odbc_driver

logger = logging.getLogger("TextToSQL.Database")


class MSSQLDatabaseEngine:
    """Enterprise Microsoft SQL Server (T-SQL) database adapter."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or get_config().db
        self._local = threading.local()
        self._use_pyodbc: Optional[bool] = None
        self._detected_driver: str = self.config.driver or resolve_best_odbc_driver()
        self._last_latency_ms: float = 0.0
        self._connection_mode: str = "INITIALIZING"

    @property
    def dialect(self) -> str:
        return "tsql"

    @property
    def detected_driver(self) -> str:
        return self._detected_driver

    @property
    def connection_mode(self) -> str:
        return self._connection_mode

    @property
    def last_latency_ms(self) -> float:
        return self._last_latency_ms

    def test_connection(self) -> Tuple[bool, str, float, str]:
        """
        Verify database connectivity, benchmark round-trip latency, and report mode.
        Returns: (is_connected: bool, message: str, latency_ms: float, mode: str)
        """
        # 1. Attempt Live Microsoft SQL Server via pyodbc
        try:
            import pyodbc
            conn_str = self.config.get_odbc_connection_string()
            t_start = time.perf_counter()

            with pyodbc.connect(conn_str, timeout=self.config.connection_timeout_sec) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT @@VERSION, DB_NAME(), CURRENT_USER, @@SERVERNAME;")
                row = cursor.fetchone()
                latency_ms = (time.perf_counter() - t_start) * 1000

                raw_version = row[0].split("\n")[0] if row else "Microsoft SQL Server"
                db_name = row[1] if row and len(row) > 1 else self.config.database
                user_name = row[2] if row and len(row) > 2 else "Unknown"
                srv_name = row[3] if row and len(row) > 3 else self.config.server

                self._use_pyodbc = True
                self._connection_mode = "LIVE_MSSQL"
                self._last_latency_ms = latency_ms

                return (
                    True,
                    f"Connected to MS SQL Server '{srv_name}' [DB: {db_name}, User: {user_name}] ({raw_version})",
                    latency_ms,
                    "LIVE_MSSQL"
                )

        except Exception as odbc_err:
            logger.info(f"pyodbc connection attempt skipped/failed ({odbc_err}). Using resilient T-SQL local engine.")
            self._use_pyodbc = False

        # 2. Local T-SQL Emulation Engine
        try:
            t_start = time.perf_counter()
            with self._get_sqlite_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT sqlite_version();")
                ver = cursor.fetchone()[0]
                latency_ms = (time.perf_counter() - t_start) * 1000

                self._connection_mode = "MOCK_EMULATOR"
                self._last_latency_ms = latency_ms

                return (
                    True,
                    f"T-SQL Local Engine Ready (SQLite v{ver} Storage: {self.config.sqlite_path})",
                    latency_ms,
                    "MOCK_EMULATOR"
                )
        except Exception as e:
            self._connection_mode = "ERROR"
            return False, f"Database initialization error: {str(e)}", 0.0, "ERROR"

    @contextlib.contextmanager
    def get_connection(self):
        """Yield a thread-safe connection instance."""
        if self._use_pyodbc is True:
            import pyodbc
            conn_str = self.config.get_odbc_connection_string()
            conn = pyodbc.connect(conn_str, timeout=self.config.connection_timeout_sec)
            try:
                yield conn
            finally:
                conn.close()
        else:
            with self._get_sqlite_connection() as conn:
                yield conn

    def _get_sqlite_connection(self):
        parent = Path(self.config.sqlite_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.config.sqlite_path,
            timeout=float(self.config.connection_timeout_sec),
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        self._ensure_information_schema_views(conn)
        return conn

    def _ensure_information_schema_views(self, conn: sqlite3.Connection):
        """Ensure standard ANSI INFORMATION_SCHEMA views exist for T-SQL compatibility."""
        cur = conn.cursor()
        cur.executescript("""
        CREATE VIEW IF NOT EXISTS INFORMATION_SCHEMA_COLUMNS AS
        SELECT 
            m.name AS TABLE_NAME,
            p.name AS COLUMN_NAME,
            UPPER(p.type) AS DATA_TYPE,
            CASE WHEN p.[notnull] = 1 THEN 'NO' ELSE 'YES' END AS IS_NULLABLE,
            p.cid AS ORDINAL_POSITION
        FROM sqlite_master m
        JOIN pragma_table_info(m.name) p
        WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%';
        """)
        conn.commit()

    def get_table_names(self, authorized_tables: Optional[List[str]] = None) -> List[str]:
        """Fetch list of user table names filtered strictly by RBAC authorization."""
        tables: List[str] = []
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if self._use_pyodbc:
                    query = """
                    SELECT TABLE_NAME 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_NAME;
                    """
                    cursor.execute(query)
                    tables = [row[0] for row in cursor.fetchall()]
                else:
                    query = """
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name;
                    """
                    cursor.execute(query)
                    tables = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"Error fetching table names: {e}")

        if authorized_tables is not None:
            auth_set = {t.lower() for t in authorized_tables}
            return [t for t in tables if t.lower() in auth_set]
        return tables

    def get_table_schema_ddl(self, table_name: str) -> str:
        """Fetch CREATE TABLE DDL formatted in T-SQL standard."""
        cols = self.get_table_columns_info(table_name)
        if not cols:
            return f"CREATE TABLE [{table_name}] ();"

        col_defs = []
        for c in cols:
            null_str = "NOT NULL" if c["notnull"] else "NULL"
            col_defs.append(f"    [{c['name']}] {c['type']} {null_str}")

        return f"CREATE TABLE [{table_name}] (\n" + ",\n".join(col_defs) + "\n);"

    def get_all_ddls(self, authorized_tables: Optional[List[str]] = None) -> Dict[str, str]:
        """Return table_name -> CREATE TABLE DDL filtered strictly by authorization."""
        tables = self.get_table_names(authorized_tables=authorized_tables)
        return {t: self.get_table_schema_ddl(t) for t in tables}

    def get_table_columns_info(self, table_name: str) -> List[Dict[str, Any]]:
        """Return list of column metadata for a given table from INFORMATION_SCHEMA."""
        clean_table = table_name.strip("[]")
        cols: List[Dict[str, Any]] = []

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self._use_pyodbc:
                cursor.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = ?
                    ORDER BY ORDINAL_POSITION;
                """, (clean_table,))
                for row in cursor.fetchall():
                    cols.append({
                        "name": row[0],
                        "type": str(row[1]).upper(),
                        "notnull": str(row[2]).upper() == "NO",
                        "pk": False
                    })
            else:
                cursor.execute(f"PRAGMA table_info([{clean_table}]);")
                for row in cursor.fetchall():
                    cols.append({
                        "name": row[1],
                        "type": row[2].upper(),
                        "notnull": bool(row[3]),
                        "pk": bool(row[5])
                    })
        return cols

    def get_foreign_keys(self, authorized_tables: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """Fetch foreign key constraints filtered strictly by active user scope."""
        fks: List[Dict[str, str]] = []
        tables = self.get_table_names(authorized_tables=authorized_tables)
        auth_set = {t.lower() for t in tables}

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for t in tables:
                if self._use_pyodbc:
                    query = """
                    SELECT 
                        OBJECT_NAME(f.parent_object_id) AS from_table,
                        COL_NAME(fc.parent_object_id, fc.parent_column_id) AS from_column,
                        OBJECT_NAME(f.referenced_object_id) AS to_table,
                        COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS to_column
                    FROM sys.foreign_keys AS f
                    INNER JOIN sys.foreign_key_columns AS fc 
                        ON f.OBJECT_ID = fc.constraint_object_id
                    WHERE OBJECT_NAME(f.parent_object_id) = ?;
                    """
                    cursor.execute(query, (t,))
                    for r in cursor.fetchall():
                        if r[2].lower() in auth_set:
                            fks.append({
                                "from_table": r[0],
                                "from_column": r[1],
                                "to_table": r[2],
                                "to_column": r[3]
                            })
                else:
                    cursor.execute(f"PRAGMA foreign_key_list([{t}]);")
                    for r in cursor.fetchall():
                        to_table = r[2]
                        if to_table.lower() in auth_set:
                            fks.append({
                                "from_table": t,
                                "from_column": r[3],
                                "to_table": to_table,
                                "to_column": r[4]
                            })
        return fks

    def probe_distinct_values(
        self,
        table_name: str,
        column_name: str,
        limit: int = 5,
        pattern: Optional[str] = None
    ) -> List[str]:
        """
        Active Data Reconnaissance probe using T-SQL standard:
        SELECT DISTINCT TOP {limit} [{col}] FROM [{table}] WHERE ...
        """
        clean_tbl = table_name.strip("[]")
        clean_col = column_name.strip("[]")

        valid_tables = self.get_table_names()
        if clean_tbl not in valid_tables:
            return []

        q_tbl = f"[{clean_tbl}]"
        q_col = f"[{clean_col}]"

        params: List[Any] = []
        where_clauses = [f"{q_col} IS NOT NULL", f"CAST({q_col} AS VARCHAR(255)) != ''"]

        if pattern:
            where_clauses.append(f"{q_col} LIKE ?")
            params.append(f"%{pattern}%")

        where_stmt = " AND ".join(where_clauses)

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if self._use_pyodbc:
                    tsql_query = f"SELECT DISTINCT TOP {int(limit)} {q_col} FROM {q_tbl} WHERE {where_stmt};"
                    cursor.execute(tsql_query, tuple(params))
                else:
                    # SQLite emulation of T-SQL probe
                    sql_query = f"SELECT DISTINCT {q_col} FROM {q_tbl} WHERE {where_stmt} LIMIT {int(limit)};"
                    cursor.execute(sql_query, tuple(params))
                rows = cursor.fetchall()
                return [str(r[0]) for r in rows if r[0] is not None]
        except Exception as err:
            logger.warning(f"Probe distinct values failed on {clean_tbl}.{clean_col}: {err}")
            return []

    def execute_query(self, sql: str, timeout_sec: Optional[int] = None) -> pd.DataFrame:
        """
        Safely execute T-SQL query with timeout protection and return Pandas DataFrame.
        """
        timeout = timeout_sec or self.config.query_timeout_sec
        result_container: Dict[str, Any] = {"df": None, "error": None}

        exec_sql = sql
        if not self._use_pyodbc:
            exec_sql = self._adapt_tsql_for_emulation(sql)

        def _worker():
            try:
                with self.get_connection() as conn:
                    result_container["df"] = pd.read_sql_query(exec_sql, conn)
            except Exception as e:
                result_container["error"] = e

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join(timeout=float(timeout))

        if thread.is_alive():
            raise TimeoutError(f"Query execution timed out after {timeout} seconds.")

        if result_container["error"] is not None:
            raise result_container["error"]

        return result_container["df"] if result_container["df"] is not None else pd.DataFrame()

    def _adapt_tsql_for_emulation(self, sql: str) -> str:
        """
        Transpile T-SQL dialect (TOP N, bracket identifiers) to SQLite syntax
        so queries run cleanly on the local test engine while retaining 100% T-SQL compliance.
        """
        try:
            import sqlglot
            expression = sqlglot.parse_one(sql, read="tsql")
            return expression.sql(dialect="sqlite")
        except Exception:
            return sql


# Compatibility Alias
DatabaseEngine = MSSQLDatabaseEngine
