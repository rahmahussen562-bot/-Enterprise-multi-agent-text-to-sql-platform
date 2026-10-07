import json
import re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
versions=json.loads((root/'.runtime/phase56-tools/versions.json').read_text())['images']
references={name.removeprefix('library/'):name.removeprefix('library/')+'@'+digest for name,digest in versions.items()}
for name in ['Dockerfile','docker-compose.prod.yml','.env.production.example','tools/run_ci_backend.py']:
    path=root/name
    value=path.read_text(encoding='utf-8')
    for image,reference in references.items():
        value=re.sub(re.escape(image)+r'(?!@)',lambda _: reference,value)
    path.write_text(value,encoding='utf-8')
(root/'docs/PHASE56_IMAGE_PINS.json').write_text(json.dumps({'registry':'https://registry-1.docker.io','verified_tags':versions},indent=2)+'\n',encoding='utf-8')
