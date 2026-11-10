"""Hybrid retrieval for AXIS answers: BM25 full-text (FTS5) + local embeddings (Ollama bge-m3),
fused with reciprocal rank fusion. Everything stays on this machine; the index is a separate
SQLite file next to vector.db and can be deleted at any time (it is rebuilt from vector.db)."""
import os, threading, time
from pathlib import Path
import server
import rag_fts, rag_embed

RRF_K = 60
CANDIDATES = 30
_SYNC_LOCK = threading.Lock()
_EMBED_STATE = {'running': False, 'embedded': 0, 'last_error': None, 'last_run': None}
_STOP = threading.Event()


def index_path():
    override = os.getenv('AXIS_RAG_DB')
    return Path(override) if override else Path(server.DB).with_name(Path(server.DB).stem + '.rag.sqlite3')


def sync_fts():
    """Cheap (hash compare): run before every retrieval so new research is searchable at once."""
    with _SYNC_LOCK, server.connect() as vc, rag_fts.open_fts(index_path()) as fc:
        return rag_fts.sync(vc, fc)


def fuse(*ranked_lists, k=RRF_K):
    """Reciprocal rank fusion of lists of {'doc_id',...}; returns doc_ids best first."""
    score = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst):
            score[item['doc_id']] = score.get(item['doc_id'], 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=lambda d: (-score[d], d))


def _semantic(question):
    """Embedding hits, or ([], reason) when the embedding index/model is not usable right now."""
    try:
        with rag_embed.open_store(index_path()) as st:
            if not rag_embed.stats(st)['count']:
                return [], 'gömme dizini henüz boş'
            return rag_embed.search(st, question, CANDIDATES), None
    except Exception as e:  # Ollama down, model missing, cloud refused …: degrade to full-text only
        return [], type(e).__name__


def _details(vc, doc_ids):
    out = []
    for d in doc_ids:
        kind, _, raw = d.partition(':')
        if kind == 'src':
            r = vc.execute('SELECT title,url,year,abstract FROM sources WHERE id=?', (raw,)).fetchone()
            if not r:
                continue
            node = vc.execute('SELECT node_id FROM evidence WHERE source_id=? LIMIT 1', (raw,)).fetchone()
            out.append({'doc_id': d, 'node_id': node[0] if node else None, 'kind': 'source', 'title': r['title'] or 'Başlıksız',
                        'url': r['url'], 'year': r['year'], 'text': str(r['abstract'] or '')})
        elif kind == 'node':
            r = vc.execute('SELECT label,kind,description FROM nodes WHERE id=?', (raw,)).fetchone()
            if not r:
                continue
            out.append({'doc_id': d, 'node_id': raw, 'kind': r['kind'], 'title': r['label'], 'url': None, 'year': None,
                        'text': str(r['description'] or '')})
    return out


def retrieve(question, limit=6, extra=()):
    """Top `limit` documents for a question and the retrieval mode actually used.
    `extra` is another ranked list of {'doc_id'} (AXIS's Turkish->English keyword matcher) fused in."""
    extra = list(extra)
    sync_fts()
    with rag_fts.open_fts(index_path()) as fc:
        lexical = rag_fts.search(fc, question, CANDIDATES)
    semantic, why = _semantic(question)
    ids = fuse(lexical, semantic, extra)
    with server.connect() as vc:
        docs = _details(vc, ids[:limit * 3])
    seen, unique = set(), []
    for d in docs:  # a paper node and its source are the same record: keep the first
        key = d['node_id'] or d['doc_id']
        if key not in seen:
            seen.add(key)
            unique.append(d)
    docs = unique[:limit]
    mode = ('hibrit' if semantic and lexical else 'anlamsal' if semantic else 'tam metin' if lexical
            else 'anahtar kelime' if extra else 'yok')
    return docs, {'mode': mode, 'lexical_hits': len(lexical), 'semantic_hits': len(semantic), 'semantic_note': why}


def _embed_worker(max_docs=None):
    _EMBED_STATE.update(running=True, last_error=None)
    try:
        with server.connect() as vc, rag_embed.open_store(index_path()) as st:
            r = rag_embed.sync(vc, st, max_docs=max_docs, stop=_STOP)
        _EMBED_STATE['embedded'] += r['embedded']
    except Exception as e:
        _EMBED_STATE['last_error'] = f'{type(e).__name__}: {str(e)[:200]}'
    finally:
        _EMBED_STATE.update(running=False, last_run=time.time())


def start_embedding(max_docs=None):
    """Embed new/changed documents in a daemon thread; at most one run at a time."""
    if _EMBED_STATE['running']:
        return False
    _EMBED_STATE['running'] = True
    threading.Thread(target=_embed_worker, args=(max_docs,), daemon=True, name='axis-rag-embed').start()
    return True


def status():
    out = {'index': str(index_path().name), 'embed_model': rag_embed.EMBED_MODEL, **_EMBED_STATE}
    try:
        with rag_embed.open_store(index_path()) as st:
            out['embedded_docs'] = rag_embed.stats(st)['count']
        with rag_fts.open_fts(index_path()) as fc:
            out['fts_docs'] = fc.execute('SELECT count(*) FROM fts_meta').fetchone()[0]
    except Exception as e:
        out['error'] = type(e).__name__
    return out
