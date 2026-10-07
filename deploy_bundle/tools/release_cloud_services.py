"""Scope release API access to approved providers; print status, never credentials.

The input stores belong in .runtime/api-private/. GitHub secrets use LibSodium
sealed-box encryption and are read back only as names and update timestamps.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".runtime" / "api-private"
ACCOUNT = "d3691c8edea502ade020588b5292be0c"
REPOSITORY = "rahmahussen562-bot/-Enterprise-multi-agent-text-to-sql-platform"
PROJECT = "sentinelsql-portal"


def call(method, url, token=None, body=None):
    headers = {"Accept": "application/json", "User-Agent": "SentinelSQL-release"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if url.startswith("https://api.github.com/"):
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    result = requests.request(method, url, headers=headers, json=body, timeout=(12, 20), allow_redirects=False)
    try:
        value = result.json()
    except ValueError:
        value = {}
    return result.status_code, value


def github_token():
    path = PRIVATE / "github-release-auth.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["token"]
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token:
        return token
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    credential = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\npath=rahmahussen562-bot/-Enterprise-multi-agent-text-to-sql-platform.git\n\n",
                                capture_output=True, text=True, timeout=20, env=env)
    fields = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)
    return fields.get("password")


def execute(mode):
    report = {}
    if mode == "cloudflare":
        token = json.loads((PRIVATE / "cloudflare-release-auth.json").read_text(encoding="utf-8"))["token"]
        status, value = call("GET", "https://api.cloudflare.com/client/v4/user/tokens/verify", token)
        report["token_verification_http"] = status
        report["token_status"] = value.get("result", {}).get("status") if isinstance(value.get("result"), dict) else None
        report["error_codes"] = [error.get("code") for error in value.get("errors", [])]
        status, value = call("GET", f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/pages/projects/{PROJECT}", token)
        report["project_http"] = status
        result = value.get("result") or {}
        report["project_name"] = result.get("name")
        report["project_error_codes"] = [error.get("code") for error in value.get("errors", [])]
    else:
        token = github_token()
        report["github_auth_available"] = bool(token)
        if mode == "secrets":
            if not token:
                return report
            from nacl.public import PublicKey, SealedBox
            status, public = call("GET", f"https://api.github.com/repos/{REPOSITORY}/actions/secrets/public-key", token)
            report["public_key_http"] = status
            if status != 200:
                return report
            secrets_to_set = {
                "CLOUDFLARE_API_TOKEN": json.loads((PRIVATE / "cloudflare-release-auth.json").read_text(encoding="utf-8"))["token"],
                "CLOUDFLARE_ACCOUNT_ID": ACCOUNT,
            }
            tunnel_file = PRIVATE / "tunnel-token.txt"
            if tunnel_file.exists():
                secrets_to_set["TUNNEL_TOKEN"] = tunnel_file.read_text(encoding="utf-8").strip()
            box = SealedBox(PublicKey(base64.b64decode(public["key"])))
            report["secret_update_http"] = {}
            for name, secret_value in secrets_to_set.items():
                encrypted = base64.b64encode(box.encrypt(secret_value.encode("utf-8"))).decode("ascii")
                status, _ = call("PUT", f"https://api.github.com/repos/{REPOSITORY}/actions/secrets/{name}", token,
                                 {"encrypted_value": encrypted, "key_id": public["key_id"]})
                report["secret_update_http"][name] = status
            status, names = call("GET", f"https://api.github.com/repos/{REPOSITORY}/actions/secrets", token)
            report["secret_list_http"] = status
            report["secret_names"] = [x["name"] for x in names.get("secrets", [])]
        if mode == "runs":
            sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            status, value = call("GET", f"https://api.github.com/repos/{REPOSITORY}/actions/runs?head_sha={sha}&per_page=5", token)
            report["workflow_runs_http"] = status
            report["head_sha"] = sha
            report["workflow_runs"] = [{key: run.get(key) for key in
                ("html_url", "status", "conclusion", "head_sha", "name")} for run in value.get("workflow_runs", [])]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("cloudflare", "secrets", "runs"))
    args = parser.parse_args()
    try:
        report = execute(args.mode)
    except requests.RequestException as error:
        report = {"network_error_type": type(error).__name__, "provider": args.mode}
    except subprocess.TimeoutExpired:
        report = {"github_credential_probe": "timed out"}
    (ROOT / "docs" / ("PRODUCTION_" + args.mode.upper() + "_STATUS.json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
