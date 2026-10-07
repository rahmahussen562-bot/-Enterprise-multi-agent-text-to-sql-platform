"""Export banking contracts while checking legacy REST request compatibility."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api.main import create_app

specification=create_app().openapi()
baseline=json.loads((ROOT/'docs/PHASE03_OPENAPI.json').read_text(encoding='utf-8'))
assert specification['paths']==baseline['paths']
expected_changes={'SessionClaims','SchemaResponse'}
for name,definition in baseline['components']['schemas'].items():
    actual=specification['components']['schemas'][name]
    if name not in expected_changes:
        assert actual==definition,name
        continue
    restored=json.loads(json.dumps(actual))
    restored['properties']['role']=definition['properties']['role']
    assert set(definition['properties']['role']['enum'])<=set(actual['properties']['role']['enum'])
    if name=='SchemaResponse':
        restored['properties']['dialect']=definition['properties']['dialect']
        assert actual['properties']['dialect']['enum']==['tsql','postgres']
    assert restored==definition,name
payload=json.dumps(specification,indent=2)+'\n'
(ROOT/'docs/PHASE04_OPENAPI.json').write_text(payload,encoding='utf-8')
(ROOT/'.runtime/phase3-source/openapi.json').write_text(payload,encoding='utf-8')
print('Phase 4 OpenAPI exported: existing REST paths/requests unchanged; banking roles and postgres added.')
