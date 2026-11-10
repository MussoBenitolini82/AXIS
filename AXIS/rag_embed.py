"""Local embedding index for AXIS retrieval (Ollama /api/embed, default model bge-m3).

Vectors are L2-normalised float32 blobs in the separate retrieval DB, so cosine similarity is a
plain dot product. Pure Python (no numpy): a few thousand 1024-d vectors scan in well under a second.
All HTTP goes through local_models.open_local (loopback only, no proxy, no redirect)."""
import heapq, json, math, operator, os, sys, threading, urllib.request
from array import array
import local_models
import rag_docs

EMBED_MODEL = os.getenv('AXIS_EMBED_MODEL', 'bge-m3')
TEXT_CHARS = 2000
_CHECKED = set()
_CHECK_LOCK = threading.Lock()


def setup(db):
    db.execute('CREATE TABLE IF NOT EXISTS embeddings(doc_id TEXT PRIMARY KEY, digest TEXT NOT NULL, '
               'model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL)')


def open_store(path=None):
    return rag_docs.open_index(setup, path)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def embed(texts, model=None, timeout=180):
    model = model or EMBED_MODEL
    if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
        raise ValueError('Gömme girdisi boş olmayan bir metin listesi olmalı')
    with _CHECK_LOCK:
        if model not in _CHECKED:
            local_models.ensure_local(model)  # refuses cloud/remote models before any embed request
            _CHECKED.add(model)
    req = urllib.request.Request(local_models.api_url('embed'), method='POST', headers={'Content-Type': 'application/json'},
                                 data=json.dumps({'model': model, 'input': texts, 'truncate': True}).encode())
    with local_models.open_local(req, timeout) as r:
        data = json.load(r)
    vecs = data.get('embeddings') if isinstance(data, dict) else None
    if not isinstance(vecs, list) or len(vecs) != len(texts):
        raise ValueError('Geçersiz gömme yanıtı')
    dim = None
    out = []
    for v in vecs:
        if not isinstance(v, list) or not v or not all(_num(x) for x in v) or (dim is not None and len(v) != dim):
            raise ValueError('Geçersiz gömme yanıtı')
        dim = len(v)
        norm = math.sqrt(sum(x * x for x in v))
        if not norm:
            raise ValueError('Geçersiz gömme yanıtı')
        out.append([x / norm for x in v])
    return out


def pack(vec):
    a = array('f', vec)
    if sys.byteorder == 'big':
        a.byteswap()
    return a.tobytes()


def unpack(blob):
    a = array('f')
    a.frombytes(blob)
    if sys.byteorder == 'big':
        a.byteswap()
    return a


def sync(vector_conn, store_conn, model=None, batch=16, max_docs=None, embed_fn=None, stop=None):
    model = model or EMBED_MODEL
    embed_fn = embed_fn or embed
    docs = list(rag_docs.iter_docs(vector_conn))  # read everything first: no cursor open during HTTP
    have = {r[0]: (r[1], r[2]) for r in store_conn.execute('SELECT doc_id, digest, model FROM embeddings')}
    live = {d['doc_id'] for d in docs}
    gone = [d for d in have if d not in live]
    for d in gone:
        store_conn.execute('DELETE FROM embeddings WHERE doc_id=?', (d,))
    store_conn.commit()
    pending = [d for d in docs if have.get(d['doc_id']) != (d['digest'], model)]
    skipped = len(docs) - len(pending)
    if max_docs is not None:
        pending = pending[:max(0, int(max_docs))]
    embedded = 0
    for i in range(0, len(pending), max(1, int(batch))):
        if stop is not None and stop.is_set():
            break
        chunk = pending[i:i + max(1, int(batch))]
        vecs = embed_fn([(d['title'] + '\n' + d['body'])[:TEXT_CHARS] for d in chunk], model)
        for d, v in zip(chunk, vecs):
            store_conn.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?)', (d['doc_id'], d['digest'], model, len(v), pack(v)))
        store_conn.commit()  # progress survives interruption
        embedded += len(chunk)
    return {'embedded': embedded, 'skipped': skipped, 'removed': len(gone)}


def search(store_conn, text, limit=20, model=None, embed_fn=None):
    if not isinstance(text, str) or not text.strip():
        return []
    model = model or EMBED_MODEL
    q = (embed_fn or embed)([text], model)[0]
    limit = max(1, min(100, int(limit)))
    scored = ((sum(map(operator.mul, q, unpack(r[1]))), r[0])
              for r in store_conn.execute('SELECT doc_id, vec FROM embeddings WHERE model=? AND dim=?', (model, len(q))))
    return [{'doc_id': d, 'score': s} for s, d in heapq.nlargest(limit, scored)]


def stats(store_conn, model=None):
    model = model or EMBED_MODEL
    return {'count': store_conn.execute('SELECT count(*) FROM embeddings WHERE model=?', (model,)).fetchone()[0], 'model': model}
