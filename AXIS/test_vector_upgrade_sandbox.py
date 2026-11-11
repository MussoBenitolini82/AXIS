import contextlib, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import axis_executor, axis_learning, central_brain
import vector_upgrade as vu


def _pair(cmd, a, b):
    return any(cmd[i] == a and cmd[i + 1] == b for i in range(len(cmd) - 1))


def sentinels(stdin_text):
    """What a completed container run prints: one AXIS-STAGE-OK line per stage nonce sent on stdin."""
    return '\n'.join(f'AXIS-STAGE-OK {k} {v}' for k, v in zip(('CONTRACT', 'BEHAVIOR', 'SUITE'), stdin_text.split()))


def host_child(code):
    """docker_command replacement: a host Python child that reads the nonces from stdin like the controller."""
    return lambda name, src: [sys.executable, '-I', '-c', code]


class VectorUpgradeSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        tests = data / 'behavior_specs'
        tests.mkdir()
        root = data / 'root'
        root.mkdir()
        self.root = root
        # ROOT too: decide()/rollback() must never write the real target files.
        for mod, name, val in ((vu, 'DATA', data), (vu, 'DB', data / 'upgrades.sqlite3'), (vu, 'TESTS', tests),
                               (vu, 'ROOT', root), (central_brain, 'DB', data / 'central_brain.sqlite3'),
                               (axis_learning, 'DB', data / 'axis_learning.sqlite3'),
                               (axis_executor, 'DB', data / 'axis_runs.sqlite3')):
            p = mock.patch.object(mod, name, val)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('AXIS_VERIFY_SUITE', None)

    def _propose(self):
        return vu.propose('skills_helpers.py', 'def f():\n return 1\n', 'sandbox test')['id']

    def _docker(self, side_effect=None, returncode=0):
        """Patch the container run and subprocess.run (cleanup) with ONE mock so call order is preserved.
        side_effect may return a result; otherwise a run that echoes the completion sentinels is returned."""
        def fake(cmd, **kw):
            if side_effect is not None:
                result = side_effect(cmd, **kw)
                if result is not None:
                    return result
            out = sentinels(kw.get('input', '')) if returncode == 0 else 'fail'
            return mock.Mock(returncode=returncode, stdout=out, stderr='')
        run = mock.Mock(side_effect=fake)
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(vu, 'docker_available', return_value=True))
        stack.enter_context(mock.patch.object(vu, '_container_run', run))
        stack.enter_context(mock.patch.object(vu.subprocess, 'run', run))
        return stack, run

    def test_docker_command_is_locked_down(self):
        uid = self._propose()
        stack, run = self._docker()
        with stack:
            result = vu.verify(uid)
        self.assertTrue(result['passed'])
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:2], ['docker', 'run'])
        for a, b in (('--network', 'none'), ('--cap-drop', 'ALL'),
                     ('--security-opt', 'no-new-privileges'), ('--pids-limit', '64'),
                     ('--memory', '512m'), ('--memory-swap', '512m'), ('--cpus', '1'),
                     ('--user', '65534:65534'), ('python', '-I')):
            self.assertTrue(_pair(cmd, a, b), (a, b))
        self.assertIn('--read-only', cmd)
        self.assertIn('python:3.12-slim', cmd)
        self.assertIn('--pull=never', cmd)
        self.assertLess(cmd.index('--pull=never'), cmd.index('python:3.12-slim'))
        mount = cmd[cmd.index('--mount') + 1]
        self.assertIn('readonly', mount)
        self.assertIn('dst=/work', mount)
        tmpfs = cmd[cmd.index('--tmpfs') + 1]
        self.assertIn('noexec', tmpfs)
        self.assertIn('nosuid', tmpfs)
        self.assertEqual(cmd.count('--mount'), 1)
        self.assertNotIn('--privileged', cmd)
        self.assertEqual(run.call_args.kwargs['timeout'], vu.VERIFY_TIMEOUT)

    def test_blocked_without_docker(self):
        uid = self._propose()
        with mock.patch.object(vu, 'docker_available', return_value=False), \
             mock.patch.object(vu, '_container_run') as crun, \
             mock.patch.object(vu.subprocess, 'run') as run:
            result = vu.verify(uid)
        self.assertFalse(result['passed'])
        self.assertTrue(result['report'].startswith('BLOCKED'))
        crun.assert_not_called()
        for call in run.call_args_list:
            args = call[0][0] if call[0] else []
            self.assertFalse(len(args) > 1 and args[:2] == ['docker', 'run'])

    def test_docker_command_has_container_name(self):
        uid = self._propose()
        stack, run = self._docker()
        with stack:
            vu.verify(uid)

        cmd = run.call_args.args[0]
        self.assertIn('--name', cmd)
        name_index = cmd.index('--name')
        self.assertEqual(name_index, cmd.index('--rm') + 1)
        name = cmd[name_index + 1]
        self.assertTrue(name.startswith('axis-verify-'))
        self.assertTrue(all(ch.isascii() and (ch.isalnum() or ch in '_.-') for ch in name))

    def test_timeout_removes_container(self):
        uid = self._propose()

        def timeout_then_cleanup(cmd, **kwargs):
            if cmd[:2] == ['docker', 'run']:
                raise vu.subprocess.TimeoutExpired(cmd, 35)
            return mock.Mock(returncode=0)

        stack, run = self._docker(timeout_then_cleanup)
        with stack:
            result = vu.verify(uid)

        self.assertEqual(run.call_count, 2)
        first_cmd = run.call_args_list[0].args[0]
        name = first_cmd[first_cmd.index('--name') + 1]
        self.assertEqual(run.call_args_list[1].args, (['docker', 'rm', '-f', name],))
        self.assertEqual(run.call_args_list[1].kwargs,
                         {'capture_output': True, 'timeout': 15})
        self.assertIs(result['passed'], False)
        self.assertTrue(result['report'].startswith('FAIL: Docker test zaman aşımı'))
        self.assertIn('; konteyner kaldırıldı', result['report'])
        self.assertIn('SUITE: ERROR (zaman aşımı)', result['report'])

    def test_timeout_cleanup_oserror_is_reported(self):
        uid = self._propose()

        def timeout_then_cleanup_error(cmd, **kwargs):
            if cmd[:2] == ['docker', 'run']:
                raise vu.subprocess.TimeoutExpired(cmd, 35)
            raise OSError('Docker cleanup failed')

        stack, run = self._docker(timeout_then_cleanup_error)
        with stack:
            result = vu.verify(uid)

        self.assertEqual(run.call_count, 2)
        first_cmd = run.call_args_list[0].args[0]
        name = first_cmd[first_cmd.index('--name') + 1]
        self.assertEqual(run.call_args_list[1].args, (['docker', 'rm', '-f', name],))
        self.assertIs(result['passed'], False)
        self.assertTrue(result['report'].startswith('FAIL: Docker test zaman aşımı'))
        self.assertIn('kaldırılamadı', result['report'])

    def test_unsafe_mount_path_not_run(self):
        for bad in ('a,readonly=false', 'a=b', 'a\x01b'):
            with self.subTest(bad=bad):
                uid = self._propose()
                fake_tmp = mock.Mock()
                fake_tmp.__enter__ = mock.Mock(return_value=str(Path(self.tmp.name) / bad))
                fake_tmp.__exit__ = mock.Mock(return_value=False)
                stack, run = self._docker()
                with stack, mock.patch.object(vu.tempfile, 'TemporaryDirectory', return_value=fake_tmp):
                    result = vu.verify(uid)
                run.assert_not_called()
                self.assertFalse(result['passed'])
                self.assertEqual(result['report'].splitlines()[:4],
                                 ['FAIL: güvensiz bağlama yolu', 'CONTRACT: NOT RUN',
                                  'BEHAVIOR: SKIPPED (davranış testi yok)', 'SUITE: NOT RUN'])
                self.assertEqual(vu.detail(uid)['report'], result['report'])

    # ---- the real bounded reader (_container_run) with a host Python child instead of docker ----
    def _real_run(self, code):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(vu, 'docker_available', return_value=True))
        stack.enter_context(mock.patch.object(vu, 'docker_command', host_child(code)))
        cleanup = stack.enter_context(mock.patch.object(vu.subprocess, 'run',
                                                        return_value=mock.Mock(returncode=0)))
        return stack, cleanup

    ECHO = ("import sys\nn=sys.stdin.readline().split()\n"
            "for k,v in zip(('CONTRACT','BEHAVIOR','SUITE'),n):print('AXIS-STAGE-OK',k,v,flush=True)\n")

    def test_non_utf8_locale_output_is_recorded(self):
        # Real child process emits bytes that neither UTF-8 nor cp125x can decode strictly.
        uid = self._propose()
        stack, _ = self._real_run('import sys; sys.stdout.buffer.write(b"\\xc4\\x9e \\x81\\xff\\n"); sys.stdout.flush()\n' + self.ECHO)
        with stack:
            result = vu.verify(uid)
        self.assertTrue(result['passed'], result['report'])
        self.assertIn('Ğ', result['report'])
        self.assertEqual(vu.detail(uid)['report'], result['report'])

    def test_sentinels_found_even_when_pushed_out_of_the_tail(self):
        uid = self._propose()
        stack, _ = self._real_run(self.ECHO + "sys.stdout.write('y'*200000)\n")
        with stack:
            result = vu.verify(uid)
        self.assertTrue(result['passed'], result['report'][:300])
        self.assertLessEqual(len(result['report']), vu.REPORT_LIMIT)

    def test_early_exit_without_evidence_fails(self):
        uid = self._propose()
        for code in ('import sys; sys.exit(0)', 'import os; os._exit(0)',
                     'print("AXIS-STAGE-OK CONTRACT guess")\nprint("AXIS-STAGE-OK SUITE guess")'):
            with self.subTest(code=code):
                stack, _ = self._real_run(code)
                with stack:
                    result = vu.verify(uid)
                self.assertFalse(result['passed'])
                self.assertEqual(result['report'].splitlines()[:4],
                                 ['FAIL', 'CONTRACT: FAIL (tamamlanma kanıtı yok)',
                                  'BEHAVIOR: SKIPPED (davranış testi yok)', 'SUITE: FAIL (tamamlanma kanıtı yok)'])

    def test_output_flood_is_cut_and_container_removed(self):
        uid = self._propose()
        with mock.patch.object(vu, 'OUTPUT_LIMIT', 300000):
            stack, cleanup = self._real_run(self.ECHO + "while True:sys.stdout.write('z'*65536)\n")
            with stack:
                result = vu.verify(uid)
        self.assertFalse(result['passed'])
        self.assertTrue(result['report'].startswith('FAIL: konteyner çıktısı 300000 bayt sınırını aştı; konteyner kaldırıldı'))
        self.assertIn('SUITE: ERROR (çıktı sınırı)', result['report'])
        self.assertEqual(cleanup.call_args.args[0][:3], ['docker', 'rm', '-f'])

    def test_docker_oserror_is_recorded(self):
        uid = self._propose()
        stack, _ = self._docker(lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError('docker')))
        with stack:
            result = vu.verify(uid)
        self.assertFalse(result['passed'])
        self.assertEqual(result['report'].splitlines()[0], 'FAIL: Docker çalıştırılamadı: FileNotFoundError')
        self.assertIn('CONTRACT: NOT RUN', result['report'])
        self.assertEqual(vu.detail(uid)['report'], result['report'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows file locking')
    def test_locked_work_dir_keeps_result(self):
        uid = self._propose()
        held, dirs = [], []

        def hold_file(cmd, **kwargs):
            mount = cmd[cmd.index('--mount') + 1]
            work = Path(mount.split('src=', 1)[1].split(',dst=', 1)[0])
            dirs.append(work)
            held.append(open(work / 'skills_helpers.py', 'rb'))

        try:
            stack, _ = self._docker(hold_file)
            with stack:
                result = vu.verify(uid)
        finally:
            for handle in held:
                handle.close()
            for work in dirs:
                shutil.rmtree(work, ignore_errors=True)
        self.assertTrue(result['passed'])
        self.assertTrue(vu.detail(uid)['report'].startswith('PASS'))

    def _docker_passes(self, run=None):
        return self._docker(run)[0]

    def _approve(self, code):
        uid = vu.propose('skills_helpers.py', code, 'apply test')['id']
        with self._docker_passes():
            return uid, vu.decide(uid, 'approve', 'ONAYLIYORUM')

    def _failing_update(self, prefix, on):
        """Fail the status UPDATE either at execute time or at commit time (after the file step)."""
        class Failing(vu.ClosingConnection):
            hit = False

            def execute(self, sql, *args):
                if sql.startswith(prefix):
                    if on == 'execute':
                        raise vu.sqlite3.OperationalError('database is locked')
                    self.hit = True
                return super().execute(sql, *args)

            def __exit__(self, exc_type, *args):
                if self.hit and exc_type is None:
                    self.rollback()
                    self.close()
                    raise vu.sqlite3.OperationalError('database is locked')
                return super().__exit__(exc_type, *args)
        return mock.patch.object(vu, 'ClosingConnection', Failing)

    def test_multiline_proposal_bytes_match_digest(self):
        code = 'def f():\n return 1\n\ndef g():\n return 2\n'
        uid = vu.propose('skills_helpers.py', code, 'crlf')['id']
        self.assertEqual((vu.DATA / (uid + '.py')).read_bytes(), code.encode())
        seen = []

        def capture(cmd, **kwargs):
            mount = cmd[cmd.index('--mount') + 1]
            work = Path(mount.split('src=', 1)[1].split(',dst=', 1)[0])
            seen.append((work / 'skills_helpers.py').read_bytes())

        with self._docker_passes(capture):
            result = vu.decide(uid, 'approve', 'ONAYLIYORUM')
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(seen, [code.encode()])
        self.assertEqual((self.root / 'skills_helpers.py').read_bytes(), code.encode())

    def test_applies_the_verified_bytes_not_a_later_reread(self):
        code = 'def f():\n return 1\n'
        uid = vu.propose('skills_helpers.py', code, 'toctou')['id']
        staged = vu.DATA / (uid + '.py')
        state = {'tested': False}
        real_safe_target = vu.safe_target

        def after_test(cmd, **kw):
            state['tested'] = True

        def swap_then_validate(name):
            if state['tested']:  # window between the last digest check and the write
                staged.write_bytes(b'def f():\n return 666\n')
            return real_safe_target(name)

        with self._docker_passes(after_test), mock.patch.object(vu, 'safe_target', swap_then_validate):
            vu.decide(uid, 'approve', 'ONAYLIYORUM')
        self.assertEqual((self.root / 'skills_helpers.py').read_bytes(), code.encode())

    def test_syntax_error_is_value_error(self):
        with self.assertRaisesRegex(ValueError, r'^Sözdizimi hatası: line 1$'):
            vu.propose('research_extensions.py', 'def f(:', 'bad')

    def test_decide_db_failure_restores_target(self):
        target = self.root / 'skills_helpers.py'
        for original in (b'def old(): return 0\n', None):
            for on in ('execute', 'commit'):
                with self.subTest(original=original, on=on):
                    target.unlink(missing_ok=True)
                    if original is not None:
                        target.write_bytes(original)
                    uid = vu.propose('skills_helpers.py', 'def f(): return 1', 'apply')['id']
                    with self._docker_passes(), self._failing_update('UPDATE upgrades SET status=?,backup=', on):
                        with self.assertRaises(vu.sqlite3.OperationalError):
                            vu.decide(uid, 'approve', 'ONAYLIYORUM')
                    if original is None:
                        self.assertFalse(target.exists())
                    else:
                        self.assertEqual(target.read_bytes(), original)
                    row = vu.detail(uid)
                    self.assertEqual((row['status'], row['backup']), ('pending', ''))
                    self.assertEqual([p.name for p in self.root.iterdir() if p != target], [])
                    self.assertEqual(list((vu.DATA / 'journal').glob('*.json')), [])

    def test_rollback_db_failure_keeps_applied_file(self):
        target = self.root / 'skills_helpers.py'
        for original in (b'def old(): return 0\n', None):
            for on in ('execute', 'commit'):
                with self.subTest(original=original, on=on):
                    target.unlink(missing_ok=True)
                    if original is not None:
                        target.write_bytes(original)
                    uid, result = self._approve('def f(): return 1')
                    self.assertEqual(result['status'], 'applied')
                    with self._failing_update('UPDATE upgrades SET status=? WHERE', on), \
                         mock.patch.object(vu.shutil, 'copy2', wraps=vu.shutil.copy2) as copy:
                        with self.assertRaises(vu.sqlite3.OperationalError):
                            vu.rollback(uid, 'GERI_AL')
                    # Never copied straight onto the target (non-atomic).
                    self.assertNotIn(target, [Path(c.args[1]) for c in copy.call_args_list])
                    self.assertEqual(target.read_bytes(), b'def f(): return 1')
                    self.assertEqual(vu.detail(uid)['status'], 'applied')
                    self.assertEqual([p.name for p in self.root.iterdir() if p != target], [])
                    self.assertEqual(vu.rollback(uid, 'GERI_AL')['status'], 'rolled_back')
                    if original is None:
                        self.assertFalse(target.exists())
                    else:
                        self.assertEqual(target.read_bytes(), original)

    def test_atomic_write_never_follows_existing_temp_names(self):
        target = self.root / 'skills_helpers.py'
        target.write_bytes(b'old')
        outside = Path(self.tmp.name) / 'outside.txt'
        outside.write_bytes(b'keep')
        # Pre-planted files at the old predictable names must be neither written through nor deleted.
        planted = [target.with_name(target.name + '.x.tmp'), target.with_name(target.name + '.x.undo')]
        for p in planted:
            p.write_bytes(b'planted')
        vu._atomic_write(target, b'new')
        self.assertEqual(target.read_bytes(), b'new')
        self.assertEqual(outside.read_bytes(), b'keep')
        for p in planted:
            self.assertEqual(p.read_bytes(), b'planted')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), sorted([target.name] + [p.name for p in planted]))

    def test_connection_closed_when_setup_fails(self):
        made = []

        class Broken(vu.ClosingConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                made.append((self, kwargs))

            def commit(self):
                raise vu.sqlite3.OperationalError('disk I/O error')

        with mock.patch.object(vu, 'ClosingConnection', Broken):
            with self.assertRaises(vu.sqlite3.OperationalError):
                vu.connection()
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0][1].get('timeout'), 15)
        with self.assertRaises(vu.sqlite3.ProgrammingError):
            made[0][0].execute('SELECT 1')

    def test_docker_available_decodes_utf8(self):
        with mock.patch.object(vu.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(vu.docker_available())
        kwargs = run.call_args.kwargs
        self.assertNotIn('text', kwargs)
        self.assertEqual((kwargs.get('encoding'), kwargs.get('errors')), ('utf-8', 'replace'))


if __name__ == '__main__':
    unittest.main()
