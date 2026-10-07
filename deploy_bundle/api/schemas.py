"""Strict transport contracts; engine dataclasses remain backward compatible."""
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

Role = Literal["sales_analyst", "inventory_lead", "compliance_officer", "branch_analyst", "fraud_investigator"]
Intent = Literal["HELP", "DATA_QUERY", "OUT_OF_SCOPE", "SECURITY_ATTACK"]
JobStatus = Literal["running", "completed", "failed", "cancelled", "interrupted"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionClaims(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    role: Role
    allowed_tables: list[str] = Field(min_length=1, max_length=32)
    issued_at: int = Field(ge=0)
    expires_at: int = Field(ge=1)


class LoginRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(StrictModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    session: SessionClaims


class QueryRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Question must not be blank.")
        return value


class ClassifyResponse(StrictModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    response: str | None = None
    sample_queries: list[str] = Field(default_factory=list)


class TraceEvent(StrictModel):
    sequence: int = Field(ge=1)
    kind: str
    agent: str
    status: str
    message: str
    timestamp: float
    duration_ms: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(StrictModel):
    detail: str
    error_code: str
    ast_trace: list[TraceEvent] = Field(default_factory=list)
    job_id: str | None = None


class QueryOutput(StrictModel):
    final_sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    executive_narrative: str
    execution_time_ms: float
    intent: Intent
    retries: list[dict[str, Any]] = Field(default_factory=list)


class JobResponse(StrictModel):
    job_id: str
    status: JobStatus
    output: QueryOutput | None = None
    error: ErrorResponse | None = None


class AuditResponse(StrictModel):
    job_id: str
    status: JobStatus
    events: list[TraceEvent]
    next_sequence: int


class HealthResponse(StrictModel):
    status: Literal["ready", "draining"]
    ast_validation: Literal["ready"]
    active_queries: int
    worker_capacity: int
    checked_at: float


class SchemaColumn(StrictModel):
    name: str
    data_type: str
    nullable: bool
    primary_key: bool


class SchemaTable(StrictModel):
    name: str
    columns: list[SchemaColumn]


class SchemaRelationship(StrictModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str


class SchemaResponse(StrictModel):
    dialect: Literal["tsql", "postgres"]
    role: Role
    tables: list[SchemaTable]
    relationships: list[SchemaRelationship]


class StreamCommand(StrictModel):
    action: Literal["start", "subscribe", "cancel"]
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    job_id: str | None = Field(default=None, min_length=36, max_length=36)
    after_sequence: int = Field(default=0, ge=0)

    @field_validator("job_id")
    @classmethod
    def valid_id(cls, value):
        if value is not None:
            UUID(value)
        return value
