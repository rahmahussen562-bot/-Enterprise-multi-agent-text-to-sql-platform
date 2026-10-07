"""Read only redacted stage/timing diagnostics for failed cancellation checks."""
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'.runtime/phase3-source/src/style.css').read_text(encoding='utf-8')
print('Login layout:',re.findall(r'\.login-dialog\{([^}]+)',source))
print('Provider key presence only:',{name:bool(os.environ.get(name)) for name in ('OPENAI_API_KEY','GEMINI_API_KEY')})
base=ROOT/'.runtime/phase04-verified-all'
for directory in base.glob('test_*'):
    if not any(part in directory.name for part in ('http_task_cancellation','graceful_shutdown','revoked_session')): continue
    path=directory/'jobs.sqlite'
    if not path.exists(): continue
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as connection:
        rows=connection.execute('SELECT created_at,status,response FROM jobs').fetchall()
        events=[json.loads(row[0]) for row in connection.execute('SELECT event FROM events ORDER BY sequence').fetchall()]
    print(json.dumps({'test':directory.name,'jobs':[{'status':status,'error_code':(json.loads(response or '{}')).get('error_code')} for _,status,response in rows],
        'stages':[{'agent':event.get('agent'),'status':event.get('status'),'elapsed_sec':round(event.get('timestamp',0)-rows[0][0],3)} for event in events] if rows else []},indent=2))
