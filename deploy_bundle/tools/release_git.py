"""Explicit release staging/commit/push, preserving unrelated local changes."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
EXPECTED = "https://github.com/rahmahussen562-bot/-Enterprise-multi-agent-text-to-sql-platform.git"
MESSAGE = "feat: v1.0.0 production release - fincore postgresql, decoupled react spa and cloudflare edge pipeline"


def run(*args, env=None, timeout=120):
    result = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                            text=True, env=env, timeout=timeout)
    if result.returncode:
        # Never print process environments or authentication diagnostics.
        raise RuntimeError("Git operation failed: " + args[0] + " (exit " + str(result.returncode) + ")")
    return result.stdout.strip()


def gate():
    document = ET.parse(ROOT / "docs" / "PRODUCTION_TEST_RESULTS.xml").getroot()
    tests = list(document.iter("testcase"))
    if len(tests) != 326 or any(x.find("failure") is not None or x.find("error") is not None or x.find("skipped") is not None for x in tests):
        raise RuntimeError("The complete 326-test release gate has not passed.")
    subprocess.run([sys.executable, str(ROOT / "tools" / "audit_release.py"), "--staged"],
                   cwd=ROOT, check=True)
    names = run("diff", "--cached", "--name-only", "--diff-filter=D").splitlines()
    if names:
        raise RuntimeError("Release unexpectedly stages deletions; inspect before committing.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("stage", "commit", "push", "remote"))
    args = parser.parse_args()
    if REPO != Path("D:/BIRD-Interact") or run("remote", "get-url", "origin") != EXPECTED:
        raise SystemExit("Unexpected repository or origin; release aborted.")
    if run("branch", "--show-current") != "main":
        raise SystemExit("Release expects main; no branch reset performed.")
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    auth = ROOT / ".runtime" / "api-private" / "github-release-auth.json"
    if auth.exists():
        token = json.loads(auth.read_text(encoding="utf-8"))["token"]
        credential = base64.b64encode(("x-access-token:" + token).encode()).decode()
        # Keep the authorization header out of command-line arguments and Git config files.
        environment.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                           GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + credential)
    if args.operation == "stage":
        subprocess.run([sys.executable, str(ROOT / "tools" / "bind_release_config.py")], cwd=ROOT, check=True)
        run("add", "--", ".gitignore", ".gitattributes", "README.md", ".github/workflows/deploy.yml", "frontend", "deploy_bundle")
        count = len(run("diff", "--cached", "--name-only").splitlines())
        print(json.dumps({"staged_release_files": count, "scope": ["frontend", "deploy_bundle", ".github/workflows/deploy.yml", "root release metadata"]}))
    elif args.operation == "commit":
        gate()
        # Include the scan evidence generated against the actual staging area.
        run("add", "--", "deploy_bundle/docs/PRODUCTION_STAGED_SECURITY_SCAN.json")
        run("commit", "-m", MESSAGE)
        print(json.dumps({"commit": run("rev-parse", "HEAD"), "message": MESSAGE}))
    else:
        report = {"operation": args.operation, "github_private_credential_present": auth.exists()}
        try:
            if args.operation == "remote":
                value = run("ls-remote", "origin", "refs/heads/main", env=environment, timeout=60)
                report["remote_main"] = value.split()[0] if value else None
            else:
                run("push", "origin", "HEAD:main", env=environment, timeout=120)
                remote = run("ls-remote", "origin", "refs/heads/main", env=environment, timeout=60)
                report["commit"] = run("rev-parse", "HEAD")
                report["remote_main"] = remote.split()[0] if remote else None
                report["confirmed"] = report["commit"] == report["remote_main"]
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            report["confirmed"] = False
            report["error"] = str(error) if isinstance(error, RuntimeError) else "Git network operation timed out."
        (ROOT / "docs" / ("PRODUCTION_GIT_" + args.operation.upper() + ".json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
