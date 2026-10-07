"""
Corporate Role-Based Access Control (RBAC) and Row/Table-Level Control (RLC).
Provides session-based authentication and table authorization whitelists.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets


@dataclass(frozen=True)
class UserSession:
    username: str
    role_title: str
    scope: str
    authorized_tables: List[str]
    rlc_description: str
    authenticated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    role: Optional[str] = None

    @property
    def allowed_tables(self) -> List[str]:
        """Alias for authorized_tables ensuring strict RBAC compatibility."""
        return self.authorized_tables


# Authorizations are server policy, independent of client credentials/tokens.
_CORPORATE_USERS: Dict[str, Dict[str, str]] = {
    "sales_analyst": {
        "role_title": "Sales Analyst",
        "scope": "Commercial Domain",
        "rlc_description": "Allowed to query customer data, billing, and transactional revenue only.",
        "authorized_tables": ["Customer", "Invoice", "InvoiceLine"],
    },
    "inventory_lead": {
        "role_title": "Inventory Lead",
        "scope": "Operational & Catalog Domain",
        "rlc_description": "Allowed to query tracks, catalog media, and artist records only.",
        "authorized_tables": ["Track", "Album", "Artist", "Genre", "MediaType"],
    },
}

from core.fincore import ROLE_COLUMNS
for _bank_role, _bank_tables in ROLE_COLUMNS.items():
    _CORPORATE_USERS[_bank_role] = {
        "role_title": _bank_role.replace("_", " ").title(),
        "scope": "FinCore Enterprise",
        "rlc_description": "Database-authenticated branch/case scope and masked role views.",
        "authorized_tables": list(_bank_tables),
    }


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310000)
    return "pbkdf2-sha256$310000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        iterations = int(rounds)
        if algorithm != "pbkdf2-sha256" or not 200000 <= iterations <= 1000000:
            return False
        salt_bytes = base64.b64decode(salt, validate=True)
        expected_bytes = base64.b64decode(expected, validate=True)
        if len(salt_bytes) < 16 or len(expected_bytes) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, iterations)
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError):
        return False


def load_accounts(path: Path) -> Dict[str, dict]:
    if path.stat().st_size > 256 * 1024:
        raise ValueError("Account directory exceeds its size budget.")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("The server account directory must be a nonempty list.")
    accounts = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"user_id", "role", "password_hash"}:
            raise ValueError("Accounts require user_id, role, and password_hash only.")
        user_id = record["user_id"]
        if (not isinstance(user_id, str) or not user_id or len(user_id) > 128
                or user_id != user_id.strip().lower() or user_id in accounts
                or record["role"] not in _CORPORATE_USERS):
            raise ValueError("Invalid account identity or server role.")
        if not isinstance(record["password_hash"], str) or len(record["password_hash"]) > 384 or not record["password_hash"].startswith("pbkdf2-sha256$"):
            raise ValueError("Plaintext account passwords are prohibited.")
        accounts[user_id] = record
    return accounts


def session_for_role(user_id: str, role: str) -> UserSession:
    record = _CORPORATE_USERS[role]
    return UserSession(username=user_id, role_title=record["role_title"], scope=record["scope"],
                       authorized_tables=list(record["authorized_tables"]), rlc_description=record["rlc_description"], role=role)


def authenticate(username: str, password: str) -> Optional[UserSession]:
    """
    Authenticate user credentials against the corporate directory.
    Returns a UserSession object upon success, or None on failure.
    """
    clean_username = username.strip().lower()
    auth_file = os.getenv("SENTINEL_AUTH_FILE", str(Path(__file__).resolve().parents[1] / ".runtime" / "api-private" / "accounts.json"))
    try:
        account = load_accounts(Path(auth_file)).get(clean_username)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not account or not verify_password(password, account["password_hash"]):
        return None
    return session_for_role(clean_username, account["role"])


def is_table_authorized(user: UserSession, table_name: str) -> bool:
    """
    Check whether a specific table identifier is present in the user's whitelist.
    Legacy T-SQL names retain their historical normalization; banking identifiers
    must match the full PostgreSQL schema identity and quoted case semantics.
    """
    tables = getattr(user, "allowed_tables", getattr(user, "authorized_tables", []))
    if getattr(user, 'role', None) in ROLE_COLUMNS:
        try:
            from sqlglot import exp
            from core.sql_validation import table_matches_allowed
            relation = exp.to_table(table_name, dialect='postgres')
            return not relation.alias and table_matches_allowed(relation, tables, 'postgres')
        except Exception:
            return False
    clean_name = table_name.strip().strip("[]").strip('"').strip("'")
    if "." in clean_name:
        clean_name = clean_name.split(".")[-1]

    whitelist_lower = {t.lower() for t in tables}
    return clean_name.lower() in whitelist_lower


def filter_authorized_tables(user: UserSession, tables: List[str]) -> List[str]:
    """
    Filter a list of database tables strictly to the user's authorized scope.
    """
    if getattr(user, 'role', None) in ROLE_COLUMNS:
        return [table for table in tables if is_table_authorized(user, table)]
    user_tables = getattr(user, "allowed_tables", getattr(user, "authorized_tables", []))
    whitelist_lower = {t.lower() for t in user_tables}
    return [t for t in tables if t.lower() in whitelist_lower]
