"""RAG: FTS5 index, embedding store, hybrid fusion and cited answers (no network)."""
import hashlib, io, json, math, sqlite3, tempfile, threading, unittest
from pathlib import Path
from unittest import mock
import rag, rag_docs, rag_embed, rag_fts, server
import vector_intelligence as vi


def vector_db():
    db = sqlite3.connect(':memory:')
    server._setup(db)
    return db


def fake_embed(texts, model=None):
    out = []
    for t in texts:
        v = [0.0] * 8
        for w in t.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 8] += 1.0
        n = math.sqrt(sum(x * x for x in v))
        out.append([x / n for x in v] if n else [1 / math.sqrt(8)] * 8)
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


class EmbedTests(TmpDir):
    def setUp(self):
        super().setUp()
        self.v = vector_db()
        self.s = self.conn(rag_embed.open_store)
        for i, t in enumerate(['graph neural networks', 'protein folding', 'reinforcement learning games']):
            self.v.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?)', (f'S{i}', t, 'u', None, 2020, t + ' abstract', 'x'))

    def test_sync_lifecycle(self):
        self.assertEqual(rag_embed.sync(self.v, self.s, embed_fn=fake_embed)['embedded'], 3)
        self.assertEqual(rag_embed.sync(self.v, self.s, embed_fn=fake_embed), {'embedded': 0, 'skipped': 3, 'removed': 0})
        self.v.execute("UPDATE sources SET abstract='new' WHERE id='S1'")
        self.v.execute("DELETE FROM sources WHERE id='S2'")
        self.assertEqual(rag_embed.sync(self.v, self.s, embed_fn=fake_embed), {'embedded': 1, 'skipped': 1, 'removed': 1})
        self.assertEqual(rag_embed.sync(self.v, self.s, model='other', embed_fn=fake_embed)['embedded'], 2)

    def test_max_docs_and_stop(self):
        self.assertEqual(rag_embed.sync(self.v, self.s, max_docs=1, embed_fn=fake_embed)['embedded'], 1)
        ev = threading.Event()
        ev.set()
        self.assertEqual(rag_embed.sync(self.v, self.s, stop=ev, embed_fn=fake_embed)['embedded'], 0)

    def test_search_best_first_and_model_filter(self):
        rag_embed.sync(self.v, self.s, embed_fn=fake_embed)
        rag_embed.sync(self.v, self.s, model='other', embed_fn=fake_embed)
        # one vector per document: switching model replaces the old vectors
        hits = rag_embed.search(self.s, 'protein folding\nprotein folding abstract', model='other', embed_fn=fake_embed)
        self.assertEqual(hits[0]['doc_id'], 'src:S1')
        self.assertEqual(len(hits), 3)
        self.assertEqual(rag_embed.search(self.s, 'protein folding', embed_fn=fake_embed), [])  # stale model ignored

    def test_pack_roundtrip(self):
        self.assertEqual(list(rag_embed.unpack(rag_embed.pack([0.5, -1.0, 2.0]))), [0.5, -1.0, 2.0])


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class EmbedHttpTests(unittest.TestCase):
    def call(self, payload, texts=('a', 'b')):
        seen = []

        def opener(req, timeout):
            seen.append(req)
            return FakeResp(json.dumps(payload).encode())
        with mock.patch.object(rag_embed.local_models, 'open_local', opener), \
                mock.patch.object(rag_embed.local_models, 'ensure_local') as ens, \
                mock.patch.object(rag_embed, '_CHECKED', set()):
            out = rag_embed.embed(list(texts), 'm1')
            rag_embed.embed(list(texts), 'm1')
        return out, seen, ens

    def test_ok_normalised_and_local(self):
        out, seen, ens = self.call({'embeddings': [[3, 4], [0, 2]]})
        self.assertEqual(out, [[0.6, 0.8], [0.0, 1.0]])
        self.assertEqual(seen[0].full_url, 'http://127.0.0.1:11434/api/embed')
        self.assertIs(json.loads(seen[0].data)['truncate'], True)
        ens.assert_called_once_with('m1')

    def test_bad_responses(self):
        for bad in [{'embeddings': [[1, 2]]}, {'embeddings': [[1, float('nan')], [1, 2]]},
                    {'embeddings': [[True, 1], [1, 2]]}, {'embeddings': [[1, 2], [1, 2, 3]]},
                    {'embeddings': [[0, 0], [1, 2]]}, {}, []]:
            with self.assertRaises(ValueError, msg=str(bad)):
                self.call(bad)

    def test_cloud_model_refused_before_request(self):
        with mock.patch.object(rag_embed, '_CHECKED', set()), \
                mock.patch.object(rag_embed.local_models, 'open_local') as op:
            with self.assertRaises(rag_embed.local_models.CloudModelError):
                rag_embed.embed(['x'], 'bge-m3:cloud')
            op.assert_not_called()


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
        user = seen[0][1]['content']
        self.assertIn('"no": 1', user)
        self.assertIn('‹b›proteins‹/b›', user)
        self.assertIn('[1]', seen[0][0]['content'])

    def test_index_failure_falls_back_to_keywords(self):
        with mock.patch.object(vi, 'ask', return_value='ok'), \
                mock.patch.object(rag, 'retrieve', side_effect=sqlite3.OperationalError('x')):
            r = vi.answer_question('pruning deep networks')
        self.assertEqual(r['retrieval']['mode'], 'anahtar kelime')


if __name__ == '__main__':
    unittest.main()
