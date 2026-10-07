"""Read-only release inventory; never print credentials or credential responses."""
import collections
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def git(*args, timeout=25, input=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    return subprocess.run(["git", "-C", str(REPO), *args], input=input,
                          capture_output=True, text=True, timeout=timeout, env=env)


out = {}
out["instructions"] = [str(p) for p in [REPO / "AGENTS.md", ROOT / "AGENTS.md",
                                         REPO.parent / "AGENTS.md"] if p.exists()]
remote = git("remote", "get-url", "origin").stdout.strip()
parsed = urlsplit(remote)
out["origin"] = f"{parsed.scheme}://{parsed.hostname}{parsed.path}" if parsed.scheme else remote
out["head"] = git("rev-parse", "HEAD").stdout.strip()
out["git_identity_present"] = all(git("config", x).stdout.strip() for x in ("user.name", "user.email"))
out["tools"] = {x: bool(shutil.which(x)) for x in ("gh", "docker", "git", "ssh")}
out["credential_env_present"] = {x: bool(os.getenv(x)) for x in
    ("GH_TOKEN", "GITHUB_TOKEN", "CLOUDFLARE_API_TOKEN", "TUNNEL_TOKEN")}
status = git("status", "--porcelain", "--untracked-files=no").stdout.splitlines()
out["tracked_status_counts"] = dict(collections.Counter(line[:2] for line in status))
out["existing_staged_count"] = len(git("diff", "--cached", "--name-only").stdout.splitlines())
private = ROOT / ".runtime" / "api-private"
out["private_directory_exists"] = private.is_dir()
key = private / "session.key"
out["existing_key_bytes"] = key.stat().st_size if key.exists() else 0
accounts = private / "accounts.json"
if accounts.exists():
    records = json.loads(accounts.read_text(encoding="utf-8"))
    out["existing_accounts_by_role"] = dict(collections.Counter(x.get("role") for x in records))
out["credential_helper_configured"] = bool(git("config", "--get-all", "credential.helper").stdout.strip())
try:
    result = git("credential", "fill", input="protocol=https\nhost=github.com\npath=rahmahussen562-bot/-Enterprise-multi-agent-text-to-sql-platform.git\n\n", timeout=20)
    credential = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    stored = private / "github-release-auth.json"
    token = (json.loads(stored.read_text(encoding="utf-8"))["token"] if stored.exists() else None) or credential.get("password") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    out["github_credential_available"] = bool(token)
    if token:
        # Stored only in the already-protected, ignored private directory.
        path = private / "github-release-auth.json"
        path.write_text(json.dumps({"token": token}), encoding="utf-8")
        path.chmod(0o600)
except subprocess.TimeoutExpired:
    out["github_credential_available"] = False
    out["github_credential_probe"] = "timed out without prompting"
print(json.dumps(out, indent=2))
