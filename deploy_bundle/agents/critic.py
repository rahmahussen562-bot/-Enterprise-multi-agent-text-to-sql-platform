"""
Agent 4: Runtime Critic & Data Sanity Agent (The Evaluator)
Runs queries safely in timeout-guarded execution sandbox.
Accepts legitimate empty results, identifies domain numeric/date anomalies,
and generates a formal executive analytical summary without informal emojis.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.database import DatabaseEngine
from core.cancellation import QueryCancelledError, check_cancelled
from core.sql_validation import (
    ValidationError,
    identifier_parts,
    parse_single_query,
    physical_tables,
    query_scopes,
    table_matches_allowed,
)

logger = logging.getLogger("TextToSQL.Critic")


@dataclass
class EvaluationResult:
    success: bool
    df: pd.DataFrame
    execution_time_ms: float
    critique: Optional[Dict[str, Any]] = None
    executive_narrative: str = ""
    sanity_warnings: List[str] = field(default_factory=list)


class RuntimeCriticAgent:
    """Agent 4: Runtime Critic & Data Sanity Agent (The Evaluator) for T-SQL."""

    def __init__(self, db_engine: DatabaseEngine, timeout_sec: int = 15):
        self.db = db_engine
        self.timeout_sec = timeout_sec
        self._col_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _get_cached_columns(self, table_name: str) -> List[Dict[str, Any]]:
        clean_tbl = table_name.casefold()
        if clean_tbl not in self._col_cache:
            try:
                columns = self.db.get_table_columns_info(table_name)
            except Exception as error:
                raise ValidationError(
                    "HALLUCINATION_SCHEMA_UNAVAILABLE",
                    f"Verified metadata is unavailable for relation [{table_name}].",
                ) from error
            if not columns or any(not isinstance(c.get("name"), str) or not c["name"] for c in columns):
                raise ValidationError(
                    "HALLUCINATION_SCHEMA_UNAVAILABLE",
                    f"Verified column metadata is missing for relation [{table_name}].",
                )
            self._col_cache[clean_tbl] = columns
        return self._col_cache[clean_tbl]

    def validate_schema_grounding(
        self,
        sql: str,
        authorized_tables: Optional[List[str]] = None,
        user_session: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Bind relations and columns in their lexical query scopes before execution.

        CTEs, derived outputs, projection aliases, and correlated subqueries are
        resolved locally. A column existing in another relation or query scope
        never establishes that the requested reference exists.
        """
        try:
            dialect = getattr(self.db, "dialect", "tsql")
            if not isinstance(dialect, str):
                dialect = "tsql"
            dialect = dialect.casefold()
            expression = parse_single_query(sql, dialect=dialect)
            scopes = query_scopes(expression)
            auth_tables = getattr(
                user_session, "allowed_tables",
                getattr(user_session, "authorized_tables", authorized_tables),
            )
            # Cache only within this audit: changed/revoked metadata must not be
            # silently reused across a long-lived critic instance.
            self._col_cache.clear()
            for table in physical_tables(expression):
                if auth_tables is not None and not table_matches_allowed(table, auth_tables, dialect):
                    raise ValidationError(
                        "HALLUCINATION_UNAUTHORIZED_TABLE",
                        f"Hallucination / RBAC Isolation: Relation [{table.sql(dialect=dialect)}] is unauthorized for the active role.",
                    )
            self._validate_scoped_columns(scopes, dialect)
            return None
        except ValidationError as error:
            return {
                "type": error.code,
                "message": error.message,
                "failed_sql": sql,
                "remediation": "Use only authorized relations and columns from verified metadata in the current query scope. Validation must succeed before execution.",
            }
        except Exception as error:
            # Broken parser/metadata/scope machinery is not a proof of safety.
            logger.warning("Schema grounding failed closed: %s", error)
            return {
                "type": "AST_PARSER_FAILURE",
                "message": "Strict AST schema grounding could not be completed.",
                "failed_sql": sql,
                "remediation": "Restore the AST validator and verified schema metadata before executing this query.",
            }

    def _validate_scoped_columns(self, scopes: List[Any], dialect: str) -> None:
        """Validate column ownership and expose only proven derived outputs."""
        from sqlglot import exp
        from sqlglot.optimizer.scope import Scope

        source_cache: Dict[int, Dict[str, Tuple[Any, List[str]]]] = {}
        output_cache: Dict[int, List[str]] = {}
        resolving = set()

        def invalid(message: str) -> None:
            raise ValidationError("HALLUCINATION_INVALID_COLUMN", message)

        def source_columns(scope: Any) -> Dict[str, Tuple[Any, List[str]]]:
            key = id(scope)
            if key in source_cache:
                return source_cache[key]
            sources = {}
            for alias, (_, source) in scope.selected_sources.items():
                normalized = alias.casefold()
                if normalized in sources:
                    invalid(f"Relation alias [{alias}] is ambiguous in this query scope.")
                if isinstance(source, exp.Table):
                    relation = exp.Table(this=source.this.copy())
                    for part in ("db", "catalog"):
                        if source.args.get(part) is not None:
                            relation.set(part, source.args[part].copy())
                    name = relation.sql(dialect=dialect) if len(identifier_parts(source)) > 1 else source.name
                    metadata = self._get_cached_columns(name)
                    for column in metadata:
                        # Real adapters return identity fields. Legacy test
                        # adapters may provide only the public column contract.
                        for field, expected in (("table_schema", source.db), ("table_catalog", source.catalog)):
                            if expected and column.get(field) and str(column[field]).casefold() != expected.casefold():
                                raise ValidationError(
                                    "HALLUCINATION_SCHEMA_UNAVAILABLE",
                                    f"Metadata identity does not match relation [{name}].",
                                )
                    names = [column["name"].casefold() for column in metadata]
                elif isinstance(source, Scope):
                    names = scope_outputs(source)
                    if not names or any(not name for name in names):
                        invalid(f"Derived relation [{alias}] has an unnamed or unresolved output.")
                    if len(names) != len(set(names)):
                        invalid(f"Derived relation [{alias}] has duplicate output column names.")
                else:
                    raise ValidationError("AST_UNSUPPORTED_SOURCE", "Unresolved relation source.")
                sources[normalized] = (source, names)
            source_cache[key] = sources
            return sources

        def column_owner(column: Any) -> Any:
            parent = column.parent
            while parent is not None and not isinstance(parent, (exp.Select, exp.SetOperation)):
                parent = parent.parent
            return parent

        def resolve(column: Any, scope: Any) -> None:
            sources = source_columns(scope)
            name = column.name.casefold()
            qualifier = column.table.casefold()
            if qualifier:
                if qualifier in sources:
                    source, names = sources[qualifier]
                    if column.db or column.catalog:
                        if not isinstance(source, exp.Table):
                            invalid(f"Derived alias [{column.table}] cannot be schema-qualified.")
                        if source.alias:
                            invalid(f"Relation alias [{column.table}] cannot be schema-qualified.")
                        source_schema = source.db or ("dbo" if dialect == "tsql" else "")
                        if column.db and column.db.casefold() != source_schema.casefold():
                            invalid(f"Schema qualifier for [{column.sql()}] does not match its relation.")
                        if column.catalog and column.catalog.casefold() != source.catalog.casefold():
                            invalid(f"Catalog qualifier for [{column.sql()}] does not match its relation.")
                    if name != "*" and names.count(name) != 1:
                        invalid(f"Column [{column.sql()}] is absent or ambiguous in relation [{column.table}].")
                    return
                # A local alias shadows the same alias in all enclosing scopes;
                # only entirely absent qualifiers may correlate outward.
            else:
                count = sum(names.count(name) for _, names in sources.values())
                if count == 1:
                    return
                if count > 1:
                    invalid(f"Unqualified column [{column.name}] is ambiguous in this query scope.")
            if scope.can_be_correlated and scope.parent is not None:
                resolve(column, scope.parent)
                return
            invalid(f"Column [{column.sql()}] cannot be resolved in this query scope.")

        def scope_outputs(scope: Any) -> List[str]:
            key = id(scope)
            if key in output_cache:
                return output_cache[key]
            if key in resolving:
                invalid("Recursive query outputs require an explicit schema policy.")
            resolving.add(key)
            try:
                if isinstance(scope.expression, exp.Union):
                    branch_scopes = getattr(scope, "set_operation_scopes", None)
                    if branch_scopes is None:
                        branch_scopes = getattr(scope, "union_scopes", [])
                    branches = [scope_outputs(branch) for branch in branch_scopes]
                    if not branches or any(len(branch) != len(branches[0]) for branch in branches):
                        invalid("UNION branches have incompatible output columns.")
                    names = list(branches[0])
                else:
                    names = []
                    sources = source_columns(scope)
                    for projection in scope.expression.selects:
                        if isinstance(projection, exp.Star):
                            if not sources:
                                invalid("SELECT * requires a verified relation source.")
                            for _, columns in sources.values():
                                names.extend(columns)
                        elif isinstance(projection, exp.Column) and projection.is_star:
                            resolve(projection, scope)
                            qualifier = projection.table.casefold()
                            if qualifier not in sources:
                                invalid("A projection wildcard must reference a local relation.")
                            names.extend(sources[qualifier][1])
                        else:
                            names.append(projection.alias_or_name.casefold())
                if scope.outer_columns:
                    if len(scope.outer_columns) != len(names):
                        invalid("Declared CTE/derived column aliases do not match its output width.")
                    names = [name.casefold() for name in scope.outer_columns]
                output_cache[key] = names
                return names
            finally:
                resolving.remove(key)

        for scope in scopes:
            source_columns(scope)  # Includes metadata validation for COUNT(*).
            outputs = scope_outputs(scope)
            for column in scope.expression.find_all(exp.Column):
                if column_owner(column) is not scope.expression:
                    continue
                # SQL Server exposes output aliases only as standalone ORDER
                # BY terms. WHERE/JOIN/other projections cannot borrow them.
                ordered = column.parent
                if (
                    not column.table and isinstance(ordered, exp.Ordered)
                    and ordered.this is column and isinstance(ordered.parent, exp.Order)
                    and ordered.parent.parent is scope.expression
                    and outputs.count(column.name.casefold()) == 1
                ):
                    continue
                resolve(column, scope)

    def evaluate(
        self,
        question: str,
        sql: str,
        iteration: int = 1,
        max_iterations: int = 3,
        user_session: Optional[Any] = None,
        authorized_tables: Optional[List[str]] = None
    ) -> EvaluationResult:
        """
        Execute query in sandbox, run post-execution sanity checks,
        and generate executive analytical synthesis.
        """
        start_t = time.perf_counter()
        check_cancelled()

        # Step 0: Pre-execution Hallucination Detection & Strict Schema Grounding
        schema_critique = self.validate_schema_grounding(
            sql=sql,
            authorized_tables=authorized_tables,
            user_session=user_session
        )
        if schema_critique:
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            return EvaluationResult(
                success=False,
                df=pd.DataFrame(),
                execution_time_ms=elapsed_ms,
                critique=schema_critique,
                sanity_warnings=[schema_critique["message"]]
            )

        # Step 1: Sandbox Execution with Timeout
        try:
            df = self.db.execute_query(sql, timeout_sec=self.timeout_sec)
        except QueryCancelledError:
            raise
        except TimeoutError as te:
            critique = {
                "type": "EXECUTION_TIMEOUT",
                "message": f"Query exceeded {self.timeout_sec}s execution limit: {str(te)}",
                "failed_sql": sql,
                "remediation": "Query is too slow or unindexed. Add indexes, restrict date ranges, or reduce table joins."
            }
            return EvaluationResult(
                success=False,
                df=pd.DataFrame(),
                execution_time_ms=(time.perf_counter() - start_t) * 1000,
                critique=critique
            )
        except Exception as err:
            critique = {
                "type": "RUNTIME_DATABASE_ERROR",
                "message": f"Database execution error: {str(err)}",
                "failed_sql": sql,
                "remediation": "Check for invalid column names, ambiguous references, or type mismatches."
            }
            return EvaluationResult(
                success=False,
                df=pd.DataFrame(),
                execution_time_ms=(time.perf_counter() - start_t) * 1000,
                critique=critique
            )

        elapsed_ms = (time.perf_counter() - start_t) * 1000
        sanity_warnings: List[str] = []

        # Step 2: An empty result is a valid answer, not permission to loosen
        # the requested conditions or row-level security predicates.
        if df.empty or len(df) == 0:
            return EvaluationResult(
                success=True,
                df=df,
                execution_time_ms=elapsed_ms,
                critique=None,
                executive_narrative=self._synthesize_narrative(question, df, elapsed_ms, []),
            )

        # Step 3: Domain Sanity Checks
        for col in df.columns:
            col_lower = str(col).lower()
            if any(k in col_lower for k in ["revenue", "price", "total", "sales", "quantity", "cost"]):
                if pd.api.types.is_numeric_dtype(df[col]):
                    neg_count = (df[col] < 0).sum()
                    if neg_count > 0:
                        sanity_warnings.append(
                            f"Domain Anomaly: Column '{col}' contains {neg_count} negative value(s)."
                        )

        for col in df.columns:
            null_ratio = df[col].isnull().mean()
            if null_ratio > 0.8:
                sanity_warnings.append(
                    f"Data Quality: Column '{col}' is {null_ratio:.0%} null."
                )

        # Step 4: Executive Analytical Synthesis
        narrative = self._synthesize_narrative(question, df, elapsed_ms, sanity_warnings)

        return EvaluationResult(
            success=True,
            df=df,
            execution_time_ms=elapsed_ms,
            critique=None,
            executive_narrative=narrative,
            sanity_warnings=sanity_warnings
        )

    def _synthesize_narrative(
        self,
        question: str,
        df: pd.DataFrame,
        elapsed_ms: float,
        warnings: List[str]
    ) -> str:
        """Synthesize a formal corporate analytical summary without emojis."""
        if df.empty:
            return "No matching records found in the database for the specified parameters."

        row_count = len(df)
        col_count = len(df.columns)

        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        summary_points = []

        if numeric_cols:
            primary_num = numeric_cols[0]
            total_val = df[primary_num].sum()
            avg_val = df[primary_num].mean()
            max_val = df[primary_num].max()
            summary_points.append(
                f"{primary_num}: Total = {total_val:,.2f} (Mean = {avg_val:,.2f}, Max = {max_val:,.2f})"
            )

        first_text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        top_leader = ""
        if first_text_cols and numeric_cols and row_count > 1:
            leader_row = df.iloc[0]
            top_leader = f" Primary record: {leader_row[first_text_cols[0]]} with {leader_row[numeric_cols[0]]}."

        narrative = (
            f"Retrieved {row_count} records across {col_count} attributes in {elapsed_ms:.1f} ms."
            f"{top_leader} "
            + "; ".join(summary_points)
        )

        if warnings:
            narrative += f" [Audit Notes: {'; '.join(warnings)}]"

        return narrative.strip()
