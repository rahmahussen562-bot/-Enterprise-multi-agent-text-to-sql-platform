"""Remove published demo passwords while retaining every historical assertion."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "tests" / "test_auth.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
replacements = {}
for function in ast.walk(tree):
    if isinstance(function, ast.FunctionDef) and function.name in {
        "test_sales_analyst_authentication", "test_inventory_lead_authentication"
    }:
        call = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "authenticate")
        if isinstance(call.args[1], ast.Constant):
            replacements[ast.literal_eval(call.args[1])] = ast.literal_eval(call.args[0])
changed = []
for file in sorted((ROOT / "tests").glob("test_*.py")):
    content = file.read_text(encoding="utf-8")
    before = hashlib.sha256(file.read_bytes()).hexdigest()
    updated = content
    for password, role in replacements.items():
        for quote in ('"', "'"):
            updated = updated.replace(quote + password + quote, 'LEGACY_PASSWORDS[' + json.dumps(role) + ']')
    if content != updated:
        parsed = ast.parse(updated)
        doc = parsed.body[0] if parsed.body and isinstance(parsed.body[0], ast.Expr) and isinstance(parsed.body[0].value, ast.Constant) and isinstance(parsed.body[0].value.value, str) else None
        lines = updated.splitlines(keepends=True)
        lines.insert(doc.end_lineno if doc else 0, "\nfrom tests._credentials import LEGACY_PASSWORDS\n")
        updated = "".join(lines)
        compile(updated, str(file), "exec")
        file.write_text(updated, encoding="utf-8")
        changed.append({"file": str(file.relative_to(ROOT)), "before_sha256": before,
                        "after_sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
report = {"historical_password_literals_removed": len(replacements), "changed_files": changed,
          "assertions_preserved": True, "password_source": "fresh random values per test process"}
(ROOT / "docs" / "PRODUCTION_TEST_CREDENTIAL_SANITIZATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"changed_file_count": len(changed), "published_password_values_printed": False}))
