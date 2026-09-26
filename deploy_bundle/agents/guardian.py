"""
Agent 3: Deterministic AST SQL Injection Firewall & RLC Enforcement (The Guardian)
Parses T-SQL queries into an Abstract Syntax Tree (AST) using sqlglot (dialect="tsql").
Enforces anti-injection quarantine, table-level RBAC/RLC authorization,
Cartesian join defense, and automatic T-SQL TOP 100 injection.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("TextToSQL.Guardian")

# Destructive and dangerous T-SQL tokens blocked by firewall
DISALLOWED_TOKENS = {
    "DROP", "DELETE", "UPDATE", "ALTER", "TRUNCATE", "INSERT",
    "REPLACE", "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "SHUTDOWN", "XP_CMDSHELL", "SP_EXECUTESQL", "BULK", "OPENROWSET"
}


class SecurityViolationException(PermissionError):
    """Raised or quarantined when an unauthorized table is referenced."""
    pass


@dataclass
class GuardianResult:
    is_valid: bool
    sanitized_sql: str
    critique: Optional[Dict[str, Any]] = None
    issues: List[str] = field(default_factory=list)
    limit_injected: bool = False


class ASTGuardianAgent:
    """Agent 3: AST Static Linter & Firewall Agent (The Guardian) for T-SQL."""

    def __init__(self, default_limit: int = 100, dialect: str = "tsql"):
        self.default_limit = default_limit
        self.dialect = dialect.lower()

    def audit(
        self,
        raw_sql: str,
        valid_tables: Optional[List[str]] = None,
        authorized_tables: Optional[Any] = None,
        username: Optional[str] = None,
        user_session: Optional[Any] = None,
        raise_on_violation: bool = False
    ) -> GuardianResult:
        """
        Audit raw T-SQL query:
        1. Multi-statement injection quarantine (semicolon stacked queries).
        2. Dangerous token firewall.
        3. AST syntax parsing via sqlglot (dialect="tsql").
        4. AST node quarantine (blocking non-SELECT, Drop, Delete, Exec, etc.).
        5. Cartesian join detection.
        6. Strict Table-Level Privilege Enforcement (RBAC/RLC).
        7. Defensive T-SQL TOP 100 injection.
        """
        issues: List[str] = []
        clean_sql = raw_sql.strip()

        # Resolve session context if provided
        if user_session is not None:
            if hasattr(user_session, "allowed_tables"):
                authorized_tables = user_session.allowed_tables
            elif hasattr(user_session, "authorized_tables"):
                authorized_tables = user_session.authorized_tables
            if not username:
                username = getattr(user_session, "username", getattr(user_session, "role_title", "User"))
        elif authorized_tables is not None and hasattr(authorized_tables, "allowed_tables"):
            authorized_tables = authorized_tables.allowed_tables

        # Phase 1: Fast Regex Security Screening
        tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", clean_sql.upper()))
        found_destructive = tokens.intersection(DISALLOWED_TOKENS)
        if found_destructive:
            critique = {
                "type": "AST_SECURITY_VIOLATION",
                "message": f"Security Firewall blocked destructive/command token(s): {sorted(list(found_destructive))}",
                "failed_sql": clean_sql,
                "remediation": "Only read-only SELECT or WITH statements are authorized. Remove destructive clauses."
            }
            return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

        # Phase 2: AST Parsing and Multi-Statement Injection Check
        try:
            import sqlglot
            from sqlglot import exp

            statements = sqlglot.parse(clean_sql, read=self.dialect)
            if not statements:
                critique = {
                    "type": "AST_SYNTAX_ERROR",
                    "message": "Empty or unparseable SQL statement.",
                    "failed_sql": clean_sql,
                    "remediation": "Provide a valid T-SQL SELECT query."
                }
                return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

            # Multi-statement injection quarantine
            if len(statements) > 1:
                critique = {
                    "type": "SQL_INJECTION_QUARANTINE",
                    "message": f"Multi-statement execution detected ({len(statements)} statements). Stacked queries are prohibited.",
                    "failed_sql": clean_sql,
                    "remediation": "Submit only a single, isolated SELECT statement without semicolons or stacked commands."
                }
                return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

            expression = statements[0]

            # Phase 3: Enforce Read-Only SELECT Root and Quarantine Forbidden AST Nodes
            if not isinstance(expression, (exp.Select, exp.Union)):
                critique = {
                    "type": "INVALID_QUERY_ROOT",
                    "message": f"Query root is '{type(expression).__name__}', expected SELECT or WITH (Select) expression.",
                    "failed_sql": clean_sql,
                    "remediation": "Structure query as a standard T-SQL SELECT or Common Table Expression (WITH ... SELECT ...)."
                }
                return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

            forbidden_node_types = (
                exp.Drop, exp.Delete, exp.Update, exp.Alter, exp.Insert,
                exp.Command, exp.Create, exp.Grant, exp.Revoke, exp.Execute
            )
            for forbidden_type in forbidden_node_types:
                if expression.find(forbidden_type):
                    critique = {
                        "type": "AST_SECURITY_VIOLATION",
                        "message": f"Security Firewall quarantined forbidden AST node type: {forbidden_type.__name__}",
                        "failed_sql": clean_sql,
                        "remediation": "Only non-mutating SELECT queries are permitted."
                    }
                    return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

            # Phase 4: Cartesian Product Detection (Missing Join Predicate or Vacuous ON TRUE)
            for join in expression.find_all(exp.Join):
                on_clause = join.args.get("on")
                has_using = join.args.get("using") is not None
                is_cross = join.kind == "CROSS" or "CROSS" in str(join).upper()
                is_vacuous_on = on_clause is None or str(on_clause).strip().upper() in ["TRUE", "1", "1 = 1", "1=1"]

                if (is_vacuous_on and not has_using) or is_cross:
                    where = expression.find(exp.Where)
                    if not where:
                        critique = {
                            "type": "AST_CARTESIAN_PRODUCT",
                            "message": f"Unintended Cartesian join detected on table {join.this}. Missing explicit 'ON' predicate.",
                            "failed_sql": clean_sql,
                            "remediation": "Add an explicit 'ON tableA.col = tableB.col' predicate to prevent table explosion."
                        }
                        return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

            # Phase 5: Extract Referenced Tables and Filter Out CTE Aliases
            referenced_tables = [
                t.name.lower() for t in expression.find_all(exp.Table)
                if t.name
            ]
            cte_names = set()
            with_node = expression.find(exp.With)
            if with_node:
                for cte in with_node.expressions:
                    if hasattr(cte, "alias") and cte.alias:
                        cte_names.add(cte.alias.lower())

            actual_tables = [t for t in referenced_tables if t not in cte_names]

            # Phase 6: Strict Table-Level Privilege Enforcement (RBAC/RLC)
            if authorized_tables is not None:
                whitelist_lower = {t.strip("[]\"'").lower() for t in authorized_tables}
                unauthorized_tables = [t for t in actual_tables if t.strip("[]\"'").lower() not in whitelist_lower]
                if unauthorized_tables:
                    unauth_table = unauthorized_tables[0]
                    role_str = username or "Active Role"
                    violation_msg = f"SecurityViolationException: Table [{unauth_table}] is unauthorized for role [{role_str}]."
                    critique = {
                        "type": "RBAC_AUTHORIZATION_VIOLATION",
                        "message": violation_msg,
                        "failed_sql": clean_sql,
                        "remediation": f"Only query authorized tables from your corporate scope: {authorized_tables}."
                    }
                    if raise_on_violation:
                        raise SecurityViolationException(violation_msg)
                    return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[violation_msg])

            # Phase 7: Schema Conformance Check (Against Database Tables)
            if valid_tables:
                valid_set = {t.lower() for t in valid_tables}
                unknown_tables = [tbl for tbl in actual_tables if tbl not in valid_set]
                if unknown_tables:
                    critique = {
                        "type": "SCHEMA_MISMATCH",
                        "message": f"Query references non-existent table(s): {unknown_tables}.",
                        "failed_sql": clean_sql,
                        "remediation": f"Reference only verified tables from the database schema: {valid_tables}."
                    }
                    return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

            # Phase 8: Defensive T-SQL Safeguard (Automatic TOP 100 Injection)
            limit_injected = False
            has_limit = expression.find(exp.Limit) is not None
            has_offset = expression.find(exp.Offset) is not None

            if not has_limit and not has_offset:
                expression = expression.limit(self.default_limit)
                limit_injected = True
                issues.append(f"Injected defensive TOP {self.default_limit} to safeguard against unindexed table explosion.")

            sanitized_sql = expression.sql(dialect="tsql")
            return GuardianResult(
                is_valid=True,
                sanitized_sql=sanitized_sql,
                critique=None,
                issues=issues,
                limit_injected=limit_injected
            )

        except SecurityViolationException:
            raise
        except ImportError:
            logger.info("sqlglot not available; applying fallback linter.")
            return self._fallback_audit(clean_sql, valid_tables, authorized_tables, username)
        except Exception as e:
            critique = {
                "type": "AST_SYNTAX_ERROR",
                "message": f"AST parser failed on T-SQL syntax: {str(e)}",
                "failed_sql": clean_sql,
                "remediation": "Correct T-SQL syntax errors, brackets, or unmatched parentheses."
            }
            return GuardianResult(is_valid=False, sanitized_sql=clean_sql, critique=critique, issues=[critique["message"]])

    def _fallback_audit(
        self,
        sql: str,
        valid_tables: Optional[List[str]],
        authorized_tables: Optional[List[str]],
        username: Optional[str]
    ) -> GuardianResult:
        """Heuristic fallback linter."""
        issues = []
        limit_injected = False

        if not re.search(r"\bTOP\s+\d+", sql, re.IGNORECASE):
            sql = re.sub(r"^\s*SELECT\b", f"SELECT TOP {self.default_limit}", sql, count=1, flags=re.IGNORECASE)
            limit_injected = True
            issues.append(f"Injected defensive TOP {self.default_limit}.")

        return GuardianResult(
            is_valid=True,
            sanitized_sql=sql,
            critique=None,
            issues=issues,
            limit_injected=limit_injected
        )
