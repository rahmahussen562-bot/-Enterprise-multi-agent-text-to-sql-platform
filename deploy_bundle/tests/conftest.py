"""Keep recovered historical tests deterministic, offline, and entirely on D:."""
import gzip
import json
import io
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

# Set before collection/importing provider configuration; dotenv does not override these.
for provider_key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[provider_key] = ""
# The recovered integration fixtures intentionally exercise the offline demo.
os.environ["SENTINEL_DEMO_MODE"] = "1"


@pytest.fixture(scope="session", autouse=True)
def legacy_offline_fixture():
    root = Path(__file__).resolve().parents[1]
    if os.name == "nt" and root.drive.upper() != "D:":
        raise RuntimeError("Phase 0/1 verification must run in the D: workspace.")
    fixture = root / "tests" / "fixtures" / "chinook.sql.gz"
    database = root / ".runtime" / "fixtures" / "pytest_chinook.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    # Reconstruct in memory so each baseline seed starts from exactly the vendored data.
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(gzip.decompress(fixture.read_bytes()).decode("utf-8"))
        payload = connection.serialize()
    finally:
        connection.close()

    def offline_download(*args, **kwargs):
        return io.BytesIO(payload)

    import pyodbc
    from core.auth import password_hash
    # Each process generates fresh passwords; published demo credentials are gone.
    from tests._credentials import LEGACY_PASSWORDS
    accounts = [{"user_id": user_id, "role": user_id, "password_hash": password_hash(password)}
                for user_id, password in LEGACY_PASSWORDS.items()]
    account_file = root / ".runtime" / "test_auth" / "accounts.json"
    account_file.parent.mkdir(parents=True, exist_ok=True)
    account_file.write_text(json.dumps(accounts), encoding="utf-8")
    with patch("utils.db_seeder.urllib.request.urlopen", side_effect=offline_download), patch(
        "pyodbc.connect", side_effect=pyodbc.Error("Unit tests use the explicit SQLite fixture")
    ), patch.dict(os.environ, {"SENTINEL_AUTH_FILE": str(account_file)}):
        yield

