import io
import json
import unittest
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

    def chat_calls(self):
        return [c for c in self.calls if c[0].endswith('/api/chat')]


MESSAGES = [{'role': 'user', 'content': 'merhaba'}]


class LocalModelGuardTests(unittest.TestCase):
    def ask(self, model, fake, url='http://127.0.0.1:11434/api/chat'):
        with patch.object(vi, 'MODEL', model), patch.object(vi, 'OLLAMA', url), \
                patch('urllib.request.urlopen', fake):
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
        with patch('urllib.request.urlopen', fake), patch.object(vector_discovery, 'installed', lambda: []):
            result = vector_discovery.health()
        self.assertTrue(result['ollama_reachable'])
        self.assertEqual(result['cloud_models_refused'], ['glm-5.3-flash:cloud'])


if __name__ == '__main__':
    unittest.main()
