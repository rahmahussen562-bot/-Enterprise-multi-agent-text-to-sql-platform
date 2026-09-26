"""
Corporate Role-Based Access Control (RBAC) and Row/Table-Level Control (RLC).
Provides session-based authentication and table authorization whitelists.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass(frozen=True)
class UserSession:
    username: str
    role_title: str
    scope: str
    authorized_tables: List[str]
    rlc_description: str
    authenticated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    @property
    def allowed_tables(self) -> List[str]:
        """Alias for authorized_tables ensuring strict RBAC compatibility."""
        return self.authorized_tables


# Hardcoded corporate identity registry
_CORPORATE_USERS: Dict[str, Dict[str, str]] = {
    "sales_analyst": {
        "password": "Sales@2026!",
        "role_title": "Sales Analyst",
        "scope": "Commercial Domain",
        "rlc_description": "Allowed to query customer data, billing, and transactional revenue only.",
        "authorized_tables": ["Customer", "Invoice", "InvoiceLine"],
    },
    "inventory_lead": {
        "password": "Ops@2026!",
        "role_title": "Inventory Lead",
        "scope": "Operational & Catalog Domain",
        "rlc_description": "Allowed to query tracks, catalog media, and artist records only.",
        "authorized_tables": ["Track", "Album", "Artist", "Genre", "MediaType"],
    },
}


def authenticate(username: str, password: str) -> Optional[UserSession]:
    """
    Authenticate user credentials against the corporate directory.
    Returns a UserSession object upon success, or None on failure.
    """
    clean_username = username.strip().lower()
    record = _CORPORATE_USERS.get(clean_username)
    if not record:
        return None

    if record["password"] != password.strip():
        return None

    return UserSession(
        username=clean_username,
        role_title=record["role_title"],
        scope=record["scope"],
        authorized_tables=list(record["authorized_tables"]),
        rlc_description=record["rlc_description"]
    )


def is_table_authorized(user: UserSession, table_name: str) -> bool:
    """
    Check whether a specific table identifier is present in the user's whitelist.
    Case-insensitive comparison stripping schema qualifiers and brackets.
    """
    clean_name = table_name.strip().strip("[]").strip('"').strip("'")
    if "." in clean_name:
        clean_name = clean_name.split(".")[-1]

    tables = getattr(user, "allowed_tables", getattr(user, "authorized_tables", []))
    whitelist_lower = {t.lower() for t in tables}
    return clean_name.lower() in whitelist_lower


def filter_authorized_tables(user: UserSession, tables: List[str]) -> List[str]:
    """
    Filter a list of database tables strictly to the user's authorized scope.
    """
    user_tables = getattr(user, "allowed_tables", getattr(user, "authorized_tables", []))
    whitelist_lower = {t.lower() for t in user_tables}
    return [t for t in tables if t.lower() in whitelist_lower]
