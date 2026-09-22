"""
Agent 4: Runtime Critic & Data Sanity Agent (The Evaluator)
Runs queries safely in timeout-guarded execution sandbox.
Diagnoses zero-result logic bugs, identifies domain numeric/date anomalies,
and generates a formal executive analytical summary without informal emojis.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from core.database import DatabaseEngine

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

    def evaluate(
        self,
        question: str,
        sql: str,
        iteration: int = 1,
        max_iterations: int = 3
    ) -> EvaluationResult:
        """
        Execute query in sandbox, run post-execution sanity checks,
        and generate executive analytical synthesis.
        """
        start_t = time.perf_counter()

        # Step 1: Sandbox Execution with Timeout
        try:
            df = self.db.execute_query(sql, timeout_sec=self.timeout_sec)
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

        # Step 2: Zero-Result Diagnosis
        if df.empty or len(df) == 0:
            if iteration < max_iterations:
                critique = {
                    "type": "ZERO_RESULTS_RETURNED",
                    "message": "Query executed successfully without database errors, but returned 0 records.",
                    "failed_sql": sql,
                    "remediation": (
                        "Zero rows returned. Likely causes: (1) exact '=' equality check on strings "
                        "instead of LIKE/ILIKE, (2) overly restrictive AND conditions, (3) INNER JOIN "
                        "filtering out rows that LEFT JOIN would preserve. Relax filters or use LIKE '%...%'."
                    )
                }
                return EvaluationResult(
                    success=False,
                    df=df,
                    execution_time_ms=elapsed_ms,
                    critique=critique
                )
            else:
                sanity_warnings.append("Notice: Result set is empty after retries.")

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
