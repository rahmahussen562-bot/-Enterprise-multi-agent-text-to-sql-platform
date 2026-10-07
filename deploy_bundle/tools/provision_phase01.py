"""Provision dependencies and every package/build temporary directory on D:."""
from pathlib import Path
import os
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
if ROOT.drive.upper() != "D:":
    raise SystemExit("Runtime provisioning requires the D: workspace.")
RUNTIME = ROOT / ".runtime"
for name, directory in {
    "TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp",
    "PIP_CACHE_DIR": "pip-cache", "UV_CACHE_DIR": "uv-cache",
    "PYTHONPYCACHEPREFIX": "pycache", "PYTHONUSERBASE": "python-user",
    "XDG_CACHE_HOME": "cache", "npm_config_cache": "npm-cache",
}.items():
    path = RUNTIME / directory
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
runtime_python = RUNTIME / "python" / "python.exe"
if not runtime_python.exists() or Path(sys.base_prefix).resolve() != runtime_python.parent:
    subprocess.run([
        sys.executable, "-B", str(ROOT / "tools" / "relocate_phase01_python.py"),
    ], cwd=ROOT, check=True)
    subprocess.run([str(runtime_python), "-B", str(Path(__file__).resolve())], cwd=ROOT, check=True)
    raise SystemExit(0)
environment = ROOT / ".venv"
python = environment / "Scripts" / "python.exe"
if not python.exists():
    venv.EnvBuilder(with_pip=False).create(environment)
print(f"Virtual environment: {environment}", flush=True)
subprocess.run([str(python), "-m", "ensurepip", "--upgrade", "--default-pip"], check=True)
lockfile = ROOT / "requirements-phase01.lock.txt"
requirements = lockfile if lockfile.exists() else ROOT / "requirements-phase01.txt"
subprocess.run([
    str(python), "-m", "pip", "install", "--only-binary=:all:",
    "-r", str(requirements),
    "--log", str(RUNTIME / "provision.log"),
], cwd=ROOT, check=True)

