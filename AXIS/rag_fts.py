"""Full-text (BM25) index over AXIS documents, SQLite FTS5, in the separate retrieval DB.
Written by GPT Luna (gpt-6-luna) from a spec; query normalisation fixed by Claude."""
import re
import sqlite3

import rag_docs


_STOPWORDS = {
    "ve", "ile", "bir", "bu", "şu", "ne", "nedir", "nasıl", "hakkında",
    "mi", "mı", "mu", "mü", "da", "de", "için", "gibi", "neler",
    "biliyorsun", "anlat", "the", "and", "of", "for", "what", "is",
    "are", "how", "about", "in", "on", "to",
}


def setup(db):
    db.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
            doc_id UNINDEXED,
            kind UNINDEXED,
            title,
            body,
            tokenize="unicode61 remove_diacritics 2"
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fts_meta(
            doc_id TEXT PRIMARY KEY,
            digest TEXT NOT NULL
        )
        """
    )


def open_fts(path=None):
    return rag_docs.open_index(setup, path)


def sync(vector_conn, fts_conn):
    docs = {str(doc["doc_id"]): doc for doc in rag_docs.iter_docs(vector_conn)}
    existing = {
        row["doc_id"]: row["digest"]
        for row in fts_conn.execute("SELECT doc_id, digest FROM fts_meta")
    }

    added = updated = removed = 0

    for doc_id, doc in docs.items():
        digest = doc["digest"]
        if doc_id not in existing:
            fts_conn.execute(
                "INSERT INTO docs_fts(doc_id, kind, title, body) VALUES (?, ?, ?, ?)",
                (doc_id, doc["kind"], doc["title"], doc["body"]),
            )
            fts_conn.execute(
                "INSERT INTO fts_meta(doc_id, digest) VALUES (?, ?)",
                (doc_id, digest),
            )
            added += 1
        elif existing[doc_id] != digest:
            fts_conn.execute("DELETE FROM docs_fts WHERE doc_id = ?", (doc_id,))
            fts_conn.execute(
                "INSERT INTO docs_fts(doc_id, kind, title, body) VALUES (?, ?, ?, ?)",
                (doc_id, doc["kind"], doc["title"], doc["body"]),
            )
            fts_conn.execute(
                "UPDATE fts_meta SET digest = ? WHERE doc_id = ?",
                (digest, doc_id),
            )
            updated += 1

    vanished = existing.keys() - docs.keys()
    for doc_id in vanished:
        fts_conn.execute("DELETE FROM docs_fts WHERE doc_id = ?", (doc_id,))
        fts_conn.execute("DELETE FROM fts_meta WHERE doc_id = ?", (doc_id,))
        removed += 1

    fts_conn.commit()
    return {"added": added, "updated": updated, "removed": removed}


def build_query(text):
    # fix (Claude): only 'İ'→'i'. Mapping 'I'→'ı' broke English queries ("Image" → "ımage").
    normalized = str(text).replace("İ", "i").casefold()
    tokens = re.findall(r"\w+", normalized)

    unique = []
    seen = set()
    for token in tokens:
        if len(token) < 2 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        unique.append(token)
        if len(unique) == 12:
            break

    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in unique)


def search(fts_conn, text, limit=20):
    query = build_query(text)
    if not query:
        return []

    limit = max(1, min(100, int(limit)))
    try:
        rows = fts_conn.execute(
            """
            SELECT doc_id, kind, title,
                   snippet(docs_fts, 3, '', '', '…', 32) AS snippet,
                   bm25(docs_fts, 0.0, 0.0, 3.0, 1.0) AS rank
            FROM docs_fts
            WHERE docs_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        return [
            {
                "doc_id": row["doc_id"],
                "kind": row["kind"],
                "title": row["title"],
                "snippet": row["snippet"],
                "score": -row["rank"],
            }
            for row in rows
        ]
    except sqlite3.OperationalError:
        return []
