"""Asynchronous PostgreSQL adapter with bounded pools and native cancellation.

Each pool authenticates as one restricted database LOGIN. Row scopes derive from
session_user and private ACL tables, never a user-controlled session variable.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import time
from uuid import UUID

import pandas as pd
from psycopg import errors, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import AsyncConnectionPool

from agents.critic import RuntimeCriticAgent
from agents.guardian import ASTGuardianAgent
from core.cancellation import QueryCancelledError, current_cancellation
from core.fincore import PG_GROUPS, ROLE_COLUMNS
from core.sql_validation import ValidationError


@dataclass(frozen=True)
class PostgresConfig:
    conninfo: str = field(repr=False)
    expected_login: str
    persona: str
    max_pool_size: int = 2
    max_waiting: int = 4
    acquire_timeout_sec: float = 2
    statement_timeout_sec: float = 5
    max_rows: int = 1000

    def __post_init__(self):
        if self.persona not in ROLE_COLUMNS or not self.expected_login:
            raise ValueError("A server-governed banking principal is required.")
        if conninfo_to_dict(self.conninfo).get("user") != self.expected_login:
            raise ValueError("DSN must authenticate the expected database LOGIN.")
        options=conninfo_to_dict(self.conninfo)
        if options.get('host') not in {'127.0.0.1','localhost','::1'} and options.get('sslmode')!='verify-full':
            raise ValueError("Remote banking connections require sslmode=verify-full.")
        if not 1 <= self.max_pool_size <= 8 or not 1 <= self.max_waiting <= 32 or not 1 <= self.max_rows <= 10000:
            raise ValueError("Invalid PostgreSQL workload budget.")
        if not all(math.isfinite(value) and 0 < value <= 120 for value in (self.acquire_timeout_sec, self.statement_timeout_sec)):
            raise ValueError("Invalid PostgreSQL timeout budget.")

    @classmethod
    def for_session(cls, session):
        path = Path(os.environ["SENTINEL_PG_AUTH_FILE"])
        if os.name=='nt' and path.resolve().drive.upper()!='D:':
            raise ValueError("Banking identity files must remain on D:.")
        if path.stat().st_size > 256 * 1024:
            raise ValueError("PostgreSQL identity directory exceeds its budget.")
        records = json.loads(path.read_text(encoding="utf-8"))
        record = records.get(session.username)
        if not isinstance(record, dict) or set(record) != {"role", "db_login", "conninfo"} or record["role"] != session.role:
            raise PermissionError("No matching server PostgreSQL identity.")
        if sum(isinstance(value,dict) and value.get('db_login')==record['db_login'] for value in records.values())!=1:
            raise PermissionError("A PostgreSQL LOGIN must belong to exactly one API identity.")
        return cls(record["conninfo"], record["db_login"], record["role"])


class ColumnCatalog:
    dialect = "postgres"
    def __init__(self, columns):
        self.columns = columns
    def get_table_columns_info(self, relation):
        if relation not in self.columns:
            raise ValidationError("HALLUCINATION_SCHEMA_UNAVAILABLE", "No authorized column metadata.")
        return self.columns[relation]


class PostgresDatabaseEngine:
    dialect = "postgres"
    connection_mode = "LIVE_POSTGRES"
    detected_driver = "psycopg3"

    def __init__(self, config: PostgresConfig):
        self.config = config
        self.allowed_columns = ROLE_COLUMNS[config.persona]
        self._metadata = {}
        self._pool = AsyncConnectionPool(config.conninfo, open=False, min_size=0, max_size=config.max_pool_size,
            max_waiting=config.max_waiting, timeout=config.acquire_timeout_sec, configure=self._configure,
            kwargs={"autocommit": True, "connect_timeout": max(1, math.ceil(config.acquire_timeout_sec)),
                    "options": "-c search_path=pg_catalog -c default_transaction_read_only=on -c timezone=UTC",
                    "application_name": "sentinelsql-fincore"})
        self.last_latency_ms = 0.0

    async def _configure(self, connection):
        async with connection.cursor() as cursor:
            await cursor.execute("""SELECT session_user,current_user,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,
                pg_has_role(session_user,'fincore_owner','MEMBER'),security.persona(),
                pg_has_role(session_user,'fincore_compliance','MEMBER'),
                pg_has_role(session_user,'fincore_branch','MEMBER'),pg_has_role(session_user,'fincore_fraud','MEMBER')
                FROM pg_catalog.pg_roles WHERE rolname=session_user""")
            row = await cursor.fetchone()
        expected = tuple(group == PG_GROUPS[self.config.persona] for group in ("fincore_compliance", "fincore_branch", "fincore_fraud"))
        if not row or row[0] != self.config.expected_login or row[1] != row[0] or any(row[2:7]) or row[7] != self.config.persona or tuple(row[8:]) != expected:
            await connection.close()
            raise PermissionError("PostgreSQL LOGIN violates banking principal governance.")

    async def open(self):
        await self._pool.open()
        # Force credential/role verification before accepting work.
        async with self._pool.connection():
            pass
        return self

    async def close(self):
        await self._pool.close()

    async def __aenter__(self):
        return await self.open()

    async def __aexit__(self, *_):
        await self.close()

    async def _read(self, query, parameters=None, timeout_sec=None, max_rows=None):
        timeout = min(timeout_sec or self.config.statement_timeout_sec, self.config.statement_timeout_sec)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid statement timeout.")
        token = current_cancellation.get()
        if token:
            token.check()
        async with self._pool.connection(timeout=self.config.acquire_timeout_sec) as connection:
            key = None
            loop = asyncio.get_running_loop()
            if token:
                def cancel_native():
                    future = asyncio.run_coroutine_threadsafe(connection.cancel_safe(timeout=2), loop)
                    future.result(timeout=3)
                key = token.register(cancel_native)
            try:
                async with connection.transaction():
                    await connection.execute("SET TRANSACTION READ ONLY")
                    await connection.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true),set_config('transaction_timeout',%s,true)",
                        (str(math.ceil(timeout*1000)), str(math.ceil(timeout*1000)), str(math.ceil((timeout+1)*1000))))
                    async with connection.cursor() as cursor:
                        started = time.perf_counter()
                        await cursor.execute(query, parameters)
                        columns = [column.name for column in cursor.description] if cursor.description else []
                        rows = await cursor.fetchmany((max_rows or self.config.max_rows) + 1)
                        if len(rows) > (max_rows or self.config.max_rows):
                            raise ValueError("RESULT_LIMIT: PostgreSQL result exceeded its row budget.")
                        if token:
                            token.check()
                        self.last_latency_ms = (time.perf_counter()-started)*1000
                        return columns, rows
            except errors.QueryCanceled as error:
                if token and token.cancelled:
                    raise QueryCancelledError("PostgreSQL driver cancellation completed.") from error
                raise TimeoutError("PostgreSQL statement timeout; transaction rolled back.") from error
            except asyncio.CancelledError:
                # Psycopg cancels the active operation on Task cancellation;
                # explicitly complete native cleanup before returning the lease.
                await asyncio.shield(connection.cancel_safe(timeout=2))
                await asyncio.shield(connection.rollback())
                raise
            finally:
                if key is not None:
                    # Do not block the event loop against a control callback
                    # waiting for cancel_safe on this same event loop.
                    await asyncio.to_thread(token.unregister, key)

    async def metadata(self):
        metadata = {}
        for relation, permitted in self.allowed_columns.items():
            schema, table = relation.split(".")
            _, rows = await self._read("""SELECT a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull
                FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relname=%s AND c.relkind='v' AND a.attnum>0 AND NOT a.attisdropped
                AND pg_catalog.has_column_privilege(current_user,c.oid,a.attname,'SELECT') ORDER BY a.attnum""", (schema, table), max_rows=64)
            selected = [{"name": name, "type": kind, "notnull": notnull, "pk": False,
                         "table_name": table, "table_schema": schema} for name, kind, notnull in rows if name in permitted]
            if {column["name"] for column in selected} != set(permitted):
                raise ValidationError("HALLUCINATION_SCHEMA_UNAVAILABLE", "Verified banking view metadata is incomplete.")
            metadata[relation] = selected
        self._metadata = metadata
        return metadata

    async def execute_query(self, query, timeout_sec=None):
        if not self._metadata:
            await self.metadata()
        audit = ASTGuardianAgent(default_limit=self.config.max_rows, dialect="postgres").audit(query,
            valid_tables=list(self.allowed_columns), authorized_tables=list(self.allowed_columns), allowed_columns=self.allowed_columns)
        if not audit.is_valid:
            raise ValidationError(audit.critique["type"], audit.critique["message"])
        denial = RuntimeCriticAgent(ColumnCatalog(self._metadata)).validate_schema_grounding(audit.sanitized_sql,
            authorized_tables=list(self.allowed_columns))
        if denial:
            raise ValidationError(denial["type"], denial["message"])
        columns, rows = await self._read(audit.sanitized_sql, timeout_sec=timeout_sec)
        return pd.DataFrame([[str(cell) if isinstance(cell, UUID) else cell for cell in row] for row in rows], columns=columns)

    async def get_table_names(self, authorized_tables=None):
        await self.metadata()
        return [name for name in self.allowed_columns if authorized_tables is None or name in authorized_tables]

    async def get_table_columns_info(self, relation):
        if relation not in self.allowed_columns:
            raise PermissionError("Unauthorized banking relation.")
        if not self._metadata:
            await self.metadata()
        return self._metadata[relation]

    async def get_all_ddls(self, authorized_tables=None):
        names = await self.get_table_names(authorized_tables)
        return {name: sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(*name.split('.')),
            sql.SQL(', ').join(sql.SQL('{} {}').format(sql.Identifier(column['name']),sql.SQL(column['type']))
                for column in self._metadata[name])).as_string() for name in names}

    async def get_foreign_keys(self, authorized_tables=None):
        # Views do not inherit base-table FK constraints. Never invent them or
        # disclose hidden customer/case relationships through the schema API.
        return []


class PostgresSyncBridge:
    """Keep the legacy synchronous agent contract on its existing worker thread.

    The reusable async adapter remains the primary implementation. A controller
    scope owns one pool and selector loop; isolated metadata calls close their
    pool when finished. No coroutine runs on ASGI's event loop synchronously.
    """
    dialect = "postgres"
    detected_driver = "psycopg3"
    connection_mode = "LIVE_POSTGRES"
    def __init__(self, config):
        self.config = config
        self.allowed_columns = ROLE_COLUMNS[config.persona]
        self._runner = None
        self._engine = None

    @contextmanager
    def scope(self):
        if self._runner is not None:
            yield self
            return
        factory = asyncio.SelectorEventLoop if os.name == "nt" else asyncio.new_event_loop
        with asyncio.Runner(loop_factory=factory) as runner:
            self._runner = runner
            self._engine = PostgresDatabaseEngine(self.config)
            try:
                runner.run(self._engine.open())
                yield self
            finally:
                runner.run(self._engine.close())
                self._runner = self._engine = None

    def _call(self, method, *args, **kwargs):
        with self.scope():
            return self._runner.run(getattr(self._engine, method)(*args, **kwargs))

    def execute_query(self, sql, timeout_sec=None):
        return self._call('execute_query',sql,timeout_sec=timeout_sec)
    def get_table_names(self, authorized_tables=None):
        return self._call('get_table_names',authorized_tables)
    def get_table_columns_info(self, name):
        return self._call('get_table_columns_info',name)
    def get_all_ddls(self, authorized_tables=None):
        return self._call('get_all_ddls',authorized_tables)
    def get_foreign_keys(self, authorized_tables=None):
        return []
