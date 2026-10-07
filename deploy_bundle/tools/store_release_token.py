"""Accept a deployment token without echo and store it in the private directory."""
import getpass
from pathlib import Path
import sys

from bootstrap_release import private_json, protect

root = Path(__file__).resolve().parents[1]
private = root / ".runtime" / "api-private"
if len(sys.argv) != 2 or sys.argv[1] not in ("cloudflare", "github"):
    raise SystemExit("Choose the approved cloudflare or github credential store.")
protect(private)
token = getpass.getpass("Credential input (hidden): ")
if not token or any(value.isspace() for value in token):
    raise SystemExit("Invalid credential input; nothing stored.")
private_json(private / (sys.argv[1] + "-release-auth.json"), {"token": token})
print("Credential stored in the ignored private directory; value was not echoed.")
