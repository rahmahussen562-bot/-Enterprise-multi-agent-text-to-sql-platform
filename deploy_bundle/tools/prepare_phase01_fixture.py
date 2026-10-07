"""Vendor the legacy Chinook fixture once; unit tests then run without network access."""
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request

root = Path(__file__).resolve().parents[1]
fixture_dir = root / "tests" / "fixtures"
runtime_dir = root / ".runtime" / "fixtures"
fixture_dir.mkdir(parents=True, exist_ok=True)
runtime_dir.mkdir(parents=True, exist_ok=True)
url = "https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_Sqlite.sqlite"
database = runtime_dir / "Chinook.sqlite"
if not database.exists():
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read(5_000_001)
    if len(payload) > 5_000_000 or not payload.startswith(b"SQLite format 3\x00"):
        raise SystemExit("Unexpected Chinook fixture payload.")
    database.write_bytes(payload)
connection = sqlite3.connect(database)
try:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Fixture integrity check failed.")
    dump = "\n".join(connection.iterdump()).encode("utf-8")
    customers = connection.execute("SELECT COUNT(*) FROM Customer WHERE Country='Brazil'").fetchone()[0]
finally:
    connection.close()
fixture = fixture_dir / "chinook.sql.gz"
fixture.write_bytes(gzip.compress(dump, mtime=0))
(fixture_dir / "chinook_manifest.json").write_text(json.dumps({
    "source_url": url,
    "sqlite_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
    "sql_gzip_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
    "brazil_customer_count": customers,
}, indent=2) + "\n", encoding="utf-8")
print(f"Vendored offline fixture: {fixture} ({fixture.stat().st_size} bytes); Brazil customers: {customers}")

