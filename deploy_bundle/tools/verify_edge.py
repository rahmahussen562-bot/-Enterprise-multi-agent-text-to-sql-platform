"""Probe live ingress using trusted TLS, without bypassing certificate validation."""
import json
import os
import ssl
import urllib.request

base = os.environ['API_ORIGIN'].rstrip('/')
if not base.startswith('https://'):
    raise SystemExit('Live API ingress requires HTTPS.')
context = ssl.create_default_context(cafile=os.getenv('SENTINEL_EDGE_CA_FILE') or None)
with urllib.request.urlopen(base+'/api/v1/health',context=context,timeout=10) as response:
    result=json.load(response)
    if response.status!=200 or result.get('status')!='ready' or result.get('ast_validation')!='ready':
        raise SystemExit('Edge health probe failed.')
print('Live API ingress passed verified TLS and AST health checks.')
