"""Regression tests for the 2026-11-11 code review fixes. Every path is isolated in a temp folder."""
import http.client, json, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import axis_feedback, axis_learning, axis_memory, central_brain, self_evolution, server, vector_agents, vector_intelligence, vector_upgrade


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(tmp.cleanup)
        self.tmp = d = Path(tmp.name)
        root = d / 'root'; specs = d / 'behavior_specs'
        dirs = {k: d / k for k in ('skills', 'proposals', 'backups')}
        for p in (root, specs, *dirs.values()): p.mkdir()
        for mod, name, val in (
                (server, 'DB', d / 'vector.db'), (central_brain, 'DB', d / 'brain.sqlite3'),
                (axis_learning, 'DB', d / 'learning.sqlite3'), (axis_memory, 'DB', d / 'memory.sqlite3'),
                (axis_feedback, 'DB', d / 'feedback.sqlite3'),
                (vector_upgrade, 'DATA', d), (vector_upgrade, 'DB', d / 'upgrades.sqlite3'),
                (vector_upgrade, 'TESTS', specs), (vector_upgrade, 'ROOT', root),
                (vector_agents, 'ROOT', root), (vector_agents, 'DB', d / 'agents.sqlite3'),
                (self_evolution, 'SKILLS', dirs['skills']), (self_evolution, 'PENDING', dirs['proposals']),
                (self_evolution, 'BACKUPS', dirs['backups']), (self_evolution, 'DB', d / 'evolution.db')):
            p = patch.object(mod, name, val); p.start(); self.addCleanup(p.stop)


class HttpTests(Isolated):
    def setUp(self):
        super().setUp()
        p = patch.object(server.axis_learning, 'record', lambda *a, **k: 'x'); p.start(); self.addCleanup(p.stop)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close); self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=10)
        try:
            c.putrequest(method, path, skip_host=bool(headers and 'Host' in headers))
            for k, v in (headers or {}).items(): c.putheader(k, v)
            c.endheaders(body)
            r = c.getresponse()
            return r.status, json.loads(r.read())
        finally:
            c.close()

    def test_get_unknown_id_is_json_400_not_dropped_connection(self):
        for path in ('/api/upgrade-detail?id=yok', '/api/agent-detail?id=yok', '/api/behavior-cases?id=yok'):
            code, body = self.request('GET', path)
            self.assertEqual(code, 400, path); self.assertIn('error', body)

    def test_foreign_host_name_is_refused(self):
        self.assertEqual(self.request('GET', '/api/status', {'Host': 'evil.example:8765'})[0], 403)
        self.assertEqual(self.request('POST', '/api/research', {'Host': 'evil.example', 'Content-Length': '2'}, b'{}')[0], 403)
        for host in ('localhost:8765', '127.0.0.1', '[::1]:8765'):
            self.assertEqual(self.request('GET', '/api/status', {'Host': host})[0], 200, host)

    def test_negative_content_length_is_rejected(self):
        code, body = self.request('POST', '/api/research', {'Content-Length': '-1'})
        self.assertEqual(code, 400); self.assertIn('Content-Length', body['error'])


class ResearchTests(Isolated):
    def job(self, status='running'):
        with server.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', ('j1', 'konu', status, '', server.now())); db.commit()

    def status(self):
        with server.connect() as db:
            return db.execute("SELECT status FROM jobs WHERE id='j1'").fetchone()[0]

    def test_failed_search_marks_job_even_if_audit_log_fails(self):
        self.job()
        with patch.object(server, 'find_works', side_effect=RuntimeError('')), \
                patch.object(server.brain, 'log', side_effect=ValueError('log bozuk')):
            server.research('konu', 'j1', 5)
        self.assertEqual(self.status(), 'failed')

    def test_completed_search_survives_audit_log_failure(self):
        self.job()
        work = {'id': 'w1', 'title': 'T', 'year': 2020, 'doi': None, 'url': '', 'abstract': 'a', 'concepts': ['c']}
        with patch.object(server, 'find_works', return_value=([work], 'OpenAlex', '')), \
                patch.object(server.brain, 'log', side_effect=ValueError('log bozuk')):
            server.research('konu', 'j1', 5)
        self.assertEqual(self.status(), 'completed')

    def test_stale_running_jobs_are_closed_at_startup(self):
        self.job()
        self.assertEqual(server.fail_stale_jobs(), 1)
        self.assertEqual(self.status(), 'failed')
        self.assertEqual(server.fail_stale_jobs(), 0)

    def test_openalex_null_concepts_do_not_abort(self):
        data = {'results': [{'id': 'w', 'title': 'T', 'concepts': None},
                            {'id': 'v', 'title': 'U', 'concepts': [{'display_name': 'X', 'score': None}, {'score': .9}, {'display_name': 'Y', 'score': .9}]}]}
        with patch.object(server, 'fetch_json', return_value=data):
            out = server.search_openalex('konu', 2)
        self.assertEqual([w['concepts'] for w in out], [[], ['Y']])

    def test_count_nodes_is_not_capped_and_search_is_literal(self):
        with server.connect() as db:
            for i in range(505): server.add_node(db, f'dugum {i}', 'concept')
            server.add_node(db, '100% dogru', 'concept')
            db.commit()
        self.assertEqual(vector_intelligence.count_nodes()['nodes'], 506)
        self.assertEqual(len(vector_intelligence.search_memory('%')), 1)
        self.assertEqual(vector_intelligence.search_memory('_'), [])


class UpgradeTests(Isolated):
    def test_contract_checks_candidate_not_behavior_runner(self):
        work = self.tmp / 'work'; work.mkdir()
        # A name that sorts after test_behavior.py, plus the runner that itself uses getattr/importlib.
        (work / 'vector_extra.py').write_text('def f():\n return 1\n', encoding='utf-8')
        (work / 'test_behavior.py').write_text(vector_upgrade.BEHAVIOR_RUNNER, encoding='utf-8')
        (work / 'test_contract.py').write_text('', encoding='utf-8')
        scope = {}
        exec(vector_upgrade.CONTRACT_TEST.replace("'/work'", repr(work.as_posix())), scope)
        result = unittest.TextTestRunner(stream=open(self.tmp / 'out.txt', 'w')).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(scope['Contract']))
        result.stream.close()
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)

    def test_agent_proposal_is_queued_only_after_behavior_cases(self):
        seen = []
        def scheduler(uid):
            seen.append((vector_upgrade.TESTS / (uid + '.json')).exists())
        cases = json.dumps([{'function': 'run', 'args': [1], 'expected': 1}])
        with patch.object(vector_upgrade, 'SCHEDULER', scheduler), \
                patch.object(vector_agents, 'llm', side_effect=['Plan', 'def run(x): return x', 'VERDICT: PASS\nok', cases]):
            r = vector_agents.run('Saf hesaplama becerisi oluştur ve öner', 'extensions/research_extensions.py')
        self.assertEqual(r['status'], 'awaiting_tests_and_approval')
        self.assertEqual(seen, [True])   # queued exactly once, with the cases already on disk

    def test_agent_proposal_for_top_level_target_is_never_queued(self):
        seen = []
        cases = json.dumps([{'function': 'run', 'args': [1], 'expected': 1}])
        with patch.object(vector_upgrade, 'SCHEDULER', seen.append), \
                patch.object(vector_agents, 'llm', side_effect=['Plan', 'def run(x): return x', 'VERDICT: PASS\nok', cases]):
            r = vector_agents.run('Saf hesaplama becerisi oluştur ve öner', 'research_extensions.py')
        self.assertEqual(r['status'], 'awaiting_tests_and_approval')
        self.assertEqual(r['proposal']['status'], 'pending')
        self.assertFalse(r['proposal']['auto_eligible'])
        self.assertEqual(seen, [])   # manual-only: needs decide(..., 'ONAYLIYORUM')

    def test_agent_proposal_is_still_queued_when_test_design_fails(self):
        seen = []
        with patch.object(vector_upgrade, 'SCHEDULER', seen.append), \
                patch.object(vector_agents, 'llm', side_effect=['Plan', 'def run(x): return x', 'VERDICT: PASS\nok', OSError('ollama yok')]):
            r = vector_agents.run('Saf hesaplama becerisi oluştur ve öner', 'extensions/research_extensions.py')
        self.assertEqual(r['status'], 'awaiting_tests_and_approval')
        self.assertEqual(seen, [r['proposal_id']])


class SkillProposalTests(Isolated):
    def test_code_with_crlf_can_be_approved_byte_exact(self):
        code = 'def run(data):\r\n    return data\r\n'
        pid = self_evolution.propose('ornek', code, 'crlf')['id']
        self.assertEqual(self_evolution.decide(pid, 'approve', 'ONAYLIYORUM')['status'], 'approved')
        self.assertEqual((self_evolution.SKILLS / 'ornek.py').read_bytes(), code.encode())

    def test_legacy_text_mode_staging_is_still_accepted(self):
        pid = self_evolution.propose('eski', 'def run(d):\n    return d\n', 'x')['id']
        (self_evolution.PENDING / (pid + '.py')).write_bytes(b'def run(d):\r\n    return d\r\n')
        self.assertEqual(self_evolution.decide(pid, 'approve', 'ONAYLIYORUM')['status'], 'approved')

    def test_altered_proposal_cannot_be_approved_but_can_be_rejected(self):
        pid = self_evolution.propose('degisen', 'def run(d):\n    return d\n', 'x')['id']
        (self_evolution.PENDING / (pid + '.py')).write_bytes(b'def run(d):\n    return 666\n')
        with self.assertRaises(ValueError): self_evolution.decide(pid, 'approve', 'ONAYLIYORUM')
        self.assertFalse((self_evolution.SKILLS / 'degisen.py').exists())
        self.assertEqual(self_evolution.decide(pid, 'reject', '')['status'], 'rejected')

    def test_missing_staged_file_can_be_rejected(self):
        pid = self_evolution.propose('kayip', 'def run(d):\n    return d\n', 'x')['id']
        (self_evolution.PENDING / (pid + '.py')).unlink()
        with self.assertRaises(ValueError): self_evolution.decide(pid, 'approve', 'ONAYLIYORUM')
        self.assertEqual(self_evolution.decide(pid, 'reject', '')['status'], 'rejected')

    def test_syntax_error_is_a_value_error(self):
        with self.assertRaises(ValueError): self_evolution.propose('bozuk', 'def run(:', 'x')


class BrainTests(Isolated):
    def test_oversized_evidence_stays_valid_json(self):
        central_brain.log('system', 'a', 'research', 'success', 'özet', None, {'ids': ['x' * 50] * 200})
        stored = json.loads(central_brain.experiences()[0]['evidence'])
        self.assertTrue(stored['truncated'])


if __name__ == '__main__':
    unittest.main()
