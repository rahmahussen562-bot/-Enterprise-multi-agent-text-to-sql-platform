"""Verify installed dependencies, record their locations, and measure D: usage."""
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv"
if ROOT.drive.upper() != "D:" or Path(sys.prefix).resolve() != ENVIRONMENT:
    raise SystemExit("Use the D: project virtual environment.")
if Path(sys.base_prefix).resolve() != ROOT / ".runtime" / "python":
    raise SystemExit("Rebase Python to the self-contained D: runtime before verification.")

for name, directory in {
    "TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp",
    "PIP_CACHE_DIR": "pip-cache", "UV_CACHE_DIR": "uv-cache",
    "PYTHONPYCACHEPREFIX": "pycache", "PYTHONUSERBASE": "python-user",
    "XDG_CACHE_HOME": "cache", "npm_config_cache": "npm-cache",
}.items():
    target = ROOT / ".runtime" / directory
    target.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(target)
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

dependencies = {}
for name in (
    "sqlglot", "fastapi", "uvicorn", "pydantic", "pytest", "reportlab",
    "pyodbc", "psycopg", "asyncpg", "pandas", "streamlit",
):
    module = importlib.import_module(name)
    location = Path(module.__file__).resolve()
    if not location.is_relative_to(ENVIRONMENT):
        raise RuntimeError(f"Dependency {name} loaded outside D: environment: {location}")
    dependencies[name] = {
        "version": importlib.metadata.version(name), "location": str(location),
    }

pip_check = subprocess.run(
    [sys.executable, "-B", "-m", "pip", "check"],
    cwd=ROOT, capture_output=True, text=True, check=True,
)
frozen = subprocess.run(
    [sys.executable, "-B", "-m", "pip", "freeze"],
    cwd=ROOT, capture_output=True, text=True, check=True,
).stdout
lock_header = (
    "# Verified Phase 0/1 environment: CPython 3.14, Windows x64.\n"
    "# Re-provision with tools/provision_phase01.py; revalidate before upgrading.\n"
)
(ROOT / "requirements-phase01.lock.txt").write_text(lock_header + frozen, encoding="utf-8")

baseline = json.loads((ROOT / "docs" / "PHASE01_TEST_BASELINE.json").read_text(encoding="utf-8"))
baseline_files = baseline["files"]
for destination, expected in baseline_files.items():
    path = ROOT / destination
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f"Recovered baseline source changed: {path}")

def directory_bytes(path):
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())

free = ctypes.c_ulonglong()
total = ctypes.c_ulonglong()
total_free = ctypes.c_ulonglong()
if not ctypes.windll.kernel32.GetDiskFreeSpaceExW(
    "D:\\", ctypes.byref(free), ctypes.byref(total), ctypes.byref(total_free)
):
    raise ctypes.WinError()
import pyodbc
report = {
    "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    "environment": str(ENVIRONMENT), "python": sys.version.split()[0],
    "base_interpreter": sys.base_prefix,
    "dependency_locations": dependencies,
    "pip_check": pip_check.stdout.strip(),
    "baseline_files_verified": len(baseline_files),
    "venv_bytes": directory_bytes(ENVIRONMENT),
    "python_runtime_bytes": directory_bytes(ROOT / ".runtime" / "python"),
    "runtime_bytes": directory_bytes(ROOT / ".runtime"),
    "d_free_bytes": free.value, "d_total_bytes": total.value,
    "odbc_drivers": pyodbc.drivers(),
    "cache_locations": {
        key: os.environ[key] for key in (
            "TEMP", "TMP", "PIP_CACHE_DIR", "UV_CACHE_DIR",
            "PYTHONPYCACHEPREFIX", "PYTHONUSERBASE", "XDG_CACHE_HOME", "npm_config_cache",
        )
    },
}
output = ROOT / "docs" / "PHASE01_ENVIRONMENT.json"
output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
