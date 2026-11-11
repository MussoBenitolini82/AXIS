"""Hybrid retrieval for AXIS answers: BM25 full-text (FTS5) + local embeddings (axis_memory, Ollama bge-m3)
+ the caller's keyword list, fused with reciprocal rank fusion. Everything stays on this machine.

Embeddings live only in axis_memory (axis_memory.sqlite3, kept up to date by server's memory worker);
the separate index file next to vector.db holds just the FTS index and is rebuilt from vector.db if deleted."""
import os, threading
from pathlib import Path
import server
import axis_memory
import rag_fts

RRF_K = 60
CANDIDATES = 30
SEMANTIC_FALLBACK_SCORE = 0.55  # when axis_memory has no recommended threshold for the model
_SYNC_LOCK = threading.Lock()


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
    """(hits, note): axis_memory embedding hits as ranked {'doc_id', ...}; ([], reason) when unusable.

    A graph node hit becomes 'node:<id>'; a PDF chunk hit becomes 'chunk:<id>' and carries its own
    label/text (chunks exist only in axis_memory). One query embedding, one scan; never raises."""
    if not server.MEMORY_INDEXING:  # imports and tests must never touch the real embedding store
        return [], 'anlamsal dizin kapalı'
    try:
        score_fn = getattr(axis_memory, 'recommended_min_score', None)
        min_score = score_fn() if callable(score_fn) else SEMANTIC_FALLBACK_SCORE
        hits = axis_memory.semantic_search(question, limit=CANDIDATES, min_score=min_score)
        out = []
        for h in hits:
            if h.get('kind') == 'chunk':
                out.append({'doc_id': 'chunk:' + h['id'], 'label': h.get('label') or '', 'text': h.get('text') or ''})
            else:
                out.append({'doc_id': 'node:' + h['id']})
    except Exception as e:  # semantic memory is optional: degrade to full-text + keywords
        return [], type(e).__name__
    return out, (None if out else 'eşleşme yok ya da gömme dizini hazır değil')


def _canonical(vc, ranked_lists):
    """Rewrite 'node:<paper>' ids to their 'src:<source>' id (evidence link) so a paper found by
    full-text (as a source) and by keywords/embeddings (as a node) is one document in the fusion
    and keeps its url/year/abstract."""
    ids = sorted({i['doc_id'][5:] for lst in ranked_lists for i in lst if i['doc_id'].startswith('node:')})
    src = {}
    for n in range(0, len(ids), 500):
        part = ids[n:n + 500]
        for r in vc.execute("SELECT e.node_id,MIN(e.source_id) FROM evidence e JOIN nodes n ON n.id=e.node_id"
                            " WHERE n.kind='paper' AND e.node_id IN (%s) GROUP BY e.node_id" % ','.join('?' * len(part)), part):
            src['node:' + r[0]] = 'src:' + r[1]
    if not src:
        return ranked_lists
    out = []
    for lst in ranked_lists:
        seen, new = set(), []
        for i in lst:
            d = src.get(i['doc_id'], i['doc_id'])
            if d not in seen:
                seen.add(d)
                new.append({**i, 'doc_id': d})
        out.append(new)
    return out


def _details(vc, doc_ids, chunks=None):
    """Display records for doc ids. `chunks` maps 'chunk:<id>' to the semantic hit that carries its text."""
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
            if not r:  # e.g. an embedding whose node was deleted and is not pruned yet
                continue
            out.append({'doc_id': d, 'node_id': raw, 'kind': r['kind'], 'title': r['label'], 'url': None, 'year': None,
                        'text': str(r['description'] or '')})
        elif kind == 'chunk':  # raw is the axis_memory item id ('chunk:<pdf digest>:<n>')
            c = (chunks or {}).get(d)
            if not c:
                continue
            out.append({'doc_id': d, 'node_id': None, 'kind': 'chunk', 'title': c.get('label') or 'Belge bölümü',
                        'url': None, 'year': None, 'text': str(c.get('text') or '')})
    return out


def retrieve(question, limit=6, extra=()):
    """Top `limit` documents for a question and the retrieval mode actually used.
    `extra` is another ranked list of {'doc_id'} (AXIS's Turkish->English keyword matcher) fused in.
    Each document carries 'semantic': True when the embedding search found it."""
    extra = list(extra)
    sync_fts()
    with rag_fts.open_fts(index_path()) as fc:
        lexical = rag_fts.search(fc, question, CANDIDATES)
    semantic, why = _semantic(question)
    with server.connect() as vc:
        lexical, semantic, extra = _canonical(vc, [lexical, semantic, extra])
        ids = fuse(lexical, semantic, extra)
        docs = _details(vc, ids[:limit * 3], {s['doc_id']: s for s in semantic if s['doc_id'].startswith('chunk:')})
    sem_ids = {s['doc_id'] for s in semantic}
    seen, unique = set(), []
    for d in docs:  # a paper node and its source are the same record: keep the first
        key = d['node_id'] or d['doc_id']
        if key not in seen:
            seen.add(key)
            d['semantic'] = d['doc_id'] in sem_ids
            unique.append(d)
    docs = unique[:limit]
    mode = ('hibrit' if semantic and lexical else 'anlamsal' if semantic else 'tam metin' if lexical
            else 'anahtar kelime' if extra else 'yok')
    return docs, {'mode': mode, 'lexical_hits': len(lexical), 'semantic_hits': len(semantic), 'semantic_note': why}


def status():
    """For /api/rag-status: embedding counts from axis_memory, document count from the FTS index."""
    out = {'index': str(index_path().name), 'embed_model': axis_memory.EMBED_MODEL, 'store': Path(axis_memory.DB).name,
           'running': False, 'last_error': None}
    try:
        m = axis_memory.status()
        pending = max(m['items'] - m['embedded'], 0)
        out.update(embedded_docs=m['embedded'], memory_items=m['items'], pending=pending, available=m['available'],
                   running=bool(pending and server.memory_worker_busy()))
        if m['available'] is False:
            out['last_error'] = 'Gömme modeline ulaşılamıyor (%s)' % axis_memory.EMBED_MODEL
        with rag_fts.open_fts(index_path()) as fc:
            out['fts_docs'] = fc.execute('SELECT count(*) FROM fts_meta').fetchone()[0]
    except Exception as e:
        out['error'] = type(e).__name__
    return out
