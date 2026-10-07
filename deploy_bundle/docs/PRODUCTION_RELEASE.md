# SentinelSQL v1.0.0 release preparation

The approved Cloudflare account is `d3691c8edea502ade020588b5292be0c`, with Pages project
`sentinelsql-portal`. Both `deploy_bundle/edge/wrangler.toml` and `frontend/wrangler.toml`
bind this public identifier. GitHub Actions continues to obtain it from the encrypted
`CLOUDFLARE_ACCOUNT_ID` repository secret.

The canonical production application is in `deploy_bundle/` and `frontend/`. Release staging
selects these directories, the production workflow and repository release metadata explicitly.
Pre-existing deletions and source edits outside this scope are preserved locally.

## Local private bootstrap

Run from `D:\BIRD-Interact\deploy_bundle`:

```cmd
.venv\Scripts\python.exe tools\bootstrap_release.py
```

The idempotent script preserves existing accounts and signing keys. Its private store is
`D:\BIRD-Interact\deploy_bundle\.runtime\api-private\`:

- `session.key`: 32 cryptographically random bytes.
- `accounts.json`: server-owned banking roles and salted PBKDF2-SHA256 password hashes
  with 310,000 iterations; it contains no plaintext passwords.
- `operator-credentials.json`: generated initial passwords for local synthetic operators,
  restricted to the local owner and SYSTEM on Windows. Treat this as private onboarding material.
- `cloudflare-release-auth.json`: local deployment token, accepted through hidden input.
- `github-release-auth.json`: optional GitHub release credential supplied securely by the operator.

The three synthetic operators are `synthetic_branch_analyst`, `synthetic_compliance_officer`
and `synthetic_fraud_investigator`. No password or token is printed. The bootstrap verifies
signed login, protected classification, tampered-token rejection and disjoint role table scopes
with `SENTINEL_DEMO_MODE=1`. This verifies local authentication; production PostgreSQL login
mappings and institution-specific branch/case assignments must be provisioned separately.

## Security and verification

The root and bundle ignore rules exclude runtime directories, `SECRETS_DIR/`, keys,
certificates, production environment files, virtual environments, build outputs, package caches,
local database files and PostgreSQL clusters. LF checkout rules keep container shell entry points
portable on Linux and Windows runners.

Historical test assertions remain intact. Published demo passwords were replaced with random
passwords generated per test process. The sanitizer records the five intentionally changed source
hashes in `PRODUCTION_TEST_CREDENTIAL_SANITIZATION.json`; older phase reports describe the
earlier, unchanged source baseline.

```cmd
.venv\Scripts\python.exe tools\audit_release.py
.venv\Scripts\python.exe tools\run_phase01_tests.py --basetemp=.runtime/production-release-test-temp-final --junitxml=docs/PRODUCTION_TEST_RESULTS.xml --tb=short -q
.venv\Scripts\python.exe tools\release_git.py stage
.venv\Scripts\python.exe tools\audit_release.py --staged
.venv\Scripts\python.exe tools\release_git.py commit
.venv\Scripts\python.exe tools\release_git.py push
```

The commit command fails unless all 326 backend checks pass with no skipped cases, the Git index
passes the secret scan and no deletion is staged. PDF text and compressed fixtures are inspected.
The only credential-URL exceptions are explicit dummy inputs in frontend rejection tests and
their JUnit names; configuration files and actual local/provider secrets have no exception.

## Provider provisioning and release tracking

```cmd
.venv\Scripts\python.exe tools\install_release_verifiers.py
.venv\Scripts\python.exe tools\release_cloud_services.py cloudflare
.venv\Scripts\python.exe tools\release_cloud_services.py secrets
.venv\Scripts\python.exe tools\release_cloud_services.py runs
```

GitHub secret provisioning uses the repository public key and LibSodium sealed-box encryption.
The credential must have Contents write for pushing and Actions Secrets write for provisioning;
a classic token also needs `workflow` scope to update a workflow. No credential is added to a
remote URL, Git configuration file or process argument.

Required Actions secrets are `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and `TUNNEL_TOKEN`.
The Cloudflare token needs Pages Edit access for the bound account. A local private
`tunnel-token.txt`, when supplied, can be encrypted into the `TUNNEL_TOKEN` repository secret.
Production deployment also requires an online runner labeled `sentinelsql-production`, its
private Compose environment, database identities and trusted TLS material described in
[the deployment runbook](CLOUDFLARE_DEPLOYMENT.md).

The configured `api.sentinelsql.internal` hostname uses managed private DNS/WARP connectivity
and institution-trusted TLS. It is not a public Internet API hostname. The workflow verifies
live backend connectivity before deploying the frontend.

Read `PRODUCTION_CLOUDFLARE_STATUS.json`, `PRODUCTION_SECRETS_STATUS.json` and
`PRODUCTION_GIT_PUSH.json` for actual provider outcomes. An active Cloudflare token alone
does not establish Pages authorization or a completed deployment. The `runs` command returns
an actual Actions run URL only after GitHub observes the corresponding pushed commit.
