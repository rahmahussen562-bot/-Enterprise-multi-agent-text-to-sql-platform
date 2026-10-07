"""Authenticated REST and owner-scoped sequenced WebSocket transport."""
import asyncio
import json
import time
from uuid import UUID
import anyio
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.responses import JSONResponse
from api.auth import APIError, require_session
from api.schemas import (
    AuditResponse, ClassifyResponse, JobResponse, LoginRequest, LoginResponse,
    QueryRequest, SessionClaims, StreamCommand, ErrorResponse, HealthResponse, SchemaResponse, SchemaTable, SchemaColumn,
)

router = APIRouter(prefix="/api/v1", responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 408, 409, 413, 422, 429, 500, 503)
})


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = request.app.state.login_attempts
    # Bounded local IP budget; edge deployments add WAF/IP and identity limits.
    bucket = [stamp for stamp in attempts.get(host, []) if stamp > now - 60]
    if len(bucket) >= 20:
        raise APIError(429, "LOGIN_RATE_LIMIT", "Login attempt budget exceeded.")
    if len(attempts) >= 1024 and host not in attempts:
        attempts.clear()
    attempts[host] = bucket + [now]
    token, claims = await request.app.state.manager.io(
        request.app.state.authority.login, body.user_id, body.password.get_secret_value())
    return LoginResponse(access_token=token, session=claims)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request):
    manager = request.app.state.manager
    return HealthResponse(status="ready" if manager.accepting else "draining", ast_validation="ready",
                          active_queries=len(manager.jobs), worker_capacity=manager.settings.max_workers,
                          checked_at=time.time())


@router.get("/schema", response_model=SchemaResponse)
async def schema(request: Request, claims: SessionClaims = Depends(require_session)):
    manager = request.app.state.manager
    if not manager.accepting or len(manager.jobs) + manager.classifying >= manager.settings.max_workers:
        raise APIError(503, "WORKLOAD_LIMIT", "Query workers are at capacity.")
    from core.cancellation import CancellationToken, cancellation_context
    cancellation = CancellationToken()
    def inspect():
        with cancellation_context(cancellation):
            return inspect_sync()
    def inspect_sync():
        database = manager.factory(claims).db
        names = sorted(set(database.get_table_names(authorized_tables=claims.allowed_tables)))
        tables = []
        for name in names:
            columns = database.get_table_columns_info(name)
            if columns:
                tables.append(SchemaTable(name=name, columns=[SchemaColumn(name=column["name"],
                    data_type=column["type"], nullable=not column.get("notnull", False),
                    primary_key=bool(column.get("pk", False))) for column in columns]))
        visible = {table.name for table in tables}
        relations = [relation for relation in database.get_foreign_keys(authorized_tables=list(visible))
                     if relation["from_table"] in visible and relation["to_table"] in visible]
        return SchemaResponse(dialect=getattr(database, "dialect", "tsql"), role=claims.role, tables=tables, relationships=relations)
    manager.classifying += 1
    worker = asyncio.create_task(anyio.to_thread.run_sync(inspect, limiter=manager.worker_limiter))
    try:
        deadline = time.monotonic() + manager.settings.job_timeout_sec
        while not worker.done():
            if await request.is_disconnected() or time.monotonic() >= deadline:
                await anyio.to_thread.run_sync(cancellation.cancel, limiter=manager.control_limiter)
                raise APIError(408, "SCHEMA_CANCELLED", "Schema inspection cancelled.")
            await asyncio.sleep(0.025)
        result = await asyncio.shield(worker)
        await manager.io(manager.authority.verify, request.headers["authorization"].split(" ", 1)[1])
        return result
    finally:
        if not worker.done():
            with anyio.CancelScope(shield=True):
                await asyncio.shield(anyio.to_thread.run_sync(cancellation.cancel, limiter=manager.control_limiter))
                await asyncio.gather(asyncio.shield(worker), return_exceptions=True)
        manager.classifying -= 1


@router.post("/query/classify", response_model=ClassifyResponse)
async def classify(body: QueryRequest, request: Request, claims: SessionClaims = Depends(require_session)):
    manager = request.app.state.manager
    if not manager.accepting or len(manager.jobs) + manager.classifying >= manager.settings.max_workers:
        raise APIError(503, "WORKLOAD_LIMIT", "Query workers are at capacity.")

    def classify_sync():
        from agents.intent_router import IntentRouter
        from core.fincore import ROLE_COLUMNS
        if claims.role in ROLE_COLUMNS:
            from agents.fincore import FinCoreIntentRouter
            classifier = FinCoreIntentRouter()
        else:
            classifier = IntentRouter()
        result = classifier.classify(body.question, user_session=manager.authority.to_engine_session(claims))
        return ClassifyResponse(intent=result.intent.value, confidence=float(result.confidence),
                                response=result.response_message, sample_queries=result.sample_queries)

    manager.classifying += 1
    try:
        return await anyio.to_thread.run_sync(classify_sync, limiter=manager.worker_limiter)
    finally:
        manager.classifying -= 1


def _error_status(code):
    if code in {"RBAC_AUTHORIZATION_VIOLATION", "HALLUCINATION_UNAUTHORIZED_TABLE", "SECURITY_ATTACK"}:
        return 403
    if code in {"QUERY_DEADLINE", "EXECUTION_TIMEOUT"}:
        return 408
    if code in {"QUERY_CANCELLED", "CLIENT_DISCONNECTED", "SERVICE_SHUTDOWN"}:
        return 409
    if code in {"WORKLOAD_LIMIT", "DATABASE_UNAVAILABLE", "AUTH_SERVICE_UNAVAILABLE"}:
        return 503
    if code in {"RESULT_LIMIT", "TELEMETRY_LIMIT"}:
        return 413
    if code in {"ENGINE_FAILURE", "DRIVER_CANCELLATION_FAILED", "SERIALIZATION_FAILED"}:
        return 500
    return 422


@router.post("/query/execute", response_model=JobResponse)
async def execute(body: QueryRequest, request: Request, claims: SessionClaims = Depends(require_session)):
    manager = request.app.state.manager
    job_id, job = await manager.submit(body.question, claims)
    completed = False
    try:
        next_check = 0.0
        while not job.task.done():
            if await request.is_disconnected():
                await manager.cancel(job_id, claims, "CLIENT_DISCONNECTED")
                await manager.wait(job)
                raise APIError(499, "CLIENT_DISCONNECTED", "Client disconnected; query cleanup completed.", job_id=job_id)
            if time.monotonic() >= next_check:
                await manager.io(manager.authority.verify, request.headers["authorization"].split(" ", 1)[1])
                next_check = time.monotonic() + 0.5
            await asyncio.sleep(0.025)
        await manager.wait(job)
        await manager.io(manager.authority.verify, request.headers["authorization"].split(" ", 1)[1])
        response = await manager.io(manager.store.get, job_id, claims)
        completed = True
        if response["error"]:
            error = response["error"]
            raise APIError(_error_status(error["error_code"]), error["error_code"], error["detail"],
                           error["ast_trace"], job_id)
        return response
    finally:
        if not completed and job_id in manager.jobs:
            # Shield the control path so cancelling an await never abandons a
            # native query. The worker remains registered until cleanup returns.
            with anyio.CancelScope(shield=True):
                await asyncio.shield(manager.cancel(job_id, claims, "CLIENT_DISCONNECTED"))
                await manager.wait(job)


@router.get("/query/jobs/{job_id}", response_model=JobResponse)
async def job_status(job_id: UUID, request: Request, claims: SessionClaims = Depends(require_session)):
    manager = request.app.state.manager
    return await manager.io(manager.store.get, str(job_id), claims)


@router.post("/query/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: UUID, request: Request, claims: SessionClaims = Depends(require_session)):
    manager = request.app.state.manager
    await manager.cancel(str(job_id), claims)
    return await manager.io(manager.store.get, str(job_id), claims)


@router.get("/telemetry/audit-logs", response_model=AuditResponse)
async def audit_logs(request: Request, job_id: UUID, after_sequence: int = Query(0, ge=0),
                     limit: int = Query(100, ge=1, le=100), claims: SessionClaims = Depends(require_session)):
    manager = request.app.state.manager
    job = await manager.io(manager.store.get, str(job_id), claims)
    events = await manager.io(manager.store.events, str(job_id), claims, after_sequence, limit)
    return AuditResponse(job_id=str(job_id), status=job["status"], events=events,
                         next_sequence=events[-1]["sequence"] if events else after_sequence)


async def _ws_json(websocket, timeout=None):
    frame = await asyncio.wait_for(websocket.receive(), timeout) if timeout else await websocket.receive()
    if frame["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(frame.get("code", 1000))
    text = frame.get("text")
    if text is None:
        raise APIError(422, "VALIDATION_ERROR", "WebSocket commands require JSON text frames.")
    if len(text.encode()) > 8192:
        raise APIError(413, "PAYLOAD_LIMIT", "WebSocket command exceeds its byte budget.")
    try:
        return json.loads(text)
    except ValueError:
        raise APIError(422, "VALIDATION_ERROR", "Invalid JSON command.")


@router.websocket("/query/stream")
async def stream(websocket: WebSocket):
    manager = websocket.app.state.manager
    authority = websocket.app.state.authority
    active_id = None
    started_here = False
    receiver = None
    accepted = False
    try:
        origin = websocket.headers.get("origin")
        if origin and origin not in manager.settings.allowed_origins:
            raise APIError(403, "ORIGIN_REJECTED", "WebSocket origin is not permitted.")
        authorization = websocket.headers.get("authorization", "")
        if authorization:
            if not authorization.lower().startswith("bearer "):
                raise APIError(401, "AUTHENTICATION_REQUIRED", "A bearer session token is required.")
            token = authorization.split(" ", 1)[1]
            claims = await manager.io(authority.verify, token)
            await websocket.accept()
            accepted = True
        else:
            await websocket.accept()
            accepted = True
            credentials = await _ws_json(websocket, timeout=5)
            if not isinstance(credentials, dict) or set(credentials) != {"token"} or not isinstance(credentials["token"], str):
                raise APIError(401, "AUTHENTICATION_REQUIRED", "Send a token in the first WebSocket frame.")
            token = credentials["token"]
            claims = await manager.io(authority.verify, token)
        await websocket.send_json({"type": "ready"})
        sequence = 0
        next_check = 0.0
        receiver = asyncio.create_task(_ws_json(websocket))
        while True:
            if time.monotonic() >= next_check or int(time.time()) >= claims.expires_at:
                claims = await manager.io(authority.verify, token)
                next_check = time.monotonic() + 0.5
            done, _ = await asyncio.wait({receiver}, timeout=0.05)
            if done:
                payload = receiver.result()
                try:
                    command = StreamCommand.model_validate(payload)
                except ValidationError:
                    raise APIError(422, "VALIDATION_ERROR", "Invalid stream command.")
                if command.action == "start":
                    if active_id is not None or not command.question or not command.question.strip():
                        raise APIError(409, "STREAM_STATE", "Start requires a question and an idle stream.")
                    active_id, _ = await manager.submit(command.question.strip(), claims)
                    started_here = True
                    sequence = 0
                    await websocket.send_json({"type": "job", "job_id": active_id})
                elif command.action == "subscribe":
                    if active_id is not None or command.job_id is None:
                        raise APIError(409, "STREAM_STATE", "Subscribe requires a job ID and an idle stream.")
                    await manager.io(manager.store.get, command.job_id, claims)
                    active_id = command.job_id
                    sequence = command.after_sequence
                    started_here = False
                else:
                    target = command.job_id or active_id
                    if target is None:
                        raise APIError(422, "STREAM_STATE", "Cancel requires a job ID.")
                    await manager.cancel(target, claims)
                receiver = asyncio.create_task(_ws_json(websocket))
            if active_id is not None:
                events = await manager.io(manager.store.events, active_id, claims, sequence, 100)
                for event in events:
                    await websocket.send_json({"type": "event", "job_id": active_id, **event})
                    sequence = event["sequence"]
                job = await manager.io(manager.store.get, active_id, claims)
                if job["status"] != "running" and len(events) < 100:
                    await manager.io(authority.verify, token)
                    output = job.get("output")
                    if output is not None:
                        # Authorized row batches belong to the result channel;
                        # financial/customer cells never enter ordinary logs.
                        rows = output["rows"]
                        for offset in range(0, len(rows), 100):
                            await manager.io(authority.verify, token)
                            await websocket.send_json({"type": "rows", "job_id": active_id,
                                "sequence": sequence + offset // 100 + 1, "offset": offset,
                                "columns": output["columns"], "rows": rows[offset:offset + 100]})
                    # Results (including authorized rows) are owner-filtered,
                    # separate from redacted, durably sequenced stage records.
                    await websocket.send_json({"type": "result", **job})
                    active_id = None
                    started_here = False
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except (APIError, asyncio.TimeoutError) as error:
        if isinstance(error, asyncio.TimeoutError):
            error = APIError(401, "AUTHENTICATION_REQUIRED", "WebSocket authentication timed out.")
        body = {"detail": error.detail, "error_code": error.code, "ast_trace": [], "job_id": error.job_id}
        if not accepted:
            await websocket.send_denial_response(JSONResponse(body, status_code=error.status))
        else:
            await websocket.send_json({"type": "error", **body})
            await websocket.close(code=1008)
    finally:
        if receiver is not None:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
        if active_id is not None and started_here and active_id in manager.jobs:
            with anyio.CancelScope(shield=True):
                job = manager.jobs[active_id]
                await asyncio.shield(manager.cancel(active_id, job.claims, "CLIENT_DISCONNECTED"))
                await manager.wait(job)
