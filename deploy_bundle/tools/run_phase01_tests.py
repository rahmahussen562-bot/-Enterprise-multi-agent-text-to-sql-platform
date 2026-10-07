"""Run the recovered baseline and adversarial suite with all artifacts on D:."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
if (os.name == "nt" and root.drive.upper() != "D:") or Path(sys.prefix).resolve() != root / ".venv":
    raise SystemExit("Use the project D: virtual environment for Phase 0/1 verification.")
for name, directory in {
    "TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp",
    "PIP_CACHE_DIR": "pip-cache", "UV_CACHE_DIR": "uv-cache",
    "PYTHONPYCACHEPREFIX": "pycache", "PYTHONUSERBASE": "python-user",
    "XDG_CACHE_HOME": "cache", "npm_config_cache": "npm-cache",
}.items():
    path = root / ".runtime" / directory
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ["PYTHONNOUSERSITE"] = "1"
os.chdir(root)
sys.path.insert(0, str(root))
import pytest

arguments = sys.argv[1:] or ["-q", "--junitxml=docs/PHASE01_TEST_RESULTS.xml"]
raise SystemExit(pytest.main(arguments))
