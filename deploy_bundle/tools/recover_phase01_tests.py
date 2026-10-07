"""Recover the unchanged 44-test baseline from Git without restoring unrelated files."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
files = [
    "tests/test_auth.py", "tests/test_critic.py", "tests/test_database.py",
    "tests/test_guardian.py", "tests/test_intent_router.py", "tests/test_orchestrator.py",
    "tests/test_reconnaissance.py", "tests/test_visualizer.py", "utils/db_seeder.py",
]
manifest = {"source_revision": revision, "files": {}}
for relative in files:
    data = subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=root)
    destination = root / relative
    if destination.exists() and destination.read_bytes() != data:
        raise SystemExit(f"Refusing to overwrite existing changes: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    manifest["files"][relative] = hashlib.sha256(data).hexdigest()
    print(f"Recovered {relative}")
(root / "docs" / "PHASE01_TEST_BASELINE.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
