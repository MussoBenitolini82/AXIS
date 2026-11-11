import io, unittest, urllib.error
from email.message import Message
from unittest import mock
import server

ATOM = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/1234.5678v1</id><title>Deep
  Nets</title><published>2021-03-01T00:00:00Z</published><summary> Ozet  metni </summary>
<category term="cs.LG"/><category term="stat.ML"/></entry></feed>'''

def http429(*a, **k):
    h = Message(); h['Retry-After'] = '7200'
    raise urllib.error.HTTPError('u', 429, 'Too Many Requests', h, io.BytesIO(b''))

class ArxivFallback(unittest.TestCase):
    def test_arxiv_parse(self):
        with mock.patch.object(server, 'fetch_text', lambda url, **k: ATOM):
            w = server.search_arxiv('deep nets', 5)
        self.assertEqual(w, [{'id': 'http://arxiv.org/abs/1234.5678v1', 'title': 'Deep Nets', 'year': 2021, 'doi': None,
                              'url': 'https://arxiv.org/abs/1234.5678v1', 'abstract': 'Ozet metni', 'concepts': ['cs.LG', 'stat.ML']}])

    def test_query_and_limit(self):
        seen = {}
        with mock.patch.object(server, 'fetch_text', lambda url, **k: seen.setdefault('u', url) and ATOM):
            server.search_arxiv('graph neural', 77)
        self.assertIn('max_results=77', seen['u'])
        self.assertIn('all%3Agraph+AND+all%3Aneural', seen['u'])
        self.assertTrue(seen['u'].startswith('https://export.arxiv.org/api/query?'))

    def test_openalex_429_falls_back(self):
        with mock.patch.object(server, 'fetch_json', http429), mock.patch.object(server, 'fetch_text', lambda url, **k: ATOM):
            works, source, note = server.find_works('deep nets', 5)
        self.assertEqual((len(works), source), (1, 'arXiv'))
        self.assertIn('kotası doldu', note); self.assertIn('2.0 saat', note)

    def test_openalex_ok_no_fallback(self):
        called = []
        with mock.patch.object(server, 'fetch_json', lambda url, timeout=18: {'results': []}), \
             mock.patch.object(server, 'fetch_text', lambda url, **k: called.append(1)):
            self.assertEqual(server.find_works('x y', 5), ([], 'OpenAlex', ''))
        self.assertEqual(called, [])

    def test_both_fail(self):
        def boom(url, **k): raise OSError('ağ yok')
        with mock.patch.object(server, 'fetch_json', http429), mock.patch.object(server, 'fetch_text', boom):
            with self.assertRaises(RuntimeError) as cm: server.find_works('deep', 5)
        self.assertIn('arXiv de başarısız', str(cm.exception))

    def test_api_key_optional(self):
        seen = {}
        with mock.patch.dict('os.environ', {'OPENALEX_API_KEY': 'k1'}), \
             mock.patch.object(server, 'fetch_json', lambda url, timeout=18: seen.setdefault('u', url) and {'results': []}):
            server.search_openalex('x', 5)
        self.assertIn('api_key=k1', seen['u'])

if __name__ == '__main__':
    unittest.main()
