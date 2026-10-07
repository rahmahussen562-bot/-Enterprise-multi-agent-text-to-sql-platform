"""Install small release-only verification libraries with caches entirely on D:."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
if os.name == "nt" and (root.drive.upper() != "D:" or Path(sys.prefix).resolve() != root / ".venv"):
    raise SystemExit("Use the D: project environment.")
environment = dict(os.environ, PYTHONNOUSERSITE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
for name, relative in (("TEMP", "tmp"), ("TMP", "tmp"), ("TMPDIR", "tmp"), ("PIP_CACHE_DIR", "pip-cache")):
    path = root / ".runtime" / relative
    path.mkdir(parents=True, exist_ok=True)
    environment[name] = str(path)
subprocess.run([sys.executable, "-m", "pip", "install", "--only-binary=:all:", "pypdf==6.19.0", "PyNaCl==1.6.2"],
               env=environment, check=True)
subprocess.run([sys.executable, "-m", "pip", "check"], env=environment, check=True)
