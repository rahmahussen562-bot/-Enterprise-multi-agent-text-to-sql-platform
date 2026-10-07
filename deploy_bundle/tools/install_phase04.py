"""Provision PostgreSQL dependencies and a portable native fixture on D:."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
assert root.drive.upper() == "D:" and Path(sys.prefix).resolve() == root / ".venv"
for name, folder in {"TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp", "PIP_CACHE_DIR": "pip-cache"}.items():
    path = root / ".runtime" / folder
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
if "--binary-only" not in sys.argv:
    requirements = root / "requirements-phase04.lock.txt"
    if not requirements.exists():
        requirements = root / "requirements-phase04.txt"
    subprocess.run([sys.executable, "-B", "-m", "pip", "install", "--only-binary=:all:", "-r", str(requirements)], check=True)
    subprocess.run([sys.executable, "-B", "-m", "pip", "check"], check=True)
    frozen = subprocess.run([sys.executable, "-B", "-m", "pip", "freeze"], capture_output=True, text=True, check=True).stdout
    (root / "requirements-phase04.lock.txt").write_text("# Phase 4 verified Windows x64 / CPython 3.14 environment.\n" + frozen, encoding="utf-8")
if "--dependencies-only" in sys.argv:
    raise SystemExit(0)
runtime = root / ".runtime" / "postgres"
runtime.mkdir(parents=True, exist_ok=True)
if (runtime / "pgsql/bin/postgres.exe").exists():
    print("Portable PostgreSQL already provisioned on D:.", flush=True)
    raise SystemExit(0)
page = urllib.request.urlopen("https://www.enterprisedb.com/download-postgresql-binaries", timeout=60).read().decode()
if "--inspect-links" in sys.argv:
    print('\n'.join(re.findall(r'.{0,150}(?:binaries\.zip|windows-x64).{0,120}',page)), flush=True)
    raise SystemExit(0)
urls = re.findall(r'https://get\.enterprisedb\.com/postgresql/postgresql-17\.[\d.-]+windows-x64-binaries\.zip', page)
# EDB's current interactive page omits some version links from server HTML.
# This reviewed 17.11 archive is served by EDB's official binary host.
url = sorted(set(urls))[-1] if urls else "https://get.enterprisedb.com/postgresql/postgresql-17.11-3-windows-x64-binaries.zip"
archive = runtime / "postgresql-windows-x64.zip"
if not archive.exists():
    print("Downloading official PostgreSQL binaries to D:.", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
        shutil_copy = __import__("shutil").copyfileobj
        shutil_copy(response, output, length=1024 * 1024)
with zipfile.ZipFile(archive) as source:
    for entry in source.infolist():
        if not entry.filename.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/")):
            continue
        target = (runtime / entry.filename).resolve()
        if not target.is_relative_to(runtime.resolve()):
            raise RuntimeError("Unsafe archive path.")
        source.extract(entry, runtime)
digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
(runtime / "provenance.json").write_text(json.dumps({"source": url, "sha256": digest,
    "checksum_boundary": "Locally computed digest; vendor page does not publish a detached checksum."}, indent=2), encoding="utf-8")
print("Portable PostgreSQL binaries: " + str(runtime / "pgsql"), flush=True)
