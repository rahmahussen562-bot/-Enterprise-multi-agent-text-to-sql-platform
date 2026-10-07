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
from agents.intent_router import IntentResult, IntentRouter, IntentType
from agents.reconnaissance import ReconnaissanceAgent, SchemaCard
from core.auth import UserSession
from core.config import AgentConfig, SystemConfig, get_config
from core.database import DatabaseEngine
from core.cancellation import QueryCancelledError, check_cancelled
from core.vanna_client import VannaTextToSQLEngine

logger = logging.getLogger("TextToSQL.Orchestrator")

# Regeneration can repair a known-catalog typo, but cannot repair an unavailable
# authorization boundary or convert a permission violation into permission.
TERMINAL_CRITIQUE_TYPES = frozenset({
    "AST_PARSER_FAILURE", "AST_SCOPE_FAILURE", "AST_UNSUPPORTED_SOURCE", "AST_UNSUPPORTED_FUNCTION",
    "AST_IDENTIFIER_COLLISION",
    "AST_SECURITY_VIOLATION", "SQL_INJECTION_QUARANTINE", "INVALID_QUERY_ROOT",
    "RBAC_AUTHORIZATION_VIOLATION", "HALLUCINATION_UNAUTHORIZED_TABLE",
    "HALLUCINATION_SCHEMA_UNAVAILABLE", "EXECUTION_TIMEOUT",
    "COLUMN_AUTHORIZATION_VIOLATION",
})


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
    intent: str = "DATA_QUERY"


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
        dialect = getattr(self.db, "dialect", "tsql")
        self.coder = SQLCoderAgent(self.config.llm, dialect=dialect)
        self.guardian = ASTGuardianAgent(default_limit=self.config.agent.defensive_limit, dialect=dialect)
        self.critic = RuntimeCriticAgent(self.db, timeout_sec=self.config.db.query_timeout_sec)
        self.intent_router = IntentRouter()

    def classify_intent(self, question: str, user_session: Optional[UserSession] = None) -> IntentResult:
        """Classify question intent against security, capability, and database boundaries."""
        return self.intent_router.classify(question, user_session=user_session)

    def execute_pipeline(
        self,
        question: str,
        user_session: Optional[UserSession] = None,
        on_event: Optional[Callable[[AgentEvent], None]] = None
    ) -> OrchestrationResult:
        """
        Execute the 4-agent state machine pipeline:
        Intent Check -> Explorer -> Coder -> Guardian -> Evaluator under active user's authorized scope.
        """
        start_time = time.perf_counter()
        dialect_label = "PostgreSQL" if getattr(self.db, "dialect", "tsql") == "postgres" else "T-SQL"
        check_cancelled()
        events: List[AgentEvent] = []
        retry_history: List[RetryRecord] = []

        # STAGE 0: Intent Routing & Operational Boundaries Check
        intent_res = self.classify_intent(question, user_session=user_session)
        if intent_res.intent == IntentType.CAPABILITY_HELP:
            return OrchestrationResult(
                success=True,
                final_sql="",
                df=pd.DataFrame(),
                executive_narrative=intent_res.response_message or "",
                events=[],
                retry_history=[],
                intent=intent_res.intent.value
            )
        elif intent_res.intent in (IntentType.SECURITY_REJECTION, IntentType.OUT_OF_SCOPE):
            return OrchestrationResult(
                success=False,
                final_sql="",
                df=pd.DataFrame(),
                executive_narrative=intent_res.response_message or "",
                events=[],
                retry_history=[],
                error_message=intent_res.response_message,
                intent=intent_res.intent.value
            )

        def _log_event(agent: str, status: str, msg: str, details: Optional[Dict[str, Any]] = None):
            check_cancelled()
            ev = AgentEvent(agent_name=agent, status=status, message=msg, details=details)
            events.append(ev)
            if on_event:
                on_event(ev)

        # HELP remains available without a session; querying never inherits an
        # unrestricted implicit system identity from an omitted principal.
        if not isinstance(user_session, UserSession) or not user_session.username.strip():
            message = "AUTHENTICATION_REQUIRED: An authenticated user session is required for data queries."
            _log_event("Authorization", "failed", message, details={"type": "AUTHENTICATION_REQUIRED"})
            return OrchestrationResult(
                success=False, final_sql="", df=pd.DataFrame(), executive_narrative="",
                events=events, retry_history=retry_history, error_message=message,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        authorized_tables = list(user_session.allowed_tables)
        username = user_session.username

        def _terminal_failure(agent: str, sql: str, denial: Dict[str, Any]) -> OrchestrationResult:
            code = denial.get("type", "VALIDATION_FAILURE")
            message = f"{code}: {denial.get('message', 'Validation failed.')}"
            _log_event(agent, "failed", message, details={"critique": denial})
            return OrchestrationResult(
                success=False, final_sql=sql, df=pd.DataFrame(), executive_narrative="",
                events=events, retry_history=retry_history, schema_card=schema_card,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
                error_message=message,
            )

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
        except QueryCancelledError:
            raise
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
                f"Drafting {dialect_label} query (Iteration {iteration}/{max_retries}){retry_note}..."
            )
            try:
                current_sql = self.coder.generate_sql(
                    question=question,
                    schema_card=schema_card,
                    critique=critique,
                    similar_examples=similar_examples
                )
                if current_sql.strip() == "[GROUNDING_ERROR]":
                    _log_event("Coder", "failed", "Closed-World Assumption: Question cannot be derived from authorized schema.")
                    return OrchestrationResult(
                        success=False,
                        final_sql="[GROUNDING_ERROR]",
                        df=pd.DataFrame(),
                        executive_narrative="[GROUNDING_ERROR]: The inquiry cannot be derived exclusively from the authorized database schema under the Closed-World Assumption.",
                        events=events,
                        retry_history=retry_history,
                        schema_card=schema_card,
                        error_message="[GROUNDING_ERROR]: Unanswerable from authorized database schema."
                    )
                _log_event("Coder", "success", f"Drafted raw {dialect_label} query (Iteration {iteration}).", details={"sql": current_sql})
            except QueryCancelledError:
                raise
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
                _log_event("Coder", "retry", "Applied bounded SQL correction.", details={"sql_diff": diff_text,
                           "failed_sql": failed_sql_before_retry, "corrected_sql": current_sql})

            # Agent 3: Guardian (AST Lint, Injection Quarantine, RBAC Table Whitelist)
            _log_event("Guardian", "running", f"Auditing {dialect_label} AST, injection vectors, and RBAC table whitelists...")
            valid_tables = self.db.get_table_names()
            guardian_result: GuardianResult = self.guardian.audit(
                current_sql,
                valid_tables=valid_tables,
                authorized_tables=authorized_tables,
                username=username,
                allowed_columns=getattr(self.db, "allowed_columns", None),
            )

            if not guardian_result.is_valid:
                critique = dict(guardian_result.critique or {
                    "type": "AST_PARSER_FAILURE", "message": "Guardian returned no validation verdict."
                })
                critique["agent"] = "Guardian"
                if critique.get("type") in TERMINAL_CRITIQUE_TYPES:
                    return _terminal_failure("Guardian", current_sql, critique)
                _log_event(
                    "Guardian", "retry",
                    f"AST Policy Violation: {critique.get('message')}",
                    details={"critique": critique}
                )
                iteration += 1
                continue

            sanitized_sql = guardian_result.sanitized_sql
            limit_msg = (" [Defensive LIMIT injected]" if dialect_label == "PostgreSQL" else " [Defensive TOP injected]") if guardian_result.limit_injected else ""
            _log_event(
                "Guardian", "success",
                f"AST passed security firewall and RBAC authorization.{limit_msg}",
                details={"sanitized_sql": sanitized_sql, "issues": guardian_result.issues}
            )

            # Agent 4: Evaluator (Runtime Critic & Data Sanity)
            _log_event("Evaluator", "running", f"Executing {dialect_label} query in sandbox and evaluating domain sanity...")
            eval_result: EvaluationResult = self.critic.evaluate(
                question=question,
                sql=sanitized_sql,
                iteration=iteration,
                max_iterations=max_retries,
                user_session=user_session,
                authorized_tables=authorized_tables
            )

            if not eval_result.success:
                critique = dict(eval_result.critique or {
                    "type": "AST_PARSER_FAILURE", "message": "Evaluator returned no validation verdict."
                })
                critique["agent"] = "Evaluator"
                if critique.get("type") in TERMINAL_CRITIQUE_TYPES:
                    return _terminal_failure("Evaluator", sanitized_sql, critique)
                _log_event(
                    "Evaluator", "retry",
                    f"Evaluator triggered diagnostic retry: {critique.get('message')}",
                    details={"critique": critique}
                )
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
            executive_narrative="Unable to synthesize a verified T-SQL query within retry limits.",
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
