"""Start the single-owner API with every runtime/cache directory on D:."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
if root.drive.upper() != "D:" or Path(sys.prefix).resolve() != root / ".venv":
    raise SystemExit("Use D:/BIRD-Interact/deploy_bundle/.venv/Scripts/python.exe.")
for name, folder in {
    "TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp", "PIP_CACHE_DIR": "pip-cache",
    "UV_CACHE_DIR": "uv-cache", "PYTHONPYCACHEPREFIX": "pycache", "PYTHONUSERBASE": "python-user",
    "XDG_CACHE_HOME": "cache", "HF_HOME": "huggingface", "TORCH_HOME": "torch",
    "MPLCONFIGDIR": "matplotlib", "npm_config_cache": "npm-cache",
}.items():
    path = root / ".runtime" / folder
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.chdir(root)
sys.path.insert(0, str(root))
import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, workers=1,
                ws_max_size=16384, timeout_graceful_shutdown=20)
