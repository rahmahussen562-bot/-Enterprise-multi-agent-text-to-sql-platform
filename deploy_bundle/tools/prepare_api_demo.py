"""Provision the explicit local demo offline from the verified fixture."""
import gzip
from pathlib import Path
import sqlite3
import sys

root = Path(__file__).resolve().parents[1]
if root.drive.upper() != "D:" or Path(sys.prefix).resolve() != root / ".venv":
    raise SystemExit("Use the D-drive virtual environment.")
database = root / "data" / "chinook.db"
database.parent.mkdir(parents=True, exist_ok=True)
if database.exists():
    raise SystemExit("Demo database already exists; it has not been overwritten.")
fixture = root / "tests" / "fixtures" / "chinook.sql.gz"
with sqlite3.connect(":memory:") as connection:
    connection.executescript(gzip.decompress(fixture.read_bytes()).decode("utf-8"))
    database.write_bytes(connection.serialize())
print(f"Explicit demo database provisioned offline at {database}")
