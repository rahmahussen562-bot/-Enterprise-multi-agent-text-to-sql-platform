from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'README.md'
text=path.read_text(encoding='utf-8')
if 'Phase 5/6 production package' not in text:
    text+='\n\n## Phase 5/6 production package\n\nThe decoupled API and React portal now have a parameterized Cloudflare deployment package. See [the deployment runbook](docs/CLOUDFLARE_DEPLOYMENT.md) for private `.internal` routing, public-zone alternatives, Docker/TLS/secret provisioning, Pages builds and CI/CD. The root workflow is `../.github/workflows/deploy.yml`; build contexts are `deploy_bundle/` and `frontend/`.\n\nVerification: 326 backend tests, 20 frontend tests and 14 edge/header tests passed, with zero npm vulnerabilities. [Execution report](docs/PHASE56_EXECUTION_REPORT.md). Docker/live Cloudflare deployment remains pending a provisioned engine, runner and protected credentials.\n'
    path.write_text(text,encoding='utf-8')
for name in ['read_phase56_context.py','read_phase56_details.py','prepare_phase56_frontend.py','fix_phase56_voice.py']:
    target=(root/'tools'/name).resolve()
    assert target.is_relative_to((root/'tools').resolve())
    target.unlink(missing_ok=True)
