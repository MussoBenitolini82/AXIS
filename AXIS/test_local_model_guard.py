import email.message
import io
import json
import os
import unittest
import urllib.request
import urllib.response
from unittest.mock import patch

import local_models
import vector_intelligence as vi


class FakeResponse(io.BytesIO):
    status = 200


class FakeOllama:
    """Stand-in for the local Ollama API that records every request."""
    def __init__(self, tags=None, show=None):
        self.tags = tags if tags is not None else {'models': [{'name': 'qwen3:8b'}]}
        self.show = show if show is not None else {'details': {'family': 'qwen3'}}
        self.calls = []

    def __call__(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        body = None if isinstance(req, str) or req.data is None else json.loads(req.data)
        self.calls.append((url, body))
        route = url.rsplit('/api/', 1)[-1]
        payload = {'tags': self.tags, 'show': self.show,
                   'chat': {'message': {'content': 'yerel yanit'}}}[route]
        return FakeResponse(json.dumps(payload).encode())

    def open(self, req, timeout=None):
        return self(req, timeout)

    def chat_calls(self):
        return [c for c in self.calls if c[0].endswith('/api/chat')]


MESSAGES = [{'role': 'user', 'content': 'merhaba'}]


class LocalModelGuardTests(unittest.TestCase):
    def ask(self, model, fake, url='http://127.0.0.1:11434/api/chat'):
        with patch.object(vi, 'MODEL', model), patch.object(vi, 'OLLAMA', url), \
                patch.object(local_models, '_opener', lambda: fake):
            return vi.ask(MESSAGES)

    def test_cloud_name_refused_without_any_request(self):
        for name in ('glm-5.3-flash:cloud', 'gpt-oss:120b-cloud'):
            fake = FakeOllama()
            with self.assertRaises(ValueError) as ctx:
                self.ask(name, fake)
            self.assertIn('Bulut', str(ctx.exception))
            self.assertEqual(fake.calls, [])

    def test_remote_host_in_show_refused(self):
        fake = FakeOllama(tags={'models': [{'name': 'glm-5.3-flash'}]},
                          show={'remote_host': 'https://ollama.com:443', 'remote_model': 'glm-5.3-flash'})
        with self.assertRaises(ValueError) as ctx:
            self.ask('glm-5.3-flash', fake)
        self.assertIn('Bulut', str(ctx.exception))
        self.assertEqual(fake.chat_calls(), [])

    def test_remote_host_in_tags_refused(self):
        fake = FakeOllama(tags={'models': [{'name': 'glm-5.3-flash', 'remote_host': 'https://ollama.com:443'}]})
        with self.assertRaises(ValueError):
            self.ask('glm-5.3-flash', fake)
        self.assertEqual(fake.chat_calls(), [])
        self.assertFalse(any(c[0].endswith('/api/show') for c in fake.calls))

    def test_local_model_passes(self):
        fake = FakeOllama()
        self.assertEqual(self.ask('qwen3:8b', fake), 'yerel yanit')
        chat = fake.chat_calls()
        self.assertEqual(len(chat), 1)
        self.assertEqual(chat[0][0], 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(chat[0][1]['model'], 'qwen3:8b')

    def test_non_loopback_base_refused(self):
        fake = FakeOllama()
        with self.assertRaises(ValueError):
            self.ask('qwen3:8b', fake, url='https://ollama.com/api/chat')
        self.assertEqual(fake.calls, [])

    def test_default_model(self):
        with patch.dict('os.environ', {}, clear=False) as env:
            env.pop('VECTOR_MODEL', None)
            self.assertEqual(local_models.model_name(), 'qwen3:8b')

    def test_health_lists_refused_cloud_models(self):
        import vector_discovery
        fake = FakeOllama(tags={'models': [{'name': 'qwen3:8b'}, {'name': 'glm-5.3-flash:cloud', 'remote_host': 'https://ollama.com:443'}]})
        with patch.object(local_models, '_opener', lambda: fake), patch.object(vector_discovery, 'installed', lambda: []):
            result = vector_discovery.health()
        self.assertTrue(result['ollama_reachable'])
        self.assertEqual(result['cloud_models_refused'], ['glm-5.3-flash:cloud'])


class FakeHTTP(urllib.request.HTTPHandler):
    """Replaces the real HTTP transport: answers in-process, never touches a socket."""
    code = 200
    location = None

    def http_open(self, req):
        headers = email.message.Message()
        if self.location:
            headers['Location'] = self.location
        resp = urllib.response.addinfourl(io.BytesIO(b'{"models": []}'), headers, req.full_url, self.code)
        resp.msg = 'Found' if self.location else 'OK'
        return resp


class RedirectHTTP(FakeHTTP):
    code = 302
    location = 'http://example.com/api/tags'


class LocalTransportTests(unittest.TestCase):
    """open_local: loopback only, proxies ignored, redirects refused."""

    def build_with(self, handler):
        real = urllib.request.build_opener
        seen = []

        def build(*handlers):
            seen.append(handlers)
            return real(*handlers, handler)
        return seen, build

    def test_proxy_env_ignored(self):
        seen, build = self.build_with(FakeHTTP)
        env = {'HTTP_PROXY': 'http://proxy.example:8080', 'HTTPS_PROXY': 'http://proxy.example:8080',
               'http_proxy': 'http://proxy.example:8080', 'https_proxy': 'http://proxy.example:8080'}
        with patch.dict(os.environ, env), patch('urllib.request.build_opener', build):
            with local_models.open_local('http://127.0.0.1:11434/api/tags', 1) as r:
                self.assertEqual(json.load(r), {'models': []})
        self.assertEqual(len(seen), 1)
        proxies = [h for h in seen[0] if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(len(proxies), 1)
        self.assertEqual(proxies[0].proxies, {})
        with patch.dict(os.environ, env):
            # A default opener would install the env proxy; ours installs no proxy_open handler at all.
            self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler) for h in urllib.request.build_opener().handlers))
            opener = local_models._opener()
        self.assertFalse([h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)])
    def test_redirect_raises(self):
        seen, build = self.build_with(RedirectHTTP)
        with patch('urllib.request.build_opener', build):
            with self.assertRaises(local_models.CloudModelError):
                local_models.open_local('http://127.0.0.1:11434/api/tags', 1)
        self.assertTrue(any(isinstance(h, urllib.request.HTTPRedirectHandler) for h in seen[0]))

    def test_non_loopback_refused_before_open(self):
        for url in ('https://ollama.com/api/tags', 'http://10.0.0.5:11434/api/tags', 'http://127.0.0.1.evil.com/api/chat'):
            with patch.object(local_models, '_opener', side_effect=AssertionError('opened')) as opener:
                with self.assertRaises(local_models.CloudModelError):
                    local_models.open_local(urllib.request.Request(url), 1)
                with self.assertRaises(local_models.CloudModelError):
                    local_models.open_local(url, 1)
                opener.assert_not_called()

    def test_all_call_sites_use_open_local(self):
        import vector_discovery
        fake = FakeOllama()
        with patch.object(local_models, 'open_local', side_effect=fake) as seam, \
                patch.object(vi, 'MODEL', 'qwen3:8b'), \
                patch.object(vi, 'OLLAMA', 'http://127.0.0.1:11434/api/chat'):
            self.assertEqual(vi.ask(MESSAGES), 'yerel yanit')
            with patch.object(vector_discovery, 'installed', lambda: []):
                self.assertTrue(vector_discovery.health()['ollama_reachable'])
        urls = [c.args[0] if isinstance(c.args[0], str) else c.args[0].full_url for c in seam.call_args_list]
        self.assertEqual([u.rsplit('/api/', 1)[-1] for u in urls], ['tags', 'show', 'chat', 'tags'])


if __name__ == '__main__':
    unittest.main()
