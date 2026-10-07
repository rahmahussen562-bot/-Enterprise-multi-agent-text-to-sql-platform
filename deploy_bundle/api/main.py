"""ASGI entry point: uvicorn api.main:app --workers 1."""
from contextlib import asynccontextmanager
from pathlib import Path
import json
import os
import anyio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from api.auth import APIError, SessionAuthority
from api.routes import router
from api.runtime import JobManager
from api.settings import APISettings


class TransportLimits:
    def __init__(self, app, max_bytes=16384):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = 0
        buffered = []
        sent = False

        async def bounded_receive():
            if buffered:
                return buffered.pop(0)
            return await receive()

        async def private_send(message):
            nonlocal sent
            if message["type"] == "http.response.start":
                sent = True
                headers = list(message.get("headers", []))
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")])
                message = {**message, "headers": headers}
            await send(message)

        # Enforce the bound before body parsing, buffering at most max_bytes.
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            length += len(message.get("body", b""))
            if length > self.max_bytes:
                response = JSONResponse({"detail": "Request exceeds its byte budget.",
                    "error_code": "PAYLOAD_LIMIT", "ast_trace": [], "job_id": None}, status_code=413)
                return await response(scope, receive, private_send)
            buffered.append(message)
            if not message.get("more_body", False):
                break
        try:
            await self.app(scope, bounded_receive, private_send)
        except APIError as error:
            if sent:
                raise
            response = JSONResponse({"detail": error.detail, "error_code": error.code, "ast_trace": [], "job_id": None}, status_code=error.status)
            await response(scope, receive, private_send)


def create_app(settings=None, controller_factory=None):
    @asynccontextmanager
    async def lifespan(application):
        if os.name == "nt" and Path.cwd().drive.upper() != "D:":
            raise RuntimeError("Start the API from its D: workspace.")
        configuration = settings or APISettings.from_environment()
        from core.sql_validation import parse_single_query
        parse_single_query("SELECT 1")
        authority = await anyio.to_thread.run_sync(SessionAuthority, configuration)
        manager = JobManager(configuration, authority, controller_factory)
        application.state.authority = authority
        application.state.manager = manager
        application.state.login_attempts = {}
        application.state.settings = configuration
        try:
            yield
        finally:
            await manager.close()

    application = FastAPI(title="SentinelSQL", version="2.0.0", lifespan=lifespan)
    origins = settings.allowed_origins if settings is not None else tuple(filter(None,
        os.getenv("SENTINEL_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")))
    application.add_middleware(CORSMiddleware, allow_origins=list(origins),
                               allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
    application.add_middleware(TransportLimits)
    application.include_router(router)

    @application.exception_handler(APIError)
    async def api_error(request, error):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
        return JSONResponse({"detail": error.detail, "error_code": error.code,
            "ast_trace": error.ast_trace, "job_id": error.job_id}, status_code=error.status, headers=headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"detail": "Request validation failed.", "error_code": "VALIDATION_ERROR",
                             "ast_trace": [], "job_id": None}, status_code=422)

    @application.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"detail": "Request could not be served.", "error_code": "HTTP_ERROR",
                             "ast_trace": [], "job_id": None}, status_code=error.status_code)

    @application.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse({"detail": "Service processing failed.", "error_code": "INTERNAL_ERROR",
                             "ast_trace": [], "job_id": None}, status_code=500)

    return application


app = create_app()
