"""Install Phase 2 extras using only the self-contained D: environment/caches."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
if root.drive.upper() != "D:" or Path(sys.prefix).resolve() != root / ".venv":
    raise SystemExit("Run with the D: virtual environment.")
for name, folder in {"TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp", "PIP_CACHE_DIR": "pip-cache"}.items():
    path = root / ".runtime" / folder
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
lock = root / "requirements-phase02.lock.txt"
requirements = lock if lock.exists() else root / "requirements-phase02.txt"
subprocess.run([sys.executable, "-B", "-m", "pip", "install", "--only-binary=:all:", "-r", str(requirements)], cwd=root, check=True)
subprocess.run([sys.executable, "-B", "-m", "pip", "check"], cwd=root, check=True)
frozen = subprocess.run([sys.executable, "-B", "-m", "pip", "freeze"], cwd=root, check=True, capture_output=True, text=True).stdout
lock.write_text("# Phase 2 verified runtime: Windows x64 / CPython 3.14.\n" + frozen, encoding="utf-8")
