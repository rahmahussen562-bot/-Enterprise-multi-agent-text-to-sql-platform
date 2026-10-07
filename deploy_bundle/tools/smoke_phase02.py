"""Exercise the production ASGI entry point over local HTTP and WebSockets."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
if root.drive.upper() != "D:" or Path(sys.prefix).resolve() != root / ".venv":
    raise SystemExit("Use the D-drive virtual environment.")
runtime = root / ".runtime" / "api-smoke"
runtime.mkdir(parents=True, exist_ok=True)
for name, folder in {"TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp", "XDG_CACHE_HOME": "cache",
                     "PYTHONPYCACHEPREFIX": "pycache", "HF_HOME": "huggingface"}.items():
    path = root / ".runtime" / folder
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.chdir(root)
sys.path.insert(0, str(root))

if "--serve" in sys.argv:
    import uvicorn
    server = uvicorn.Server(uvicorn.Config("api.main:app", host="127.0.0.1", port=int(os.environ["SENTINEL_SMOKE_PORT"]),
                                           ws_max_size=16384, timeout_graceful_shutdown=20))
    async def serve():
        async def shutdown_signal():
            while not (runtime / "stop").exists():
                await asyncio.sleep(0.1)
            server.should_exit = True
        monitor = asyncio.create_task(shutdown_signal())
        try:
            await server.serve()
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
    asyncio.run(serve())
    raise SystemExit(0)

import httpx
from websockets.sync.client import connect
from core.auth import password_hash

identifier = "smoke_" + secrets.token_hex(8)
password = secrets.token_urlsafe(24)
accounts_file = runtime / "accounts.json"
accounts_file.write_text(json.dumps([{"user_id": identifier, "role": "sales_analyst", "password_hash": password_hash(password)}]), encoding="utf-8")
with socket.socket() as channel:
    channel.bind(("127.0.0.1", 0))
    port = channel.getsockname()[1]
environment = dict(os.environ, SENTINEL_SMOKE_PORT=str(port), SENTINEL_AUTH_FILE=str(accounts_file),
    SENTINEL_SESSION_KEY=secrets.token_urlsafe(48), SENTINEL_API_STATE=str(runtime / "jobs.sqlite"),
    SENTINEL_DEMO_MODE="1", SQLITE_PATH=str(root / "data" / "chinook.db"), MSSQL_TIMEOUT="1",
    OPENAI_API_KEY="", GEMINI_API_KEY="", ANTHROPIC_API_KEY="")
stop = runtime / "stop"
stop.unlink(missing_ok=True)
report = {}
with (runtime / "server.log").open("w", encoding="utf-8") as log:
    process = subprocess.Popen([sys.executable, "-B", __file__, "--serve"], cwd=root, env=environment,
        stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
            deadline = time.monotonic() + 20
            while True:
                try:
                    response = client.get("/openapi.json")
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Uvicorn startup failed; inspect the D-drive smoke log.")
                    time.sleep(0.1)
            report["openapi_status"] = response.status_code
            response = client.post("/api/v1/auth/login", json={"user_id": identifier, "password": password})
            response.raise_for_status()
            token = response.json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            classify = client.post("/api/v1/query/classify", headers=headers, json={"question": "List customers in Brazil"})
            classify.raise_for_status()
            report["classification"] = classify.json()["intent"]
            execution = client.post("/api/v1/query/execute", headers=headers, json={"question": "List customers in Brazil"})
            execution.raise_for_status()
            report["execute_status"] = execution.status_code
            report["row_count"] = execution.json()["output"]["row_count"]
            with connect(f"ws://127.0.0.1:{port}/api/v1/query/stream", open_timeout=5) as websocket:
                websocket.send(json.dumps({"token": token}))
                assert json.loads(websocket.recv(timeout=5))["type"] == "ready"
                websocket.send(json.dumps({"action": "start", "question": "List customers in Brazil"}))
                sequences = []
                row_count = 0
                while True:
                    frame = json.loads(websocket.recv(timeout=15))
                    if frame["type"] in {"event", "rows"}:
                        sequences.append(frame["sequence"])
                    if frame["type"] == "rows":
                        row_count += len(frame["rows"])
                    if frame["type"] == "result":
                        assert frame["status"] == "completed"
                        assert row_count == frame["output"]["row_count"]
                        break
                assert sequences == list(range(1, len(sequences) + 1))
                report["websocket_frames_ordered"] = True
                report["websocket_row_count"] = row_count
    finally:
        stop.write_text("stop", encoding="ascii")
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError("Uvicorn smoke process failed to shut down gracefully.")
report["shutdown_exit_code"] = process.returncode
assert process.returncode == 0
(root / "docs" / "PHASE02_LIVE_SMOKE.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
