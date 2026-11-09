import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import multi_ai_review as m

def fake_api(content='{"findings":[]}', context_length=40960, prompt_eval=lambda num_ctx: 100, done_reason='stop', eval_count=50):
    """Stand-in for the local Ollama API that records request payloads."""
    def api(route, payload=None):
        api.payloads[route]=payload
        if route=='tags':
            return {'models':[{'name':'local:1'}]}
        if route=='show':
            info={} if context_length is None else {'qwen3.context_length':context_length}
            return {'model_info':info}
        return {'message':{'content':content}, 'prompt_eval_count':prompt_eval(payload['options']['num_ctx']),
                'done_reason':done_reason, 'eval_count':eval_count}
    api.payloads={}
    return api

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
        api=fake_api()
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1','Security Auditor':'local:1'}, Path(d), api)
            self.assertEqual(result['distinct_models'], 1)
            self.assertEqual(result['independent_provider_reviews'], 'NOT_RUN')

    def test_invalid_response_is_failed(self):
        api=fake_api(content='not JSON')
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
            self.assertEqual(result['reports'][1]['status'], 'FAILED')
            self.assertEqual(result['reports'][1]['reason'], 'JSONDecodeError')

    def test_think_disabled_and_stats_recorded(self):
        api=fake_api()
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
        self.assertIs(api.payloads['chat']['think'], False)
        report=result['reports'][1]
        self.assertEqual(report['done_reason'], 'stop')
        self.assertEqual(report['eval_count'], 50)

    def test_output_truncated_is_failed(self):
        api=fake_api(content='{"findings":[', done_reason='length')
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
        report=result['reports'][1]
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(report['reason'].startswith('OutputTruncated'))
        self.assertEqual(report['findings'], [])

    def test_eval_count_at_limit_is_failed(self):
        api=fake_api(eval_count=m.NUM_PREDICT)
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
        self.assertTrue(result['reports'][1]['reason'].startswith('OutputTruncated'))

    def test_invalid_response_excerpt_scrubbed(self):
        api=fake_api(content='oops api_key="abc123secretvalue"')
        with tempfile.TemporaryDirectory() as d:
            directory, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
            report=result['reports'][1]
            self.assertEqual(report['status'], 'FAILED')
            self.assertIn('oops', report['raw_response_excerpt'])
            self.assertNotIn('abc123secretvalue', json.dumps(result))
            self.assertNotIn('abc123secretvalue', (directory/'reviewer.json').read_text(encoding='utf-8'))

    def test_num_ctx_covers_whole_bundle(self):
        api=fake_api()
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['multi_ai_review.py'], {'Reviewer':'local:1'}, Path(d), api)
        chat=api.payloads['chat']
        prompt_chars=sum(len(x['content']) for x in chat['messages'])
        num_ctx=chat['options']['num_ctx']
        # Must hold the prompt even at a pessimistic 2.5 chars/token, plus the output budget.
        self.assertGreaterEqual(num_ctx, prompt_chars/2.5 + chat['options']['num_predict'])
        self.assertLessEqual(num_ctx, 40960)
        self.assertEqual(result['reports'][1]['status'], 'COMPLETED')
        self.assertEqual(result['reports'][1]['num_ctx'], num_ctx)

    def test_truncated_prompt_is_failed(self):
        # Ollama keeps only num_ctx tokens; a prompt that filled the window must not count as a review.
        api=fake_api(prompt_eval=lambda num_ctx: num_ctx - m.NUM_PREDICT)
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
        report=result['reports'][1]
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(report['reason'].startswith('ContextTruncated'))
        self.assertEqual(report['findings'], [])

    def test_bundle_larger_than_model_context_not_sent(self):
        api=fake_api(context_length=2048)
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['multi_ai_review.py'], {'Reviewer':'local:1'}, Path(d), api)
        self.assertNotIn('chat', api.payloads)
        self.assertEqual(result['reports'][1]['status'], 'FAILED')
        self.assertIn('exceeds model context', result['reports'][1]['reason'])

    def test_unknown_context_length_not_sent(self):
        api=fake_api(context_length=None)
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
        self.assertNotIn('chat', api.payloads)
        self.assertEqual(result['reports'][1]['status'], 'FAILED')

    def test_cloud_model_blocked(self):
        calls=[]
        def api(route, payload=None):
            calls.append(route)
            return {'models':[{'name':'x:cloud'}]}
        with tempfile.TemporaryDirectory() as d:
            m.run(['axis_sqlite.py'], {'Reviewer':'x:cloud'}, Path(d), api)
        self.assertEqual(calls, ['tags'])
