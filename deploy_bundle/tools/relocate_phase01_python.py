"""Copy the existing Python runtime to D: and rebase the project environment."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
runtime = root / ".runtime"
destination = runtime / "python"
if root.drive.upper() != "D:" or not destination.is_relative_to(root):
    raise SystemExit("The Python runtime must stay inside the approved D: workspace.")
temporary = runtime / "tmp"
temporary.mkdir(parents=True, exist_ok=True)
for name in ("TEMP", "TMP", "TMPDIR"):
    os.environ[name] = str(temporary)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["PYTHONNOUSERSITE"] = "1"
source = Path(sys.base_prefix).resolve()
if not destination.exists():
    # Global third-party packages and bytecode are not part of the isolated runtime.
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("site-packages", "__pycache__"))
python = destination / "python.exe"
check = subprocess.run(
    [str(python), "-B", "-c", "import json, sys; print(json.dumps({'base_prefix': sys.base_prefix, 'version': sys.version}))"],
    cwd=root, capture_output=True, text=True, check=True,
)
details = json.loads(check.stdout)
if Path(details["base_prefix"]).resolve() != destination:
    raise RuntimeError("The copied interpreter did not resolve its standard library on D:.")
# venv defaults to clear=False: installed project packages are preserved.
subprocess.run(
    [str(python), "-B", "-m", "venv", "--without-pip", str(root / ".venv")],
    cwd=root, check=True,
)
print(check.stdout.strip())
print(f"Rebased environment: {root / '.venv'}")
