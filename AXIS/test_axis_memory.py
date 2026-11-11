import io, json, tempfile, unittest, urllib.error, zlib
from pathlib import Path
from unittest.mock import patch

import axis_memory, local_models

DIM = 64


def bow(text):
    v = [0.0] * DIM
    for w in text.lower().replace('\n', ' ').split():
        v[zlib.crc32(w.strip('.,!?').encode()) % DIM] += 1.0
    return v


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Fake:
    """Stands in for local_models.open_local with a deterministic embedder."""
    def __init__(self, mutate=None, fail=False):
        self.calls = []
        self.mutate = mutate
        self.fail = fail

    def __call__(self, req, timeout):
        if self.fail:
            raise urllib.error.URLError('down')
        body = json.loads(req.data.decode())
        self.calls.append((req.full_url, body, timeout))
        vecs = [bow(t) for t in body['input']]
        if self.mutate:
            vecs = self.mutate(vecs)
        return FakeResponse(json.dumps({'embeddings': vecs}).encode())


class MemoryCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        for obj, name, val in ((axis_memory, 'DB', Path(tmp.name) / 'mem.sqlite3'),
                               (axis_memory, 'EMBED_MODEL', 'fake-embed')):
            p = patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(local_models, 'ensure_local', lambda m, *a, **k: m)
        p.start()
        self.addCleanup(p.stop)
        axis_memory.reset_availability()
        self.addCleanup(axis_memory.reset_availability)

    def use(self, fake):
        p = patch.object(local_models, 'open_local', fake)
        p.start()
        self.addCleanup(p.stop)
        return fake

    def seed(self):
        axis_memory.upsert_many([
            {'id': 'a', 'kind': 'note', 'label': 'kedi', 'text': 'kedi sütü sever'},
            {'id': 'b', 'kind': 'note', 'label': 'araba', 'text': 'araba yakıt tüketir'},
            {'id': 'c', 'kind': 'note', 'label': 'kod', 'text': 'python kod yazmak eğlenceli'}])


class ChunkTests(MemoryCase):
    def test_empty_and_short(self):
        self.assertEqual(axis_memory.chunk_text(''), [])
        self.assertEqual(axis_memory.chunk_text('  \n '), [])
        self.assertEqual(axis_memory.chunk_text(' kısa metin '), ['kısa metin'])

    def test_paragraph_boundary_preferred(self):
        text = 'a' * 60 + '\n\n' + 'b' * 60
        chunks = axis_memory.chunk_text(text, size=100, overlap=10)
        self.assertEqual(chunks[0], 'a' * 60)

    def test_sentence_then_whitespace(self):
        text = 'Birinci cümle burada bitiyor. İkinci cümle de uzun uzun devam ediyor işte'
        chunks = axis_memory.chunk_text(text, size=45, overlap=5)
        self.assertTrue(chunks[0].endswith('bitiyor.'))
        words = 'kelime ' * 40
        for c in axis_memory.chunk_text(words, size=50, overlap=10):
            self.assertTrue(all(w == 'kelime' for w in c.split()))

    def test_overlap_deterministic_and_no_empty(self):
        text = ' '.join('sözcük%d' % i for i in range(300))
        a = axis_memory.chunk_text(text, size=200, overlap=40)
        self.assertEqual(a, axis_memory.chunk_text(text, size=200, overlap=40))
        self.assertGreater(len(a), 3)
        self.assertTrue(all(c and c == c.strip() for c in a))
        for prev, nxt in zip(a, a[1:]):
            tail = prev[-60:]
            self.assertTrue(any(w in nxt for w in tail.split()[1:]), 'no overlap')
        self.assertEqual(a[-1].split()[-1], 'sözcük299')

    def test_turkish_text(self):
        text = 'Çağrı şöyle dedi: ığdır ağrı dağı. ' * 40
        chunks = axis_memory.chunk_text(text, size=120, overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all('Çağrı' in c or 'ığdır' in c for c in chunks))


class UpsertTests(MemoryCase):
    def test_digest_change_clears_embedding(self):
        self.use(Fake())
        self.assertTrue(axis_memory.upsert('x', 'note', 'l', 'merhaba dünya'))
        self.assertFalse(axis_memory.upsert('x', 'note', 'l', 'merhaba dünya'))
        axis_memory.backfill()
        self.assertEqual(axis_memory.status()['embedded'], 1)
        self.assertTrue(axis_memory.upsert('x', 'note', 'l', 'başka metin'))
        self.assertEqual(axis_memory.status()['embedded'], 0)

    def test_upsert_no_network_and_delete(self):
        fake = self.use(Fake())
        self.seed()
        self.assertEqual(fake.calls, [])
        axis_memory.delete('a')
        self.assertEqual(axis_memory.status()['items'], 2)


class BackfillSearchTests(MemoryCase):
    def test_backfill_counts(self):
        self.use(Fake())
        self.seed()
        r = axis_memory.backfill(limit=2)
        self.assertEqual((r['embedded'], r['pending'], r['available']), (2, 1, True))
        r = axis_memory.backfill()
        self.assertEqual((r['embedded'], r['pending']), (1, 0))
        self.assertEqual(axis_memory.backfill()['embedded'], 0)
        self.assertEqual(axis_memory.status(), {'model': 'fake-embed', 'items': 3, 'embedded': 3, 'available': True})

    def test_search_ranking_and_min_score(self):
        self.use(Fake())
        self.seed()
        axis_memory.backfill()
        hits = axis_memory.semantic_search('kedi sütü sever')
        self.assertEqual(hits[0]['id'], 'a')
        self.assertGreater(hits[0]['score'], 0.9)
        self.assertEqual([h['id'] for h in hits], ['a'])
        loose = axis_memory.semantic_search('kedi araba', min_score=0.0, limit=2)
        self.assertEqual(len(loose), 2)
        self.assertGreaterEqual(loose[0]['score'], loose[1]['score'])
        self.assertEqual(axis_memory.semantic_search('   '), [])

    def test_other_model_vectors_ignored_and_reembedded(self):
        self.use(Fake())
        self.seed()
        axis_memory.backfill()
        with patch.object(axis_memory, 'EMBED_MODEL', 'other-model'):
            self.assertEqual(axis_memory.semantic_search('kedi sütü sever'), [])
            self.assertEqual(axis_memory.status()['embedded'], 0)
            r = axis_memory.backfill()
            self.assertEqual((r['embedded'], r['pending']), (3, 0))
            self.assertEqual(axis_memory.semantic_search('kedi sütü sever')[0]['id'], 'a')

    def test_search_nothing_embedded(self):
        fake = self.use(Fake())
        self.seed()
        self.assertEqual(axis_memory.semantic_search('kedi'), [])
        self.assertEqual(fake.calls, [])


class FailureTests(MemoryCase):
    def test_unavailable_and_negative_cache(self):
        fake = self.use(Fake())
        self.seed()
        axis_memory.backfill()
        down = Fake(fail=True)
        with patch.object(local_models, 'open_local', down):
            self.assertIsNone(axis_memory.embed(['x']))
            self.assertEqual(axis_memory.semantic_search('kedi'), [])
            self.assertFalse(axis_memory.backfill()['available'])
        self.assertEqual(down.calls, [])
        # Cache active: a healthy server is not even asked.
        before = len(fake.calls)
        self.assertIsNone(axis_memory.embed(['x']))
        self.assertEqual(len(fake.calls), before)
        self.assertFalse(axis_memory.status()['available'])
        axis_memory.reset_availability()
        self.assertIsNone(axis_memory.status()['available'])
        self.assertIsNotNone(axis_memory.embed(['x']))

    def test_negative_cache_counts_requests(self):
        count = []

        def boom(req, timeout):
            count.append(1)
            raise urllib.error.URLError('down')
        with patch.object(local_models, 'open_local', boom):
            self.assertIsNone(axis_memory.embed(['a']))
            self.assertIsNone(axis_memory.embed(['a']))
        self.assertEqual(len(count), 1)

    def test_cache_expires(self):
        self.use(Fake(fail=True))
        self.assertIsNone(axis_memory.embed(['a']))
        axis_memory._down_until = 0.0
        self.use(Fake())
        self.assertIsNotNone(axis_memory.embed(['a']))

    def test_cloud_model_refused(self):
        sent = []
        # Put the real guard back over the setUp stub.
        with patch.object(local_models, 'ensure_local', _real_ensure_local), \
                patch.object(axis_memory, 'EMBED_MODEL', 'x:cloud'), \
                patch.object(local_models, 'open_local', lambda *a, **k: sent.append(a)):
            self.assertIsNone(axis_memory.embed(['merhaba']))
        self.assertEqual(sent, [])

    def test_malformed_responses(self):
        cases = {
            'count': lambda v: v[:-1],
            'nan': lambda v: [[float('nan')] + x[1:] for x in v],
            'ragged': lambda v: [v[0][:-1]] + v[1:],
            'zero': lambda v: [[0.0] * DIM for _ in v],
            'strings': lambda v: [['a'] * DIM for _ in v],
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                axis_memory.reset_availability()
                self.use(Fake(mutate=mutate))
                self.assertIsNone(axis_memory.embed(['bir', 'iki']))

    def test_missing_key_and_garbage(self):
        axis_memory.reset_availability()
        with patch.object(local_models, 'open_local', lambda req, t: FakeResponse(b'{}')):
            self.assertIsNone(axis_memory.embed(['a']))
        axis_memory.reset_availability()
        with patch.object(local_models, 'open_local', lambda req, t: FakeResponse(b'not json')):
            self.assertIsNone(axis_memory.embed(['a']))


class ReviewFixTests(MemoryCase):
    def test_zero_pending_never_probed(self):
        fake = self.use(Fake())
        self.assertIsNone(axis_memory.status()['available'])
        r = axis_memory.backfill()
        self.assertEqual((r['embedded'], r['pending'], r['available']), (0, 0, True))
        self.assertEqual(len(fake.calls), 1)
        axis_memory.backfill()
        self.assertEqual(len(fake.calls), 1)  # already probed

    def test_zero_pending_probe_failure(self):
        self.use(Fake(fail=True))
        self.assertFalse(axis_memory.backfill()['available'])

    def test_stale_vector_not_attached(self):
        base = Fake()

        def edit_midflight(req, timeout):
            axis_memory.upsert('x', 'note', 'l', 'tamamen yeni metin')
            return base(req, timeout)
        axis_memory.upsert('x', 'note', 'l', 'eski metin')
        with patch.object(local_models, 'open_local', edit_midflight):
            r = axis_memory.backfill()
        self.assertEqual((r['embedded'], r['pending']), (0, 1))
        self.assertEqual(axis_memory.status()['embedded'], 0)

    def test_lock_not_held_during_request(self):
        held = []
        base = Fake()

        def probe(req, timeout):
            held.append(axis_memory.LOCK._is_owned())
            return base(req, timeout)
        self.seed()
        with patch.object(local_models, 'open_local', probe):
            axis_memory.backfill()
            axis_memory.semantic_search('kedi')
        self.assertEqual(held, [False, False])

    def test_digest_unambiguous(self):
        self.assertTrue(axis_memory.upsert('x', 'n', 'ab', 'c'))
        self.assertTrue(axis_memory.upsert('x', 'n', 'a', 'bc'))

    def test_scan_cap_newest_first(self):
        self.use(Fake())
        axis_memory.upsert('old', 'n', 'kedi', 'kedi süt')
        axis_memory.upsert('new', 'n', 'kedi', 'kedi süt')
        axis_memory.backfill()
        with axis_memory._open() as db:
            db.execute("UPDATE items SET created='2020-01-01T00:00:00' WHERE id='old'")
        with patch.object(axis_memory, 'SCAN_CAP', 1):
            hits = axis_memory.semantic_search('kedi süt')
        self.assertEqual([h['id'] for h in hits], ['new'])

    def test_response_and_dimension_bounds(self):
        with patch.object(axis_memory, 'MAX_RESPONSE', 10):
            self.use(Fake())
            self.assertIsNone(axis_memory.embed(['a']))
        axis_memory.reset_availability()
        with patch.object(axis_memory, 'MAX_DIM', DIM - 1):
            self.assertIsNone(axis_memory.embed(['a']))

    def test_too_many_texts_and_backfill_cap(self):
        fake = self.use(Fake())
        with patch.object(axis_memory, 'MAX_TEXTS', 2):
            self.assertIsNone(axis_memory.embed(['a', 'b', 'c']))
        self.assertEqual(fake.calls, [])
        self.assertIsNone(axis_memory.status()['available'])
        axis_memory.upsert_many({'id': str(i), 'kind': 'n', 'label': 'l', 'text': 't%d' % i} for i in range(5))
        with patch.object(axis_memory, 'MAX_BACKFILL', 3):
            self.assertEqual(axis_memory.backfill(limit=999)['embedded'], 3)

    def test_recommended_min_score(self):
        with patch.object(axis_memory, 'EMBED_MODEL', 'bge-m3'):
            self.assertEqual(axis_memory.recommended_min_score(), 0.55)
        self.assertEqual(axis_memory.recommended_min_score(), 0.35)


class EmbedShapeTests(MemoryCase):
    def test_normalised_batched_truncated(self):
        fake = self.use(Fake())
        texts = ['sözcük %d' % i for i in range(40)]
        texts[0] = 'u' * 5000
        out = axis_memory.embed(texts)
        self.assertEqual([len(c[1]['input']) for c in fake.calls], [16, 16, 8])
        self.assertEqual(len(fake.calls[0][1]['input'][0]), 2000)
        self.assertEqual(fake.calls[0][2], 30)
        self.assertTrue(fake.calls[0][0].endswith('/api/embed'))
        self.assertEqual(fake.calls[0][1]['model'], 'fake-embed')
        self.assertEqual(len(out), 40)
        for v in out:
            self.assertAlmostEqual(sum(x * x for x in v), 1.0, places=6)


_real_ensure_local = local_models.ensure_local

if __name__ == '__main__':
    unittest.main()
