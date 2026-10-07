"""Bind approved public deployment identifiers and repository ignore rules."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ACCOUNT = "d3691c8edea502ade020588b5292be0c"
if REPO != Path("D:/BIRD-Interact"):
    raise SystemExit("Unexpected release workspace.")

frontend_config = REPO / "frontend" / "wrangler.toml"
text = frontend_config.read_text(encoding="utf-8")
if "account_id" not in text:
    text = text.replace('name = "sentinelsql-portal"', 'name = "sentinelsql-portal"\naccount_id = "' + ACCOUNT + '"')
frontend_config.write_text(text, encoding="utf-8")
source = ROOT / ".runtime" / "phase3-source" / "wrangler.toml"
if source.exists():
    source.write_text(text, encoding="utf-8")

ignore = REPO / ".gitignore"
historical = (ignore.read_text(encoding="utf-8") if ignore.exists() else
              subprocess.run(["git", "-C", str(REPO), "show", "HEAD:.gitignore"],
                             capture_output=True, text=True, check=True).stdout)
marker = "# SentinelSQL production release isolation"
if marker not in historical:
    historical += "\n\n" + marker + "\n" + "\n".join([
        ".runtime/", "SECRETS_DIR/", "secrets/", ".env", ".env.*", "!.env.example", "!.env.production.example",
        "*.key", "*.pem", "*.crt", "*.db", "*.sqlite", "*.sqlite3", "*.db-wal", "*.db-shm",
        "*.sqlite-wal", "*.sqlite-shm", "*.sqlite3-wal", "*.sqlite3-shm", "pgdata/", "postgres-data/",
        ".venv/", "venv/", "node_modules/", "dist/", ".next/", "build/", ".pytest_cache/", ".ruff_cache/",
        "pytest-cache*/", "pytest-tmp*/", "*.sql.dump", "*.dump", "*.backup", "*.p12", "*.pfx",
        "credentials.json", "operator-credentials.json", "github-release-auth.json", "cloudflare-release-auth.json",
    ]) + "\n"
ignore.write_text(historical, encoding="utf-8")

attributes = REPO / ".gitattributes"
current = attributes.read_text(encoding="utf-8") if attributes.exists() else ""
if "# SentinelSQL portable container and source files" not in current:
    current += "\n# SentinelSQL portable container and source files\n" + "\n".join([
        "*.sh text eol=lf", "*.py text eol=lf", "*.mjs text eol=lf", "*.ts text eol=lf", "*.tsx text eol=lf",
        "*.yml text eol=lf", "*.toml text eol=lf", "*.sql text eol=lf", "*.pdf binary", "*.gz binary",
    ]) + "\n"
attributes.write_text(current, encoding="utf-8")

# The current product lives in these directories; keep the repository entry point current.
readme = REPO / "README.md"
readme.write_text("""# SentinelSQL Enterprise

Enterprise Text-to-SQL Gateway and Deterministic Hallucination Defense for FinCore banking analytics.

The production application is a React/TypeScript SPA in `frontend/` and an asynchronous FastAPI service in
`deploy_bundle/`. The SQL engine combines server-governed RBAC, PostgreSQL FORCE RLS, scoped AST validation,
closed-world schema grounding, bounded workloads and driver cancellation.

- [Deployment and operations](deploy_bundle/docs/CLOUDFLARE_DEPLOYMENT.md)
- [Architecture audit and roadmap](deploy_bundle/docs/ARCHITECTURAL_AUDIT_AND_MODERNIZATION.md)
- [Backend setup and verification](deploy_bundle/README.md)
- [FinCore schema](deploy_bundle/data/fincore_schema.sql)
- [Production workflow](.github/workflows/deploy.yml)

Cloudflare Pages project: `sentinelsql-portal`. The API target `api.sentinelsql.internal` requires managed private
DNS, Cloudflare Zero Trust connectivity and an institution-trusted certificate. Production release gates verify
the backend before publishing the frontend. Operator credentials and cryptographic material are provisioned
locally and must never be committed.
""", encoding="utf-8")
print("Approved Cloudflare account bound in both Wrangler configurations; repository ignore rules restored.")
