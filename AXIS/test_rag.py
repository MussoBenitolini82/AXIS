"""RAG: FTS5 index, axis_memory embeddings, hybrid fusion and cited answers (no network)."""
import sqlite3, tempfile, unittest
from pathlib import Path
from unittest import mock
import axis_memory, rag, rag_docs, rag_fts, server
import vector_intelligence as vi


def vector_db():
    db = sqlite3.connect(':memory:')
    server._setup(db)
    return db


def fake_embed(texts):
    """Deterministic unit vectors, one axis per 'topic' keyword."""
    axis_memory._state = True  # what a real successful embed records
    out = []
    for t in texts:
        t = str(t).lower()
        out.append([1.0, 0.0, 0.0] if 'kuantum' in t or 'quantum' in t else [0.0, 1.0, 0.0] if 'protein' in t else [0.0, 0.0, 1.0])
    return out


class TmpDir(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = Path(t.name)

    def conn(self, opener):
        c = opener(self.dir / 'idx.sqlite3')
        self.addCleanup(c.close)
        return c


class DocsTests(unittest.TestCase):
    def test_paper_nodes_skipped(self):
        v = vector_db()
        v.execute("INSERT INTO sources VALUES ('W1','T','u',NULL,2020,'abs','x')")
        v.execute("INSERT INTO nodes VALUES ('paper:t','T','paper','d','x'),('topic:a','A','topic','d','x')")
        self.assertEqual(sorted(d['doc_id'] for d in rag_docs.iter_docs(v)), ['node:topic:a', 'src:W1'])


class FtsTests(TmpDir):
    def setUp(self):
        super().setUp()
        self.v = vector_db()
        self.f = self.conn(rag_fts.open_fts)
        self.v.execute("INSERT INTO sources VALUES ('A','Graph neural networks','u',NULL,2021,'message passing on graphs','x')")
        self.v.execute("INSERT INTO sources VALUES ('B','Vision','u',NULL,2020,'we also mention graph once','x')")
        self.v.execute("INSERT INTO nodes VALUES ('concept:o','Derin öğrenme','concept','İstanbul notları','x')")

    def test_sync_idempotent_update_remove(self):
        self.assertEqual(rag_fts.sync(self.v, self.f), {'added': 3, 'updated': 0, 'removed': 0})
        self.assertEqual(rag_fts.sync(self.v, self.f), {'added': 0, 'updated': 0, 'removed': 0})
        self.v.execute("UPDATE sources SET abstract='changed' WHERE id='B'")
        self.v.execute("DELETE FROM sources WHERE id='A'")
        self.assertEqual(rag_fts.sync(self.v, self.f), {'added': 0, 'updated': 1, 'removed': 1})

    def test_ranking_and_folding(self):
        rag_fts.sync(self.v, self.f)
        self.assertEqual(rag_fts.search(self.f, 'graph')[0]['doc_id'], 'src:A')  # title beats body
        self.assertEqual(rag_fts.search(self.f, 'ogrenme')[0]['doc_id'], 'node:concept:o')
        self.assertEqual(rag_fts.search(self.f, 'İSTANBUL')[0]['doc_id'], 'node:concept:o')
        self.assertEqual(rag_fts.search(self.f, 'VISION')[0]['doc_id'], 'src:B')  # English capitals still match

    def test_hostile_queries(self):
        rag_fts.sync(self.v, self.f)
        for q in ['AND', 'NEAR(', '"', '*', 'a:b', '-x', '', '   ', 'graph" OR "x', 'title:graph']:
            self.assertIsInstance(rag_fts.search(self.f, q), list, q)
        self.assertLessEqual(len(rag_fts.search(self.f, 'graph', 10 ** 6)), 100)


class HybridTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        p = mock.patch.object(server, 'DB', Path(t.name) / 'vector.db')
        p.start()
        self.addCleanup(p.stop)
        with server.connect() as db:
            db.execute("INSERT INTO sources VALUES ('W1','Pruning deep networks','https://x/1',NULL,2022,'We prune weights of neural networks.','x')")
            self.pid = server.add_node(db, 'Pruning deep networks', 'paper', 'We prune')
            db.execute('INSERT INTO evidence VALUES (?,?,?)', (self.pid, 'W1', 'q'))
            db.execute("INSERT INTO sources VALUES ('W2','Protein folding','javascript:alert(1)',NULL,2020,'Folding <b>proteins</b>.','x')")
            db.commit()

    def test_fuse(self):
        self.assertEqual(rag.fuse([{'doc_id': 'a'}, {'doc_id': 'b'}], [{'doc_id': 'b'}]), ['b', 'a'])

    def test_fts_only_when_no_embeddings(self):
        docs, info = rag.retrieve('pruning', 6)
        self.assertEqual(info['mode'], 'tam metin')
        self.assertEqual(docs[0]['node_id'], self.pid)
        self.assertTrue(rag.index_path().name.endswith('.rag.sqlite3'))
        self.assertEqual(rag.index_path().parent, Path(server.DB).parent)

    def test_semantic_hits_fused(self):
        with mock.patch.object(rag, '_semantic', return_value=([{'doc_id': 'src:W2'}], None)):
            docs, info = rag.retrieve('budama', 6)  # Turkish word: no lexical hit, semantic finds W2
        self.assertEqual(info['mode'], 'anlamsal')
        self.assertEqual(docs[0]['doc_id'], 'src:W2')

    def test_dedupe_paper_node_and_source(self):
        docs, _ = rag.retrieve('pruning', 6, extra=[{'doc_id': 'node:' + self.pid}])
        self.assertEqual([d['node_id'] for d in docs].count(self.pid), 1)

    def test_answer_numbered_sources_and_safe_urls(self):
        seen = []
        with mock.patch.object(vi, 'ask', side_effect=lambda m, t=0.2: seen.append(m) or 'Budama [1].'), \
                mock.patch.object(rag, '_semantic', return_value=([{'doc_id': 'src:W1'}, {'doc_id': 'src:W2'}], None)):
            r = vi.answer_question('Sinir ağı pruning nedir?')
        self.assertEqual([s['no'] for s in r['sources']], [1, 2])
        self.assertEqual(r['sources'][0]['url'], 'https://x/1')
        self.assertIsNone(r['sources'][1]['url'])  # non-http URL never reaches the UI
        self.assertEqual(r['retrieval']['mode'], 'hibrit')
        self.assertFalse(r['general_knowledge'])
        self.assertTrue(r['semantic'])
        user = seen[0][1]['content']
        self.assertIn('"no": 1', user)
        self.assertIn('‹b›proteins‹/b›', user)
        self.assertIn('[1]', seen[0][0]['content'])

    def test_index_failure_falls_back_to_keywords(self):
        with mock.patch.object(vi, 'ask', return_value='ok'), \
                mock.patch.object(rag, 'retrieve', side_effect=sqlite3.OperationalError('x')):
            r = vi.answer_question('pruning deep networks')
        self.assertEqual(r['retrieval']['mode'], 'anahtar kelime')
        self.assertFalse(r['semantic'])

    def test_indexing_off_never_calls_axis_memory(self):
        with mock.patch.object(axis_memory, 'semantic_search') as ss:
            docs, info = rag.retrieve('pruning', 6)
        ss.assert_not_called()
        self.assertEqual((info['semantic_hits'], info['semantic_note']), (0, 'anlamsal dizin kapalı'))
        self.assertFalse(docs[0]['semantic'])


class MemoryRetrievalTests(unittest.TestCase):
    """rag.retrieve reads embeddings from axis_memory only: one store, one query embedding per question."""
    def setUp(self):
        t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(t.cleanup)
        d = Path(t.name)
        for mod, name, val in ((server, 'DB', d / 'vector.db'), (axis_memory, 'DB', d / 'memory.sqlite3'),
                               (server, 'MEMORY_INDEXING', True)):
            p = mock.patch.object(mod, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(axis_memory, 'embed', side_effect=fake_embed)
        self.embed = p.start()
        self.addCleanup(p.stop)
        axis_memory.reset_availability()
        self.addCleanup(axis_memory.reset_availability)
        with server.connect() as db:
            db.execute("INSERT INTO sources VALUES ('W1','Quantum error correction','https://x/q',NULL,2023,'Surface codes for quantum computers.','x')")
            self.paper = server.add_node(db, 'Quantum error correction', 'paper', 'Surface codes')
            db.execute('INSERT INTO evidence VALUES (?,?,?)', (self.paper, 'W1', 'q'))
            self.concept = server.add_node(db, 'Protein katlanması', 'concept', 'protein yapısı')
            self.topic = server.add_node(db, 'Dolanıklık', 'topic', 'kuantum dolanıklık olgusu')
            db.commit()
        axis_memory.upsert('chunk:abc:0', 'chunk', 'Kitap.pdf · bölüm 1', 'Kuantum <b>dolanıklık</b> ' + 'k' * 800)
        self.assertEqual(server.memory_sync_once()['pending'], 0)
        self.embed.reset_mock()

    def test_retrieve_maps_node_paper_and_chunk_hits(self):
        docs, info = rag.retrieve('kuantum', 6)  # Turkish query: no full-text hit on the English paper
        by = {d['doc_id']: d for d in docs}
        self.assertEqual(set(by), {'src:W1', 'node:' + self.topic, 'chunk:chunk:abc:0'})  # the protein concept is below the threshold
        self.assertEqual((by['src:W1']['node_id'], by['src:W1']['url'], by['src:W1']['year']), (self.paper, 'https://x/q', 2023))
        chunk = by['chunk:chunk:abc:0']
        self.assertEqual((chunk['kind'], chunk['node_id'], chunk['title']), ('chunk', None, 'Kitap.pdf · bölüm 1'))
        self.assertTrue(chunk['text'].startswith('Kuantum <b>dolanıklık</b>'))
        self.assertTrue(all(d['semantic'] for d in docs))
        self.assertEqual((info['semantic_hits'], info['semantic_note']), (3, None))
        self.assertIn(info['mode'], ('hibrit', 'anlamsal'))

    def test_paper_found_by_all_three_lists_is_one_document(self):
        docs, _ = rag.retrieve('quantum', 6, extra=[{'doc_id': 'node:' + self.paper}])
        self.assertEqual(docs[0]['doc_id'], 'src:W1')  # full-text (source) + keyword (node) + embedding (node) add up
        self.assertEqual([d['node_id'] for d in docs].count(self.paper), 1)

    def test_one_question_embeds_the_query_exactly_once(self):
        seen = []
        with mock.patch.object(vi, 'ask', side_effect=lambda m, t=0.2: seen.append(m) or 'Yanıt [1].'):
            r = vi.answer_question('Kuantum dolanıklık nedir?')
        self.assertEqual(self.embed.call_count, 1)
        self.assertEqual(self.embed.call_args.args[0], ['Kuantum dolanıklık nedir?'])
        self.assertTrue(r['semantic'])
        self.assertIn('chunk:abc:0', [m['id'] for m in r['used_memory']])
        self.assertIn(self.paper, [m['id'] for m in r['used_memory']])
        paper = next(s for s in r['sources'] if s['node_id'] == self.paper)
        self.assertEqual((paper['url'], paper['year']), ('https://x/q', 2023))
        user = seen[0][1]['content']
        self.assertIn('Kuantum ‹b›dolanıklık‹/b›', user)  # chunk text is numbered, neutralised …
        self.assertNotIn('k' * 701, user)                  # … and capped
        self.assertEqual([s['no'] for s in r['sources']], list(range(1, len(r['sources']) + 1)))

    def test_embedding_outage_degrades_to_full_text(self):
        self.embed.side_effect = None
        self.embed.return_value = None
        docs, info = rag.retrieve('quantum', 6)
        self.assertEqual((info['mode'], info['semantic_hits']), ('tam metin', 0))
        self.assertEqual(docs[0]['doc_id'], 'src:W1')

    def test_status_counts_come_from_axis_memory_and_fts(self):
        rag.sync_fts()
        s = rag.status()
        self.assertEqual((s['embedded_docs'], s['memory_items'], s['pending'], s['fts_docs']), (4, 4, 0, 3))
        self.assertEqual((s['embed_model'], s['store'], s['running'], s['last_error']), (axis_memory.EMBED_MODEL, 'memory.sqlite3', False, None))
        self.assertNotIn('error', s)


if __name__ == '__main__':
    unittest.main()
