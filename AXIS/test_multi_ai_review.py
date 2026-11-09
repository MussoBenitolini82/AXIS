import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import multi_ai_review as m

class ReviewTests(unittest.TestCase):
    def test_paths(self):
        for path in ('../.env', 'vector.db', '../AXIS_V14_GELISTIRME_PLANI.md'):
            with self.assertRaises(ValueError): m.bundle([path])

    def test_redaction(self):
        self.assertNotIn('super-secret-value', m.scrub('api_key="super-secret-value"'))

    def test_no_models_no_calls(self):
        calls=[]
        def api(route, payload=None):
            calls.append(route)
            return {'models': []}
        with tempfile.TemporaryDirectory() as d:
            directory, result=m.run(['axis_sqlite.py'], {'Reviewer':'missing'}, Path(d), api)
            self.assertEqual(calls, ['tags'])
            self.assertEqual(result['distinct_models'], 0)
            self.assertEqual(len(list(directory.glob('*.json'))), 6)
            self.assertEqual(result['reports'][1]['status'], 'NOT_RUN')

    def test_real_response_and_shared_model(self):
        def api(route, payload=None):
            return {'models':[{'name':'local:1'}]} if route=='tags' else {'message':{'content':'{"findings":[]}'}}
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1','Security Auditor':'local:1'}, Path(d), api)
            self.assertEqual(result['distinct_models'], 1)
            self.assertEqual(result['independent_provider_reviews'], 'NOT_RUN')

    def test_invalid_response_is_failed(self):
        def api(route, payload=None):
            return {'models':[{'name':'local:1'}]} if route=='tags' else {'message':{'content':'not JSON'}}
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
            self.assertEqual(result['reports'][1]['status'], 'FAILED')

    def test_cloud_model_blocked(self):
        calls=[]
        def api(route, payload=None):
            calls.append(route)
            return {'models':[{'name':'x:cloud'}]}
        with tempfile.TemporaryDirectory() as d:
            m.run(['axis_sqlite.py'], {'Reviewer':'x:cloud'}, Path(d), api)
        self.assertEqual(calls, ['tags'])
