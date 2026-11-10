"""Research record count: default 50, user-selectable 1..200. OpenAlex is mocked (no network); temp databases only."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import axis_learning
import central_brain
import server


class ImmediatePool:
    def submit(self, fn, *a, **k):
        fn(*a, **k)


class ResearchLimitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        for mod, name, val in ((server, 'DB', d / 'vector.db'), (central_brain, 'DB', d / 'brain.sqlite3'),
                               (axis_learning, 'DB', d / 'learning.sqlite3')):
            p = mock.patch.object(mod, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.urls = []

        def fake_fetch(url, *a, **k):
            self.urls.append(url)
            return {'results': [{'id': 'W%d' % i, 'title': 'Makale %d' % i, 'concepts': []} for i in range(3)]}
        p = mock.patch.object(server, 'fetch_json', fake_fetch)
        p.start()
        self.addCleanup(p.stop)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_address[1]
        p = mock.patch.object(server, 'POOL', ImmediatePool())
        p.start()
        self.addCleanup(p.stop)

    def per_page(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.urls[-1]).query)['per-page'][0]

    def post(self, payload):
        req = urllib.request.Request(self.base + '/api/research', data=json.dumps(payload).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_default_is_50_and_reaches_per_page(self):
        code, body = self.post({'topic': 'makine öğrenmesi'})
        self.assertEqual(code, 202)
        self.assertEqual(self.per_page(), '50')

    def test_explicit_limit_passed_through(self):
        for n in (1, 100, 200):
            code, _ = self.post({'topic': 'makine öğrenmesi', 'limit': n})
            self.assertEqual(code, 202)
            self.assertEqual(self.per_page(), str(n))

    def test_invalid_limits_rejected_with_400(self):
        for bad in (0, 201, -5, 'abc', '50', True, 7.5, None, [50]):
            before = len(self.urls)
            code, body = self.post({'topic': 'makine öğrenmesi', 'limit': bad})
            self.assertEqual(code, 400, bad)
            self.assertIn('Kayıt sayısı', body['error'])
            self.assertEqual(len(self.urls), before)

    def test_job_details_mention_requested_count(self):
        code, body = self.post({'topic': 'makine öğrenmesi', 'limit': 30})
        with server.connect() as db:
            row = db.execute('SELECT status,details FROM jobs WHERE id=?', (body['job_id'],)).fetchone()
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['details'], '30 kayıt istendi · 3 akademik kayıt işlendi')

    def test_start_research_validates_limit(self):
        for bad in (0, 201, 'abc', True):
            with self.assertRaises(ValueError):
                server.start_research('makine öğrenmesi', bad)

    def test_fetch_timeout_is_longer_for_large_responses(self):
        seen = {}
        with mock.patch.object(server, 'fetch_json', lambda url, timeout=18: seen.update(t=timeout) or {'results': []}):
            server.search_openalex('x', 200)
        self.assertGreaterEqual(seen['t'], 40)


if __name__ == '__main__':
    unittest.main()
