"""No-network regressions for lexical grounding and legitimate empty answers."""
import builtins

import pandas as pd
import pytest

from agents.critic import RuntimeCriticAgent


class VerifiedDatabase:
    dialect = "tsql"

    def __init__(self):
        self.calls = []
        self.metadata_calls = []
        self.columns = {
            "accounts": ["AccountId", "Label"],
            "transactions": ["TransactionId", "AccountId", "Amount"],
            "dbo.accounts": ["AccountId", "Label"],
            "dbo.transactions": ["TransactionId", "AccountId", "Amount"],
            "private.accounts": ["AccountId", "Secret"],
        }

    def get_table_columns_info(self, name):
        self.metadata_calls.append(name)
        normalized = name.replace("[", "").replace("]", "").casefold()
        return [{"name": column, "type": "INT", "notnull": False, "pk": False}
                for column in self.columns.get(normalized, [])]

    def execute_query(self, sql, timeout_sec=None):
        self.calls.append(sql)
        return pd.DataFrame(columns=["AccountId"])


@pytest.fixture
def db():
    return VerifiedDatabase()


def evaluate(db, sql, allowed=None):
    return RuntimeCriticAgent(db).evaluate(
        "Show matching accounts", sql,
        authorized_tables=allowed if allowed is not None else ["Accounts", "Transactions"],
    )


def test_missing_parser_fails_closed_without_execution(db, monkeypatch):
    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "sqlglot" or name.startswith("sqlglot."):
            raise ImportError("parser intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    result = evaluate(db, "SELECT AccountId FROM Accounts")
    assert not result.success
    assert result.critique["type"] == "AST_PARSER_FAILURE"
    assert db.calls == []


def test_parser_exception_fails_closed_without_execution(db, monkeypatch):
    import sqlglot

    def broken(*args, **kwargs):
        raise RuntimeError("parser failure")

    monkeypatch.setattr(sqlglot, "parse", broken)
    result = evaluate(db, "SELECT AccountId FROM Accounts")
    assert not result.success
    assert result.critique["type"] == "AST_PARSER_FAILURE"
    assert db.calls == []


@pytest.mark.parametrize("sql", ["SELECT * FROM (", "", "-- only a comment"])
def test_unparseable_sql_fails_closed_without_execution(db, sql):
    result = evaluate(db, sql)
    assert not result.success
    assert result.critique["type"] == "AST_PARSER_FAILURE"
    assert db.calls == []


@pytest.mark.parametrize("sql", [
    "SELECT wrong.AccountId FROM Accounts AS a",
    "SELECT Accounts.AccountId FROM Accounts AS a",
    "SELECT a.Amount FROM Accounts AS a JOIN Transactions AS t ON a.AccountId=t.AccountId",
    "SELECT a.AccountId FROM Accounts AS a WHERE a.AccountId > 1 AND wrong.Label='x'",
    "SELECT a.AccountId FROM Accounts AS a WHERE a.AccountId > 1 OR wrong.Label='x'",
    "SELECT AccountId FROM Accounts AS a JOIN Transactions AS t ON a.AccountId=t.AccountId",
    "SELECT Fabricated AS AccountId FROM Accounts",
    "SELECT AccountId AS Fabricated FROM Accounts WHERE Fabricated = 1",
    "SELECT AccountId AS Fabricated FROM Accounts GROUP BY Fabricated",
    "SELECT (SELECT TransactionId AS Fabricated FROM Transactions) AS value FROM Accounts WHERE Fabricated = 1",
    "SELECT d.Amount FROM (SELECT AccountId FROM Accounts) AS d",
    "SELECT a.AccountId FROM Accounts AS a WHERE EXISTS (SELECT 1 FROM Transactions AS a WHERE a.Label='x')",
    "SELECT nonexistent.* FROM Accounts",
    "SELECT private.Accounts.AccountId FROM dbo.Accounts",
    "SELECT dbo.a.AccountId FROM dbo.Accounts AS a",
    "WITH c AS (SELECT AccountId FROM Accounts) SELECT c.Secret FROM c",
    "SELECT d.* FROM (SELECT AccountId, AccountId AS AccountId FROM Accounts) AS d",
])
def test_invalid_column_binding_does_not_execute(db, sql):
    result = evaluate(db, sql)
    assert not result.success, sql
    assert result.critique["type"] == "HALLUCINATION_INVALID_COLUMN", result.critique
    assert db.calls == []


@pytest.mark.parametrize("sql", [
    "SELECT * FROM (SELECT Secret FROM private.Accounts) AS nested",
    "WITH Accounts AS (SELECT AccountId FROM dbo.Accounts) SELECT * FROM private.Accounts",
    "WITH PrivateAccounts AS (SELECT Secret FROM private.Accounts) SELECT * FROM PrivateAccounts",
    "WITH Accounts AS (SELECT Secret FROM private.Accounts) SELECT * FROM Accounts",
])
def test_cte_and_nested_sources_cannot_bypass_rbac(db, sql):
    result = evaluate(db, sql, allowed=["Accounts"])
    assert not result.success
    assert result.critique["type"] == "HALLUCINATION_UNAUTHORIZED_TABLE", result.critique
    assert db.calls == []


@pytest.mark.parametrize("sql", [
    "SELECT a.AccountId FROM Accounts AS a",
    "SELECT AccountId FROM Accounts WHERE AccountId>1 AND Label='x'",
    "SELECT AccountId FROM Accounts WHERE AccountId>1 OR Label='x'",
    "SELECT AccountId FROM Accounts WHERE NOT (AccountId>1 OR Label='x')",
    "SELECT a.AccountId FROM Accounts AS a JOIN Transactions AS t ON a.AccountId=t.AccountId AND t.Amount>0 WHERE a.Label='x' OR a.AccountId=2",
    "SELECT AccountId AS account_key FROM Accounts ORDER BY account_key",
    "WITH c AS (SELECT AccountId AS account_key FROM Accounts) SELECT account_key FROM c ORDER BY account_key",
    "WITH c(account_key) AS (SELECT AccountId FROM Accounts) SELECT c.account_key FROM c",
    "SELECT d.account_key FROM (SELECT AccountId AS account_key FROM Accounts) AS d",
    "SELECT a.AccountId, (SELECT SUM(t.Amount) FROM Transactions AS t WHERE t.AccountId=a.AccountId) AS total FROM Accounts AS a",
    "SELECT a.AccountId FROM Accounts AS a WHERE EXISTS (SELECT 1 FROM Transactions AS t WHERE t.AccountId=a.AccountId)",
    "SELECT AccountId AS account_key FROM Accounts UNION ALL SELECT AccountId FROM Transactions ORDER BY account_key",
    "SELECT COUNT(*) AS total FROM Accounts",
    "SELECT a.* FROM Accounts AS a",
    "WITH c AS (SELECT * FROM Accounts) SELECT c.AccountId FROM c",
    "SELECT dbo.Accounts.AccountId FROM dbo.Accounts",
    "SELECT 1 AS answer",
])
def test_valid_scoped_queries_and_empty_answers_complete_once(db, sql):
    result = evaluate(db, sql)
    assert result.success, result.critique
    assert result.df.empty
    assert result.critique is None
    assert result.sanity_warnings == []
    assert result.executive_narrative == "No matching records found in the database for the specified parameters."
    assert db.calls == [sql]


@pytest.mark.parametrize("sql", ["SELECT missing FROM Unknown", "SELECT * FROM Unknown", "SELECT COUNT(*) FROM Unknown"])
def test_missing_metadata_fails_closed_including_wildcards(db, sql):
    result = evaluate(db, sql, allowed=["Unknown"])
    assert not result.success
    assert result.critique["type"] == "HALLUCINATION_SCHEMA_UNAVAILABLE"
    assert db.calls == []


def test_metadata_failure_fails_closed(db, monkeypatch):
    def missing(*args):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(db, "get_table_columns_info", missing)
    result = evaluate(db, "SELECT AccountId FROM Accounts")
    assert not result.success
    assert result.critique["type"] == "HALLUCINATION_SCHEMA_UNAVAILABLE"
    assert db.calls == []


def test_qualified_metadata_never_uses_bare_table(db):
    result = evaluate(db, "SELECT Secret FROM private.Accounts", allowed=["private.Accounts"])
    assert result.success, result.critique
    assert db.metadata_calls == ["private.Accounts"]


def test_schema_changes_do_not_reuse_previous_metadata(db):
    critic = RuntimeCriticAgent(db)
    sql = "SELECT Label FROM Accounts"
    assert critic.evaluate("labels", sql, authorized_tables=["Accounts"]).success
    db.columns["accounts"] = ["AccountId"]
    result = critic.evaluate("labels", sql, authorized_tables=["Accounts"])
    assert not result.success
    assert result.critique["type"] == "HALLUCINATION_INVALID_COLUMN"
    assert db.calls == [sql]


def test_empty_result_does_not_request_filter_relaxation_at_any_iteration(db):
    critic = RuntimeCriticAgent(db)
    sql = "SELECT AccountId FROM Accounts WHERE AccountId=12345"
    for iteration in (1, 2, 3):
        result = critic.evaluate("exact account", sql, iteration=iteration, max_iterations=3,
                                 authorized_tables=["Accounts"])
        assert result.success
        assert result.critique is None
        assert result.sanity_warnings == []
    assert db.calls == [sql, sql, sql]


@pytest.mark.parametrize("sql", [
    "SELECT steal_secrets() AS value",
    "SELECT dbo.export_secrets() AS value",
    "SELECT other_db.dbo.export_secrets() AS value",
    "SELECT [private].[export_secrets]() AS value",
    "SELECT dbo.SUM(1) AS value",
    "SELECT dbo.GETUTCDATE() AS value",
    "SELECT SUM(dbo.export_secrets()) AS value FROM Accounts",
    "SELECT AccountId FROM Accounts WHERE AccountId>1 AND dbo.export_secrets()=1",
    "SELECT AccountId FROM Accounts WHERE AccountId>1 OR dbo.export_secrets()=1",
    "SELECT SERVERPROPERTY('Edition') AS value",
    "SELECT DB_NAME() AS value",
    "SELECT SUSER_SNAME() AS value",
    "SELECT HOST_NAME() AS value",
    "SELECT CURRENT_USER AS value",
    "SELECT SESSION_USER AS value",
    "SELECT NEXT VALUE FOR dbo.sequence AS value",
    "SELECT pg_read_file('/etc/passwd') AS value",
    "SELECT pg_sleep(1) AS value",
    "SELECT REPLICATE('x', 2000000000) AS value",
])
def test_unapproved_scalar_functions_are_denied_without_execution(db, sql):
    result = evaluate(db, sql)
    assert not result.success, sql
    assert result.critique["type"] == "AST_UNSUPPORTED_FUNCTION", result.critique
    assert db.calls == []
    assert db.metadata_calls == []


def test_server_system_variables_are_denied_without_execution(db):
    result = evaluate(db, "SELECT @@VERSION AS server_version")
    assert not result.success
    assert result.critique["type"] == "AST_SECURITY_VIOLATION"
    assert db.calls == []


@pytest.mark.parametrize("sql", [
    "SELECT SUM(AccountId), AVG(AccountId), MIN(AccountId), MAX(AccountId), COUNT(*), STDEV(AccountId), STDEVP(AccountId), VAR(AccountId), VARP(AccountId) FROM Accounts",
    "SELECT ABS(-1), CEILING(1.2), FLOOR(1.2), ROUND(1.123,2), POWER(2,3), SQRT(4), SIGN(-1), LOG(3), LOG10(100), EXP(1)",
    "SELECT COALESCE(NULL,1), ISNULL(NULL,1), NULLIF(1,2), IIF(1=1,1,0), CASE WHEN 1=1 THEN 1 ELSE 0 END",
    "SELECT GETDATE(), GETUTCDATE(), SYSDATETIME(), SYSUTCDATETIME(), CURRENT_TIMESTAMP",
    "SELECT DATEADD(day,1,'2026-01-01'), DATEDIFF(day,'2026-01-01','2026-02-01'), DATENAME(month,'2026-01-01'), DATEPART(year,'2026-01-01'), YEAR('2026-01-01'), MONTH('2026-01-01'), DAY('2026-01-01'), EOMONTH('2026-01-01'), DATEFROMPARTS(2026,1,1)",
    "SELECT CAST(1 AS DECIMAL(10,2)), TRY_CAST('x' AS INT), CONVERT(VARCHAR(20),1), TRY_CONVERT(INT,'x'), FORMAT(GETDATE(),'yyyy-MM')",
    "SELECT LOWER('A'), UPPER('a'), LEN('abc'), DATALENGTH('abc'), TRIM(' a '), LTRIM(' a '), RTRIM(' a '), SUBSTRING('abc',1,2), LEFT('abc',1), RIGHT('abc',1), REPLACE('abc','a','b'), CONCAT('a','b'), CONCAT_WS('-','a','b'), CHARINDEX('a','abc'), ASCII('a'), CHAR(65), UNICODE('a'), NCHAR(65), REVERSE('abc')",
    "SELECT ROW_NUMBER() OVER (ORDER BY AccountId), RANK() OVER (ORDER BY AccountId), DENSE_RANK() OVER (ORDER BY AccountId), NTILE(4) OVER (ORDER BY AccountId), LAG(AccountId) OVER (ORDER BY AccountId), LEAD(AccountId) OVER (ORDER BY AccountId), FIRST_VALUE(AccountId) OVER (ORDER BY AccountId), LAST_VALUE(AccountId) OVER (ORDER BY AccountId) FROM Accounts",
    "SELECT COUNT(*) OVER (PARTITION BY Label) AS per_label FROM Accounts",
])
def test_vetted_analytical_functions_remain_compatible(db, sql):
    result = evaluate(db, sql)
    assert result.success, result.critique
    assert result.critique is None
    assert db.calls == [sql]
