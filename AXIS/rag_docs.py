"""Shared document set for AXIS retrieval (full-text and embedding indexes).

A document is one academic source (title + abstract) or one non-paper knowledge node
(topic/concept/skill…: label + description). Paper nodes are skipped: they duplicate sources.
"""
import hashlib, os
from pathlib import Path
from axis_sqlite import open_db

INDEX_PATH = Path(os.getenv('AXIS_RAG_DB', str(Path(__file__).with_name('rag.sqlite3'))))
MAX_BODY = 6000


def open_index(setup, path=None):
    """Open the separate retrieval index DB (never vector.db) with the caller's table setup."""
    def _setup(db):
        db.execute('PRAGMA journal_mode=WAL')
        setup(db)
        db.commit()
    return open_db(str(path or INDEX_PATH), _setup, timeout=20)


def digest(title, body):
    return hashlib.sha256((title + '\0' + body).encode('utf-8')).hexdigest()


def iter_docs(vector_conn):
    """Yield dicts {doc_id, kind, title, body, digest} from vector.db (read only)."""
    for r in vector_conn.execute('SELECT id,title,abstract FROM sources'):
        title, body = str(r[1] or ''), str(r[2] or '')[:MAX_BODY]
        yield {'doc_id': 'src:' + r[0], 'kind': 'source', 'title': title, 'body': body, 'digest': digest(title, body)}
    for r in vector_conn.execute("SELECT id,label,kind,description FROM nodes WHERE kind<>'paper'"):
        title, body = str(r[1] or ''), str(r[3] or '')[:MAX_BODY]
        yield {'doc_id': 'node:' + r[0], 'kind': str(r[2]), 'title': title, 'body': body, 'digest': digest(title, body)}
