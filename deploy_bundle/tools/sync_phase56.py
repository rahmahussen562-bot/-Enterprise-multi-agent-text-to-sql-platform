"""Publish staged frontend/workflow changes only to the user-requested D: repository."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
repository=root.parent.resolve()
if str(repository).replace('\\','/').casefold()!='d:/bird-interact':
    raise SystemExit('Unexpected repository destination.')
subprocess.run([sys.executable,str(root/'tools/provision_phase03.py')],check=True)
workflow=repository/'.github/workflows/deploy.yml'
workflow.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(root/'.runtime/phase56-source/deploy.yml',workflow)
front=repository/'frontend'
path=front/'package-lock.json'
shutil.copyfile(path,root/'.runtime/phase3-source/package-lock.json')
print('Phase 5/6 workflow installed: '+str(workflow))
