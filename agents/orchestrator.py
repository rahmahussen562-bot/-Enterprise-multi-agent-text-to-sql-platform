"""
Central Controller & Pipeline Coordinator: 4-Agent State Machine for T-SQL.
Coordinates Explorer, Coder, Guardian, and Evaluator under strict RBAC table scopes,
closed-loop self-healing retry cycles, and clean ASCII telemetry.
"""
import difflib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from agents.coder import SQLCoderAgent
from agents.critic import EvaluationResult, RuntimeCriticAgent
from agents.guardian import ASTGuardianAgent, GuardianResult
from agents.reconnaissance import ReconnaissanceAgent, SchemaCard
from core.auth import UserSession
from core.config import AgentConfig, SystemConfig, get_config
from core.database import DatabaseEngine
from core.vanna_client import VannaTextToSQLEngine

logger = logging.getLogger("TextToSQL.Orchestrator")


@dataclass
class AgentEvent:
    agent_name: str
    status: str  # "running", "success", "retry", "failed"
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class RetryRecord:
    iteration: int
    trigger_agent: str
    critique_type: str
    critique_message: str
    failed_sql: str
    corrected_sql: str
    sql_diff: str


@dataclass
class OrchestrationResult:
    success: bool
    final_sql: str
    df: pd.DataFrame
    executive_narrative: str
    events: List[AgentEvent]
    retry_history: List[RetryRecord]
    schema_card: Optional[SchemaCard] = None
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None


class CentralController:
    """Central Controller: 4-Agent State Machine with RBAC and Self-Healing."""

    def __init__(
        self,
        db_engine: Optional[DatabaseEngine] = None,
        vanna_engine: Optional[VannaTextToSQLEngine] = None,
        config: Optional[SystemConfig] = None
    ):
        self.config = config or get_config()
        self.db = db_engine or DatabaseEngine(self.config.db)
        self.vanna = vanna_engine or VannaTextToSQLEngine(self.config.llm, self.config.vector)

        self.explorer = ReconnaissanceAgent(self.db, self.vanna)
        self.coder = SQLCoderAgent(self.config.llm, dialect="tsql")
        self.guardian = ASTGuardianAgent(default_limit=self.config.agent.defensive_limit, dialect="tsql")
        self.critic = RuntimeCriticAgent(self.db, timeout_sec=self.config.db.query_timeout_sec)

    def execute_pipeline(
        self,
        question: str,
        user_session: Optional[UserSession] = None,
        on_event: Optional[Callable[[AgentEvent], None]] = None
    ) -> OrchestrationResult:
        """
        Execute the 4-agent state machine pipeline:
        Explorer -> Coder -> Guardian -> Evaluator under active user's authorized scope.
        """
        start_time = time.perf_counter()
        events: List[AgentEvent] = []
        retry_history: List[RetryRecord] = []

        authorized_tables = user_session.authorized_tables if user_session else None
        username = user_session.username if user_session else "system"

        def _log_event(agent: str, status: str, msg: str, details: Optional[Dict[str, Any]] = None):
            ev = AgentEvent(agent_name=agent, status=status, message=msg, details=details)
            events.append(ev)
            if on_event:
                on_event(ev)

        # STAGE 1: Schema & Data Reconnaissance (The Explorer)
        _log_event("Explorer", "running", f"Pruning DDLs within authorized scope for user '{username}'...")
        try:
            schema_card = self.explorer.run(
                question,
                max_tables=self.config.vector.top_k_tables,
                authorized_tables=authorized_tables
            )
            _log_event(
                "Explorer", "success",
                f"Retrieved {len(schema_card.candidate_tables)} authorized candidate tables and grounded {len(schema_card.grounded_values)} entity columns.",
                details={
                    "tables": schema_card.candidate_tables,
                    "grounded_values": schema_card.grounded_values
                }
            )
        except Exception as e:
            _log_event("Explorer", "failed", f"Reconnaissance error: {str(e)}")
            return OrchestrationResult(
                success=False,
                final_sql="",
                df=pd.DataFrame(),
                executive_narrative="",
                events=events,
                retry_history=retry_history,
                error_message=f"Explorer failed: {str(e)}"
            )

        similar_examples = self.vanna.retrieve_similar_examples(question)

        # STAGE 2-4: Self-Healing Synthesis Loop (Coder <-> Guardian <-> Evaluator)
        critique: Optional[Dict[str, Any]] = None
        current_sql = ""
        sanitized_sql = ""
        max_retries = self.config.agent.max_retries
        iteration = 1

        while iteration <= max_retries:
            failed_sql_before_retry = current_sql

            # Agent 2: Coder
            retry_note = " [Critique Applied]" if critique else ""
            _log_event(
                "Coder", "running",
                f"Drafting T-SQL query (Iteration {iteration}/{max_retries}){retry_note}..."
            )
            try:
                current_sql = self.coder.generate_sql(
                    question=question,
                    schema_card=schema_card,
                    critique=critique,
                    similar_examples=similar_examples
                )
                _log_event("Coder", "success", f"Drafted raw T-SQL query (Iteration {iteration}).", details={"sql": current_sql})
            except Exception as e:
                _log_event("Coder", "failed", f"Coder generation error: {str(e)}")
                critique = {"type": "CODER_EXCEPTION", "message": str(e), "failed_sql": current_sql}
                iteration += 1
                continue

            # Record Diff if self-healing occurred
            if critique and failed_sql_before_retry:
                diff_text = self._compute_diff(failed_sql_before_retry, current_sql)
                retry_history.append(RetryRecord(
                    iteration=iteration,
                    trigger_agent=critique.get("agent", "Unknown"),
                    critique_type=critique.get("type", "UNKNOWN"),
                    critique_message=critique.get("message", ""),
                    failed_sql=failed_sql_before_retry,
                    corrected_sql=current_sql,
                    sql_diff=diff_text
                ))

            # Agent 3: Guardian (AST Lint, Injection Quarantine, RBAC Table Whitelist)
            _log_event("Guardian", "running", "Auditing T-SQL AST, injection vectors, and RBAC table whitelists...")
            valid_tables = self.db.get_table_names()
            guardian_result: GuardianResult = self.guardian.audit(
                current_sql,
                valid_tables=valid_tables,
                authorized_tables=authorized_tables,
                username=username
            )

            if not guardian_result.is_valid:
                _log_event(
                    "Guardian", "retry",
                    f"AST Policy Violation: {guardian_result.critique.get('message')}",
                    details={"critique": guardian_result.critique}
                )
                critique = guardian_result.critique
                critique["agent"] = "Guardian"
                iteration += 1
                continue

            sanitized_sql = guardian_result.sanitized_sql
            limit_msg = " [Defensive TOP injected]" if guardian_result.limit_injected else ""
            _log_event(
                "Guardian", "success",
                f"AST passed security firewall and RBAC authorization.{limit_msg}",
                details={"sanitized_sql": sanitized_sql, "issues": guardian_result.issues}
            )

            # Agent 4: Evaluator (Runtime Critic & Data Sanity)
            _log_event("Evaluator", "running", "Executing T-SQL query in sandbox and evaluating domain sanity...")
            eval_result: EvaluationResult = self.critic.evaluate(
                question=question,
                sql=sanitized_sql,
                iteration=iteration,
                max_iterations=max_retries
            )

            if not eval_result.success:
                _log_event(
                    "Evaluator", "retry",
                    f"Evaluator triggered diagnostic retry: {eval_result.critique.get('message')}",
                    details={"critique": eval_result.critique}
                )
                critique = eval_result.critique
                critique["agent"] = "Evaluator"
                iteration += 1
                continue

            # Successful Completion
            total_elapsed_ms = (time.perf_counter() - start_time) * 1000
            _log_event(
                "Evaluator", "success",
                f"Execution verified. Returned {len(eval_result.df)} rows in {eval_result.execution_time_ms:.1f}ms.",
                details={"rows": len(eval_result.df), "warnings": eval_result.sanity_warnings}
            )

            return OrchestrationResult(
                success=True,
                final_sql=sanitized_sql,
                df=eval_result.df,
                executive_narrative=eval_result.executive_narrative,
                events=events,
                retry_history=retry_history,
                schema_card=schema_card,
                execution_time_ms=total_elapsed_ms
            )

        # Max retries exceeded
        total_elapsed_ms = (time.perf_counter() - start_time) * 1000
        _log_event("Orchestrator", "failed", f"Maximum retries ({max_retries}) exceeded without valid outcome.")
        return OrchestrationResult(
            success=False,
            final_sql=sanitized_sql or current_sql,
            df=pd.DataFrame(),
            executive_narrative="Unable to synthesize a verified, non-empty T-SQL query within retry limits.",
            events=events,
            retry_history=retry_history,
            schema_card=schema_card,
            execution_time_ms=total_elapsed_ms,
            error_message=critique.get("message") if critique else "Maximum retries exceeded."
        )

    def _compute_diff(self, old_sql: str, new_sql: str) -> str:
        """Generate a clean unified text diff between failed and corrected T-SQL."""
        old_lines = old_sql.strip().splitlines()
        new_lines = new_sql.strip().splitlines()
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile="failed_attempt.sql",
            tofile="corrected_attempt.sql",
            lineterm=""
        )
        return "\n".join(diff)
