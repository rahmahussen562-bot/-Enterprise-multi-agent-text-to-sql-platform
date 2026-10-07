"""Idempotent private bootstrap for synthetic FinCore operators.

Run with the project virtual environment. Existing keys/accounts are preserved.
Generated passwords are stored only in the ignored, access-restricted directory.
No credential, hash, session token or key is printed.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".runtime" / "api-private"
ROLES = ("branch_analyst", "compliance_officer", "fraud_investigator")


def protect(path):
    if os.name == "nt":
        identity = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
        grants = [identity + (":(OI)(CI)F" if path.is_dir() else ":F"),
                  "*S-1-5-18" + (":(OI)(CI)F" if path.is_dir() else ":F")]
        result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", *grants],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Private file permissions could not be restricted.")
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def private_json(path, value):
    temporary = path.with_suffix(path.suffix + ".new")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            protect(temporary)
            json.dump(value, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        protect(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    if os.name == "nt" and (ROOT.drive.upper() != "D:" or Path(sys.prefix).resolve() != ROOT / ".venv"):
        raise SystemExit("Use the isolated D: project virtual environment.")
    sys.path.insert(0, str(ROOT))
    from core.auth import load_accounts, password_hash, verify_password
    from api.auth import SessionAuthority
    from api.main import create_app
    from api.settings import APISettings
    from fastapi.testclient import TestClient

    ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--quiet", str(PRIVATE / "session.key")])
    if ignored.returncode:
        raise SystemExit("Private directory must be ignored before provisioning.")
    PRIVATE.mkdir(parents=True, exist_ok=True)
    protect(PRIVATE)
    key = PRIVATE / "session.key"
    created_key = not key.exists()
    if created_key:
        with key.open("xb") as handle:
            protect(key)
            handle.write(secrets.token_bytes(32))
    protect(key)
    if len(key.read_bytes()) != 32:
        raise SystemExit("Existing session key must contain exactly 32 bytes; it was preserved.")
    accounts_file = PRIVATE / "accounts.json"
    records = list(load_accounts(accounts_file).values()) if accounts_file.exists() else []
    credential_file = PRIVATE / "operator-credentials.json"
    credentials = json.loads(credential_file.read_text(encoding="utf-8")) if credential_file.exists() else []
    created = []
    for role in ROLES:
        user_id = "synthetic_" + role
        existing = next((record for record in records if record["user_id"] == user_id), None)
        if existing is not None:
            if existing["role"] != role:
                raise SystemExit("An operator identity has a conflicting server role; preserved accounts.")
            known = next((value for value in credentials if value["user_id"] == user_id), None)
            if known is None or not verify_password(known["password"], existing["password_hash"]):
                raise SystemExit("Existing operator credentials cannot be verified; no password reset performed.")
            continue
        password = secrets.token_urlsafe(32)
        records.append({"user_id": user_id, "role": role, "password_hash": password_hash(password)})
        credentials.append({"user_id": user_id, "role": role, "password": password})
        created.append(role)
    private_json(credential_file, credentials)
    private_json(accounts_file, records)
    load_accounts(accounts_file)

    # Explicit demo/mock mode uses the same signed authority; it grants no bypass.
    environment = {"SENTINEL_DEMO_MODE": "1", "SENTINEL_SESSION_KEY_FILE": str(key),
                   "SENTINEL_AUTH_FILE": str(accounts_file),
                   "SENTINEL_API_STATE": str(PRIVATE / "bootstrap-verification.sqlite")}
    with patch.dict(os.environ, environment):
        os.environ.pop("SENTINEL_SESSION_KEY", None)
        settings = APISettings.from_environment()
        assert settings.signing_key == key.read_bytes()
        authority = SessionAuthority(settings)
        role_tables = []
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/health").status_code == 200
            for role in ROLES:
                user = next(value for value in credentials if value["role"] == role)
                result = client.post("/api/v1/auth/login", json={"user_id": user["user_id"], "password": user["password"]})
                assert result.status_code == 200
                token = result.json()["access_token"]
                claims = authority.verify(token)
                assert claims.role == role
                assert set(claims.model_dump()) == {"user_id", "role", "allowed_tables", "issued_at", "expires_at"}
                role_tables.append(set(claims.allowed_tables))
                protected = "/api/v1/query/classify"
                authenticated = client.post(protected, json={"question": "Help"}, headers={"Authorization": "Bearer " + token})
                if authenticated.status_code != 200:
                    raise RuntimeError("Protected verification status=" + str(authenticated.status_code) +
                                       " code=" + str(authenticated.json().get("error_code")))
                pieces = token.split(".")
                pieces[-1] = ("A" if pieces[-1][0] != "A" else "B") + pieces[-1][1:]
                invalid = client.post(protected, json={"question": "Help"}, headers={"Authorization": "Bearer " + ".".join(pieces)})
                assert invalid.status_code == 401
                assert key.read_bytes().hex() not in invalid.text
                assert user["password"] not in invalid.text
        assert all(not left.intersection(right) for i, left in enumerate(role_tables) for right in role_tables[i+1:])
    report = {"private_directory": str(PRIVATE), "session_key_bytes": 32, "created_key": created_key,
              "created_operator_roles": created, "verified_roles": list(ROLES),
              "password_storage": "PBKDF2-SHA256, random salts, 310000 iterations",
              "demo_authentication_verified": True, "tampered_tokens_rejected": True,
              "role_scopes_disjoint": True, "credential_values_printed": False,
              "verification_scope": "local authentication and protected classification; no production database deployment"}
    (ROOT / "docs" / "PRODUCTION_BOOTSTRAP_VERIFICATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
