"""Synchronize existing source agents without restoring deleted directories."""
import hashlib
import json
from pathlib import Path
import subprocess

BUNDLE = Path(__file__).resolve().parents[1]
REPOSITORY = BUNDLE.parent
if REPOSITORY != Path("D:/BIRD-Interact"):
    raise SystemExit("Source synchronization requires the approved D: repository.")

targets = ["agents/guardian.py", "agents/critic.py", "agents/orchestrator.py"]
output = BUNDLE / "docs" / "PHASE01_SOURCE_SYNC.json"
previous_sync = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
prepared = []
for relative in targets:
    target = REPOSITORY / relative
    current = target.read_bytes()  # Existing source only; never revive deleted files.
    original = subprocess.run(
        ["git", "show", f"HEAD:{relative}"], cwd=REPOSITORY,
        capture_output=True, check=True,
    ).stdout
    replacement = (BUNDLE / relative).read_bytes()
    # Git may check out CRLF; allow that normalization, never unrelated edits.
    if current.replace(b"\r\n", b"\n") not in (
        original.replace(b"\r\n", b"\n"), replacement.replace(b"\r\n", b"\n")
    ) and hashlib.sha256(current).hexdigest() != previous_sync.get(str(target)):
        raise RuntimeError(f"Refusing to overwrite pre-existing source edits: {target}")
    prepared.append((target, replacement))

manifest = {}
for target, replacement in prepared:
    target.write_bytes(replacement)
    manifest[str(target)] = hashlib.sha256(replacement).hexdigest()
output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
