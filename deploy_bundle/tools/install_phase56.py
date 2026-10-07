"""Install only deployment validation tooling into the existing D: virtual environment."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
if os.name=='nt' and (root.drive.upper()!='D:' or Path(sys.prefix).resolve()!=root/'.venv'):
    raise SystemExit('Use the project D: environment.')
for name,folder in {'TEMP':'tmp','TMP':'tmp','TMPDIR':'tmp','PIP_CACHE_DIR':'pip-cache'}.items():
    directory=root/'.runtime'/folder
    directory.mkdir(parents=True,exist_ok=True)
    os.environ[name]=str(directory)
os.environ['PIP_DISABLE_PIP_VERSION_CHECK']='1'
subprocess.run([sys.executable,'-B','-m','pip','install','--only-binary=:all:','-r',str(root/'requirements-deployment.txt')],check=True)
subprocess.run([sys.executable,'-B','-m','pip','check'],check=True)
