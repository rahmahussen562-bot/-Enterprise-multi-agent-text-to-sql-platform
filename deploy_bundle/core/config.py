"""
Configuration settings for the Enterprise Multi-Agent Text-to-SQL platform.
Configured for Microsoft SQL Server (T-SQL) with dynamic pyodbc driver resolution,
encryption handling, and RBAC enforcement.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Candidate SQL Server ODBC drivers ordered by priority
SQL_SERVER_ODBC_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
]


def resolve_best_odbc_driver(installed_drivers: Optional[List[str]] = None) -> str:
    """
    Identify the highest priority SQL Server ODBC driver installed on the host.
    Falls back gracefully to 'SQL Server' if pyodbc is unavailable or no match is found.
    """
    if installed_drivers is None:
        try:
            import pyodbc
            installed_drivers = pyodbc.drivers()
        except Exception:
            installed_drivers = []

    installed_set = {d.strip().lower(): d.strip() for d in installed_drivers}

    for candidate in SQL_SERVER_ODBC_DRIVERS:
        if candidate.lower() in installed_set:
            return installed_set[candidate.lower()]

    return "SQL Server"


@dataclass
class DatabaseConfig:
    dialect: str = "tsql"  # Default dialect: Microsoft SQL Server (T-SQL)

    # Granular environment variables or MSSQL_CONNECTION_STRING
    server: str = os.getenv("MSSQL_SERVER", os.getenv("DB_SERVER", r"localhost\SQLEXPRESS"))
    database: str = os.getenv("MSSQL_DATABASE", os.getenv("DB_NAME", "Chinook"))
    username: Optional[str] = os.getenv("MSSQL_USER", os.getenv("DB_USER"))
    password: Optional[str] = os.getenv("MSSQL_PASSWORD", os.getenv("DB_PASSWORD"))
    trusted_connection: bool = os.getenv("MSSQL_TRUSTED_CONNECTION", os.getenv("DB_TRUSTED_CONNECTION", "yes")).lower() in ("yes", "true", "1")
    connection_string: Optional[str] = os.getenv("MSSQL_CONNECTION_STRING", os.getenv("DB_CONNECTION_STRING"))

    # Driver & SSL Configuration
    driver: str = os.getenv("MSSQL_DRIVER", "")
    trust_server_certificate: bool = os.getenv("MSSQL_TRUST_SERVER_CERTIFICATE", "yes").lower() in ("yes", "true", "1")
    encrypt: str = os.getenv("MSSQL_ENCRYPT", "optional")

    # Offline emulation is an explicit demo choice, never a production fallback.
    allow_sqlite_emulation: bool = os.getenv("SENTINEL_DEMO_MODE", "false").lower() in ("yes", "true", "1")
    sqlite_path: str = os.getenv("SQLITE_PATH", "data/chinook.db")
    connection_timeout_sec: int = int(os.getenv("MSSQL_TIMEOUT", "10"))
    query_timeout_sec: int = int(os.getenv("MSSQL_QUERY_TIMEOUT", "15"))

    def __post_init__(self):
        if not self.driver:
            self.driver = resolve_best_odbc_driver()

    def get_odbc_connection_string(self) -> str:
        """Construct a production-ready pyodbc connection string with SSL flags."""
        if self.connection_string:
            return self.connection_string

        params = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
            f"DATABASE={self.database}",
            f"Timeout={self.connection_timeout_sec}"
        ]

        if self.trusted_connection:
            params.append("Trusted_Connection=yes")
        elif self.username and self.password:
            params.append(f"UID={self.username}")
            params.append(f"PWD={self.password}")

        # SSL & Encryption handling for modern ODBC drivers (especially Driver 18)
        if "ODBC Driver 18" in self.driver:
            if self.trust_server_certificate:
                params.append("TrustServerCertificate=yes")
            if self.encrypt:
                params.append(f"Encrypt={self.encrypt}")
        elif "ODBC Driver 17" in self.driver and self.trust_server_certificate:
            params.append("TrustServerCertificate=yes")

        return ";".join(params) + ";"

    def get_sanitized_connection_string(self) -> str:
        """Mask sensitive credentials for secure UI display and logging."""
        conn_str = self.get_odbc_connection_string()
        return re.sub(r"PWD=[^;]+", "PWD=***", conn_str, flags=re.IGNORECASE)


@dataclass
class AgentConfig:
    max_retries: int = 3
    defensive_limit: int = 100  # Default TOP 100 injection
    enable_active_reconnaissance: bool = True
    reconnaissance_sample_limit: int = 5
    strict_ast_linting: bool = True
    enable_rbac_enforcement: bool = True
    zero_result_retry: bool = True
    domain_sanity_checks: bool = True


@dataclass
class VectorStoreConfig:
    persist_directory: str = "data/chroma_db"
    collection_name: str = "bird_schema_store"
    top_k_tables: int = 5
    top_k_examples: int = 3


@dataclass
class LLMConfig:
    provider: str = "auto"
    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.0
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    gemini_api_key: Optional[str] = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    anthropic_api_key: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))


@dataclass
class SystemConfig:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    vector: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    def ensure_directories(self) -> None:
        """Ensure necessary data folders exist."""
        Path("data").mkdir(parents=True, exist_ok=True)
        Path(self.vector.persist_directory).mkdir(parents=True, exist_ok=True)
        Path(self.db.sqlite_path).parent.mkdir(parents=True, exist_ok=True)


_global_config: Optional[SystemConfig] = None


def get_config() -> SystemConfig:
    """Retrieve or instantiate singleton configuration."""
    global _global_config
    if _global_config is None:
        _global_config = SystemConfig()
        _global_config.ensure_directories()
    return _global_config
