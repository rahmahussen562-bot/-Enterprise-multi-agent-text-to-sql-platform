"""Provision private local session keys and hashed accounts; no default passwords."""
import getpass
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
if root.drive.upper() != "D:" or Path(sys.prefix).resolve() != root / ".venv":
    raise SystemExit("Use the D: project virtual environment.")
sys.path.insert(0, str(root))
from core.auth import password_hash
from core.fincore import ROLE_COLUMNS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--roles', nargs='+', choices=['sales_analyst','inventory_lead',*ROLE_COLUMNS],
                    default=['sales_analyst','inventory_lead'], help='Personas to provision on first setup.')
selected_roles = parser.parse_args().roles

private = root / ".runtime" / "api-private"
private.mkdir(parents=True, exist_ok=True)
if os.name == "nt":
    identity = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["icacls", str(private), "/inheritance:r", "/grant:r",
        identity + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], check=True)
else:
    private.chmod(0o700)
key = private / "session.key"
if not key.exists():
    key.write_bytes(secrets.token_bytes(32))
    key.chmod(0o600)
accounts_file = private / "accounts.json"
if accounts_file.exists():
    raise SystemExit("Account directory already exists; update it explicitly rather than overwriting users.")
accounts = []
for role in selected_roles:
    user_id = input(f"Corporate ID for {role} (default {role}): ").strip().lower() or role
    if not user_id or len(user_id) > 128 or any(account["user_id"] == user_id for account in accounts):
        raise SystemExit("Account IDs must be distinct and at most 128 characters.")
    password = getpass.getpass(f"New password for {user_id} (at least 12 characters): ")
    if len(password) < 12 or len(password) > 1024 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Password length/confirmation failed; no account file written.")
    accounts.append({"user_id": user_id, "role": role, "password_hash": password_hash(password)})
accounts_file.write_text(json.dumps(accounts, indent=2) + "\n", encoding="utf-8")
accounts_file.chmod(0o600)
print(f"Private session key and hashed accounts provisioned in {private}")
