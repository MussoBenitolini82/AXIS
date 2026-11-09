import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import multi_ai_review as m

OMIT = object()

def fake_api(content='{"findings":[]}', context_length=40960, prompt_eval=lambda num_ctx: 100, done_reason='stop', eval_count=50):
    """Stand-in for the local Ollama API that records request payloads."""
    def api(route, payload=None):
        api.payloads[route]=payload
        if route=='tags':
            return {'models':[{'name':'local:1'}]}
        if route=='show':
            info={} if context_length is None else {'qwen3.context_length':context_length}
            return {'model_info':info}
        resp={'message':{'content':content}, 'prompt_eval_count':prompt_eval(payload['options']['num_ctx']),
              'done_reason':done_reason, 'eval_count':eval_count}
        return {k:v for k,v in resp.items() if v is not OMIT}
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

    def test_bool_context_length_rejected(self):
        with self.assertRaises(m.ContextTruncated):
            m.context_limit({'model_info':{'qwen3.context_length':True}})
        self.assertEqual(m.context_limit({'model_info':{'a.context_length':True, 'b.context_length':4096}}), 4096)

    def test_cloud_backed_metadata_reason_kept(self):
        base=fake_api()
        def api(route, payload=None):
            result=base(route, payload)
            if route=='show':
                result['remote_host']='https://ollama.com:443'
            return result
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
        self.assertNotIn('chat', base.payloads)
        self.assertEqual(result['reports'][1]['status'], 'FAILED')
        self.assertEqual(result['reports'][1]['reason'], 'ValueError: Cloud-backed models forbidden')

    def test_bundle_rejects_empty_duplicate_and_non_regular(self):
        with self.assertRaises(ValueError): m.bundle([])
        with self.assertRaises(ValueError): m.bundle(['axis_sqlite.py', 'axis_sqlite.py'])
        with self.assertRaises(ValueError): m.bundle(['axis_sqlite.py', './axis_sqlite.py'])
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'pkg.py').mkdir()
            with self.assertRaises(ValueError): m.bundle(['pkg.py'], root=Path(d))

    def test_metadata_routes_use_short_timeout(self):
        seen=[]
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return b'{}'
        class Opener:
            def open(self, req, timeout):
                seen.append((req.full_url, timeout))
                return Response()
        def build_opener(*handlers):
            self.assertTrue(any(isinstance(h, m.urllib.request.ProxyHandler) and h.proxies=={} for h in handlers))
            self.assertTrue(any(isinstance(h, m.NoRedirect) for h in handlers))
            return Opener()
        with patch.object(m.urllib.request, 'build_opener', build_opener):
            m.local_api('tags')
            m.local_api('show', {'model':'local:1'})
            m.local_api('chat', {'model':'local:1'})
        self.assertEqual(seen, [('http://127.0.0.1:11434/api/tags', 15), ('http://127.0.0.1:11434/api/show', 15),
                                ('http://127.0.0.1:11434/api/chat', m.CHAT_TIMEOUT)])

def finding(**kw):
    base={"severity":"low","file":"a.py","line":1,"confidence":"high","explanation":"x"}
    base.update(kw)
    return base

class HardeningTests(unittest.TestCase):
    def run_one(self, api):
        with tempfile.TemporaryDirectory() as d:
            directory, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
            files={p.name:p.read_text(encoding='utf-8') for p in directory.glob('*.json')}
        return result['reports'][1], files

    def test_bad_metadata_fails_closed(self):
        cases=[('no prompt_eval', dict(prompt_eval=lambda n: OMIT)), ('prompt None', dict(prompt_eval=lambda n: None)),
               ('prompt str', dict(prompt_eval=lambda n: '100')), ('prompt bool', dict(prompt_eval=lambda n: True)),
               ('prompt 0', dict(prompt_eval=lambda n: 0)),
               ('no eval_count', dict(eval_count=OMIT)), ('eval None', dict(eval_count=None)),
               ('eval str', dict(eval_count='5')), ('eval bool', dict(eval_count=False)), ('eval negative', dict(eval_count=-1)),
               ('no done_reason', dict(done_reason=OMIT)), ('done None', dict(done_reason=None)),
               ('done unload', dict(done_reason='unload'))]
        for label, kw in cases:
            with self.subTest(label):
                report,_=self.run_one(fake_api(**kw))
                self.assertEqual(report['status'], 'FAILED')
                self.assertTrue(report['reason'].startswith('ResponseUnverifiable: '), report['reason'])
                self.assertEqual(report['findings'], [])

    def test_zero_eval_count_completes(self):
        report,_=self.run_one(fake_api(eval_count=0))
        self.assertEqual(report['status'], 'COMPLETED')

    def test_secret_in_explanation_keeps_json_valid(self):
        content=json.dumps({'findings':[finding(explanation='uses api_key="x" here')]})
        report,files=self.run_one(fake_api(content=content))
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertIn('[REDACTED]', report['findings'][0]['explanation'])
        self.assertNotIn('"x"', report['findings'][0]['explanation'])
        json.loads(files['reviewer.json'])

    def test_extra_keys_dropped(self):
        content=json.dumps({'findings':[finding(extra={"password":"hunter2"}, other='z', suggested_fix='fix it')]})
        report,files=self.run_one(fake_api(content=content))
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['dropped_finding_keys'], 2)
        self.assertEqual(set(report['findings'][0]), {'severity','file','line','confidence','explanation','suggested_fix'})
        for text in files.values():
            self.assertNotIn('hunter2', text)

    def test_severity_normalised_and_line_none(self):
        content=json.dumps({'findings':[finding(severity='HIGH', line=None)]})
        report,_=self.run_one(fake_api(content=content))
        self.assertEqual(report['findings'][0]['severity'], 'high')
        self.assertIsNone(report['findings'][0]['line'])

    def test_invalid_fields_fail(self):
        cases=[('severity', dict(severity='urgent')), ('severity', dict(severity=1)), ('line', dict(line='3')),
               ('line', dict(line=True)), ('explanation', dict(explanation='x'*4001)), ('explanation', dict(explanation=5)),
               ('file', dict(file='f'*301)), ('confidence', dict(confidence='c'*51)),
               ('suggested_fix', dict(suggested_fix='y'*4001))]
        for field, kw in cases:
            with self.subTest(field=field, kw=str(kw)[:40]):
                report,_=self.run_one(fake_api(content=json.dumps({'findings':[finding(**kw)]})))
                self.assertEqual(report['status'], 'FAILED')
                self.assertEqual(report['reason'], 'ValueError: Invalid finding schema: '+field)
                self.assertEqual(report['findings'], [])

    def test_scrub_patterns(self):
        key='-----BEGIN RSA PRIVATE KEY-----\nMIIabc\ndef\n-----END RSA PRIVATE KEY-----'
        cases=[('{"password": "hunter2"}','hunter2'), ("{'password': 'hunter2'}",'hunter2'), ('"api_key":"abcd1234"','abcd1234'),
               ('password = "hunter2"','hunter2'), ('password: hunter2','hunter2'), ("token='tok123'",'tok123'),
               ('client_secret = s3cr3tvalue','s3cr3tvalue'), ('access-key: AK123456','AK123456'), ('passwd=zzz999','zzz999'),
               ('Authorization: Bearer abcdef123456','abcdef123456'), ('AKIAIOSFODNN7EXAMPLE','AKIAIOSFODNN7EXAMPLE'),
               ('github_pat_11ABCDEFG0123456789abcd','github_pat_11ABCDEFG0123456789abcd'),
               ('ghp_'+'a'*24,'a'*24), ('gho_'+'b'*24,'b'*24), ('xoxb-1234567890-abcdef','1234567890-abcdef'),
               ('sk-abcdefghijkl1234','abcdefghijkl1234'), ('AIza'+'c'*25,'c'*25),
               ('https://user:pw123@host/x','pw123'), (key,'MIIabc')]
        for text, secret in cases:
            with self.subTest(text[:30]):
                out=m.scrub(text)
                self.assertNotIn(secret, out)
                self.assertIn('[REDACTED]', out)
                self.assertNotIn('[REDACTED]"', out)
                self.assertNotIn("[REDACTED]'", out)
        self.assertEqual(m.scrub('password = "hunter2"'), 'password = [REDACTED]')
        self.assertEqual(m.scrub('https://user:pw123@host/x'), 'https://[REDACTED]@host/x')

    def test_scrub_env_basic_cookie_pwd(self):
        cases=[('os.environ["TOKEN"]="tokenv123"','tokenv123'), ("os.environ['API_KEY'] = 'apienv456'",'apienv456'),
               ('Authorization: Basic dXNlcjpwYXNzd29yZA==','dXNlcjpwYXNzd29yZA'),
               ('{"Authorization": "Basic dXNlcjpwYXNzd29yZA=="}','dXNlcjpwYXNzd29yZA'),
               ('Cookie: session=sess789; other=oth012','sess789'), ('Cookie: session=sess789; other=oth012','oth012'),
               ('Set-Cookie: sid=sid345; Path=/; HttpOnly','sid345'), ('{"Cookie": "sid=sid345"}','sid345'),
               ('pwd=pw678','pw678'), ('PWD: pw678','pw678')]
        for text, secret in cases:
            with self.subTest(text):
                out=m.scrub(text)
                self.assertNotIn(secret, out)
                self.assertIn('[REDACTED]', out)
                self.assertNotIn('[REDACTED]"', out)
                self.assertNotIn("[REDACTED]'", out)
        self.assertEqual(m.scrub('os.environ["TOKEN"]="tokenv123"'), 'os.environ["TOKEN"]=[REDACTED]')
        self.assertEqual(m.scrub('Authorization: Basic dXNlcjpwYXNzd29yZA=='), 'Authorization: Basic [REDACTED]')
        for prose in ('the token count is 5', 'password policy', 'Basic authentication is weak', 'the Set-Cookie header',
                      'cookie policy applies', 'print the pwd output', 'Authorization required'):
            with self.subTest(prose):
                self.assertEqual(m.scrub(prose), prose)

    def test_timeout_bounds(self):
        import contextlib, io
        parse=lambda *a: m.build_parser().parse_args(['axis_sqlite.py', *a])
        self.assertEqual(parse().timeout, m.CHAT_TIMEOUT)
        self.assertEqual(parse('--timeout', '1').timeout, 1)
        self.assertEqual(parse('--timeout', '7200').timeout, 7200)
        for bad in ('0', '-5', '7201', 'abc'):
            with self.subTest(bad), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse('--timeout', bad)

    def test_scrub_secret_and_private_key_names(self):
        for text in ('SECRET_KEY = "django-insecure-abc"', 'private_key: django-insecure-abc', '{"secret-key": "django-insecure-abc"}'):
            with self.subTest(text):
                self.assertNotIn('django-insecure-abc', m.scrub(text))

    def test_untrusted_provider_stats_not_persisted(self):
        base=fake_api()
        def api(route, payload=None):
            result=base(route, payload)
            if route=='chat':
                result.update(done_reason={'password':'hunter2'}, eval_count='hunter3', prompt_eval_count=['hunter4'])
            return result
        report,files=self.run_one(api)
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual((report['done_reason'], report['eval_count'], report['prompt_eval_count']), (None, None, None))
        for text in files.values():
            for leak in ('hunter2', 'hunter3', 'hunter4'):
                self.assertNotIn(leak, text)
        report,_=self.run_one(fake_api(done_reason='api_key=abcdef123456 '+'x'*5000))
        self.assertNotIn('abcdef123456', report['done_reason'])
        self.assertLessEqual(len(report['done_reason']), 40)

    def test_findings_container_errors_named(self):
        for content in ('{"findings":"x"}', '{}', '[]', json.dumps({'findings':[finding()]*101})):
            with self.subTest(content[:20]):
                report,_=self.run_one(fake_api(content=content))
                self.assertEqual(report['status'], 'FAILED')
                self.assertEqual(report['reason'], 'ValueError: Invalid finding schema: findings')

    def test_non_string_model_names_fail_closed(self):
        calls=[]
        def api(route, payload=None):
            calls.append(route)
            return {'models':[{'name':1}, {'name':'local:1'}]}
        with tempfile.TemporaryDirectory() as d:
            _, result=m.run(['axis_sqlite.py'], {'Reviewer':'local:1'}, Path(d), api)
        self.assertEqual(calls, ['tags'])
        self.assertEqual(result['ollama'], 'UNAVAILABLE:ValueError')
        self.assertEqual(result['installed_models'], [])
        self.assertEqual(result['reports'][1]['status'], 'NOT_RUN')

    def test_scrub_no_backtracking(self):
        import time
        start=time.time()
        m.scrub('password' + '=' * 50000 + ' ' * 50000 + '"' * 50000 + '-----BEGIN PRIVATE KEY-----' * 2000)
        m.scrub('a' * 200000 + '://' + 'b:' * 50000)
        m.scrub('Authorization: ' * 20000 + 'Basic ' * 20000 + 'Cookie:' * 20000 + 'os.environ["token"]' * 20000)
        self.assertLess(time.time()-start, 5)
