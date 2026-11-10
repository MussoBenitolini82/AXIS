"""Automatic apply of core upgrades (user decision 2026-11-10).

Docker/subprocess are always mocked; DATA, DB, TESTS and ROOT point to temp dirs so no real module is written.
"""
import hashlib
import os
import pathlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import central_brain
import vector_upgrade as vu

ORIGINAL = 'def f():\n return 0\n'
NEW = 'def f():\n return 1\n'


class AutoUpgradeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        (data / 'behavior_specs').mkdir()
        self.root = data / 'root'
        self.root.mkdir()
        for mod, name, val in ((vu, 'DATA', data), (vu, 'DB', data / 'upgrades.sqlite3'),
                               (vu, 'TESTS', data / 'behavior_specs'), (vu, 'ROOT', self.root),
                               (vu, 'SCHEDULER', None), (central_brain, 'DB', data / 'brain.sqlite3')):
            p = mock.patch.object(mod, name, val, create=True)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('AXIS_AUTO_APPLY', None)

    def docker(self, returncode=0, side_effect=None, available=True):
        run = mock.Mock(return_value=mock.Mock(returncode=returncode, stdout='ok', stderr=''), side_effect=side_effect)
        return (mock.patch.object(vu, 'docker_available', return_value=available),
                mock.patch.object(vu.subprocess, 'run', run), run)

    def propose(self, target='research_extensions.py', code=NEW, original=ORIGINAL):
        if original is not None:
            (self.root / target).write_bytes(original.encode())
        return vu.propose(target, code, 'otomatik test')['id']

    def docker_runs(self, run):
        return [c for c in run.call_args_list if c.args and c.args[0][:2] == ['docker', 'run']]

    # ---- PASS → applied through decide(), with a fresh second Docker test ----
    def test_pass_auto_applies(self):
        uid = self.propose()
        a, r, run = self.docker(0)
        with a, r:
            result = vu.auto_pipeline(uid)
        self.assertEqual(result['outcome'], 'applied')
        self.assertTrue(result['restart_required'])
        self.assertEqual((self.root / 'research_extensions.py').read_bytes(), NEW.encode())
        d = vu.detail(uid)
        self.assertEqual(d['status'], 'applied')
        self.assertTrue(d['report'].startswith('PASS'))
        self.assertTrue(Path(d['backup']).exists())
        self.assertEqual(Path(d['backup']).read_bytes(), ORIGINAL.encode())
        self.assertEqual(len(self.docker_runs(run)), 2)  # pipeline test + fresh test inside decide()

    def test_fail_or_blocked_applies_nothing(self):
        for rc, available, prefix in ((1, True, 'FAIL'), (0, False, 'BLOCKED')):
            uid = self.propose()
            a, r, run = self.docker(rc, available=available)
            with a, r, mock.patch.object(vu, 'decide', wraps=vu.decide) as decide:
                result = vu.auto_pipeline(uid)
            self.assertEqual(result['outcome'], 'not_applied')
            decide.assert_not_called()
            d = vu.detail(uid)
            self.assertEqual(d['status'], 'pending')
            self.assertTrue(d['report'].startswith(prefix), d['report'])
            self.assertEqual((self.root / 'research_extensions.py').read_bytes(), ORIGINAL.encode())
            if not available:
                self.assertEqual(self.docker_runs(run), [])

    # ---- scope ----
    def test_protected_and_invalid_targets_refused(self):
        for name in ('vector_upgrade.py', 'local_models.py', 'server.py', 'axis_sqlite.py'):
            with self.assertRaisesRegex(ValueError, 'korunan'):
                vu.safe_target(name)
        for name in ('test_server.py', 'test_ask.py'):
            with self.assertRaisesRegex(ValueError, 'test dosyaları'):
                vu.safe_target(name)
        for name in sorted(vu.PROTECTED) + ['test_server.py', 'test_ask.py', 'TEST_x.py', '../server.py',
                                             '..\\server.py', 'sub/x.py', 'C:/x.py', '/etc/x.py', 'index.html',
                                             'notes.txt', 'x.PY', '', 'x', 'a b.py', 'Server.py', None]:
            with self.assertRaises(ValueError, msg=name):
                vu.safe_target(name)
            with self.assertRaises(ValueError, msg=name):
                vu.propose(name, NEW, 'x')
        self.assertEqual(vu.listing(), [])

    def test_ordinary_module_allowed(self):
        for name in ('vector_intelligence.py', 'research_extensions.py', 'skills_helpers.py', 'central_brain.py'):
            self.assertEqual(vu.safe_target(name), self.root / name)
        uid = self.propose('vector_intelligence.py')
        self.assertEqual(vu.detail(uid)['target'], 'vector_intelligence.py')

    def test_symlink_refused(self):
        self.assertEqual(vu.safe_target('vector_intelligence.py'), self.root / 'vector_intelligence.py')
        with mock.patch.object(pathlib.Path, 'is_symlink', return_value=True):
            with self.assertRaises(ValueError):
                vu.safe_target('vector_intelligence.py')

    # ---- kill switch ----
    def test_kill_switch_disables_auto_apply(self):
        for value in ('0', 'false', 'off', 'OFF', ' False '):
            os.environ['AXIS_AUTO_APPLY'] = value
            self.assertFalse(vu.auto_apply_enabled())
            scheduler = mock.Mock()
            with mock.patch.object(vu, 'SCHEDULER', scheduler):
                uid = self.propose()
            scheduler.assert_not_called()
            self.assertFalse(vu.detail(uid)['status'] != 'pending')
            a, r, run = self.docker(0)
            with a, r:
                self.assertEqual(vu.auto_pipeline(uid)['outcome'], 'disabled')
            run.assert_not_called()
            self.assertEqual(vu.detail(uid)['status'], 'pending')
            self.assertEqual((self.root / 'research_extensions.py').read_bytes(), ORIGINAL.encode())
        # The explicit per-item API path still works while auto-apply is off.
        a, r, run = self.docker(0)
        with a, r:
            self.assertEqual(vu.decide(uid, 'approve', 'ONAYLIYORUM')['status'], 'applied')
        self.assertEqual((self.root / 'research_extensions.py').read_bytes(), NEW.encode())

    def test_enabled_by_default_and_propose_schedules(self):
        self.assertTrue(vu.auto_apply_enabled())
        scheduler = mock.Mock()
        with mock.patch.object(vu, 'SCHEDULER', scheduler):
            d = vu.propose('research_extensions.py', NEW, 'x')
        scheduler.assert_called_once_with(d['id'])
        self.assertTrue(d['auto_apply_queued'])

    def test_sweep_queues_only_untested_pending(self):
        a_id = self.propose()
        b_id = self.propose('skills_helpers.py')
        a, r, run = self.docker(1)
        with a, r:
            vu.verify(b_id)  # tested (FAIL) → not swept again
        scheduler = mock.Mock()
        with mock.patch.object(vu, 'SCHEDULER', scheduler):
            self.assertEqual(vu.sweep_untested(), [a_id])
        scheduler.assert_called_once_with(a_id)

    # ---- digest ----
    def test_digest_change_between_test_and_apply_refused(self):
        for tamper_on_run in (1, 2):
            uid = self.propose()
            staged = vu.DATA / (uid + '.py')
            calls = {'n': 0}

            def run(cmd, **kw):
                if cmd[:2] == ['docker', 'run']:
                    calls['n'] += 1
                    if calls['n'] == tamper_on_run:
                        staged.write_bytes(b'def f():\n return 666\n')
                return mock.Mock(returncode=0, stdout='ok', stderr='')
            with mock.patch.object(vu, 'docker_available', return_value=True), \
                    mock.patch.object(vu.subprocess, 'run', side_effect=run):
                result = vu.auto_pipeline(uid)
            self.assertEqual(result['outcome'], 'not_applied', tamper_on_run)
            self.assertIn('değişmiş', result['error'])
            self.assertEqual(vu.detail(uid)['status'], 'pending')
            self.assertEqual((self.root / 'research_extensions.py').read_bytes(), ORIGINAL.encode())

    # ---- audit ----
    def test_audit_entries_written(self):
        ok = self.propose()
        a, r, _ = self.docker(0)
        with a, r:
            vu.auto_pipeline(ok)
        bad = self.propose('skills_helpers.py')
        a, r, _ = self.docker(1)
        with a, r:
            vu.auto_pipeline(bad)
        exp = [e for e in central_brain.experiences() if e['agent'] == 'auto_upgrade']
        by_action = {e['action']: e for e in exp}
        self.assertEqual(by_action['auto_apply']['status'], 'success')
        self.assertIn('Otomatik uygulandı: research_extensions.py — otomatik test', by_action['auto_apply']['summary'])
        self.assertEqual(by_action['auto_apply']['task_id'], ok)
        self.assertEqual(by_action['auto_not_applied']['status'], 'failure')
        status = vu.auto_status()
        self.assertTrue(status['enabled'])
        outcomes = {(e['upgrade_id'], e['outcome'], e['upgrade_status']) for e in status['events']}
        self.assertEqual(outcomes, {(ok, 'applied', 'applied'), (bad, 'not_applied', 'pending')})
        self.assertIn('vector_upgrade.py', status['protected'])

    # ---- rollback ----
    def test_rollback_after_auto_apply_restores_module(self):
        uid = self.propose('vector_intelligence.py', NEW, ORIGINAL)
        a, r, _ = self.docker(0)
        with a, r:
            self.assertEqual(vu.auto_pipeline(uid)['outcome'], 'applied')
        target = self.root / 'vector_intelligence.py'
        self.assertEqual(target.read_bytes(), NEW.encode())
        with self.assertRaises(ValueError):
            vu.rollback(uid, 'ONAYLIYORUM')
        result = vu.rollback(uid, 'GERI_AL')
        self.assertEqual(result, {'status': 'rolled_back', 'restart_required': True})
        self.assertEqual(target.read_bytes(), ORIGINAL.encode())
        self.assertEqual(vu.detail(uid)['status'], 'rolled_back')
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), hashlib.sha256(ORIGINAL.encode()).hexdigest())

    def test_rollback_of_new_file_removes_it(self):
        uid = self.propose('brand_new_module.py', NEW, original=None)
        a, r, _ = self.docker(0)
        with a, r:
            vu.auto_pipeline(uid)
        self.assertTrue((self.root / 'brand_new_module.py').exists())
        vu.rollback(uid, 'GERI_AL')
        self.assertFalse((self.root / 'brand_new_module.py').exists())


if __name__ == '__main__':
    unittest.main()
