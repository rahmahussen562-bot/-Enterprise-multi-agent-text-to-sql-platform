"""Durable owner-scoped jobs and append-only ordered event records."""
from contextlib import closing
import json
import sqlite3
import time
from api.auth import APIError


class JobStore:
    def __init__(self, path, max_events=256):
        self.path = path
        self.max_events = max_events
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL,
                    status TEXT NOT NULL, created_at REAL NOT NULL, response TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id), sequence INTEGER NOT NULL,
                    event TEXT NOT NULL, PRIMARY KEY(job_id, sequence));
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(user_id, role);
            """)
            # A stopped process cannot claim previously running jobs completed.
            connection.execute("UPDATE jobs SET status='interrupted', response=? WHERE status='running'",
                (json.dumps({"detail": "Service restarted before completion.", "error_code": "SERVICE_RESTARTED", "ast_trace": []}),))
            connection.commit()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def create(self, job_id, claims):
        with closing(self.connect()) as connection:
            with connection:
                connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,NULL)",
                    (job_id, claims.user_id, claims.role, "running", time.time()))

    def get(self, job_id, claims):
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=? AND user_id=? AND role=?",
                (job_id, claims.user_id, claims.role)).fetchone()
        if row is None:
            raise APIError(404, "JOB_NOT_FOUND", "Query job was not found.")
        response = json.loads(row["response"]) if row["response"] else None
        return {"job_id": job_id, "status": row["status"],
                "output": response if row["status"] == "completed" else None,
                "error": response if row["status"] in {"failed", "cancelled", "interrupted"} else None}

    def append(self, job_id, event, terminal=False):
        with closing(self.connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                sequence = connection.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE job_id=?", (job_id,)).fetchone()[0]
                if sequence >= self.max_events and not terminal:
                    raise APIError(413, "TELEMETRY_LIMIT", "Query exceeded its event budget.")
                record = {**event, "sequence": sequence}
                connection.execute("INSERT INTO events VALUES(?,?,?)", (job_id, sequence, json.dumps(record, allow_nan=False)))
        return record

    def finish(self, job_id, status, response):
        with closing(self.connect()) as connection:
            with connection:
                connection.execute("UPDATE jobs SET status=?, response=? WHERE job_id=? AND status='running'",
                    (status, json.dumps(response, allow_nan=False), job_id))

    def events(self, job_id, claims, after=0, limit=100):
        self.get(job_id, claims)
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT event FROM events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (job_id, after, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def trace(self, job_id, claims):
        return self.events(job_id, claims, limit=self.max_events + 1)
