"""
Enterprise Microsoft SQL Server (T-SQL) Database Engine via pyodbc.
Implements dynamic driver discovery, live schema introspection via INFORMATION_SCHEMA,
safe parameterized T-SQL value probing, and explicitly enabled local demo emulation.
"""
import contextlib
import logging
import math
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.config import DatabaseConfig, get_config, resolve_best_odbc_driver
from core.cancellation import QueryCancelledError, cancellable_connection, check_cancelled, current_cancellation

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
        check_cancelled()
        # 1. Attempt Live Microsoft SQL Server via pyodbc
        try:
            import pyodbc
            conn_str = self.config.get_odbc_connection_string()
            t_start = time.perf_counter()

            with contextlib.closing(pyodbc.connect(conn_str, timeout=self.config.connection_timeout_sec)) as conn:
                conn.timeout = self.config.query_timeout_sec
                with cancellable_connection(conn, native_odbc=True) as leased:
                    cursor = leased.cursor()
                    try:
                        cursor.execute("SELECT @@VERSION, DB_NAME(), CURRENT_USER, @@SERVERNAME;")
                        row = cursor.fetchone()
                        check_cancelled()
                    finally:
                        cursor.close()
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

        except QueryCancelledError:
            raise
        except Exception as odbc_err:
            check_cancelled()
            if not getattr(self.config, "allow_sqlite_emulation", False):
                self._use_pyodbc = None
                self._connection_mode = "ERROR"
                self._last_latency_ms = 0.0
                return (
                    False,
                    f"Live SQL Server connection failed; explicit demo emulation is disabled: {odbc_err}",
                    0.0,
                    "ERROR",
                )
            logger.info("Live connection failed (%s); explicitly configured demo emulation enabled.", odbc_err)
            self._use_pyodbc = False

        # 2. Local T-SQL Emulation Engine
        try:
            t_start = time.perf_counter()
            with contextlib.closing(self._get_sqlite_connection()) as conn:
                with cancellable_connection(conn, native_odbc=False):
                    cursor = conn.cursor()
                    try:
                        cursor.execute("SELECT sqlite_version();")
                        ver = cursor.fetchone()[0]
                        check_cancelled()
                    finally:
                        cursor.close()
                latency_ms = (time.perf_counter() - t_start) * 1000

                self._connection_mode = "MOCK_EMULATOR"
                self._last_latency_ms = latency_ms

                return (
                    True,
                    f"T-SQL Local Engine Ready (SQLite v{ver} Storage: {self.config.sqlite_path})",
                    latency_ms,
                    "MOCK_EMULATOR"
                )
        except QueryCancelledError:
            raise
        except Exception as e:
            check_cancelled()
            self._connection_mode = "ERROR"
            return False, f"Database initialization error: {str(e)}", 0.0, "ERROR"

    @contextlib.contextmanager
    def get_connection(self):
        """Yield a thread-safe connection instance."""
        check_cancelled()
        if self._use_pyodbc is True:
            import pyodbc
            conn_str = self.config.get_odbc_connection_string()
            conn = pyodbc.connect(conn_str, timeout=self.config.connection_timeout_sec)
            try:
                conn.timeout = self.config.query_timeout_sec
                with cancellable_connection(conn, native_odbc=True) as leased:
                    yield leased
            finally:
                conn.close()
        else:
            if not getattr(self.config, "allow_sqlite_emulation", False):
                raise ConnectionError("Live database connectivity is unavailable and explicit demo emulation is disabled.")
            # sqlite3's context manager commits/rolls back; it does not close.
            with contextlib.closing(self._get_sqlite_connection()) as conn:
                with cancellable_connection(conn, native_odbc=False) as leased:
                    yield leased

    def _get_sqlite_connection(self):
        if not getattr(self.config, "allow_sqlite_emulation", False):
            raise ConnectionError("SQLite emulation requires explicit SENTINEL_DEMO_MODE configuration.")
        parent = Path(self.config.sqlite_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.config.sqlite_path,
            timeout=float(self.config.connection_timeout_sec),
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        try:
            with cancellable_connection(conn, native_odbc=False):
                self._ensure_information_schema_views(conn)
                check_cancelled()
        except BaseException:
            conn.close()
            raise
        return conn

    def _ensure_information_schema_views(self, conn: sqlite3.Connection):
        """Ensure standard ANSI INFORMATION_SCHEMA views exist for T-SQL compatibility."""
        cur = conn.cursor()
        try:
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
        finally:
            cur.close()

    def get_table_names(self, authorized_tables: Optional[Any] = None) -> List[str]:
        """Fetch list of user table names filtered strictly by RBAC authorization."""
        auth_list = None
        if authorized_tables is not None:
            if hasattr(authorized_tables, "allowed_tables"):
                auth_list = authorized_tables.allowed_tables
            elif hasattr(authorized_tables, "authorized_tables"):
                auth_list = authorized_tables.authorized_tables
            elif isinstance(authorized_tables, (list, tuple, set)):
                auth_list = list(authorized_tables)

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

        if auth_list is not None:
            auth_set = {t.strip("[]\"'").lower() for t in auth_list}
            return [t for t in tables if t.strip("[]\"'").lower() in auth_set]
        return tables

    def get_table_schema_ddl(self, table_name: str, authorized_tables: Optional[Any] = None) -> str:
        """Fetch CREATE TABLE DDL formatted in T-SQL standard with RBAC enforcement."""
        clean_tbl = table_name.strip("[]\"'")
        if authorized_tables is not None:
            auth_list = getattr(authorized_tables, "allowed_tables", getattr(authorized_tables, "authorized_tables", authorized_tables))
            if isinstance(auth_list, (list, tuple, set)):
                auth_set = {t.strip("[]\"'").lower() for t in auth_list}
                if clean_tbl.lower() not in auth_set:
                    raise PermissionError(f"SecurityViolationException: Table [{clean_tbl}] is unauthorized for active session.")

        cols = self.get_table_columns_info(clean_tbl)
        if not cols:
            return f"CREATE TABLE [{clean_tbl}] ();"

        col_defs = []
        for c in cols:
            null_str = "NOT NULL" if c["notnull"] else "NULL"
            col_defs.append(f"    [{c['name']}] {c['type']} {null_str}")

        return f"CREATE TABLE [{clean_tbl}] (\n" + ",\n".join(col_defs) + "\n);"

    def get_all_ddls(self, authorized_tables: Optional[Any] = None) -> Dict[str, str]:
        """Return table_name -> CREATE TABLE DDL filtered strictly by authorization."""
        tables = self.get_table_names(authorized_tables=authorized_tables)
        return {t: self.get_table_schema_ddl(t, authorized_tables=authorized_tables) for t in tables}

    def get_table_columns_info(self, table_name: str) -> List[Dict[str, Any]]:
        """Resolve metadata for the exact catalog/schema/table, never a basename fallback."""
        import sqlglot
        from sqlglot import exp
        from sqlglot.tokens import TokenType

        tokens = sqlglot.Dialect.get_or_raise("tsql").tokenize(table_name)
        if len(tokens) not in {1, 3, 5} or any(
            token.token_type not in {TokenType.VAR, TokenType.IDENTIFIER} if index % 2 == 0
            else token.token_type != TokenType.DOT
            for index, token in enumerate(tokens)
        ):
            raise ValueError("A plain, optionally schema-qualified table identifier is required.")
        table = sqlglot.parse_one(table_name, read="tsql", into=exp.Table)
        if not isinstance(table, exp.Table) or not table.name or any(
            not isinstance(part, exp.Identifier) for part in table.parts
        ) or any(value for key, value in table.args.items() if key not in {"this", "db", "catalog"}):
            raise ValueError("A plain, optionally schema-qualified table identifier is required.")
        clean_table = table.name
        table_schema = table.db or "dbo"
        table_catalog = table.catalog or self.config.database
        cols: List[Dict[str, Any]] = []

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self._use_pyodbc:
                cursor.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
                           TABLE_NAME, TABLE_SCHEMA, TABLE_CATALOG
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = ? AND TABLE_SCHEMA = ? AND TABLE_CATALOG = ?
                    ORDER BY ORDINAL_POSITION;
                """, (clean_table, table_schema, table_catalog))
                for row in cursor.fetchall():
                    cols.append({
                        "name": row[0],
                        "type": str(row[1]).upper(),
                        "notnull": str(row[2]).upper() == "NO",
                        "pk": False,
                        "table_name": row[3],
                        "table_schema": row[4],
                        "table_catalog": row[5]
                    })
            else:
                if table_schema.casefold() not in {"dbo", "main"} or table_catalog.casefold() != self.config.database.casefold():
                    raise PermissionError("The local emulator cannot inspect another catalog or schema.")
                quoted_table = '"' + clean_table.replace('"', '""') + '"'
                cursor.execute(f"PRAGMA main.table_info({quoted_table});")
                for row in cursor.fetchall():
                    cols.append({
                        "name": row[1],
                        "type": row[2].upper(),
                        "notnull": bool(row[3]),
                        "pk": bool(row[5]),
                        "table_name": clean_table,
                        "table_schema": table_schema,
                        "table_catalog": table_catalog
                    })
            cursor.close()
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
                    WHERE OBJECT_NAME(f.parent_object_id) = ?
                      AND OBJECT_SCHEMA_NAME(f.parent_object_id) = 'dbo'
                      AND OBJECT_SCHEMA_NAME(f.referenced_object_id) = 'dbo';
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
        pattern: Optional[str] = None,
        authorized_tables: Optional[Any] = None
    ) -> List[str]:
        """
        Active Data Reconnaissance probe using T-SQL standard:
        SELECT DISTINCT TOP {limit} [{col}] FROM [{table}] WHERE ...
        Strictly enforces RBAC authorized tables.
        """
        clean_tbl = table_name.strip("[]\"'")
        clean_col = column_name.strip("[]\"'")

        if authorized_tables is not None:
            auth_list = getattr(authorized_tables, "allowed_tables", getattr(authorized_tables, "authorized_tables", authorized_tables))
            if isinstance(auth_list, (list, tuple, set)):
                auth_set = {t.strip("[]\"'").lower() for t in auth_list}
                if clean_tbl.lower() not in auth_set:
                    logger.warning(f"Unauthorized probe attempt blocked on table: {clean_tbl}")
                    return []

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
        Execute synchronously with native cancellation and bounded result materialization.

        ODBC's statement timeout stops work in the driver; SQLite's progress handler
        interrupts its virtual machine. No background query thread survives a timeout.
        This boundary expects SQL already approved by the AST Guardian.
        """
        timeout = float(self.config.query_timeout_sec if timeout_sec is None else timeout_sec)
        check_cancelled()
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Query timeout must be a finite, positive number of seconds.")
        max_rows = int(getattr(self.config, "max_result_rows", 10000))
        max_bytes = int(getattr(self.config, "max_result_bytes", 10 * 1024 * 1024))
        if max_rows <= 0 or max_bytes <= 0:
            raise ValueError("Result row and byte budgets must be positive.")
        deadline = time.monotonic() + timeout
        exec_sql = sql
        if not self._use_pyodbc:
            exec_sql = self._adapt_tsql_for_emulation(sql)
        with self.get_connection() as conn:
            cursor = None
            interrupted = False
            cancelled = False

            def _cancel():
                nonlocal cancelled
                if cancelled:
                    return
                cancelled = True
                if self._use_pyodbc:
                    if cursor is not None:
                        cursor.cancel()
                else:
                    conn.interrupt()

            def _progress():
                nonlocal interrupted
                token = current_cancellation.get()
                if token is not None and token.cancelled:
                    return 1
                if time.monotonic() >= deadline:
                    interrupted = True
                    _cancel()
                    return 1
                return 0

            try:
                if self._use_pyodbc:
                    # pyodbc exposes SQL_ATTR_QUERY_TIMEOUT on the connection.
                    # Unsupported timeout configuration is an error, never a fallback.
                    conn.timeout = max(1, math.ceil(max(0, deadline - time.monotonic())))
                    conn.autocommit = False
                else:
                    conn.execute("PRAGMA query_only = ON;")
                    remaining_ms = max(1, math.ceil(max(0, deadline - time.monotonic()) * 1000))
                    conn.execute(f"PRAGMA busy_timeout = {remaining_ms};")
                    conn.set_progress_handler(_progress, 1000)
                cursor = conn.cursor()
                if time.monotonic() >= deadline:
                    raise TimeoutError("The query deadline elapsed before execution.")
                cursor.execute(exec_sql)
                if cursor.description is None:
                    raise ValueError("Only queries returning a result set may be executed.")
                columns = [item[0] for item in cursor.description]
                records = []
                total_bytes = 0
                while True:
                    check_cancelled()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("The query deadline elapsed during execution.")
                    batch = cursor.fetchmany(min(256, max_rows + 1 - len(records)))
                    if time.monotonic() >= deadline:
                        raise TimeoutError("The query deadline elapsed while fetching results.")
                    if not batch:
                        break
                    for row in batch:
                        record = tuple(row)
                        total_bytes += sum(len(str(value).encode("utf-8")) for value in record if value is not None)
                        records.append(record)
                        if len(records) > max_rows or total_bytes > max_bytes:
                            _cancel()
                            raise ValueError("Query result exceeds the configured row or byte budget.")
                return pd.DataFrame.from_records(records, columns=columns)
            except Exception as exc:
                check_cancelled()
                sqlstate = str(exc.args[0]) if exc.args else ""
                timed_out = isinstance(exc, TimeoutError) or interrupted or sqlstate in {"HYT00", "HYT01"}
                if not self._use_pyodbc and isinstance(exc, sqlite3.OperationalError):
                    timed_out = timed_out or (time.monotonic() >= deadline and "locked" in str(exc).lower())
                if timed_out:
                    try:
                        _cancel()
                    except Exception as cancel_exc:
                        # SQL execution has already returned here. Surface unsupported
                        # cancellation rather than silently claiming successful cleanup.
                        raise RuntimeError("Driver cancellation failed after query timeout.") from cancel_exc
                    raise TimeoutError(f"Query execution timed out after {timeout:g} seconds.") from exc
                raise
            finally:
                if not self._use_pyodbc:
                    conn.set_progress_handler(None, 0)
                try:
                    conn.rollback()
                finally:
                    if cursor is not None:
                        cursor.close()

    def _adapt_tsql_for_emulation(self, sql: str) -> str:
        """
        Transpile T-SQL dialect (TOP N, bracket identifiers) to SQLite syntax
        so queries run cleanly on the local test engine while retaining 100% T-SQL compliance.
        """
        try:
            import sqlglot
            from sqlglot import exp
            expressions = sqlglot.parse(sql, read="tsql")
            if len(expressions) != 1 or expressions[0] is None:
                raise ValueError("Exactly one SQL statement is required.")
            expression = expressions[0]
        except Exception as exc:
            raise ValueError("AST_PARSER_FAILURE: Cannot safely transpile SQL for the local emulator.") from exc

        if isinstance(expression, (exp.Select, exp.Union)):
            from core.sql_validation import identifier_parts, physical_tables

            # T-SQL permits recursive CTEs without the RECURSIVE keyword.
            # SQLGlot's lexical scope resolver needs this semantic flag to
            # distinguish an unqualified self-reference from a physical table.
            # Qualified relations remain physical and undergo the checks below.
            for with_clause in expression.find_all(exp.With):
                with_clause.set("recursive", True)

            # SQL Server's approved default schema is dbo; the emulator stores
            # these same relations in SQLite's main database. Resolve physical
            # sources lexically so a CTE with a matching name stays a CTE.
            for table in physical_tables(expression):
                parts = identifier_parts(table)
                if (
                    len(parts) > 3
                    or (table.db and table.db.casefold() not in {"dbo", "main"})
                    or (table.catalog and table.catalog.casefold() != self.config.database.casefold())
                ):
                    raise PermissionError("The local emulator cannot query another catalog or schema.")
                table.set("db", exp.to_identifier("main"))
                table.set("catalog", None)

            # Preserve legitimate fully qualified column references after the
            # relation rewrite. Alias/column ownership is proven by the Critic.
            for column in expression.find_all(exp.Column):
                if not column.db and not column.catalog:
                    continue
                if (
                    (column.db and column.db.casefold() not in {"dbo", "main"})
                    or (column.catalog and column.catalog.casefold() != self.config.database.casefold())
                ):
                    raise PermissionError("The local emulator cannot query another catalog or schema.")
                column.set("db", exp.to_identifier("main"))
                column.set("catalog", None)

        try:
            return expression.sql(dialect="sqlite")
        except Exception as exc:
            raise ValueError("AST_PARSER_FAILURE: Cannot safely transpile SQL for the local emulator.") from exc


# Compatibility Alias
DatabaseEngine = MSSQLDatabaseEngine
