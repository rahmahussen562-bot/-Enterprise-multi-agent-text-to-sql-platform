"""Remove historical test passwords from published PDFs without changing layout."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
for name in ("TEMP", "TMP", "TMPDIR"):
    os.environ[name] = str(ROOT / ".runtime" / "tmp")
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, TextStringObject

baseline = json.loads((ROOT / "docs" / "PHASE01_TEST_BASELINE.json").read_text(encoding="utf-8"))
historical = subprocess.run(["git", "show", baseline["source_revision"] + ":tests/test_auth.py"],
                            cwd=ROOT, capture_output=True, text=True, check=True).stdout
tree = ast.parse(historical)
passwords = []
for function in ast.walk(tree):
    if isinstance(function, ast.FunctionDef) and function.name in {
        "test_sales_analyst_authentication", "test_inventory_lead_authentication"
    }:
        call = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "authenticate")
        passwords.append(ast.literal_eval(call.args[1]))

inspection = []
for language in ("EN", "AR"):
    source = ROOT / "docs" / f"SentinelSQL_Enterprise_Documentation_{language}.pdf"
    reader = PdfReader(source)
    affected = [index for index, page in enumerate(reader.pages)
                if any(password in (page.extract_text() or "") for password in passwords)]
    record = {"file": source.name, "pages": len(reader.pages), "credential_pages": [i + 1 for i in affected]}
    if "--inspect" in sys.argv:
        inspection.append(record)
        continue
    writer = PdfWriter()
    replaced = 0

    def clean_string(value):
        global replaced
        if isinstance(value, TextStringObject):
            text = str(value)
            for password in passwords:
                replaced += text.count(password)
                text = text.replace(password, "[private]")
            return TextStringObject(text)
        return value

    for page in reader.pages:
        content = ContentStream(page.get_contents(), reader)
        for operands, operator in content.operations:
            if operator == b"TJ":
                for index, value in enumerate(operands[0]):
                    operands[0][index] = clean_string(value)
            elif operator in (b"Tj", b"'", b'"'):
                operands[-1] = clean_string(operands[-1])
        # Add only the edited page's reachable objects; do not clone obsolete
        # content streams containing old credentials into the output file.
        page.replace_contents(content)
        writer.add_page(page)
    if reader.metadata:
        writer.add_metadata({key: str(value) for key, value in reader.metadata.items() if value is not None})
    temporary = source.with_suffix(".redacted.pdf")
    writer.write(temporary)
    check = PdfReader(temporary)
    assert len(check.pages) == len(reader.pages)
    assert not any(password in (page.extract_text() or "") for page in check.pages for password in passwords)
    assert not any(password.encode() in temporary.read_bytes() for password in passwords)
    temporary.replace(source)
    record["replacements"] = replaced
    inspection.append(record)
    poppler = Path("C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe")
    output = ROOT / ".runtime" / "pdf-review"
    output.mkdir(parents=True, exist_ok=True)
    for index in affected:
        subprocess.run([str(poppler), "-f", str(index + 1), "-l", str(index + 1), "-scale-to", "1500", "-png",
                        str(source), str(output / language)], check=True)

print(json.dumps(inspection, indent=2))
if "--inspect" not in sys.argv:
    (ROOT / "docs" / "PHASE02_CREDENTIAL_REDACTION.json").write_text(json.dumps(inspection, indent=2) + "\n", encoding="utf-8")
