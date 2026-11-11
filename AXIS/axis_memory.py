"""Semantic memory: local Ollama embeddings stored in SQLite. Degrades silently to empty results."""
import array, hashlib, json, math, os, threading, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

import axis_sqlite, local_models

DB = Path(os.getenv('AXIS_MEMORY_DB', Path(__file__).resolve().parent / 'axis_memory.sqlite3'))
EMBED_MODEL = os.getenv('AXIS_EMBED_MODEL', 'bge-m3')
LOCK = threading.RLock()

MAX_TEXT = 2000  # embed() keeps only this prefix of each text; callers chunk long content (see chunk_text)
MAX_TEXTS = 512  # per embed() call
MAX_BACKFILL = 512
MAX_RESPONSE = 16 * 1024 * 1024
MAX_DIM = 8192
RECOMMENDED_MIN_SCORE = {'bge-m3': 0.55}
BATCH = 16
TIMEOUT = 30
RETRY_AFTER = 60
SCAN_CAP = 20000

_down_until = 0.0
_state = None  # None = not probed, True/False = last embed outcome


def recommended_min_score():
    return RECOMMENDED_MIN_SCORE.get(EMBED_MODEL, 0.35)


def reset_availability():
    global _down_until, _state
    with LOCK:
        _down_until = 0.0
        _state = None


def _setup(db):
    db.execute('CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, kind TEXT, label TEXT, text TEXT,'
               ' digest TEXT, embedding BLOB, model TEXT, created TEXT)')


def _open():
    return axis_sqlite.open_db(DB, _setup)


def _digest(label, text):
    return hashlib.sha256(json.dumps([label or '', text or ''], ensure_ascii=False).encode('utf-8')).hexdigest()


# ---------------------------------------------------------------- chunking

def _cut_point(text, start, end, size):
    """Best cut index in text[start:end]: paragraph, then sentence, then whitespace, else hard cut."""
    floor = start + size // 2
    window = text[floor:end]
    i = window.rfind('\n\n')
    if i >= 0:
        return floor + i + 2
    best = -1
    for mark in ('. ', '! ', '? ', '.\n', '!\n', '?\n', '… '):
        best = max(best, window.rfind(mark))
    if best >= 0:
        return floor + best + 2
    for i in range(len(window) - 1, -1, -1):
        if window[i].isspace():
            return floor + i + 1
    return end


def chunk_text(text, size=900, overlap=150):
    text = (text or '').strip()
    if not text:
        return []
    size = max(int(size), 1)
    overlap = max(0, min(int(overlap), size // 2))
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        cut = end if end >= len(text) else _cut_point(text, start, end, size)
        piece = text[start:cut].strip()
        if piece:
            chunks.append(piece)
        if cut >= len(text):
            break
        nxt = cut - overlap
        if nxt <= start:
            start = cut
        else:
            # Begin the next chunk on a word boundary, not mid-word.
            while nxt < cut and not text[nxt - 1].isspace():
                nxt += 1
            start = nxt
    return chunks


# ---------------------------------------------------------------- embedding

def _request(batch):
    """POST one batch to the local Ollama embed endpoint; returns the raw 'embeddings' value."""
    body = json.dumps({'model': EMBED_MODEL, 'input': batch}).encode('utf-8')
    req = urllib.request.Request(local_models.api_url('embed'), data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with local_models.open_local(req, TIMEOUT) as r:
        raw = r.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('response too large')
        return json.loads(raw.decode('utf-8')).get('embeddings')


def _normalise(vectors, count):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError('vector count')
    dim = None
    out = []
    for v in vectors:
        if not isinstance(v, list) or not v:
            raise ValueError('vector shape')
        if dim is None:
            dim = len(v)
            if dim > MAX_DIM:
                raise ValueError('dimension too large')
        elif len(v) != dim:
            raise ValueError('ragged')
        floats = []
        for x in v:
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
                raise ValueError('bad number')
            floats.append(float(x))
        norm = math.sqrt(sum(x * x for x in floats))
        if not norm or not math.isfinite(norm):
            raise ValueError('zero vector')
        out.append([x / norm for x in floats])
    return out


def embed(texts):
    """L2-normalised vectors for texts, or None on any failure (remembered for 60 s)."""
    global _down_until, _state
    try:
        texts = [str(t)[:MAX_TEXT] for t in texts]
        if not texts:
            return []
        if len(texts) > MAX_TEXTS:
            return None  # caller error, not an outage: do not trip the negative cache
        with LOCK:
            if time.monotonic() < _down_until:
                return None
        local_models.ensure_local(EMBED_MODEL)
        vectors = []
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            vectors.extend(_normalise(_request(batch), len(batch)))
        if len({len(v) for v in vectors}) != 1:
            raise ValueError('ragged')
        with LOCK:
            _state = True
        return vectors
    except Exception:
        with LOCK:
            _down_until = time.monotonic() + RETRY_AFTER
            _state = False
        return None


# ---------------------------------------------------------------- storage

def _upsert(db, item_id, kind, label, text):
    digest = _digest(label, text)
    row = db.execute('SELECT kind,label,text,digest FROM items WHERE id=?', (item_id,)).fetchone()
    if row is None:
        db.execute('INSERT INTO items(id,kind,label,text,digest,embedding,model,created) VALUES(?,?,?,?,?,NULL,NULL,?)',
                   (item_id, kind, label, text, digest, datetime.now(timezone.utc).isoformat(timespec='seconds')))
        return True
    if row['digest'] != digest:
        db.execute('UPDATE items SET kind=?,label=?,text=?,digest=?,embedding=NULL,model=NULL WHERE id=?',
                   (kind, label, text, digest, item_id))
        return True
    if row['kind'] != kind:
        db.execute('UPDATE items SET kind=? WHERE id=?', (kind, item_id))
        return True
    return False


def upsert(item_id, kind, label, text):
    with LOCK, _open() as db:
        return _upsert(db, str(item_id), kind, label or '', text or '')


def upsert_many(items):
    items = list(items)
    changed = 0
    with LOCK, _open() as db:
        for it in items:
            if _upsert(db, str(it['id']), it.get('kind', ''), it.get('label') or '', it.get('text') or ''):
                changed += 1
    return changed


def delete(item_id):
    with LOCK, _open() as db:
        db.execute('DELETE FROM items WHERE id=?', (str(item_id),))


_PENDING = '(embedding IS NULL OR model IS NULL OR model<>?)'


def backfill(limit=64):
    limit = min(max(int(limit), 0), MAX_BACKFILL)
    model = EMBED_MODEL
    with LOCK, _open() as db:
        rows = db.execute('SELECT id,label,text,digest FROM items WHERE ' + _PENDING + ' ORDER BY created,id LIMIT ?',
                          (model, limit)).fetchall()
    # No lock during the network call; updates below only apply if the row is unchanged.
    vectors = embed([(r['label'] + '\n' + r['text']).strip() for r in rows]) if rows else None
    if not rows and _state is None:
        embed(['ping'])  # nothing to embed: one cheap probe so 'available' is a real answer
    embedded = 0
    with LOCK, _open() as db:
        if vectors:
            for r, v in zip(rows, vectors):
                cur = db.execute('UPDATE items SET embedding=?,model=? WHERE id=? AND digest=?',
                                 (array.array('f', v).tobytes(), model, r['id'], r['digest']))
                embedded += cur.rowcount
        pending = db.execute('SELECT COUNT(*) FROM items WHERE ' + _PENDING, (model,)).fetchone()[0]
    return {'embedded': embedded, 'pending': pending, 'available': bool(_state)}


def semantic_search(query, limit=6, min_score=0.35):
    if not (query or '').strip():
        return []
    model = EMBED_MODEL
    with LOCK, _open() as db:
        if not db.execute('SELECT 1 FROM items WHERE embedding IS NOT NULL AND model=? LIMIT 1',
                          (model,)).fetchone():
            return []
    vectors = embed([query])  # network call outside the lock
    if not vectors:
        return []
    q = vectors[0]
    with LOCK, _open() as db:
        # Newest first so the scan cap drops the oldest rows deterministically.
        rows = db.execute('SELECT id,kind,label,text,embedding FROM items WHERE embedding IS NOT NULL'
                          ' AND model=? ORDER BY created DESC,id LIMIT ?', (model, SCAN_CAP)).fetchall()
    hits = []
    for r in rows:
        vec = array.array('f')
        try:
            vec.frombytes(r['embedding'])
        except (ValueError, TypeError):
            continue
        if len(vec) != len(q):
            continue
        score = sum(a * b for a, b in zip(q, vec))
        if score >= min_score:
            hits.append({'id': r['id'], 'kind': r['kind'], 'label': r['label'], 'text': r['text'], 'score': score})
    hits.sort(key=lambda h: h['score'], reverse=True)
    return hits[:max(int(limit), 0)]


def status():
    with LOCK, _open() as db:
        total = db.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        done = db.execute('SELECT COUNT(*) FROM items WHERE embedding IS NOT NULL AND model=?',
                          (EMBED_MODEL,)).fetchone()[0]
    return {'model': EMBED_MODEL, 'items': total, 'embedded': done, 'available': _state}
