"""Fail-closed SQL parsing and lexical relation binding shared by safety agents.

This module deliberately imports SQLGlot at validation time: a missing or broken
parser is a denial, never an invitation to use a regular-expression executor.
"""
from typing import Any, Iterable, List, Tuple


# This is a reviewed semantic allowlist, not a list of every function SQLGlot
# can parse. In particular, parser support does not authorize server identity,
# catalog introspection, sequences, external I/O, or application-defined code.
# Exact AST types prevent an unapproved function subclass from inheriting trust.
APPROVED_ANALYTICAL_FUNCTION_TYPES = frozenset({
    # Aggregation and bounded scalar arithmetic.
    "Sum", "Count", "Avg", "Min", "Max", "Stddev", "StddevPop",
    "StddevSamp", "Variance", "VariancePop", "Abs", "Ceil", "Floor",
    "Round", "Pow", "Sqrt", "Sign", "Ln", "Log", "Exp",
    # Conditions, casts, and subquery predicates.
    "Case", "If", "Coalesce", "Nullif", "Cast", "TryCast", "Convert", "Exists",
    # String transformations; no file/network/system access.
    "Lower", "Upper", "Length", "Trim", "Substring", "Left", "Right",
    "Replace", "Concat", "ConcatWs", "StrPosition", "Ascii", "Chr",
    "Unicode", "Reverse",
    # Date arithmetic, formatting, and the clock. SQLGlot introduces conversion
    # nodes while parsing T-SQL DATEADD/DATEDIFF/YEAR/EOMONTH expressions.
    "CurrentTimestamp", "CurrentDate", "CurrentTime", "DateAdd", "DateSub",
    "DateDiff", "DateTrunc", "Extract", "Year", "Month", "Day", "LastDay",
    "DateFromParts", "TimeToStr", "TimeStrToTime", "StrToTime", "TsOrDsToDate",
    "TsOrDsToDatetime", "TsOrDsAdd", "TsOrDsDiff",
    # Analytical window operations.
    "RowNumber", "Rank", "DenseRank", "PercentRank", "CumeDist", "Ntile",
    "Lag", "Lead", "FirstValue", "LastValue", "NthValue",
})

# These SQL Server builtins remain Anonymous nodes in the pinned SQLGlot
# version. Only these exact, unqualified names are authorized. Qualified calls
# are always denied, even when their final name resembles an approved builtin.
APPROVED_TSQL_ANONYMOUS_FUNCTIONS = frozenset({
    "getutcdate", "sysutcdatetime", "stdevp", "var", "varp", "datalength", "nchar",
})


class ValidationError(ValueError):
    """A stable denial code with an explanation suitable for an agent critique."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_single_query(sql: str, dialect: str = "tsql") -> Any:
    """Parse exactly one read-only SELECT/UNION, including read-only CTEs."""
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.errors import ErrorLevel
    except Exception as error:
        raise ValidationError("AST_PARSER_FAILURE", "The required AST parser is unavailable.") from error

    try:
        statements = sqlglot.parse(sql, read=dialect, error_level=ErrorLevel.RAISE)
    except Exception as error:
        raise ValidationError("AST_PARSER_FAILURE", f"Strict AST parsing failed: {error}") from error

    statements = [statement for statement in statements if statement is not None]
    if not statements:
        raise ValidationError("AST_PARSER_FAILURE", "No parseable SQL statement was provided.")
    if len(statements) != 1:
        raise ValidationError("SQL_INJECTION_QUARANTINE", "Stacked statements are prohibited.")

    expression = statements[0]
    # SELECT INTO, writable CTEs, and locking reads are not read-only even when
    # their outermost expression is SELECT. Inspect the entire tree first.
    forbidden_names = (
        "Drop", "Delete", "Update", "Alter", "Insert", "Command", "Create",
        "Grant", "Revoke", "Execute", "Into", "Copy", "Merge", "Transaction",
        "Commit", "Rollback", "TruncateTable", "Lock", "Use", "Set",
    )
    forbidden_types = tuple(
        node_type for name in forbidden_names
        if isinstance((node_type := getattr(exp, name, None)), type)
    )
    for node in expression.walk():
        if isinstance(node, forbidden_types):
            raise ValidationError(
                "AST_SECURITY_VIOLATION",
                f"Read-only SQL cannot contain {type(node).__name__} nodes.",
            )
        if isinstance(node, exp.Parameter) and isinstance(node.this, exp.Parameter):
            raise ValidationError(
                "AST_SECURITY_VIOLATION",
                "Server/session system variables are outside the analytical query policy.",
            )
        # SQLGlot models AND/OR as Func subclasses for AST construction. They
        # are logical SQL syntax, not callable functions or policy exemptions
        # for any of their operands; the walk still inspects both operands.
        if isinstance(node, exp.Func) and not isinstance(node, (exp.And, exp.Or)):
            if isinstance(node.parent, exp.Dot):
                raise ValidationError(
                    "AST_UNSUPPORTED_FUNCTION",
                    "Schema-qualified, catalog-qualified, and receiver-method functions are not authorized.",
                )
            if isinstance(node, exp.Anonymous):
                approved = (
                    dialect.lower() == "tsql"
                    and node.name.casefold() in APPROVED_TSQL_ANONYMOUS_FUNCTIONS
                )
            else:
                approved = type(node).__name__ in APPROVED_ANALYTICAL_FUNCTION_TYPES
            if not approved:
                raise ValidationError(
                    "AST_UNSUPPORTED_FUNCTION",
                    f"Function [{node.name if isinstance(node, exp.Anonymous) else node.sql_name()}] is not in the approved analytical function policy.",
                )
    if not isinstance(expression, (exp.Select, exp.Union)):
        raise ValidationError(
            "INVALID_QUERY_ROOT",
            f"Query root {type(expression).__name__} must be SELECT or UNION.",
        )
    return expression


# Descriptive alias retained for callers that use the read-only wording.
parse_readonly_query = parse_single_query


def query_scopes(expression: Any) -> List[Any]:
    """Return child-first lexical scopes, rejecting unsupported FROM sources."""
    try:
        from sqlglot import exp
        from sqlglot.optimizer.scope import Scope, traverse_scope

        scopes = list(traverse_scope(expression))
        if not scopes:
            raise ValidationError("AST_SCOPE_FAILURE", "The query has no resolvable SELECT scope.")
        for scope in scopes:
            if not isinstance(scope.expression, (exp.Select, exp.Union)):
                raise ValidationError("AST_UNSUPPORTED_SOURCE", "Only SELECT query sources are supported.")
            if scope.udtfs or scope.lateral_sources:
                raise ValidationError("AST_UNSUPPORTED_SOURCE", "Table-valued or lateral sources are not authorized.")
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    identifier_parts(source)
                    if source.args.get("pivots"):
                        raise ValidationError("AST_UNSUPPORTED_SOURCE", "Pivoted sources require an explicit policy.")
                elif not isinstance(source, Scope):
                    raise ValidationError("AST_UNSUPPORTED_SOURCE", "Unresolved query source cannot be authorized.")
        return scopes
    except ValidationError:
        raise
    except Exception as error:
        raise ValidationError("AST_SCOPE_FAILURE", f"Lexical source binding failed: {error}") from error


def identifier_parts(table: Any) -> Tuple[str, ...]:
    """Return the full catalog/schema/relation identity, never just a basename."""
    from sqlglot import exp

    parts = table.parts
    if not parts or any(not isinstance(part, exp.Identifier) for part in parts):
        raise ValidationError("AST_UNSUPPORTED_SOURCE", "Only static relation identifiers are supported.")
    return tuple(part.name.casefold() for part in parts)


def physical_tables(expression: Any) -> List[Any]:
    """Resolve real relations separately from lexically bound CTE/derived names."""
    from sqlglot import exp

    tables: List[Any] = []
    seen = set()
    for scope in query_scopes(expression):
        for _, source in scope.selected_sources.values():
            if isinstance(source, exp.Table) and id(source) not in seen:
                tables.append(source)
                seen.add(id(source))
    return tables


def table_matches_allowed(table: Any, allowed_tables: Iterable[str], dialect: str = "tsql") -> bool:
    """Match explicit identities exactly, with only the legacy dbo exception.

    A bare legacy whitelist entry authorizes ``Customer`` and ``dbo.Customer``
    in T-SQL, but never ``private.Customer`` or ``other_db.dbo.Customer``.
    Explicitly qualified entries do not authorize an ambiguous bare name.
    """
    from sqlglot import exp

    def identity(relation):
        parts = identifier_parts(relation)
        if dialect.lower() in {"postgres", "postgresql"}:
            return tuple(part.name if part.args.get("quoted") else part.name.lower() for part in relation.parts)
        return parts
    actual = identity(table)
    for allowed_name in allowed_tables:
        try:
            candidate = exp.to_table(str(allowed_name), dialect=dialect)
            if candidate.alias:
                continue
            permitted = identity(candidate)
        except Exception:
            continue
        if actual == permitted:
            return True
        if (
            dialect.lower() == "tsql" and len(permitted) == 1
            and actual == ("dbo", permitted[0])
        ):
            return True
    return False
