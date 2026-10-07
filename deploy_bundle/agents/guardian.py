"""Deterministic, fail-closed AST firewall and table authorization for SQL."""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.sql_validation import (
    ValidationError, identifier_parts, parse_single_query, physical_tables,
    query_scopes, table_matches_allowed,
)

logger = logging.getLogger("TextToSQL.Guardian")

# Retained for callers importing the legacy token registry. Authorization uses
# parsed nodes, so harmless words inside comments/literals do not become SQL.
DISALLOWED_TOKENS = {
    "DROP", "DELETE", "UPDATE", "ALTER", "TRUNCATE", "INSERT",
    "REPLACE", "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "SHUTDOWN", "XP_CMDSHELL", "SP_EXECUTESQL", "BULK", "OPENROWSET",
}


class SecurityViolationException(PermissionError):
    """Raised or quarantined when an unauthorized table is referenced."""


@dataclass
class GuardianResult:
    is_valid: bool
    sanitized_sql: str
    critique: Optional[Dict[str, Any]] = None
    issues: List[str] = field(default_factory=list)
    limit_injected: bool = False


class ASTGuardianAgent:
    """Read-only query firewall preserving the original Guardian contract."""

    def __init__(self, default_limit: int = 100, dialect: str = "tsql"):
        if not isinstance(default_limit, int) or default_limit <= 0:
            raise ValueError("default_limit must be a positive integer")
        self.default_limit = default_limit
        self.dialect = dialect.lower()

    @staticmethod
    def _deny(sql: str, code: str, message: str, remediation: str) -> GuardianResult:
        critique = {
            "type": code, "message": message, "failed_sql": sql,
            "remediation": remediation,
        }
        return GuardianResult(False, sql, critique=critique, issues=[message])

    def _reject_identifier_collisions(self, names: Optional[List[str]]) -> None:
        """Case-folded lookup must not collapse two distinct catalog objects."""
        from sqlglot import exp

        seen = {}
        for name in names or []:
            relation = exp.to_table(str(name), dialect=self.dialect)
            if self.dialect == "tsql" and len(identifier_parts(relation)) == 1:
                relation.set("db", exp.to_identifier("dbo"))
            folded = identifier_parts(relation)
            spelling = tuple(part.name for part in relation.parts)
            if folded in seen and seen[folded] != spelling:
                raise ValidationError(
                    "AST_IDENTIFIER_COLLISION",
                    f"Distinct relation spellings {seen[folded]} and {spelling} collide under identifier matching.",
                )
            seen[folded] = spelling

    def _canonicalize_table(self, table: Any, names: Optional[List[str]]) -> None:
        """Render the permitted physical identity, never an implicit schema."""
        from sqlglot import exp

        canonical = table.copy()
        for name in names or []:
            if table_matches_allowed(table, [name], dialect=self.dialect):
                canonical = exp.to_table(str(name), dialect=self.dialect)
                break
        if self.dialect == "tsql" and len(identifier_parts(canonical)) == 1:
            canonical.set("db", exp.to_identifier("dbo"))

        # Table aliases remain query-owned names, separate from the authorized
        # physical identifier. Keep implicit table qualifiers working when a
        # case-insensitive match is rendered using its approved spelling.
        original_name = table.this.copy()
        changed_name = table.name != canonical.name
        for key in ("this", "db", "catalog"):
            value = canonical.args.get(key)
            table.set(key, value.copy() if value is not None else None)
        if changed_name and not table.alias:
            table.set("alias", exp.TableAlias(this=original_name))

    @staticmethod
    def _joins_scopes(predicate: Any, previous: set, joined: str) -> bool:
        """Require a non-vacuous ON relationship for every possible OR branch."""
        from sqlglot import exp

        if predicate is None:
            return False
        if isinstance(predicate, exp.Paren):
            return ASTGuardianAgent._joins_scopes(predicate.this, previous, joined)
        if isinstance(predicate, exp.And):
            return (
                ASTGuardianAgent._joins_scopes(predicate.this, previous, joined)
                or ASTGuardianAgent._joins_scopes(predicate.expression, previous, joined)
            )
        if isinstance(predicate, exp.Or):
            return (
                ASTGuardianAgent._joins_scopes(predicate.this, previous, joined)
                and ASTGuardianAgent._joins_scopes(predicate.expression, previous, joined)
            )
        comparison_types = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
        if not isinstance(predicate, comparison_types):
            return False

        def sources(side: Any) -> set:
            if side is None or side.find(exp.Select) is not None:
                return set()
            return {column.table.casefold() for column in side.find_all(exp.Column) if column.table}

        left, right = sources(predicate.this), sources(predicate.expression)
        return bool(
            (joined in left and right.intersection(previous))
            or (joined in right and left.intersection(previous))
        )

    def audit(
        self,
        raw_sql: str,
        valid_tables: Optional[List[str]] = None,
        authorized_tables: Optional[Any] = None,
        username: Optional[str] = None,
        user_session: Optional[Any] = None,
        raise_on_violation: bool = False,
        allowed_columns: Optional[Dict[str, List[str]]] = None,
    ) -> GuardianResult:
        """Validate one AST, bind physical relations, and cap its outer result."""
        clean_sql = raw_sql.strip()
        if user_session is not None:
            if hasattr(user_session, "allowed_tables"):
                authorized_tables = user_session.allowed_tables
            elif hasattr(user_session, "authorized_tables"):
                authorized_tables = user_session.authorized_tables
            if not username:
                username = getattr(user_session, "username", getattr(user_session, "role_title", "User"))
        elif authorized_tables is not None and hasattr(authorized_tables, "allowed_tables"):
            authorized_tables = authorized_tables.allowed_tables

        try:
            expression = parse_single_query(clean_sql, dialect=self.dialect)
            from sqlglot import exp

            scopes = query_scopes(expression)
            tables = physical_tables(expression)
            self._reject_identifier_collisions(valid_tables)
            self._reject_identifier_collisions(authorized_tables)
            for table in tables:
                identity = ".".join(identifier_parts(table))
                if authorized_tables is not None and not table_matches_allowed(
                    table, authorized_tables, dialect=self.dialect,
                ):
                    role = username or "Active Role"
                    message = f"SecurityViolationException: Table [{identity}] is unauthorized for role [{role}]."
                    if raise_on_violation:
                        raise SecurityViolationException(message)
                    return self._deny(
                        clean_sql, "RBAC_AUTHORIZATION_VIOLATION", message,
                        f"Only query authorized relations from corporate scope: {authorized_tables}.",
                    )
                if valid_tables is not None and not table_matches_allowed(
                    table, valid_tables, dialect=self.dialect,
                ):
                    return self._deny(
                        clean_sql, "SCHEMA_MISMATCH",
                        f"Query references non-existent relation [{identity}].",
                        f"Reference only verified relations: {valid_tables}.",
                    )
                self._canonicalize_table(
                    table, authorized_tables if authorized_tables is not None else valid_tables,
                )

            # An unrelated WHERE (including one inside a nested query) cannot
            # authorize a CROSS JOIN or vacuous ON in any other SELECT scope.
            for scope in scopes:
                select = scope.expression
                if not isinstance(select, exp.Select):
                    continue
                from_clause = select.args.get("from_") or select.args.get("from")
                previous = set()
                if from_clause is not None and from_clause.this is not None:
                    previous.add(from_clause.this.alias_or_name.casefold())
                for join in select.args.get("joins") or []:
                    joined = join.this.alias_or_name.casefold()
                    using = join.args.get("using")
                    has_relationship = bool(using) or self._joins_scopes(join.args.get("on"), previous, joined)
                    if join.kind.upper() == "CROSS" or not has_relationship:
                        return self._deny(
                            clean_sql, "AST_CARTESIAN_PRODUCT",
                            f"Unintended Cartesian join detected on source {join.this}.",
                            "Use an explicit non-vacuous ON relationship between joined sources, or USING columns.",
                        )
                    previous.add(joined)

            if allowed_columns is not None:
                # A projection wildcard must not expand to masked fields in a
                # physical relation. COUNT(*) remains an analytical aggregate.
                for node in expression.find_all(exp.Star):
                    if not isinstance(node.parent, exp.Count):
                        raise ValidationError("COLUMN_AUTHORIZATION_VIOLATION", "Explicit authorized column projections are required.")
                from agents.critic import RuntimeCriticAgent
                class MaskedCatalog:
                    dialect = self.dialect
                    def get_table_columns_info(catalog, name):
                        if name not in allowed_columns:
                            raise ValidationError("HALLUCINATION_SCHEMA_UNAVAILABLE", "No masked column policy for this relation.")
                        return [{"name": column} for column in allowed_columns[name]]
                denial = RuntimeCriticAgent(MaskedCatalog()).validate_schema_grounding(
                    expression.sql(dialect=self.dialect), authorized_tables=list(allowed_columns))
                if denial:
                    raise ValidationError("COLUMN_AUTHORIZATION_VIOLATION", "Column reference is outside the verified masked scope.")

            # Inspect only the root limit. A nested TOP, OFFSET, TOP PERCENT,
            # WITH TIES, parameter, or oversized TOP cannot defeat the row cap.
            root_limit = expression.args.get("limit")
            literal = (root_limit.expression or root_limit.args.get("count")) if root_limit is not None else None
            safe_limit = False
            if root_limit is not None and isinstance(literal, exp.Literal) and not literal.is_string:
                try:
                    count = int(literal.this)
                    options = root_limit.args.get("limit_options")
                    modifiers = bool(options and (options.args.get("percent") or options.args.get("with_ties")))
                    safe_limit = 0 <= count <= self.default_limit and not modifiers
                except (TypeError, ValueError):
                    pass
            limit_injected = not safe_limit
            issues: List[str] = []
            if limit_injected:
                expression.set("limit", exp.Limit(expression=exp.Literal.number(self.default_limit)))
                issues.append(f"Enforced defensive outer result limit of {self.default_limit} rows.")

            return GuardianResult(
                True, expression.sql(dialect=self.dialect),
                issues=issues, limit_injected=limit_injected,
            )
        except SecurityViolationException:
            raise
        except ValidationError as error:
            return self._deny(
                clean_sql, error.code, error.message,
                "Submit one read-only query using the verified, authorized schema; strict AST validation is required.",
            )
        except Exception as error:
            logger.warning("AST validation failed closed: %s", error)
            return self._deny(
                clean_sql, "AST_PARSER_FAILURE", f"AST validation could not complete: {error}",
                "Restore the required parser and correct SQL syntax before execution.",
            )

    def _fallback_audit(
        self,
        sql: str,
        valid_tables: Optional[List[str]],
        authorized_tables: Optional[List[str]],
        username: Optional[str],
    ) -> GuardianResult:
        """Retained legacy hook; fallback execution is expressly forbidden."""
        return self._deny(
            sql, "AST_PARSER_FAILURE", "Strict AST validation is unavailable; execution is prohibited.",
            "Install and restore the required SQLGlot parser before executing queries.",
        )
