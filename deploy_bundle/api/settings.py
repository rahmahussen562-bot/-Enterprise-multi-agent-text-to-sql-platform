"""Explicit local settings; private state and all new runtime files stay on D:."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class APISettings:
    signing_key: bytes
    accounts_file: Path
    state_file: Path
    session_ttl_sec: int = 900
    max_workers: int = 4
    job_timeout_sec: float = 60.0
    shutdown_timeout_sec: float = 15.0
    max_events: int = 256
    max_result_rows: int = 1000
    max_response_bytes: int = 2 * 1024 * 1024
    allowed_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:5173")

    def __post_init__(self):
        if len(self.signing_key) < 32:
            raise ValueError("Session signing key requires at least 32 bytes.")
        if not 30 <= self.session_ttl_sec <= 3600:
            raise ValueError("Session TTL must be between 30 and 3600 seconds.")
        if not 1 <= self.max_workers <= 32 or not 1 <= self.job_timeout_sec <= 300:
            raise ValueError("Invalid worker or query deadline budget.")
        if not 1 <= self.shutdown_timeout_sec <= 60 or not 16 <= self.max_events <= 1024:
            raise ValueError("Invalid shutdown/event budget.")
        if not 1 <= self.max_result_rows <= 10000 or not 1024 <= self.max_response_bytes <= 10 * 1024 * 1024:
            raise ValueError("Invalid response budget.")
        for path in (self.accounts_file, self.state_file):
            if os.name == "nt" and path.resolve().drive.upper() != "D:":
                raise ValueError("API account/state files must reside on D:.")

    @classmethod
    def from_environment(cls):
        private = ROOT / ".runtime" / "api-private"
        secret = os.getenv("SENTINEL_SESSION_KEY")
        key_file = os.getenv("SENTINEL_SESSION_KEY_FILE")
        if secret and key_file:
            raise ValueError("Configure one session key source.")
        path = Path(key_file) if key_file else private / "session.key"
        if os.name == "nt" and path.resolve().drive.upper() != "D:":
            raise ValueError("Private session keys must reside on D:.")
        key = secret.encode("utf-8") if secret else path.read_bytes()
        return cls(
            signing_key=key,
            accounts_file=Path(os.getenv("SENTINEL_AUTH_FILE", str(private / "accounts.json"))),
            state_file=Path(os.getenv("SENTINEL_API_STATE", str(private / "jobs.sqlite"))),
            session_ttl_sec=int(os.getenv("SENTINEL_SESSION_TTL", "900")),
            max_workers=int(os.getenv("SENTINEL_API_WORKERS", "4")),
            job_timeout_sec=float(os.getenv("SENTINEL_JOB_TIMEOUT", "60")),
            allowed_origins=tuple(filter(None, os.getenv("SENTINEL_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(","))),
        )
