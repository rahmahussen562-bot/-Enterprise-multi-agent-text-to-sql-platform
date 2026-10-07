"""Database cancellation tests use local SQLite and deterministic ODBC doubles only."""
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from sqlglot.errors import ParseError

from core.config import DatabaseConfig
from core.database import DatabaseEngine


@pytest.fixture
def sqlite_engine(tmp_path):
    database_path = tmp_path / "cancellation.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE Accounts (AccountId INTEGER, Amount NUMERIC)")
        connection.executemany("INSERT INTO Accounts VALUES (?, ?)", [(1, 10), (2, 20)])
    connection.close()
    engine = DatabaseEngine(DatabaseConfig(sqlite_path=str(database_path), allow_sqlite_emulation=True))
    engine._use_pyodbc = False
    return engine


def test_sqlite_long_query_is_interrupted_without_a_worker(sqlite_engine, monkeypatch):
    operations = []

    class TrackingCursor(sqlite3.Cursor):
        def close(self):
            operations.append("cursor.close")
            return super().close()

    class TrackingConnection(sqlite3.Connection):
        def cursor(self):
            return super().cursor(factory=TrackingCursor)

        def interrupt(self):
            operations.append("interrupt")
            return super().interrupt()

        def rollback(self):
            operations.append("rollback")
            return super().rollback()

        def close(self):
            operations.append("connection.close")
            return super().close()

    monkeypatch.setattr(
        sqlite_engine, "_get_sqlite_connection",
        lambda: sqlite3.connect(sqlite_engine.config.sqlite_path, factory=TrackingConnection),
    )

    def no_background_query(*args, **kwargs):
        pytest.fail("Database execution must not create an orphanable query thread.")

    monkeypatch.setattr(threading, "Thread", no_background_query)
    sql = (
        "WITH numbers AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM numbers WHERE n < 100000000) "
        "SELECT SUM(n) AS total FROM numbers"
    )
    # Load the dialect/scope machinery before measuring the database deadline;
    # this test must prove native interruption, not just cold-import timeout.
    sqlite_engine._adapt_tsql_for_emulation(sql)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out") as timeout_error:
        sqlite_engine.execute_query(sql, timeout_sec=0.1)
    assert time.monotonic() - started < 2
    assert isinstance(timeout_error.value.__cause__, sqlite3.OperationalError)
    assert "interrupted" in str(timeout_error.value.__cause__).lower()
    assert operations[-4:] == ["interrupt", "rollback", "cursor.close", "connection.close"]
    # The cancelled statement released resources and does not poison later reads.
    assert len(sqlite_engine.execute_query("SELECT AccountId FROM Accounts")) == 2


def test_sqlite_normal_and_empty_results_keep_columns(sqlite_engine):
    result = sqlite_engine.execute_query("SELECT TOP 1 AccountId, Amount FROM Accounts ORDER BY AccountId")
    assert list(result.columns) == ["AccountId", "Amount"]
    assert result.iloc[0].tolist() == [1, 10]
    empty = sqlite_engine.execute_query("SELECT AccountId FROM Accounts WHERE AccountId = 999")
    assert empty.empty
    assert list(empty.columns) == ["AccountId"]


def test_sqlite_rejects_mutation_and_releases_connection(sqlite_engine):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        sqlite_engine.execute_query("UPDATE Accounts SET Amount = 0")
    assert sqlite_engine.execute_query("SELECT SUM(Amount) AS total FROM Accounts").iloc[0, 0] == 30


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_deadline_never_opens_a_connection(sqlite_engine, monkeypatch, timeout):
    monkeypatch.setattr(sqlite_engine, "get_connection", lambda: pytest.fail("Invalid deadline opened a connection."))
    with pytest.raises(ValueError, match="positive"):
        sqlite_engine.execute_query("SELECT 1", timeout_sec=timeout)


def test_sqlite_result_row_budget_is_enforced(sqlite_engine):
    sqlite_engine.config.max_result_rows = 1
    with pytest.raises(ValueError, match="budget"):
        sqlite_engine.execute_query("SELECT AccountId FROM Accounts")
    sqlite_engine.config.max_result_rows = 100
    assert len(sqlite_engine.execute_query("SELECT AccountId FROM Accounts")) == 2


def test_sqlite_result_byte_budget_is_enforced(sqlite_engine):
    sqlite_engine.config.max_result_bytes = 2
    with pytest.raises(ValueError, match="budget"):
        sqlite_engine.execute_query("SELECT 'sensitive payload' AS payload")


class NativeTimeout(Exception):
    pass


class ODBCCursor:
    def __init__(self, operations, *, timeout_stage=None, cancel_error=None):
        self.operations = operations
        self.timeout_stage = timeout_stage
        self.cancel_error = cancel_error
        self.description = [("AccountId",)]
        self.fetched = False

    def execute(self, sql, *parameters):
        self.operations.append(("execute", sql, parameters) if parameters else ("execute", sql))
        if self.timeout_stage == "execute":
            raise NativeTimeout("HYT00", "Native statement timeout")
        return self

    def fetchmany(self, size):
        self.operations.append(("fetch", size))
        if self.timeout_stage == "fetch":
            raise NativeTimeout("HYT01", "Native fetch timeout")
        if self.fetched:
            return []
        self.fetched = True
        return [(42,)]

    def cancel(self):
        self.operations.append("cancel")
        if self.cancel_error:
            raise self.cancel_error

    def close(self):
        self.operations.append("cursor.close")


class ODBCConnection:
    def __init__(self, cursor, operations):
        self.active_cursor = cursor
        self.operations = operations
        self.timeout = None
        self.autocommit = True

    def cursor(self):
        return self.active_cursor

    def rollback(self):
        self.operations.append("rollback")

    def close(self):
        self.operations.append("connection.close")


def make_odbc_engine(monkeypatch, *, timeout_stage=None, cancel_error=None):
    operations = []
    cursor = ODBCCursor(operations, timeout_stage=timeout_stage, cancel_error=cancel_error)
    connection = ODBCConnection(cursor, operations)
    connect_calls = []

    def connect(connection_string, *, timeout):
        connect_calls.append(timeout)
        return connection

    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(connect=connect))
    engine = DatabaseEngine(DatabaseConfig(driver="SQL Server", connection_timeout_sec=4))
    engine._use_pyodbc = True
    return engine, connection, operations, connect_calls


@pytest.mark.parametrize("stage", ["execute", "fetch"])
def test_odbc_native_timeout_cancels_rolls_back_and_closes(monkeypatch, stage):
    engine, connection, operations, connect_calls = make_odbc_engine(monkeypatch, timeout_stage=stage)
    with pytest.raises(TimeoutError, match="timed out"):
        engine.execute_query("SELECT AccountId FROM dbo.Accounts", timeout_sec=2)
    assert connection.timeout == 2
    assert connection.autocommit is False
    assert connect_calls == [4]
    assert operations[-4:] == ["cancel", "rollback", "cursor.close", "connection.close"]


def test_odbc_no_query_worker_and_clean_normal_read(monkeypatch):
    engine, _, operations, _ = make_odbc_engine(monkeypatch)
    monkeypatch.setattr(threading, "Thread", lambda *args, **kwargs: pytest.fail("Query worker created."))
    result = engine.execute_query("SELECT AccountId FROM dbo.Accounts")
    assert result["AccountId"].tolist() == [42]
    assert "cancel" not in operations
    assert operations[-3:] == ["rollback", "cursor.close", "connection.close"]


def test_odbc_unsupported_cancel_is_reported_but_resources_close(monkeypatch):
    engine, _, operations, _ = make_odbc_engine(
        monkeypatch, timeout_stage="execute", cancel_error=NotImplementedError("cancel unavailable")
    )
    with pytest.raises(RuntimeError, match="cancellation failed"):
        engine.execute_query("SELECT AccountId FROM dbo.Accounts")
    assert operations[-4:] == ["cancel", "rollback", "cursor.close", "connection.close"]


def test_sqlite_qualified_metadata_does_not_fallback_to_another_schema(sqlite_engine):
    metadata = sqlite_engine.get_table_columns_info("[dbo].[Accounts]")
    assert [column["name"] for column in metadata] == ["AccountId", "Amount"]
    assert all(column["table_schema"] == "dbo" for column in metadata)
    with pytest.raises(PermissionError, match="another catalog or schema"):
        sqlite_engine.get_table_columns_info("[restricted].[Accounts]")
    with pytest.raises(PermissionError, match="another catalog or schema"):
        sqlite_engine.get_table_columns_info("[OtherBank].[dbo].[Accounts]")


@pytest.mark.parametrize("sql", [
    "SELECT AccountId FROM dbo.Accounts ORDER BY AccountId",
    "SELECT dbo.Accounts.AccountId FROM dbo.Accounts ORDER BY AccountId",
    "SELECT [Chinook].[dbo].[Accounts].[AccountId] FROM [Chinook].[dbo].[Accounts] ORDER BY AccountId",
    "WITH Accounts AS (SELECT AccountId FROM dbo.Accounts) SELECT AccountId FROM Accounts ORDER BY AccountId",
    "SELECT nested.AccountId FROM (SELECT AccountId FROM dbo.Accounts) AS nested ORDER BY AccountId",
])
def test_sqlite_maps_only_physical_dbo_sources_and_preserves_cte_aliases(sqlite_engine, sql):
    result = sqlite_engine.execute_query(sql)
    assert result["AccountId"].tolist() == [1, 2]


@pytest.mark.parametrize("relation", [
    "private.Accounts", "OtherBank.dbo.Accounts", "OtherBank.main.Accounts",
])
def test_sqlite_foreign_qualifier_never_falls_back_to_public_table(sqlite_engine, relation):
    with pytest.raises(PermissionError, match="another catalog or schema"):
        sqlite_engine.execute_query(f"SELECT AccountId FROM {relation}")
    assert len(sqlite_engine.execute_query("SELECT AccountId FROM dbo.Accounts")) == 2


def test_sqlite_recursive_cte_self_reference_is_lexical(sqlite_engine):
    result = sqlite_engine.execute_query(
        "WITH numbers AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM numbers WHERE n < 5) "
        "SELECT SUM(n) AS total FROM numbers"
    )
    assert result["total"].tolist() == [15]


def test_sqlite_recursive_flag_does_not_hide_qualified_physical_table(sqlite_engine):
    with pytest.raises(PermissionError, match="another catalog or schema"):
        sqlite_engine.execute_query(
            "WITH Accounts AS (SELECT 1 AS AccountId UNION ALL SELECT AccountId FROM private.Accounts) "
            "SELECT AccountId FROM Accounts"
        )


def test_sqlite_metadata_rejects_unsafe_identifier(sqlite_engine):
    with pytest.raises((ValueError, ParseError)):
        sqlite_engine.get_table_columns_info("Accounts; DROP TABLE Accounts")
    assert len(sqlite_engine.execute_query("SELECT AccountId FROM Accounts")) == 2


def test_sqlite_initialization_failure_closes_unyielded_connection(sqlite_engine, monkeypatch):
    closed = []
    connection = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connection)

    def failed_initialization(conn):
        raise sqlite3.OperationalError("schema initialization locked")

    monkeypatch.setattr(sqlite_engine, "_ensure_information_schema_views", failed_initialization)
    with pytest.raises(sqlite3.OperationalError, match="initialization locked"):
        sqlite_engine._get_sqlite_connection()
    assert closed == [True]


def test_odbc_metadata_matches_exact_catalog_and_schema(monkeypatch):
    engine, connection, operations, _ = make_odbc_engine(monkeypatch)
    connection.active_cursor.fetchall = lambda: [
        ("AccountId", "int", "NO", "Accounts", "reporting", "Chinook")
    ]
    columns = engine.get_table_columns_info("[Chinook].[reporting].[Accounts]")
    query, parameters = operations[0][1:]
    assert "TABLE_SCHEMA = ?" in query and "TABLE_CATALOG = ?" in query
    assert parameters == (("Accounts", "reporting", "Chinook"),)
    assert columns[0]["table_schema"] == "reporting"
    assert columns[0]["table_catalog"] == "Chinook"
    assert operations[-2:] == ["cursor.close", "connection.close"]


def test_failed_live_connection_without_demo_never_initializes_sqlite(tmp_path, monkeypatch):
    database_path = tmp_path / "must-not-create" / "fallback.sqlite"

    def unavailable(*args, **kwargs):
        raise ConnectionError("SQL Server unavailable")

    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(connect=unavailable))
    engine = DatabaseEngine(DatabaseConfig(
        driver="SQL Server", sqlite_path=str(database_path), allow_sqlite_emulation=False,
    ))
    monkeypatch.setattr(engine, "_get_sqlite_connection", lambda: pytest.fail("Implicit fallback initialized SQLite."))
    connected, message, latency, mode = engine.test_connection()
    assert connected is False
    assert mode == engine.connection_mode == "ERROR"
    assert latency == 0
    assert "demo emulation is disabled" in message
    assert not database_path.parent.exists()


@pytest.mark.parametrize("connection_mode", [None, False])
def test_unknown_or_failed_live_mode_without_demo_denies_local_execution(tmp_path, connection_mode):
    database_path = tmp_path / "must-not-create" / "fallback.sqlite"
    engine = DatabaseEngine(DatabaseConfig(
        driver="SQL Server", sqlite_path=str(database_path), allow_sqlite_emulation=False,
    ))
    engine._use_pyodbc = connection_mode
    with pytest.raises(ConnectionError, match="demo emulation is disabled"):
        engine.execute_query("SELECT 1 AS answer")
    with pytest.raises(ConnectionError, match="explicit SENTINEL_DEMO_MODE"):
        engine._get_sqlite_connection()
    assert not database_path.parent.exists()


def test_explicit_demo_allows_local_initialization_after_failed_live_connection(tmp_path, monkeypatch):
    database_path = tmp_path / "explicit-demo" / "demo.sqlite"

    def unavailable(*args, **kwargs):
        raise ConnectionError("SQL Server unavailable")

    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(connect=unavailable))
    engine = DatabaseEngine(DatabaseConfig(
        driver="SQL Server", sqlite_path=str(database_path), allow_sqlite_emulation=True,
    ))
    connected, _, _, mode = engine.test_connection()
    assert connected is True and mode == "MOCK_EMULATOR"
    assert database_path.exists()
    assert engine.execute_query("SELECT 1 AS answer")["answer"].tolist() == [1]
