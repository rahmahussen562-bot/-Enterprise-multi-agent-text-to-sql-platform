"""Bounded workers, durable telemetry, native cancellation and isolated engines."""
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import difflib
import hashlib
import json
import math
import time
from uuid import uuid4
import anyio
import pandas as pd
from api.auth import APIError
from api.schemas import QueryOutput
from api.settings import ROOT
from api.store import JobStore
from core.cancellation import CancellationToken, QueryCancelledError, cancellation_context


def controller_factory(claims):
    from core.fincore import ROLE_COLUMNS
    if claims.role in ROLE_COLUMNS:
        from agents.fincore import FinCoreController
        from core.auth import session_for_role
        from core.postgres import PostgresConfig, PostgresSyncBridge
        session = session_for_role(claims.user_id, claims.role)
        return FinCoreController(PostgresSyncBridge(PostgresConfig.for_session(session)), session.role)
    from agents.orchestrator import CentralController
    from core.config import SystemConfig
    from core.database import DatabaseEngine
    config = SystemConfig()
    namespace = hashlib.sha256((claims.user_id + ":" + claims.role + ":" + ",".join(claims.allowed_tables)).encode()).hexdigest()[:32]
    config.vector.persist_directory = str(ROOT / ".runtime" / "api-private" / "retrieval" / namespace)
    database = DatabaseEngine(config.db)
    if not database.test_connection()[0]:
        raise APIError(503, "DATABASE_UNAVAILABLE", "The configured database is unavailable.")
    return CentralController(db_engine=database, config=config)


def redact_sql(sql, dialect="tsql"):
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.errors import ErrorLevel
        statements = sqlglot.parse(sql[:8192], read=dialect, error_level=ErrorLevel.RAISE)
        for statement in statements:
            if statement is None:
                continue
            for node in statement.walk():
                node.pop_comments()
            for literal in list(statement.find_all(exp.Literal)):
                literal.replace(exp.Literal.string("[REDACTED]") if literal.is_string else exp.Literal.number(0))
        return "; ".join(statement.sql(dialect=dialect) for statement in statements if statement is not None)
    except Exception:
        return "[SQL withheld: unparseable]"


def safe_event(event, starts, dialect="tsql"):
    now = time.monotonic()
    duration = None
    if event.status == "running":
        starts[event.agent_name] = now
    elif event.agent_name in starts:
        duration = max(0.0, (now - starts.pop(event.agent_name)) * 1000)
    details = {}
    original = event.details or {}
    for key in ("sql", "sanitized_sql"):
        if key in original:
            details[key] = redact_sql(str(original[key])[:65536], dialect)
    if "sql_diff" in original:
        old = redact_sql(original.get("failed_sql", ""), dialect)
        new = redact_sql(original.get("corrected_sql", ""), dialect)
        details["sql_diff"] = "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(),
            fromfile="failed.sql", tofile="corrected.sql", lineterm=""))
    critique = original.get("critique") or {}
    if critique.get("type"):
        details["verdict"] = str(critique["type"])[:128]
    if event.agent_name == "Guardian" and event.status == "success":
        details["ast_verdict"] = "PASS"
    if event.agent_name == "Evaluator" and event.status == "success":
        details["schema_grounding"] = "PASS"
    if isinstance(original.get("rows"), int):
        details["row_count"] = original["rows"]
    # Grounded customer values and exception payloads never enter ordinary logs.
    message = (f"{event.agent_name} {event.status}." if event.status in {"failed", "retry"} else event.message[:1000])
    return {"kind": "sql_diff" if "sql_diff" in details else "stage", "agent": event.agent_name, "status": event.status,
            "message": message, "timestamp": time.time(), "duration_ms": duration, "details": details}


def _scalar(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _scalar(value.item())
    raise APIError(500, "SERIALIZATION_FAILED", "A result cell has an unsupported type.")


def output_for(result, settings):
    if len(result.df) > settings.max_result_rows:
        raise APIError(413, "RESULT_LIMIT", "Query exceeded the API row budget.")
    output = QueryOutput(final_sql=result.final_sql, columns=[str(column) for column in result.df.columns],
        rows=[[_scalar(cell) for cell in row] for row in result.df.itertuples(index=False, name=None)],
        row_count=len(result.df), executive_narrative=result.executive_narrative,
        execution_time_ms=float(result.execution_time_ms), intent=str(result.intent),
        retries=[{"iteration": retry.iteration, "trigger_agent": retry.trigger_agent,
                  "critique_type": retry.critique_type, "sql_diff": "\n".join(difflib.unified_diff(
                      redact_sql(retry.failed_sql).splitlines(), redact_sql(retry.corrected_sql).splitlines(),
                      fromfile="failed.sql", tofile="corrected.sql", lineterm=""))} for retry in result.retry_history])
    if len(output.model_dump_json().encode()) > settings.max_response_bytes:
        raise APIError(413, "RESULT_LIMIT", "Query exceeded the API response budget.")
    return output.model_dump()


@dataclass
class RunningJob:
    claims: object
    token: CancellationToken
    task: asyncio.Task | None = None
    deadline_task: asyncio.Task | None = None
    reason: str = "QUERY_CANCELLED"
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class JobManager:
    def __init__(self, settings, authority, factory=None):
        self.settings = settings
        self.authority = authority
        self.factory = factory or controller_factory
        # Local durable jobs have one ASGI owner; fail startup rather than let
        # another process mark this process's live jobs as interrupted.
        settings.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._lease = open(settings.state_file.with_suffix(".lock"), "a+b")
        self._lease.seek(0)
        if self._lease.read(1) == b"":
            self._lease.write(b"1")
            self._lease.flush()
        self._lease.seek(0)
        try:
            import os
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.store = JobStore(settings.state_file, settings.max_events)
        except BaseException:
            self._lease.close()
            raise
        self.jobs = {}
        self.classifying = 0
        self.accepting = True
        self.worker_limiter = anyio.CapacityLimiter(settings.max_workers)
        self.io_limiter = anyio.CapacityLimiter(8)
        self.control_limiter = anyio.CapacityLimiter(2)

    async def io(self, function, *args):
        return await anyio.to_thread.run_sync(function, *args, limiter=self.io_limiter)

    async def submit(self, question, claims):
        # No unbounded queue: admit at most max_workers jobs before spawning.
        if not self.accepting or len(self.jobs) + self.classifying >= self.settings.max_workers:
            raise APIError(503, "WORKLOAD_LIMIT", "Query workers are at capacity.")
        job_id = str(uuid4())
        job = RunningJob(claims, CancellationToken())
        self.jobs[job_id] = job
        try:
            await self.io(self.store.create, job_id, claims)
            job.task = asyncio.create_task(self._run(job_id, question, job))
            job.deadline_task = asyncio.create_task(self._deadline(job_id))
        except BaseException:
            self.jobs.pop(job_id, None)
            job.finished.set()
            raise
        return job_id, job

    async def _deadline(self, job_id):
        await asyncio.sleep(self.settings.job_timeout_sec)
        if job_id in self.jobs:
            await self.cancel(job_id, self.jobs[job_id].claims, "QUERY_DEADLINE")

    def _work(self, job_id, question, job):
        starts = {}
        status = "failed"
        response = None
        try:
            with cancellation_context(job.token):
                self.store.append(job_id, {"kind": "job_started", "agent": "API", "status": "running",
                    "message": "Query admitted.", "timestamp": time.time(), "duration_ms": None, "details": {}})
                controller = self.factory(job.claims)
                result = controller.execute_pipeline(question, user_session=self.authority.to_engine_session(job.claims),
                    on_event=lambda event: self.store.append(job_id, safe_event(event, starts, getattr(getattr(controller,"db",None), "dialect", "tsql"))))
                job.token.check()
                if not result.success:
                    code = "QUERY_REJECTED"
                    for event in reversed(result.events):
                        critique = (event.details or {}).get("critique") or {}
                        if critique.get("type"):
                            code = critique["type"]
                            break
                    if result.intent == "SECURITY_ATTACK":
                        code = "SECURITY_ATTACK"
                    elif result.intent == "OUT_OF_SCOPE":
                        code = "OUT_OF_SCOPE"
                    raise APIError(422, code, "The query did not pass deterministic validation.")
                response = output_for(result, self.settings)
                status = "completed"
        except QueryCancelledError:
            status = "cancelled"
            response = {"detail": "Query cancelled and worker cleanup completed.", "error_code": job.reason,
                        "ast_trace": [], "job_id": job_id}
            if job.token.failures:
                response["error_code"] = "DRIVER_CANCELLATION_FAILED"
                response["detail"] = "Driver cancellation failed; worker cleanup completed."
        except APIError as error:
            response = {"detail": error.detail, "error_code": error.code, "ast_trace": [], "job_id": job_id}
        except Exception:
            response = {"detail": "Query processing failed.", "error_code": "ENGINE_FAILURE", "ast_trace": [], "job_id": job_id}
        if status != "completed":
            response["ast_trace"] = self.store.trace(job_id, job.claims)[-32:]
        self.store.append(job_id, {"kind": "job_finished", "agent": "API", "status": status,
            "message": "Query worker completed cleanup.", "timestamp": time.time(), "duration_ms": None,
            "details": {"error_code": response.get("error_code"), "row_count": response.get("row_count", 0)}}, terminal=True)
        self.store.finish(job_id, status, response)

    async def _run(self, job_id, question, job):
        try:
            await anyio.to_thread.run_sync(self._work, job_id, question, job,
                                           abandon_on_cancel=False, limiter=self.worker_limiter)
        finally:
            if job.deadline_task is not None:
                job.deadline_task.cancel()
            self.jobs.pop(job_id, None)
            job.finished.set()

    async def cancel(self, job_id, claims, reason="QUERY_CANCELLED"):
        job = self.jobs.get(job_id)
        if job is not None:
            # An unavailable audit store must never prevent native cleanup.
            # Active admission already holds the authenticated owner locally.
            if (job.claims.user_id, job.claims.role) != (claims.user_id, claims.role):
                raise APIError(404, "JOB_NOT_FOUND", "Query job was not found.")
            if not job.token.cancelled:
                job.reason = reason
            await anyio.to_thread.run_sync(job.token.cancel, limiter=self.control_limiter)
        else:
            await self.io(self.store.get, job_id, claims)

    async def wait(self, job):
        await asyncio.shield(job.task)

    async def close(self):
        self.accepting = False
        jobs = list(self.jobs.items())
        await asyncio.gather(*(self.cancel(job_id, job.claims, "SERVICE_SHUTDOWN") for job_id, job in jobs))
        if jobs:
            await asyncio.wait_for(asyncio.gather(*(job.finished.wait() for _, job in jobs)),
                                   timeout=self.settings.shutdown_timeout_sec)
        self._lease.close()
