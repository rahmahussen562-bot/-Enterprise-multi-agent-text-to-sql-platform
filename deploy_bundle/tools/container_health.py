"""Dependency-free ASGI/AST liveness probe; database readiness is checked separately."""
import json
import urllib.request

with urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3) as response:
    body = json.load(response)
    if response.status != 200 or body.get('status') != 'ready':
        raise SystemExit(1)
