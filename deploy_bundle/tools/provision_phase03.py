"""Initialize and synchronize the explicitly requested D-drive frontend workspace."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
source = root / ".runtime" / "phase3-source"
target = Path("D:/BIRD-Interact/frontend").resolve()
if str(target).replace("\\", "/").casefold() != "d:/bird-interact/frontend":
    raise SystemExit("Unexpected frontend destination.")
target.mkdir(parents=True, exist_ok=True)
for path in source.rglob("*"):
    if path.is_file():
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
runtime = target / ".runtime"
runtime.mkdir(exist_ok=True)
node_source = Path("C:/Users/HP/AppData/Local/Programs/nodejs")
node_target = runtime / "node"
if not (node_target / "node.exe").exists():
    node_target.mkdir(exist_ok=True)
    shutil.copyfile(node_source / "node.exe", node_target / "node.exe")
    shutil.copytree(node_source / "node_modules" / "npm", node_target / "node_modules" / "npm", dirs_exist_ok=True)
    for name in ("npm.cmd", "npx.cmd"):
        shutil.copyfile(node_source / name, node_target / name)
for name, folder in {"TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp", "npm_config_cache": "npm-cache",
                     "npm_config_prefix": "npm-global", "PLAYWRIGHT_BROWSERS_PATH": "browsers"}.items():
    location = runtime / folder
    location.mkdir(exist_ok=True)
    os.environ[name] = str(location)
os.environ["PATH"] = str(node_target) + os.pathsep + os.environ["PATH"]
os.environ["npm_config_update_notifier"] = "false"
os.environ["NODE_OPTIONS"] = "--max-old-space-size=256 --max-semi-space-size=1"
os.environ["npm_config_maxsockets"] = "1"
os.environ["npm_config_userconfig"] = str(target / ".npmrc")
if "--install" in sys.argv:
    subprocess.run([str(node_target / "node.exe"), str(node_target / "node_modules" / "npm" / "bin" / "npm-cli.js"),
                    "install", "--no-fund", "--no-audit"], cwd=target, check=True)
print(f"Frontend source and runtime: {target}")
