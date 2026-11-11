"""Automatic apply of upgrades (user decision 2026-11-10, scope narrowed to extensions/*.py on 2026-11-11).

Docker/subprocess are always mocked; DATA, DB, TESTS and ROOT point to temp dirs so no real module is written.
"""
import contextlib
import hashlib
import os
import pathlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import axis_executor
import axis_learning
import central_brain
import vector_upgrade as vu

ORIGINAL = 'def f():\n return 0\n'
NEW = 'def f():\n return 1\n'
EXT = 'extensions/research_tools.py'


def sentinels(stdin_text):
    """What a completed container run prints: one AXIS-STAGE-OK line per stage nonce sent on stdin."""
    return '\n'.join(f'AXIS-STAGE-OK {k} {v}' for k, v in zip(('CONTRACT', 'BEHAVIOR', 'SUITE'), stdin_text.split()))


class AutoUpgradeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        (data / 'behavior_specs').mkdir()
        self.root = data / 'root'
        self.root.mkdir()
        (self.root / 'extensions').mkdir()
        for mod, name, val in ((vu, 'DATA', data), (vu, 'DB', data / 'upgrades.sqlite3'),
                               (vu, 'TESTS', data / 'behavior_specs'), (vu, 'ROOT', self.root),
                               (vu, 'SCHEDULER', None), (central_brain, 'DB', data / 'brain.sqlite3'),
                               (axis_learning, 'DB', data / 'axis_learning.sqlite3'),
                               (axis_executor, 'DB', data / 'axis_runs.sqlite3')):
            p = mock.patch.object(mod, name, val, create=True)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('AXIS_AUTO_APPLY', None)
        os.environ.pop('AXIS_VERIFY_SUITE', None)

    def path(self, target):
        return self.root.joinpath(*target.split('/'))

    def docker(self, returncode=0, side_effect=None, available=True):
        """One mock for the container run and for subprocess.run (cleanup), so call order is preserved.
        A passing container echoes the per-run completion sentinels it received on stdin."""
        def fake(cmd, **kw):
            if side_effect is not None:
                side_effect(cmd, **kw)
            out = sentinels(kw.get('input', '')) if returncode == 0 else 'fail'
            return mock.Mock(returncode=returncode, stdout=out, stderr='')
        run = mock.Mock(side_effect=fake)
        both = contextlib.ExitStack()
        both.enter_context(mock.patch.object(vu, '_container_run', run))
        both.enter_context(mock.patch.object(vu.subprocess, 'run', run))
        return mock.patch.object(vu, 'docker_available', return_value=available), both, run

    def propose(self, target=EXT, code=NEW, original=ORIGINAL):
        if original is not None:
            self.path(target).write_bytes(original.encode())
        return vu.propose(target, code, 'otomatik test')['id']

    def docker_runs(self, run):
        return [c for c in run.call_args_list if c.args and c.args[0][:2] == ['docker', 'run']]

    # ---- PASS → applied through decide(), with a fresh second Docker test ----
    def test_pass_auto_applies_extension(self):
        uid = self.propose()
        a, r, run = self.docker(0)
        with a, r:
            result = vu.auto_pipeline(uid)
        self.assertEqual(result['outcome'], 'applied')
        self.assertTrue(result['restart_required'])
        self.assertEqual(self.path(EXT).read_bytes(), NEW.encode())
        d = vu.detail(uid)
        self.assertEqual(d['status'], 'applied')
        self.assertTrue(d['report'].startswith('PASS'))
        self.assertIn('SUITE: PASS', d['report'])
        self.assertTrue(Path(d['backup']).exists())
        self.assertEqual(Path(d['backup']).read_bytes(), ORIGINAL.encode())
        self.assertEqual(len(self.docker_runs(run)), 2)  # pipeline test + fresh test inside decide()

    def test_fail_or_blocked_applies_nothing(self):
        for rc, available, prefix in ((1, True, 'FAIL'), (104, True, 'FAIL'), (0, False, 'BLOCKED')):
            uid = self.propose()
            a, r, run = self.docker(rc, available=available)
            with a, r, mock.patch.object(vu, 'decide', wraps=vu.decide) as decide:
                result = vu.auto_pipeline(uid)
            self.assertEqual(result['outcome'], 'not_applied')
            decide.assert_not_called()
            d = vu.detail(uid)
            self.assertEqual(d['status'], 'pending')
            self.assertTrue(d['report'].startswith(prefix), d['report'])
            self.assertEqual(self.path(EXT).read_bytes(), ORIGINAL.encode())
            if not available:
                self.assertEqual(self.docker_runs(run), [])

    # ---- top-level modules: never automatic, still manually approvable ----
    def test_top_level_target_is_never_auto_applied(self):
        scheduler = mock.Mock()
        with mock.patch.object(vu, 'SCHEDULER', scheduler):
            d = vu.propose('research_extensions.py', NEW, 'x')
            self.assertFalse(d['auto_apply_queued'])
            self.assertFalse(d['auto_eligible'])
            self.assertFalse(vu.schedule_auto(d['id']))
            self.assertEqual(vu.sweep_untested(), [])
        scheduler.assert_not_called()
        a, r, run = self.docker(0)
        with a, r:
            result = vu.auto_pipeline(d['id'])
        self.assertEqual(result['outcome'], 'manual_only')
        run.assert_not_called()
        self.assertEqual(vu.detail(d['id'])['status'], 'pending')
        self.assertFalse((self.root / 'research_extensions.py').exists())

    def test_top_level_target_can_be_approved_manually(self):
        uid = self.propose('research_extensions.py')
        a, r, run = self.docker(0)
        with a, r:
            self.assertEqual(vu.decide(uid, 'approve', 'ONAYLIYORUM')['status'], 'applied')
        self.assertEqual((self.root / 'research_extensions.py').read_bytes(), NEW.encode())
        self.assertEqual(len(self.docker_runs(run)), 1)
        self.assertEqual(vu.rollback(uid, 'GERI_AL')['status'], 'rolled_back')
        self.assertEqual((self.root / 'research_extensions.py').read_bytes(), ORIGINAL.encode())

    def test_auto_eligible(self):
        self.assertTrue(vu.auto_eligible(EXT))
        for name in ('research_extensions.py', 'extensions/server.py', 'extensions/test_x.py',
                     'extensions/../server.py', 'extensions\\x.py', 'extensions/a/b.py', None, ''):
            self.assertFalse(vu.auto_eligible(name), name)

    # ---- scope ----
    def test_protected_and_invalid_targets_refused(self):
        for name in ('vector_upgrade.py', 'local_models.py', 'server.py', 'axis_sqlite.py'):
            with self.assertRaisesRegex(ValueError, 'korunan'):
                vu.safe_target(name)
            with self.assertRaisesRegex(ValueError, 'korunan'):
                vu.safe_target('extensions/' + name)
        for name in ('test_server.py', 'test_ask.py', 'extensions/test_x.py'):
            with self.assertRaisesRegex(ValueError, 'test dosyaları'):
                vu.safe_target(name)
        for name in sorted(vu.PROTECTED) + ['test_server.py', 'test_ask.py', 'TEST_x.py', '../server.py',
                                             '..\\server.py', 'sub/x.py', 'C:/x.py', '/etc/x.py', 'index.html',
                                             'notes.txt', 'x.PY', '', 'x', 'a b.py', 'Server.py', None,
                                             'extensions/../server.py', 'extensions\\x.py', 'extensions/a/x.py']:
            with self.assertRaises(ValueError, msg=name):
                vu.safe_target(name)
            with self.assertRaises(ValueError, msg=name):
                vu.propose(name, NEW, 'x')
        self.assertEqual(vu.listing(), [])

    def test_ordinary_module_allowed(self):
        for name in ('vector_intelligence.py', 'research_extensions.py', 'skills_helpers.py', 'central_brain.py'):
            self.assertEqual(vu.safe_target(name), self.root / name)
        self.assertEqual(vu.safe_target(EXT), self.path(EXT))
        uid = self.propose('vector_intelligence.py')
        self.assertEqual(vu.detail(uid)['target'], 'vector_intelligence.py')

    def test_symlink_refused(self):
        self.assertEqual(vu.safe_target('vector_intelligence.py'), self.root / 'vector_intelligence.py')
        with mock.patch.object(pathlib.Path, 'is_symlink', return_value=True):
            with self.assertRaises(ValueError):
                vu.safe_target('vector_intelligence.py')
            with self.assertRaises(ValueError):
                vu.safe_target(EXT)

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
            self.assertEqual(self.path(EXT).read_bytes(), ORIGINAL.encode())
        # The explicit per-item API path still works while auto-apply is off.
        a, r, run = self.docker(0)
        with a, r:
            self.assertEqual(vu.decide(uid, 'approve', 'ONAYLIYORUM')['status'], 'applied')
        self.assertEqual(self.path(EXT).read_bytes(), NEW.encode())

    def test_enabled_by_default_and_propose_schedules_extension(self):
        self.assertTrue(vu.auto_apply_enabled())
        scheduler = mock.Mock()
        with mock.patch.object(vu, 'SCHEDULER', scheduler):
            d = vu.propose(EXT, NEW, 'x')
            no = vu.propose('extensions/other_tool.py', NEW, 'x', schedule=False)
        scheduler.assert_called_once_with(d['id'])
        self.assertTrue(d['auto_apply_queued'])
        self.assertTrue(d['auto_eligible'])
        self.assertFalse(no['auto_apply_queued'])

    def test_sweep_queues_only_untested_pending_extensions(self):
        a_id = self.propose()
        b_id = self.propose('extensions/skills_helpers.py')
        self.propose('skills_helpers.py')  # top-level: never swept
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

            def tamper(cmd, **kw):
                if cmd[:2] == ['docker', 'run']:
                    calls['n'] += 1
                    if calls['n'] == tamper_on_run:
                        staged.write_bytes(b'def f():\n return 666\n')
            a, r, _ = self.docker(0, side_effect=tamper)
            with a, r:
                result = vu.auto_pipeline(uid)
            self.assertEqual(result['outcome'], 'not_applied', tamper_on_run)
            self.assertIn('değişmiş', result['error'])
            self.assertEqual(vu.detail(uid)['status'], 'pending')
            self.assertEqual(self.path(EXT).read_bytes(), ORIGINAL.encode())

    # ---- audit ----
    def test_audit_entries_written(self):
        ok = self.propose()
        a, r, _ = self.docker(0)
        with a, r:
            vu.auto_pipeline(ok)
        bad = self.propose('extensions/skills_helpers.py')
        a, r, _ = self.docker(1)
        with a, r:
            vu.auto_pipeline(bad)
        exp = [e for e in central_brain.experiences() if e['agent'] == 'auto_upgrade']
        by_action = {e['action']: e for e in exp}
        self.assertEqual(by_action['auto_apply']['status'], 'success')
        self.assertIn('Otomatik uygulandı: ' + EXT + ' — otomatik test', by_action['auto_apply']['summary'])
        self.assertEqual(by_action['auto_apply']['task_id'], ok)
        self.assertEqual(by_action['auto_not_applied']['status'], 'failure')
        status = vu.auto_status()
        self.assertTrue(status['enabled'])
        self.assertEqual(status['auto_scope'], 'extensions/*.py')
        self.assertTrue(status['suite_enabled'])
        outcomes = {(e['upgrade_id'], e['outcome'], e['upgrade_status']) for e in status['events']}
        self.assertEqual(outcomes, {(ok, 'applied', 'applied'), (bad, 'not_applied', 'pending')})
        self.assertIn('vector_upgrade.py', status['protected'])
        self.assertIn('test_*.py', status['protected'])

    # ---- rollback ----
    def test_rollback_after_auto_apply_restores_extension(self):
        target = 'extensions/vector_tools.py'
        uid = self.propose(target, NEW, ORIGINAL)
        a, r, _ = self.docker(0)
        with a, r:
            self.assertEqual(vu.auto_pipeline(uid)['outcome'], 'applied')
        path = self.path(target)
        self.assertEqual(path.read_bytes(), NEW.encode())
        with self.assertRaises(ValueError):
            vu.rollback(uid, 'ONAYLIYORUM')
        result = vu.rollback(uid, 'GERI_AL')
        self.assertEqual(result, {'status': 'rolled_back', 'restart_required': True})
        self.assertEqual(path.read_bytes(), ORIGINAL.encode())
        self.assertEqual(vu.detail(uid)['status'], 'rolled_back')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hashlib.sha256(ORIGINAL.encode()).hexdigest())

    def test_rollback_of_new_extension_file_removes_it(self):
        uid = self.propose('extensions/brand_new_module.py', NEW, original=None)
        a, r, _ = self.docker(0)
        with a, r:
            self.assertEqual(vu.auto_pipeline(uid)['outcome'], 'applied')
        self.assertTrue(self.path('extensions/brand_new_module.py').exists())
        vu.rollback(uid, 'GERI_AL')
        self.assertFalse(self.path('extensions/brand_new_module.py').exists())
        self.assertEqual(list((self.root / 'extensions').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
