"""GET /static/<name>: only lowercase .js/.css files from AXIS/static, correct types, no traversal. Temp dirs only."""
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import axis_learning
import central_brain
import server


class StaticRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        for mod, name, val in ((server, 'DB', d / 'vector.db'), (central_brain, 'DB', d / 'brain.sqlite3'),
                               (axis_learning, 'DB', d / 'learning.sqlite3')):
            p = mock.patch.object(mod, name, val)
            p.start()
            self.addCleanup(p.stop)
        static = d / 'static'
        static.mkdir()
        (static / 'graph.js').write_text('window.AxisGraph={};', encoding='utf-8')
        (static / 'app.css').write_text('body{color:red}', encoding='utf-8')
        (static / 'x.py').write_text('SECRET=1', encoding='utf-8')
        (static / 'sub').mkdir()
        (static / 'sub' / 'a.js').write_text('nested', encoding='utf-8')
        (d / 'outside.js').write_text('outside', encoding='utf-8')
        p = mock.patch.object(server, 'STATIC', static)
        p.start()
        self.addCleanup(p.stop)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_address[1]

    def get(self, path):
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_serves_js_with_type(self):
        code, headers, body = self.get('/static/graph.js')
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'text/javascript; charset=utf-8')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(body, b'window.AxisGraph={};')

    def test_serves_css_with_type(self):
        code, headers, body = self.get('/static/app.css?v=1')
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'text/css; charset=utf-8')
        self.assertEqual(body, b'body{color:red}')

    def test_rejects_traversal_bad_names_and_missing(self):
        for path in ('/static/../server.py', '/static/..%2fserver.py', '/static/%2e%2e/server.py',
                     '/static/%2e%2e%2fserver.py', '/static/..\\server.py', '/static/x.py', '/static/APP.CSS',
                     '/static/Graph.js', '/static/missing.js', '/static/sub/a.js', '/static/../outside.js',
                     '/static/%2e%2e%2foutside.js', '/static/', '/static', '/static/app.css.map', '/static/.js',
                     '/static/' + 'a' * 41 + '.js', '/static/app.css%00.js', '/static/app%2ecss', '/static/sub'):
            code, _, body = self.get(path)
            self.assertEqual(code, 404, path)
            self.assertNotIn(b'SECRET', body, path)
            self.assertNotIn(b'outside', body, path)

    def test_static_file_helper_rejects_bad_names(self):
        for name in ('../server.py', '..', '', 'x.py', 'APP.css', 'a/b.js', 'a\\b.js', 'missing.css', 'graph.js\n'):
            self.assertEqual(server.static_file(name), (None, None), name)
        self.assertEqual(server.static_file('graph.js')[1], 'text/javascript')

    def test_missing_static_dir_is_404(self):
        with mock.patch.object(server, 'STATIC', server.ROOT / 'no-such-static-dir'):
            code, _, _ = self.get('/static/graph.js')
        self.assertEqual(code, 404)

    def test_index_still_served(self):
        code, headers, body = self.get('/')
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'text/html; charset=utf-8')
        self.assertIn(b'/static/app.css', body)

    def test_real_app_css_is_served(self):
        with mock.patch.object(server, 'STATIC', server.ROOT / 'static'):
            code, headers, body = self.get('/static/app.css')
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'text/css; charset=utf-8')
        self.assertIn(b'--accent', body)


if __name__ == '__main__':
    unittest.main()
