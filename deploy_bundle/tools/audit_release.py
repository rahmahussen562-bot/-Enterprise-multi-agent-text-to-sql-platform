"""Audit release contents without ever displaying matched secret values.

Scans the candidate files or actual Git index, including decompressed PDF text.
It checks ignored private paths, known local secret material, provider tokens,
private key blocks and published credentials from the historical test baseline.
"""
import argparse
import ast
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PRIVATE = ROOT / ".runtime" / "api-private"


def git(*args, input=None):
    return subprocess.run(["git", "-C", str(REPO), *args], input=input,
                          capture_output=True, check=True).stdout


def forbidden_values():
    values = []
    for name in ("cloudflare-release-auth.json", "github-release-auth.json"):
        path = PRIVATE / name
        if path.exists():
            values.append((name, json.loads(path.read_text(encoding="utf-8"))["token"].encode()))
    key = PRIVATE / "session.key"
    if key.exists():
        value = key.read_bytes()
        values.extend(("session signing key", x) for x in (value, value.hex().encode(), base64.b64encode(value)))
    path = PRIVATE / "operator-credentials.json"
    if path.exists():
        values.extend(("local operator password", x["password"].encode()) for x in json.loads(path.read_text(encoding="utf-8")))
    baseline = json.loads((ROOT / "docs" / "PHASE01_TEST_BASELINE.json").read_text(encoding="utf-8"))
    source = git("show", baseline["source_revision"] + ":tests/test_auth.py").decode()
    tree = ast.parse(source)
    for function in ast.walk(tree):
        if isinstance(function, ast.FunctionDef) and function.name in {
            "test_sales_analyst_authentication", "test_inventory_lead_authentication"
        }:
            call = next(x for x in ast.walk(function) if isinstance(x, ast.Call)
                        and isinstance(x.func, ast.Name) and x.func.id == "authenticate")
            values.append(("published demo password", ast.literal_eval(call.args[1]).encode()))
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    if args.staged:
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
    else:
        names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "deploy_bundle", "frontend", ".github").decode().split("\0")
        names += [".gitignore", "README.md", *git("diff", "--name-only", "--diff-filter=M", "-z", "--", "agents", "core").decode().split("\0")]
    names = sorted(set(x for x in names if x))
    staged_content = {}
    if args.staged and names:
        stream = io.BytesIO(git("cat-file", "--batch", input="".join(":" + name + "\n" for name in names).encode()))
        for name in names:
            header = stream.readline().split()
            if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
                raise RuntimeError("Could not inspect a staged blob; scan fails closed.")
            length = int(header[2])
            staged_content[name] = stream.read(length)
            if len(staged_content[name]) != length or stream.read(1) != b"\n":
                raise RuntimeError("Incomplete staged blob; scan fails closed.")
    private_paths = ["SECRETS_DIR/token.txt", ".runtime/api-private/accounts.json", "deploy_bundle/.runtime/api-private/session.key",
                     "deploy_bundle/.runtime/api-private/cloudflare-release-auth.json", "deploy_bundle/test.pem",
                     "deploy_bundle/test.crt", "deploy_bundle/.env.production", "frontend/.env.production",
                     "frontend/node_modules/example/index.js", "frontend/dist/index.html", "deploy_bundle/data/local.sqlite3",
                     "deploy_bundle/pgdata/PG_VERSION"]
    missing = [name for name in private_paths if subprocess.run(["git", "-C", str(REPO), "check-ignore", "--no-index", "--quiet", name]).returncode]
    values = forbidden_values()
    patterns = {
        "provider token": re.compile(rb"(?:cfut_|ghp_|github_pat_|AIza)[A-Za-z0-9_-]{20,}"),
        "private key block": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
        "credential URL": re.compile(rb"(?:postgres(?:ql)?|mysql|https?)://[^\s/:'\"]+:[^\s@/'\"]+@"),
    }
    findings = []
    synthetic_negative_urls = []
    scanned = 0
    for name in names:
        if args.staged:
            content = staged_content[name]
        else:
            file = REPO / name
            if not file.is_file():
                continue
            content = file.read_bytes()
        scanned += 1
        path = Path(name)
        if any(part in {".runtime", "node_modules", "SECRETS_DIR", "secrets"} for part in path.parts) or path.suffix in {".key", ".pem", ".crt", ".db", ".sqlite", ".sqlite3", ".pfx", ".p12"}:
            findings.append({"file": name, "category": "private/build file in release"})
        sources = [content]
        if path.suffix == ".pdf":
            from pypdf import PdfReader
            sources += [(page.extract_text() or "").encode() for page in PdfReader(io.BytesIO(content)).pages]
        if name.endswith(".gz"):
            sources.append(gzip.decompress(content))
        for category, value in values:
            if any(value in source for source in sources):
                findings.append({"file": name, "category": category})
        for category, pattern in patterns.items():
            matches = [match.group() for source in sources for match in pattern.finditer(source)]
            if category == "credential URL" and matches:
                # Published negative tests deliberately reject dummy URL userinfo.
                # This narrow exception never applies to configuration or live material.
                dummy = []
                if name in {"frontend/src/api/routing.test.ts", "deploy_bundle/docs/PHASE56_FRONTEND_TEST_RESULTS.xml"}:
                    dummy = [b"https://" + b"user:secret@"]
                if name == "frontend/tools/pages-security.test.mjs":
                    dummy = [b"https://" + b"user:pw@"]
                if dummy and all(match in dummy for match in matches):
                    synthetic_negative_urls.append(name)
                    continue
            if matches:
                findings.append({"file": name, "category": category})
    report = {"mode": "staged" if args.staged else "candidate", "scanned_files": scanned,
              "required_ignore_rules_verified": not missing, "unignored_private_paths": missing,
              "findings": findings, "synthetic_negative_test_urls": synthetic_negative_urls,
              "secret_values_printed": False,
              "pass": not findings and not missing}
    output = ROOT / "docs" / ("PRODUCTION_STAGED_SECURITY_SCAN.json" if args.staged else "PRODUCTION_CANDIDATE_SECURITY_SCAN.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
