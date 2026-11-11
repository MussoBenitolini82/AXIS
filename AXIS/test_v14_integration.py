"""AXIS v14 wiring: semantic memory, feedback learning, task traces, skill runs, memory status.

Every store lives in a temp dir; Ollama is never called (vector_intelligence.ask and axis_memory.embed are mocked)
and the HTTP tests talk to a real ThreadingHTTPServer on port 0.
"""
import base64
import hashlib
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import axis_feedback
import axis_learning
import axis_memory
import axis_trace
import axis_v13
import central_brain
import self_evolution
import server
import skill_runner
import vector_agents
import vector_intelligence as vi


def fake_embed(texts):
    """Deterministic unit vectors: 3 'topics' picked by keyword."""
    axis_memory._state = True  # what a real successful embed records
    out = []
    for t in texts:
        t = str(t).lower()
        out.append([1.0, 0.0, 0.0] if 'kuantum' in t else [0.0, 1.0, 0.0] if 'fotosentez' in t else [0.0, 0.0, 1.0])
    return out


class ImmediatePool:
    def submit(self, fn, *a, **k):
        fn(*a, **k)


class Base(unittest.TestCase):
    index = True  # MEMORY_INDEXING on: the semantic path is exercised

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.dir = d = Path(tmp.name)
        for mod, name, val in ((server, 'DB', d / 'vector.db'), (central_brain, 'DB', d / 'brain.sqlite3'),
                               (axis_learning, 'DB', d / 'learning.sqlite3'),
                               (axis_memory, 'DB', d / 'memory.sqlite3'), (axis_feedback, 'DB', d / 'feedback.sqlite3'),
                               (self_evolution, 'DB', d / 'evolution.db'), (self_evolution, 'SKILLS', d / 'skills'),
                               (self_evolution, 'PENDING', d / 'proposals'), (self_evolution, 'BACKUPS', d / 'backups'),
                               (server, 'MEMORY_INDEXING', self.index),
                               (vi, 'MODEL', 'qwen3:8b'), (vi, 'OLLAMA', 'http://127.0.0.1:11434/api/chat')):
            p = mock.patch.object(mod, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(axis_memory, 'embed', side_effect=fake_embed)
        self.embed = p.start()
        self.addCleanup(p.stop)
        axis_memory.reset_availability()
        server.ASK_JOBS.clear()
        self.addCleanup(server.ASK_JOBS.clear)
        self.seen = []

        def fake_ask(messages, temperature=0.2):
            self.seen.append(messages)
            return 'Yanıt.'
        p = mock.patch.object(vi, 'ask', side_effect=fake_ask)
        p.start()
        self.addCleanup(p.stop)

    def seed(self, rows):
        with server.connect() as db:
            ids = [server.add_node(db, label, kind, desc) for label, kind, desc in rows]
            db.commit()
        return ids


class HttpBase(Base):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_address[1]

    def call(self, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, method='GET' if payload is None else 'POST',
                                     headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def ask(self, question):
        code, body = self.call('/api/ask', {'question': question})
        self.assertEqual(code, 202)
        end = time.time() + 10
        while time.time() < end:
            code, job = self.call('/api/ask-result?id=' + body['job_id'])
            if job['status'] != 'running':
                return body['job_id'], job
            time.sleep(0.03)
        self.fail('ask job did not finish')


class SemanticAnswerTests(Base):
    def hits(self, *rows):
        return mock.patch.object(axis_memory, 'semantic_search', return_value=list(rows))

    def test_merge_keyword_first_then_semantic_chunk_and_node(self):
        kw, other = self.seed([('kuantum hesaplama', 'topic', 'kuantum bilgisayarlar'), ('Bilgi kuramı', 'concept', 'entropi')])
        with self.hits({'id': kw, 'kind': 'topic', 'label': 'x', 'text': 'x', 'score': .9},
                       {'id': 'chunk:abc:2', 'kind': 'chunk', 'label': 'Kitap.pdf · bölüm 3', 'text': 'Ç' * 900, 'score': .8},
                       {'id': other, 'kind': 'concept', 'label': 'x', 'text': 'x', 'score': .7},
                       {'id': 'concept:silinmis', 'kind': 'concept', 'label': 'y', 'text': 'y', 'score': .6}) as ss:
            items = vi.relevant_memory('kuantum')
            self.assertEqual([r['id'] for r in items], [kw, 'chunk:abc:2', other])
            self.assertEqual(items[1], {'id': 'chunk:abc:2', 'label': 'Kitap.pdf · bölüm 3', 'kind': 'chunk', 'description': 'Ç' * 900})
            self.assertEqual(items[2]['label'], 'Bilgi kuramı')  # a graph node comes back as its own row
            self.assertEqual(ss.call_args.args[0], 'kuantum')
            self.assertEqual(ss.call_args.kwargs['min_score'], axis_memory.recommended_min_score())
        self.assertEqual(vi.MAX_MEMORY_ITEMS, 8)

    def test_semantic_hits_capped_at_max_items(self):
        self.seed([('kuantum a', 'topic', 'x')])
        rows = [{'id': 'chunk:z:%d' % i, 'kind': 'chunk', 'label': 'c', 'text': 't', 'score': .9} for i in range(20)]
        with self.hits(*rows):
            self.assertEqual(len(vi.relevant_memory('kuantum')), 8)

    def test_chunk_text_reaches_prompt_and_result_flags_semantic(self):
        self.seed([('Fotosentez', 'concept', 'bitkiler')])
        with self.hits({'id': 'chunk:abc:0', 'kind': 'chunk', 'label': 'Kitap.pdf · bölüm 1', 'text': 'Kuantum dolanıklık ' + 'k' * 800, 'score': .9}):
            r = vi.answer_question('Dolanıklık nedir?')
        self.assertTrue(r['semantic'])
        self.assertEqual(r['used_feedback'], 0)
        self.assertIn('chunk:abc:0', [m['id'] for m in r['used_memory']])
        user = self.seen[0][1]['content']
        self.assertIn('Kuantum dolanıklık', user)
        self.assertNotIn('k' * 701, user)  # chunk text is capped at 700 characters

    def test_failing_or_empty_semantic_search_keeps_keyword_behaviour(self):
        ids = self.seed([('neural networks', 'topic', 'x')])
        for patch in (mock.patch.object(axis_memory, 'semantic_search', side_effect=RuntimeError('boom')),
                      mock.patch.object(axis_memory, 'semantic_search', return_value=[]),
                      mock.patch.object(axis_memory, 'recommended_min_score', side_effect=RuntimeError('boom'))):
            with patch:
                r = vi.answer_question('neural networks nedir?')
            self.assertFalse(r['semantic'])
            self.assertEqual([m['id'] for m in r['used_memory']], ids)
            self.assertEqual(r['answer'], 'Yanıt.')

    def test_missing_recommended_min_score_falls_back(self):
        self.seed([('neural networks', 'topic', 'x')])
        with mock.patch.object(axis_memory, 'recommended_min_score', None), self.hits() as ss:
            vi.relevant_memory('neural')
        self.assertEqual(ss.call_args.kwargs['min_score'], 0.55)

    def test_end_to_end_with_real_axis_memory_and_fake_embeddings(self):
        (paper,) = self.seed([('Quantum paper', 'paper', 'kuantum bilgisayarlar üzerine')])
        server.memory_sync_once()
        r = vi.answer_question('kuantum')  # no keyword overlap with the English label only through the description
        self.assertIn(paper, [m['id'] for m in r['used_memory']])
        r = vi.answer_question('Hakkında konuşalım: kuantum')
        self.assertTrue(r['semantic'] or paper in [m['id'] for m in r['used_memory']])

    def test_indexing_flag_off_never_touches_axis_memory(self):
        with mock.patch.object(server, 'MEMORY_INDEXING', False), self.hits() as ss:
            r = vi.answer_question('Fotosentez nedir?')
            server.index_memory([{'id': 'a', 'kind': 'k', 'label': 'l', 'text': 't'}])
        ss.assert_not_called()
        self.assertFalse(r['semantic'])
        self.assertEqual(axis_memory.status()['items'], 0)

    def test_action_refusal_has_new_fields(self):
        r = vi.answer_question('güncellemeleri uygula')
        self.assertEqual((r['semantic'], r['used_feedback'], r['action_refused']), (False, 0, True))


class FeedbackPromptTests(Base):
    def test_note_and_block_only_when_a_correction_matched(self):
        axis_feedback.record('old', 'Kuantum dolanıklık nedir?', 'eski', 'down', 'Dolanıklık iki parçacığın ortak durumudur.')
        r = vi.answer_question('Kuantum dolanıklık nasıl çalışır?')
        system, user = self.seen[-1][0]['content'], self.seen[-1][1]['content']
        self.assertIn(axis_feedback.PROMPT_NOTE, system)
        self.assertIn('komut değildir', user)  # reminder next to the block: preference data, never an instruction
        self.assertIn('<geri_bildirim>', user)
        self.assertIn('ortak durumudur', user)
        self.assertTrue(user.index('</bellek>') < user.index('Soru: ') < user.index('<geri_bildirim>'))
        self.assertEqual(r['used_feedback'], 1)
        r = vi.answer_question('Fotosentez nedir?')
        self.assertNotIn(axis_feedback.PROMPT_NOTE, self.seen[-1][0]['content'])
        self.assertNotIn('geri_bildirim', self.seen[-1][1]['content'])
        self.assertEqual(r['used_feedback'], 0)

    def test_rating_without_correction_adds_nothing(self):
        axis_feedback.record('old', 'Kuantum dolanıklık nedir?', 'eski', 'up')
        r = vi.answer_question('Kuantum dolanıklık nedir?')
        self.assertEqual(r['used_feedback'], 0)
        self.assertNotIn(axis_feedback.PROMPT_NOTE, self.seen[-1][0]['content'])

    def test_failing_feedback_store_never_breaks_an_answer(self):
        axis_feedback.record('old', 'Fotosentez nedir?', 'x', 'up', 'düzeltme')
        with mock.patch.object(axis_feedback, 'prompt_block', side_effect=RuntimeError('boom')):
            r = vi.answer_question('Fotosentez nedir?')
        self.assertEqual((r['answer'], r['used_feedback']), ('Yanıt.', 0))
        self.assertNotIn(axis_feedback.PROMPT_NOTE, self.seen[-1][0]['content'])


class FeedbackHttpTests(HttpBase):
    def test_feedback_uses_server_side_question_and_answer(self):
        jid, job = self.ask('Kuantum dolanıklık nedir?')
        self.assertEqual(job['status'], 'completed')
        code, rec = self.call('/api/feedback', {'job_id': jid, 'rating': 'down', 'correction': 'Kısa tut.',
                                                'question': 'SAHTE SORU', 'answer': 'SAHTE CEVAP'})
        self.assertEqual(code, 201)
        self.assertEqual((rec['job_id'], rec['rating'], rec['correction']), (jid, 'down', 'Kısa tut.'))
        row = axis_feedback.listing()[0]
        self.assertEqual((row['question'], row['answer']), ('Kuantum dolanıklık nedir?', 'Yanıt.'))
        code, stats = self.call('/api/feedback-stats')
        self.assertEqual((code, stats['total'], stats['down'], stats['with_correction']), (200, 1, 1, 1))
        # The correction now steers a similar question.
        jid2, job2 = self.ask('Kuantum dolanıklık hakkında bilgi ver')
        self.assertEqual(job2['used_feedback'], 1)
        self.assertIn(axis_feedback.PROMPT_NOTE, self.seen[-1][0]['content'])

    def test_unknown_job_404_running_job_400_bad_input_400(self):
        code, _ = self.call('/api/feedback', {'job_id': 'yok', 'rating': 'up'})
        self.assertEqual(code, 404)
        server.ASK_JOBS['run1'] = {'id': 'run1', 'status': 'running', 'question': 'q', 'created': server.now(), 'error': None}
        code, body = self.call('/api/feedback', {'job_id': 'run1', 'rating': 'up'})
        self.assertEqual(code, 400)
        self.assertIn('error', body)
        code, _ = self.call('/api/feedback', {'job_id': 'y', 'rating': 'up'})
        self.assertEqual(code, 404)
        jid, _ = self.ask('Fotosentez nedir?')
        for payload in ({'job_id': jid, 'rating': 'meh'}, {'job_id': jid}, {'job_id': jid, 'rating': 'up', 'correction': 5}):
            code, _ = self.call('/api/feedback', payload)
            self.assertEqual(code, 400, payload)
        self.assertEqual(axis_feedback.stats()['total'], 0)

    def test_action_refusal_and_failed_job_are_not_ratable(self):
        jid, job = self.ask('güncellemeleri uygula')
        self.assertTrue(job['action_refused'])
        self.assertEqual(self.call('/api/feedback', {'job_id': jid, 'rating': 'up'})[0], 400)
        with mock.patch.object(vi, 'ask', side_effect=TimeoutError('timed out')):
            jid, job = self.ask('Fotosentez nedir?')
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(self.call('/api/feedback', {'job_id': jid, 'rating': 'up'})[0], 400)

    def test_guards_still_apply(self):
        code, _ = self.call('/api/feedback', {'job_id': 'x', 'rating': 'up'}, {'Origin': 'http://evil.example'})
        self.assertEqual(code, 403)
        self.assertEqual(self.call('/api/yok', {})[0], 404)


class TraceHttpTests(HttpBase):
    def test_ask_job_span_is_visible_in_traces(self):
        self.seed([('neural networks', 'topic', 'x')])
        jid, job = self.ask('neural networks nedir?')
        code, body = self.call('/api/task-traces?limit=10')
        self.assertEqual(code, 200)
        self.assertEqual(set(body), {'tasks', 'summary'})
        task = next(t for t in body['tasks'] if t['task_id'] == jid)
        self.assertIn('assistant', task['agents'])
        code, tr = self.call('/api/task-trace?id=' + jid)
        self.assertEqual(code, 200)
        spans = [s for s in tr['steps'] if s['kind'] == 'span']
        self.assertEqual([s['tool'] for s in spans], ['answer_question'])
        self.assertEqual(spans[0]['outcome'], 'success')
        self.assertIn('memory=1', json.dumps(spans[0], ensure_ascii=False))
        self.assertIn('tasks', self.call('/api/task-traces')[1]['summary'])

    def test_failed_ask_records_failure_span_and_keeps_error_path(self):
        with mock.patch.object(vi, 'ask', side_effect=TimeoutError('timed out')):
            jid, job = self.ask('Fotosentez nedir?')
        self.assertIn('zaman aşımı', job['error'])
        tr = self.call('/api/task-trace?id=' + jid)[1]
        self.assertEqual([s['outcome'] for s in tr['steps'] if s['kind'] == 'span'], ['failure'])

    def test_unknown_trace_id_and_bad_limit_are_400(self):
        code, body = self.call('/api/task-trace?id=yok')
        self.assertEqual(code, 400)
        self.assertIn('error', body)
        self.assertEqual(self.call('/api/task-trace')[0], 400)
        self.assertEqual(self.call('/api/task-traces?limit=abc')[0], 400)

    def test_research_span_notes_source_and_partial_on_zero_works(self):
        with mock.patch.object(server, 'POOL', ImmediatePool()), \
                mock.patch.object(server, 'find_works', return_value=([], 'OpenAlex', '')):
            code, body = self.call('/api/research', {'topic': 'boş konu'})
        self.assertEqual(code, 202)
        tr = self.call('/api/task-trace?id=' + body['job_id'])[1]
        span = next(s for s in tr['steps'] if s['kind'] == 'span')
        self.assertEqual((span['agent'], span['tool'], span['outcome']), ('research', 'literature_search', 'partial'))
        self.assertIn('source=OpenAlex', json.dumps(span))
        self.assertIn('records=0', json.dumps(span))

    def test_research_failure_keeps_failed_job_and_records_failure_span(self):
        with mock.patch.object(server, 'POOL', ImmediatePool()), \
                mock.patch.object(server, 'find_works', side_effect=RuntimeError('ağ yok')):
            code, body = self.call('/api/research', {'topic': 'başarısız konu'})
        self.assertEqual(self.call('/api/status')[1]['jobs'][0]['status'], 'failed')
        tr = self.call('/api/task-trace?id=' + body['job_id'])[1]
        self.assertEqual([s['outcome'] for s in tr['steps'] if s['kind'] == 'span'], ['failure'])

    def test_agent_run_span_and_new_default_targets(self):
        with mock.patch.object(vector_agents, 'run', return_value={'id': 'r1', 'status': 'awaiting_tests_and_approval'}) as run, \
                mock.patch.object(axis_v13, 'development', return_value={'ok': 1}) as dev, \
                mock.patch.object(axis_v13, 'repair', return_value={'ok': 2}) as rep:
            self.assertEqual(self.call('/api/agent-run', {'request': 'x'})[0], 201)
            self.assertEqual(self.call('/api/axis-v13-develop', {'request': 'x'})[0], 201)
            self.assertEqual(self.call('/api/axis-v13-repair', {'error': 'x'})[0], 201)
            self.assertEqual(self.call('/api/agent-run', {'request': 'x', 'target': 'extensions/baska.py'})[0], 201)
        self.assertEqual(run.call_args_list[0].args[1], 'extensions/research_extensions.py')
        self.assertEqual(run.call_args_list[1].args[1], 'extensions/baska.py')
        self.assertEqual(dev.call_args.args[1], 'extensions/research_extensions.py')
        self.assertEqual(rep.call_args.args[1], 'extensions/research_extensions.py')
        steps = [s for t in axis_trace.tasks(include_api=True) for s in axis_trace.trace(t['task_id'])['steps']]
        self.assertEqual(sum(1 for s in steps if s['kind'] == 'span' and s['tool'] == 'agent_run'), 2)


class SkillHttpTests(HttpBase):
    def approve(self, name='merhaba', source=b'def run(data):\n    return data\n'):
        digest = hashlib.sha256(source).hexdigest()
        (self.dir / 'skills').mkdir(exist_ok=True)
        (self.dir / 'skills' / (name + '.py')).write_bytes(source)
        return mock.patch.object(self_evolution, 'approved_digest', lambda s: (digest, '2026-01-01T00:00:00') if s == name else None)

    def test_runnable_lists_approved_skills(self):
        self.assertEqual(self.call('/api/skills-runnable'), (200, []))
        with self.approve():
            code, body = self.call('/api/skills-runnable')
        self.assertEqual(code, 200)
        self.assertEqual([x['skill'] for x in body], ['merhaba'])
        self.assertEqual(set(body[0]), {'skill', 'sha256', 'approved_at'})

    def test_run_invalid_requests_are_400(self):
        for payload in ({}, {'skill': 5}, {'skill': '../x', 'data': {}}, {'skill': 'onaysiz', 'data': {}}):
            code, body = self.call('/api/skill-run', payload)
            self.assertEqual(code, 400, payload)
            self.assertIn('error', body)

    def test_run_blocked_without_docker_is_200(self):
        with self.approve(), mock.patch.object(skill_runner.vector_upgrade, 'docker_available', return_value=False), \
                mock.patch.object(skill_runner.subprocess, 'run') as sp:
            code, body = self.call('/api/skill-run', {'skill': 'merhaba', 'data': {'a': 1}})
        self.assertEqual(code, 200)
        self.assertEqual((body['skill'], body['status']), ('merhaba', 'blocked'))
        self.assertTrue(body['error'])
        sp.assert_not_called()

    def test_run_result_is_passed_through(self):
        fake = {'skill': 's', 'status': 'success', 'output': {'x': 1}, 'error': None, 'elapsed_s': 0.1, 'sha256': 'ab'}
        with mock.patch.object(skill_runner, 'run', return_value=fake) as run:
            code, body = self.call('/api/skill-run', {'skill': 's', 'data': {'q': 2}})
        self.assertEqual((code, body), (200, fake))
        run.assert_called_once_with('s', {'q': 2})


class MemoryTests(HttpBase):
    def test_capabilities_lists_new_features_and_embed_model(self):
        code, body = self.call('/api/capabilities')
        self.assertEqual(code, 200)
        for f in ('semantic_memory', 'feedback_learning', 'task_trace', 'skill_run'):
            self.assertIn(f, body['features'])
        self.assertEqual(body['embed_model'], axis_memory.EMBED_MODEL)

    def test_status_and_backfill_endpoints(self):
        self.assertEqual(self.call('/api/memory-status')[1], {'model': axis_memory.EMBED_MODEL, 'items': 0, 'embedded': 0, 'available': None})
        axis_memory.upsert('a', 'concept', 'Kuantum', 'metin')
        code, r = self.call('/api/memory-backfill', {})
        self.assertEqual(code, 200)
        self.assertEqual((r['embedded'], r['pending']), (1, 0))
        self.assertEqual(self.call('/api/memory-status')[1]['embedded'], 1)

    def test_backfill_without_ollama_is_a_normal_200(self):
        axis_memory.upsert('a', 'concept', 'Kuantum', 'metin')
        self.embed.side_effect = None
        self.embed.return_value = None
        code, r = self.call('/api/memory-backfill', {})
        self.assertEqual((code, r['embedded'], r['pending']), (200, 0, 1))

    def test_research_indexes_topic_and_papers(self):
        works = [{'id': 'W%d' % i, 'title': 'Kuantum makale %d' % i, 'year': 2020, 'doi': None, 'url': '',
                  'abstract': 'Uzun özet ' * 80 + str(i), 'concepts': ['c']} for i in range(2)]
        with mock.patch.object(server, 'POOL', ImmediatePool()), \
                mock.patch.object(server, 'find_works', return_value=(works, 'OpenAlex', '')):
            code, body = self.call('/api/research', {'topic': 'kuantum konusu'})
        self.assertEqual(code, 202)
        self.assertEqual(self.call('/api/status')[1]['jobs'][0]['status'], 'completed')
        with axis_memory._open() as db:
            rows = {r['id']: dict(r) for r in db.execute('SELECT id,kind,label,text FROM items')}
        self.assertEqual(sum(1 for r in rows.values() if r['kind'] == 'paper'), 2)
        paper = rows[server.node_id('paper', 'Kuantum makale 0')]
        self.assertEqual(paper['text'], works[0]['abstract'])  # the full abstract, not the 350-char node description
        self.assertEqual(rows[server.node_id('topic', 'kuantum konusu')]['label'], 'kuantum konusu')

    def test_index_failure_never_fails_research(self):
        works = [{'id': 'W1', 'title': 'Makale', 'year': 2020, 'doi': None, 'url': '', 'abstract': 'a', 'concepts': []}]
        with mock.patch.object(server, 'POOL', ImmediatePool()), \
                mock.patch.object(server, 'find_works', return_value=(works, 'OpenAlex', '')), \
                mock.patch.object(axis_memory, 'upsert_many', side_effect=RuntimeError('disk dolu')):
            self.call('/api/research', {'topic': 'kuantum konusu'})
        self.assertEqual(self.call('/api/status')[1]['jobs'][0]['status'], 'completed')

    def make_pdf(self, pages=6):
        import fitz
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page()
            y = 72
            for j in range(40):
                page.insert_text((50, y), 'Kuantum satir %d-%d dolanikligin ayrintili anlatimi burada' % (i, j), fontsize=9)
                y += 16
        raw = doc.tobytes()
        doc.close()
        return raw

    def test_pdf_chunks_are_indexed(self):
        raw = self.make_pdf()
        digest = hashlib.sha256(raw).hexdigest()[:16]
        code, body = self.call('/api/pdf', {'filename': 'Kitap.pdf', 'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual(code, 201)
        self.assertGreater(body['chunks'], 3)
        self.assertNotIn('Yalnızca ilk 5500', body['note'])
        with axis_memory._open() as db:
            rows = [dict(r) for r in db.execute("SELECT id,kind,label FROM items WHERE kind='chunk' ORDER BY id")]
        self.assertEqual(len(rows), body['chunks'])
        self.assertIn('chunk:%s:0' % digest, [r['id'] for r in rows])
        self.assertEqual(next(r for r in rows if r['id'] == 'chunk:%s:1' % digest)['label'], 'Kitap.pdf · bölüm 2')
        with axis_memory._open() as db:  # text beyond the first 5500 characters is searchable
            self.assertTrue(any('5-39' in r['text'] for r in db.execute("SELECT text FROM items WHERE kind='chunk'")))

    def test_pdf_upload_survives_index_failure(self):
        raw = self.make_pdf(1)
        with mock.patch.object(axis_memory, 'upsert_many', side_effect=RuntimeError('boom')):
            code, body = self.call('/api/pdf', {'filename': 'a.pdf', 'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual(code, 201)
        with mock.patch.object(axis_memory, 'chunk_text', side_effect=RuntimeError('boom')):
            code, body = self.call('/api/pdf', {'filename': 'b.pdf', 'content_base64': base64.b64encode(raw + b' ').decode()})
        self.assertIn(code, (201, 400))  # a changed byte may break the PDF; either way the server answered normally

    def test_sync_once_indexes_graph_and_embeds_in_batches(self):
        ids = self.seed([('Kuantum konu', 'topic', 'kuantum'), ('Makale', 'paper', 'kısa'), ('Fotosentez', 'concept', 'bitki')])
        with server.connect() as db:
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?)', ('s1', 'Makale', '', '', 2020, 'tam kuantum özeti', server.now()))
            db.execute('INSERT INTO evidence VALUES (?,?,?)', (ids[1], 's1', 'kısa'))
            db.commit()
        with mock.patch.object(server, 'MEMORY_BATCH', 2):
            r = server.memory_sync_once()
        self.assertEqual((r['synced'], r['pending']), (3, 0))
        self.assertEqual(r['embedded'], 3)
        self.assertEqual(axis_memory.status()['embedded'], 3)
        hit = axis_memory.semantic_search('kuantum', min_score=.5)
        self.assertEqual({h['id'] for h in hit}, {ids[0], ids[1]})
        self.assertEqual(next(h for h in hit if h['id'] == ids[1])['text'], 'tam kuantum özeti')
        self.assertEqual(server.memory_sync_once()['synced'], 0)  # idempotent

    def test_sync_once_stops_when_embeddings_unavailable(self):
        self.seed([('Kuantum konu', 'topic', 'kuantum')])
        self.embed.side_effect = None
        self.embed.return_value = None
        r = server.memory_sync_once()
        self.assertEqual((r['embedded'], r['pending']), (0, 1))
        self.assertEqual(self.embed.call_count, 1)

    def test_background_worker_syncs_without_blocking(self):
        self.seed([('Kuantum konu', 'topic', 'kuantum')])
        self.addCleanup(server.stop_memory_worker)
        gate = threading.Event()
        real = server.memory_sync_once

        def slow():
            gate.wait(5)
            return real()
        with mock.patch.object(server, 'memory_sync_once', side_effect=slow):
            t0 = time.monotonic()
            self.assertTrue(server.start_memory_worker())
            self.assertLess(time.monotonic() - t0, 1)  # start-up never waits for the pass
            self.assertFalse(server.start_memory_worker())  # one worker only
            self.assertTrue(server._MEM_THREAD[0].daemon)
            gate.set()
            end = time.time() + 5
            while time.time() < end and axis_memory.status()['embedded'] < 1:
                time.sleep(0.05)
        self.assertEqual(axis_memory.status()['embedded'], 1)
        server.stop_memory_worker()
        self.assertFalse(server._MEM_THREAD[0].is_alive())


class RobustnessTests(HttpBase):
    def hits(self, *rows):
        return mock.patch.object(axis_memory, 'semantic_search', return_value=list(rows))

    def test_broken_tracing_never_changes_ask_result(self):
        self.seed([('neural networks', 'topic', 'x')])
        with mock.patch.object(axis_trace, 'span', side_effect=RuntimeError('trace bozuk')):
            jid, job = self.ask('neural networks nedir?')
        self.assertEqual((job['status'], job['answer']), ('completed', 'Yanıt.'))

    def test_span_exit_and_note_failures_keep_answer_research_and_agent_run(self):
        class BadSpan:
            def __enter__(self):
                return self

            def note(self, *a):
                raise RuntimeError('note')

            def partial(self):
                raise RuntimeError('partial')

            def __exit__(self, *a):
                raise RuntimeError('exit')
        works = [{'id': 'W1', 'title': 'Makale', 'year': 2020, 'doi': None, 'url': '', 'abstract': 'a', 'concepts': []}]
        with mock.patch.object(axis_trace, 'span', side_effect=lambda *a, **k: BadSpan()),                 mock.patch.object(server, 'POOL', ImmediatePool()),                 mock.patch.object(server, 'find_works', return_value=(works, 'OpenAlex', '')),                 mock.patch.object(vector_agents, 'run', return_value={'id': 'r', 'status': 'awaiting_tests_and_approval'}):
            jid, job = self.ask('Fotosentez nedir?')
            self.assertEqual((job['status'], job['answer']), ('completed', 'Yanıt.'))
            self.call('/api/research', {'topic': 'kuantum konusu'})
            self.assertEqual(self.call('/api/status')[1]['jobs'][0]['status'], 'completed')
            code, body = self.call('/api/agent-run', {'request': 'x'})
            self.assertEqual((code, body['status']), (201, 'awaiting_tests_and_approval'))

    def test_original_exception_survives_a_failing_span_exit(self):
        class BadSpan:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                raise RuntimeError('exit')
        with mock.patch.object(axis_trace, 'span', side_effect=lambda *a, **k: BadSpan()),                 mock.patch.object(vi, 'ask', side_effect=TimeoutError('timed out')):
            jid, job = self.ask('Fotosentez nedir?')
        self.assertEqual(job['status'], 'failed')
        self.assertIn('zaman aşımı', job['error'])

    def test_semantic_flag_false_when_chunks_do_not_reach_prompt(self):
        self.seed([('Fotosentez', 'concept', 'bitkiler')])
        with self.hits({'id': 'chunk:abc:0', 'kind': 'chunk', 'label': 'K', 'text': 't', 'score': .9}),                 mock.patch.object(vi, 'RAG_CONTEXT_CHARS', 20):
            r = vi.answer_question('Fotosentez nedir?')
        self.assertFalse(r['semantic'])
        self.assertNotIn('chunk:abc:0', [m['id'] for m in r['used_memory']])

    def test_semantic_hits_get_reserved_slots_when_keywords_fill_everything(self):
        self.seed([('neural network %d' % i, 'paper', 'neural network') for i in range(12)])
        with self.hits({'id': 'chunk:a:0', 'kind': 'chunk', 'label': 'c0', 'text': 't0', 'score': .9},
                       {'id': 'chunk:a:1', 'kind': 'chunk', 'label': 'c1', 'text': 't1', 'score': .8}):
            items = vi.relevant_memory('neural network')
        self.assertEqual(len(items), 7)
        self.assertEqual([r['id'] for r in items[5:]], ['chunk:a:0', 'chunk:a:1'])
        with self.hits():
            self.assertEqual(len(vi.relevant_memory('neural network')), 8)  # no semantic hits: today's behaviour

    def test_pdf_chunk_count_is_what_was_stored(self):
        raw = MemoryTests.make_pdf(self, 1)
        with mock.patch.object(axis_memory, 'upsert_many', side_effect=RuntimeError('boom')):
            code, body = self.call('/api/pdf', {'filename': 'a.pdf', 'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual((code, body['chunks']), (201, 0))
        self.assertIn('eklenemedi', body['note'])
        with mock.patch.object(server, 'MEMORY_INDEXING', False):
            self.assertEqual(self.call('/api/pdf', {'filename': 'a.pdf', 'content_base64': base64.b64encode(raw).decode()})[1]['chunks'], 0)


if __name__ == '__main__':
    unittest.main()
