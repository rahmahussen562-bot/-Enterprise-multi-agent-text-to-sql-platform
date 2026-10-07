"""Strict HS256 tokens with server-governed roles and no built-in credentials."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from core.auth import _CORPORATE_USERS, load_accounts, password_hash, session_for_role, verify_password
from api.schemas import SessionClaims


class APIError(Exception):
    def __init__(self, status, code, detail, ast_trace=None, job_id=None):
        self.status = status
        self.code = code
        self.detail = detail
        self.ast_trace = ast_trace or []
        self.job_id = job_id


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value):
    if not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise ValueError("Invalid base64url.")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate token claims.")
        result[key] = value
    return result


class SessionAuthority:
    def __init__(self, settings):
        self.settings = settings
        load_accounts(settings.accounts_file)  # Fail startup on missing/untrusted directory.
        self._dummy_hash = password_hash(secrets.token_urlsafe(32))

    def accounts(self):
        try:
            return load_accounts(self.settings.accounts_file)
        except (OSError, ValueError, KeyError, TypeError):
            raise APIError(503, "AUTH_SERVICE_UNAVAILABLE", "Account directory is unavailable.")

    def login(self, user_id, password):
        user_id = user_id.strip().lower()
        record = self.accounts().get(user_id)
        verified = verify_password(password, record["password_hash"] if record else self._dummy_hash)
        if record is None or not verified:
            raise APIError(401, "INVALID_CREDENTIALS", "Invalid credentials.")
        now = int(time.time())
        claims = SessionClaims(user_id=user_id, role=record["role"],
            allowed_tables=list(_CORPORATE_USERS[record["role"]]["authorized_tables"]),
            issued_at=now, expires_at=now + self.settings.session_ttl_sec)
        return self.sign(claims), claims

    def sign(self, claims):
        header = _encode(b'{"alg":"HS256","typ":"JWT"}')
        payload = _encode(claims.model_dump_json().encode("utf-8"))
        unsigned = header + "." + payload
        return unsigned + "." + _encode(hmac.digest(self.settings.signing_key, unsigned.encode("ascii"), "sha256"))

    def verify(self, token):
        try:
            if len(token) > 8192:
                raise ValueError("Oversized token.")
            header, payload, signature = token.split(".")
            expected = hmac.digest(self.settings.signing_key, (header + "." + payload).encode("ascii"), "sha256")
            if not hmac.compare_digest(_decode(signature), expected):
                raise ValueError("Bad signature.")
            metadata = json.loads(_decode(header), object_pairs_hook=_unique_object)
            if metadata != {"alg": "HS256", "typ": "JWT"}:
                raise ValueError("Unsupported token algorithm.")
            values = json.loads(_decode(payload), object_pairs_hook=_unique_object)
            claims = SessionClaims.model_validate(values)
            now = int(time.time())
            if (claims.issued_at > now + 30 or claims.expires_at <= now
                    or not 0 < claims.expires_at - claims.issued_at <= self.settings.session_ttl_sec):
                raise ValueError("Expired/invalid session lifetime.")
            record = self.accounts().get(claims.user_id)
            if record is None or record["role"] != claims.role:
                raise ValueError("Role revoked.")
            if claims.allowed_tables != list(_CORPORATE_USERS[claims.role]["authorized_tables"]):
                raise ValueError("Entitlements differ from server policy.")
            return claims
        except APIError:
            raise
        except (ValueError, TypeError, KeyError, UnicodeError, ValidationError):
            raise APIError(401, "INVALID_SESSION", "Invalid or expired session token.")

    def to_engine_session(self, claims):
        return session_for_role(claims.user_id, claims.role)


bearer = HTTPBearer(auto_error=False)


def require_session(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "AUTHENTICATION_REQUIRED", "A bearer session token is required.")
    return request.app.state.authority.verify(credentials.credentials)
