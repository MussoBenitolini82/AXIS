"""Local-only Ollama guard. Cloud-backed models are refused before any request reaches them."""
import json, os, urllib.error, urllib.parse, urllib.request

DEFAULT_MODEL='qwen3:8b'
BASE='http://127.0.0.1:11434'
LOOPBACK={'127.0.0.1','localhost','::1'}

class CloudModelError(ValueError):
    """The model is cloud-backed or otherwise not a local Ollama model."""

def model_name():
    return os.getenv('VECTOR_MODEL',DEFAULT_MODEL)

def api_url(route,base=BASE):
    """Ollama API URL on a loopback host only."""
    host=urllib.parse.urlsplit(base).hostname
    if host not in LOOPBACK:raise CloudModelError('Ollama adresi yalnızca yerel (127.0.0.1) olabilir: '+str(base))
    return base.rstrip('/')+'/api/'+route

def is_cloud_name(model):
    return not isinstance(model,str) or not model.strip() or ':cloud' in model.lower() or '-cloud' in model.lower()

def is_remote(metadata):
    return isinstance(metadata,dict) and bool(metadata.get('remote_host') or metadata.get('remote_model'))

def _api(route,payload=None,base=BASE,timeout=15):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(api_url(route,base),data=data,headers={'Content-Type':'application/json'},method='GET' if payload is None else 'POST')
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.load(r)

def ensure_local(model,base=BASE,timeout=15):
    """Raise CloudModelError unless model is a locally installed, non-cloud Ollama model."""
    if is_cloud_name(model):raise CloudModelError('Bulut tabanlı model reddedildi; AXIS yalnızca yerel modelleri kullanır: '+str(model))
    try:
        tags=_api('tags',base=base,timeout=timeout)
        for entry in tags.get('models',[]) if isinstance(tags,dict) else []:
            if isinstance(entry,dict) and model in (entry.get('name'),entry.get('model')) and is_remote(entry):
                raise CloudModelError('Bulut tabanlı model reddedildi (remote_host/remote_model): '+model)
        metadata=_api('show',{'model':model},base=base,timeout=timeout)
    except urllib.error.HTTPError as e:
        raise CloudModelError('Model yerel olarak doğrulanamadı ('+str(e.code)+'): '+model) from None
    except urllib.error.URLError as e:
        raise CloudModelError('Yerel Ollama sunucusuna ulaşılamadı: '+str(e.reason)) from None
    if is_remote(metadata):raise CloudModelError('Bulut tabanlı model reddedildi (remote_host/remote_model): '+model)
    return model
