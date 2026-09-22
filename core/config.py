"""
Configuration settings for the Enterprise Multi-Agent Text-to-SQL platform.
Configured for Microsoft SQL Server (T-SQL) with RBAC and RLC enforcement.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class DatabaseConfig:
    dialect: str = "tsql"  # Default dialect: Microsoft SQL Server (T-SQL)
    driver: str = os.getenv("DB_DRIVER", "SQL Server")
    server: str = os.getenv("DB_SERVER", "localhost")
    database: str = os.getenv("DB_NAME", "Chinook")
    username: Optional[str] = os.getenv("DB_USER")
    password: Optional[str] = os.getenv("DB_PASSWORD")
    trusted_connection: bool = os.getenv("DB_TRUSTED_CONNECTION", "yes").lower() in ("yes", "true", "1")
    connection_string: Optional[str] = os.getenv("DB_CONNECTION_STRING")
    sqlite_path: str = os.getenv("SQLITE_PATH", "data/chinook.db")
    connection_timeout_sec: int = 10
    query_timeout_sec: int = 15

    def get_odbc_connection_string(self) -> str:
        """Construct a standard pyodbc connection string."""
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

        return ";".join(params)


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
