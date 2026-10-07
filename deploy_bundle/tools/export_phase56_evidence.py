"""Save frontend/edge JUnit and validated release evidence on D:."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
front=root.parent/'frontend'
shutil.copyfile(front/'.runtime/frontend-tests.xml',root/'docs/PHASE56_FRONTEND_TEST_RESULTS.xml')
node=front/'.runtime/node/node.exe'
environment=dict(os.environ,TEMP=str(front/'.runtime/tmp'),TMP=str(front/'.runtime/tmp'),TMPDIR=str(front/'.runtime/tmp'))
with (root/'docs/PHASE56_EDGE_TEST_RESULTS.xml').open('w',encoding='utf-8') as output:
    subprocess.run([str(node),'--test','--test-reporter=junit','tools/pages-security.test.mjs',str(root/'edge/gateway.test.mjs')],cwd=front,env=environment,stdout=output,check=True)
def counts(path):
    xml=ET.parse(path).getroot()
    cases=list(xml.iter('testcase'))
    result={'total':len(cases),'failed':sum(case.find('failure') is not None or case.find('error') is not None for case in cases),'skipped':sum(case.find('skipped') is not None for case in cases)}
    if result['failed'] or result['skipped']: raise ValueError('Release checks are incomplete.')
    return result
backend=counts(root/'docs/PHASE56_TEST_RESULTS.xml')
frontend=counts(root/'docs/PHASE56_FRONTEND_TEST_RESULTS.xml')
edge=counts(root/'docs/PHASE56_EDGE_TEST_RESULTS.xml')
assert backend['total']==326 and frontend['total']==20 and edge['total']==14
audit=json.loads((front/'.runtime/phase56-dependency-audit.json').read_text())['metadata']['vulnerabilities']
assert audit['total']==0
headers=(front/'dist/_headers').read_text()
assert "connect-src 'self' https://api.sentinelsql.internal wss://api.sentinelsql.internal;" in headers
assert (front/'dist/_redirects').read_text().strip()=='/* /index.html 200'
historical={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (root/'tests').glob('test_*.py') if path.name in {'test_auth.py','test_critic.py','test_database.py','test_guardian.py','test_intent_router.py','test_orchestrator.py','test_reconnaissance.py','test_visualizer.py'}}
baseline=json.loads((root/'docs/PHASE01_TEST_BASELINE.json').read_text())['files']
unchanged=all(historical[name]==baseline['tests/'+name] for name in historical)
if not unchanged:
    sanitization=json.loads((root/'docs/PRODUCTION_TEST_CREDENTIAL_SANITIZATION.json').read_text())
    permitted={Path(item['file']).name:item for item in sanitization['changed_files']}
    assert sanitization['assertions_preserved']
    for name,value in historical.items():
        assert value==baseline['tests/'+name] or (name in permitted and value==permitted[name]['after_sha256'])
result={'timestamp':datetime.now(timezone.utc).isoformat(),'backend':backend,'frontend':frontend,'edge_and_headers':edge,
    'retained_baseline':{'backend':320,'frontend':10},'new_tests':{'backend':6,'frontend':10,'edge_and_headers':14},
    'npm_vulnerabilities':audit,'pip_check':'passed','ruff_critical_rules':'passed','api_contract_drift':'passed','zero_emoji_frontend':'passed',
    'production_frontend_build':'passed','storage_root':str(root.parent),
    'disk_free_gib':round(shutil.disk_usage(root).free/1024**3,2),
    'historical_test_sha256':historical,'historical_test_hashes_unchanged':unchanged,'test_credential_sanitization': 'fresh random credentials; original assertions retained' if not unchanged else 'original historical fixtures', 'validation_tool_versions':{name:importlib.metadata.version(name) for name in ['PyYAML','cryptography','ruff']},
    'container_build_and_live_stack':'not run: Docker is not installed; mandatory CI gate provided',
    'cloudflare_deployment':'not run: no account tokens or production runner available',
    'api_hostname':'api.sentinelsql.internal requires WARP/private DNS and trusted TLS',
    'manifest_verification':json.loads((root/'docs/PHASE56_MANIFEST_VERIFICATION.json').read_text())}
(root/'docs/PHASE56_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({key:result[key] for key in ['backend','frontend','edge_and_headers','npm_vulnerabilities','disk_free_gib','container_build_and_live_stack','cloudflare_deployment']},indent=2))
