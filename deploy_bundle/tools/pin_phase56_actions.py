"""Pin reviewed action commits obtained from official GitHub release links."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
references={
    'actions/checkout@v6':('d23441a48e516b6c34aea4fa41551a30e30af803','v6.1.0'),
    'cloudflare/wrangler-action@v4':('953926a2e2182532811c01a25e53647d93bf07c0','v4.1.3'),
    'actions/setup-python@v6':('ece7cb06caefa5fff74198d8649806c4678c61a1','v6.3.0'),
    'actions/setup-node@v6':('249970729cb0ef3589644e2896645e5dc5ba9c38','v6.5.0'),
    'actions/upload-artifact@v6':('b7c566a772e6b6bfb58ed0dc250532a479d7789f','v6.0.0'),
    'actions/download-artifact@v8':('70fc10c6e5e1ce46ad2ea6f2b72d43f7d47b13c3','v8.0.0'),
    'docker/setup-buildx-action@v3':('8d2750c68a42422c14e847fe6c8ac0403b4cbd6f','v3.12.0'),
    'docker/login-action@v3':('c94ce9fb468520275223c153574b00df6fe4bcc9','v3.7.0'),
    'docker/build-push-action@v7':('c3c9e263c25d99ce0380d002d59b67737d91b0dc','v7.4.0'),
}
path=root/'.runtime/phase56-source/deploy.yml'
text=path.read_text(encoding='utf-8')
for name,(sha,tag) in references.items():
    text=text.replace(name,name.split('@')[0]+'@'+sha+' # '+tag)
path.write_text(text,encoding='utf-8')
(root/'docs/PHASE56_ACTION_PINS.json').write_text(json.dumps({name:{'commit':sha,'release':tag,'source':'https://github.com/'+name.split('@')[0]+'/commit/'+sha} for name,(sha,tag) in references.items()},indent=2)+'\n',encoding='utf-8')
