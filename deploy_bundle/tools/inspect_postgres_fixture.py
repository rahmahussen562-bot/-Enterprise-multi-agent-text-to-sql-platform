"""Read-only native fixture diagnostics without exposing credentials or SQL."""
import json
from pathlib import Path
import re
import psycopg
root=Path(__file__).resolve().parents[1]/'.runtime/postgres'
admin=json.loads((root/'private/admin.json').read_text())
options=(root/'cluster/postmaster.opts').read_text()
port=re.search(r'-p[ "\\]+(\d+)',options).group(1)
print('Inspecting the owned native fixture.',flush=True)
with psycopg.connect(host='127.0.0.1',port=port,dbname='postgres',connect_timeout=5,**admin) as connection:
    rows=connection.execute('SELECT pid,datname,state,wait_event_type,wait_event FROM pg_stat_activity').fetchall()
    print(rows,flush=True)
