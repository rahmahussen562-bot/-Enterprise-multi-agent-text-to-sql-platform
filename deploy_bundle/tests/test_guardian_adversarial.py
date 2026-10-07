"""Security boundaries that the legacy parser fallback and global CTE set missed."""
import builtins
from unittest.mock import patch

import pytest
import sqlglot

from agents.guardian import ASTGuardianAgent
from core.sql_validation import identifier_parts, parse_single_query, physical_tables


def audit(sql, allowed=None, valid=None):
    return ASTGuardianAgent().audit(
        sql, authorized_tables=["Customer", "Invoice"] if allowed is None else allowed,
        valid_tables=["Customer", "Invoice", "Track"] if valid is None else valid,
    )


def test_missing_parser_fails_closed():
    real_import = builtins.__import__

    def missing_parser(name, *args, **kwargs):
        if name == "sqlglot" or name.startswith("sqlglot."):
            raise ImportError("parser deliberately unavailable")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=missing_parser):
        result = audit("SELECT * FROM Customer")
    assert not result.is_valid
    assert result.critique["type"] == "AST_PARSER_FAILURE"


def test_parser_exception_fails_closed():
    with patch("sqlglot.parse", side_effect=RuntimeError("parser fault")):
        result = audit("SELECT * FROM Customer")
    assert not result.is_valid
    assert result.critique["type"] == "AST_PARSER_FAILURE"


@pytest.mark.parametrize("sql", ["", "SELECT (", "SELECT * FROM ("])
def test_invalid_syntax_fails_closed(sql):
    result = audit(sql)
    assert not result.is_valid
    assert result.critique["type"] == "AST_PARSER_FAILURE"


@pytest.mark.parametrize("sql", [
    "WITH Track AS (SELECT * FROM dbo.Track) SELECT * FROM Track",
    "WITH Track AS (SELECT * FROM Customer) SELECT * FROM dbo.Track",
    "SELECT * FROM Customer WHERE EXISTS (SELECT 1 FROM Track)",
    "SELECT * FROM (SELECT * FROM Track) AS hidden",
    "SELECT * FROM Customer UNION ALL SELECT * FROM Track",
    "WITH visible AS (SELECT * FROM Customer) SELECT * FROM visible WHERE EXISTS (SELECT 1 FROM Track)",
])
def test_cte_nested_and_union_sources_cannot_bypass_rbac(sql):
    result = audit(sql)
    assert not result.is_valid
    assert result.critique["type"] == "RBAC_AUTHORIZATION_VIOLATION"


@pytest.mark.parametrize("relation", ["private.Customer", "other_db.dbo.Customer", "other_db.private.Customer"])
def test_bare_whitelist_cannot_authorize_other_schema_or_catalog(relation):
    result = audit(f"SELECT * FROM {relation}")
    assert not result.is_valid
    assert result.critique["type"] == "RBAC_AUTHORIZATION_VIOLATION"


def test_legacy_default_dbo_qualification_remains_authorized():
    assert audit("SELECT * FROM [dbo].[Customer]").is_valid


def test_explicit_qualified_whitelist_requires_exact_relation():
    exact = ["reporting_branch.Customer"]
    assert audit("SELECT * FROM reporting_branch.Customer", exact, exact).is_valid
    for sql in ("SELECT * FROM Customer", "SELECT * FROM dbo.Customer", "SELECT * FROM other.Customer"):
        result = audit(sql, exact, exact)
        assert not result.is_valid
        assert result.critique["type"] == "RBAC_AUTHORIZATION_VIOLATION"


def test_cte_alias_is_not_a_physical_relation():
    sql = "WITH visible AS (SELECT CustomerId FROM Customer) SELECT CustomerId FROM visible"
    expression = parse_single_query(sql)
    assert [identifier_parts(table) for table in physical_tables(expression)] == [("customer",)]
    assert audit(sql).is_valid


def test_sanitizer_qualifies_nested_physical_relations_but_not_cte_aliases():
    sql = (
        "WITH visible AS (SELECT CustomerId FROM Customer) "
        "SELECT v.CustomerId FROM visible v "
        "WHERE EXISTS (SELECT 1 FROM Invoice i WHERE i.CustomerId = v.CustomerId)"
    )
    result = audit(sql)
    assert result.is_valid, result.critique
    sanitized = parse_single_query(result.sanitized_sql)
    assert {identifier_parts(table) for table in physical_tables(sanitized)} == {
        ("dbo", "customer"), ("dbo", "invoice"),
    }
    cte_refs = [table for table in sanitized.find_all(sqlglot.exp.Table) if table.name == "visible"]
    assert len(cte_refs) == 1
    assert not cte_refs[0].db and not cte_refs[0].catalog


def test_sanitizer_renders_authorized_spelling_instead_of_user_casing():
    result = audit(
        "SELECT customer.CustomerId FROM private.customer",
        allowed=["Private.Customer"], valid=["Private.Customer"],
    )
    assert result.is_valid, result.critique
    table = physical_tables(parse_single_query(result.sanitized_sql))[0]
    assert table.db == "Private"
    assert table.name == "Customer"
    assert table.alias == "customer"


def test_sanitizer_uses_verified_catalog_spelling_when_no_authorization_list_supplied():
    result = ASTGuardianAgent().audit("SELECT * FROM reporting.customer", valid_tables=["Reporting.Customer"])
    assert result.is_valid, result.critique
    table = physical_tables(parse_single_query(result.sanitized_sql))[0]
    assert table.db == "Reporting"
    assert table.name == "Customer"


@pytest.mark.parametrize("valid,allowed", [
    (["dbo.Customer", "dbo.customer"], ["Customer"]),
    (["Customer"], ["Customer", "customer"]),
])
def test_case_colliding_relation_identities_fail_closed(valid, allowed):
    result = audit("SELECT * FROM Customer", allowed=allowed, valid=valid)
    assert not result.is_valid
    assert result.critique["type"] == "AST_IDENTIFIER_COLLISION"


@pytest.mark.parametrize("sql", [
    "SELECT * INTO copied FROM Customer",
    "WITH changed AS (DELETE FROM Customer RETURNING CustomerId) SELECT * FROM changed",
])
def test_select_root_cannot_hide_mutations(sql):
    result = audit(sql)
    assert not result.is_valid
    assert result.critique["type"] in {"AST_SECURITY_VIOLATION", "AST_PARSER_FAILURE"}


@pytest.mark.parametrize("sql", [
    "SELECT * FROM Customer c CROSS JOIN Invoice i WHERE c.CustomerId = 1",
    "SELECT * FROM Customer c JOIN Invoice i ON 1 = 1 WHERE c.CustomerId = 1",
    "SELECT * FROM Customer c JOIN Invoice i ON i.InvoiceId = i.InvoiceId WHERE c.CustomerId = 1",
    "SELECT * FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId OR 1 = 1",
    "SELECT * FROM Customer WHERE EXISTS (SELECT 1 FROM Customer c JOIN Invoice i ON 1 = 1)",
])
def test_where_or_nested_predicate_cannot_authorize_cartesian_join(sql):
    result = audit(sql)
    assert not result.is_valid
    assert result.critique["type"] == "AST_CARTESIAN_PRODUCT"


def test_real_join_and_filtered_join_remain_valid():
    assert audit("SELECT * FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId AND i.Total > 1").is_valid


@pytest.mark.parametrize("sql", [
    "SELECT * FROM (SELECT TOP 1 * FROM Customer) AS c",
    "SELECT TOP 100000 * FROM Customer",
    "SELECT TOP 1 PERCENT * FROM Customer",
    "SELECT TOP 1 WITH TIES * FROM Customer ORDER BY CustomerId",
    "SELECT * FROM Customer ORDER BY CustomerId OFFSET 0 ROWS",
    "SELECT * FROM Customer UNION ALL SELECT * FROM Customer",
])
def test_outer_row_limit_cannot_be_bypassed(sql):
    result = audit(sql)
    assert result.is_valid, result.critique
    assert result.limit_injected
    bounded = sqlglot.parse_one(result.sanitized_sql, read="tsql")
    limit = bounded.args["limit"]
    count = limit.expression or limit.args.get("count")
    assert count.this == "100", result.sanitized_sql
    options = limit.args.get("limit_options")
    assert not options or not (options.args.get("percent") or options.args.get("with_ties"))


def test_empty_catalog_does_not_disable_closed_world_check():
    result = audit("SELECT * FROM Customer", valid=[])
    assert not result.is_valid
    assert result.critique["type"] == "SCHEMA_MISMATCH"


def test_existing_smaller_fetch_limit_preserves_requested_result_size():
    result = audit("SELECT * FROM Customer ORDER BY CustomerId OFFSET 0 ROWS FETCH NEXT 25 ROWS ONLY")
    assert result.is_valid, result.critique
    assert not result.limit_injected
    bounded = sqlglot.parse_one(result.sanitized_sql, read="tsql")
    assert bounded.args["limit"].args["count"].this == "25"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM OPENJSON('[1,2,3]')",
    "SELECT * FROM dbo.unapproved_function()",
])
def test_external_or_table_valued_sources_fail_closed(sql):
    result = audit(sql)
    assert not result.is_valid
    assert result.critique["type"] in {
        "AST_UNSUPPORTED_SOURCE", "AST_UNSUPPORTED_FUNCTION", "AST_SCOPE_FAILURE", "AST_PARSER_FAILURE",
    }


def test_destructive_words_inside_literals_are_not_executable_nodes():
    assert audit("SELECT 'DROP DELETE' AS label FROM Customer").is_valid


def test_legacy_fallback_hook_cannot_permit_execution():
    result = ASTGuardianAgent()._fallback_audit("SELECT * FROM Track", [], [], "viewer")
    assert not result.is_valid
    assert result.critique["type"] == "AST_PARSER_FAILURE"
