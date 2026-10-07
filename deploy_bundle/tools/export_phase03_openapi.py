import json
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from api.main import create_app
specification = create_app().openapi()
baseline = json.loads((root / "docs" / "PHASE02_OPENAPI.json").read_text(encoding="utf-8"))
assert set(baseline["paths"]) <= set(specification["paths"])
for path, definition in baseline["paths"].items():
    assert specification["paths"][path] == definition
for name, definition in baseline["components"]["schemas"].items():
    assert specification["components"]["schemas"][name] == definition
payload = json.dumps(specification, indent=2) + "\n"
(root / "docs" / "PHASE03_OPENAPI.json").write_text(payload, encoding="utf-8")
(root / ".runtime" / "phase3-source" / "openapi.json").write_text(payload, encoding="utf-8")
print("Phase 2 schemas preserved; Phase 3 health/schema contracts exported.")
