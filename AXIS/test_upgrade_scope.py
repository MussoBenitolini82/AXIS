"""extensions/*.py targets, auto-apply scope, staged source copy and the in-container regression suite.

Real Docker is never called: docker_available / subprocess.run are patched. DATA, DB, TESTS and ROOT point to
temp dirs. One test runs the container controller script with the host Python against a tiny fake ROOT whose
paths are rewritten (only harmless test code is executed) to check the exit-code protocol end to end.
"""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import axis_executor
import axis_learning
import central_brain
import vector_upgrade as vu

NEW = 'def f():\n return 1\n'


def sentinels(stdin_text):
    return '\n'.join(f'AXIS-STAGE-OK {k} {v}' for k, v in zip(('CONTRACT', 'BEHAVIOR', 'SUITE'), stdin_text.split()))


def _pair(cmd, a, b):
    return any(cmd[i] == a and cmd[i + 1] == b for i in range(len(cmd) - 1))


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = data = Path(tmp.name)
        (data / 'behavior_specs').mkdir()
        self.root = data / 'root'
        self.root.mkdir()
        for name, val in (('DATA', data), ('DB', data / 'upgrades.sqlite3'), ('TESTS', data / 'behavior_specs'),
                          ('ROOT', self.root), ('SCHEDULER', None)):
            p = mock.patch.object(vu, name, val)
            p.start()
            self.addCleanup(p.stop)
        # auto_pipeline -> _audit -> central_brain.log: no test may touch a real store.
        for mod, name in ((central_brain, 'central_brain.sqlite3'), (axis_learning, 'axis_learning.sqlite3'),
                          (axis_executor, 'axis_runs.sqlite3')):
            p = mock.patch.object(mod, 'DB', data / name)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for key in ('AXIS_AUTO_APPLY', 'AXIS_VERIFY_SUITE'):
            os.environ.pop(key, None)

    def docker(self, side_effect=None, returncode=0, stdout='ok', proof=True):
        """One mock for the container run and subprocess.run (cleanup). Unless side_effect returns a result,
        the fake container prints `stdout` plus (proof=True) the completion sentinels for the stdin nonces."""
        def fake(cmd, **kw):
            if side_effect is not None:
                result = side_effect(cmd, **kw)
                if result is not None:
                    return result
            out = stdout + '\n' + (sentinels(kw.get('input', '')) if proof else '')
            return mock.Mock(returncode=returncode, stdout=out, stderr='')
        run = mock.Mock(side_effect=fake)
        both = contextlib.ExitStack()
        both.enter_context(mock.patch.object(vu, '_container_run', run))
        both.enter_context(mock.patch.object(vu.subprocess, 'run', run))
        return mock.patch.object(vu, 'docker_available', return_value=True), both, run

    def fake_tree(self):
        r = self.root
        (r / 'alpha.py').write_text('def a():\n return 1\n', encoding='utf-8')
        (r / 'test_alpha.py').write_text('import unittest, alpha\nclass T(unittest.TestCase):\n'
                                         ' def test_a(self): self.assertEqual(alpha.a(), 1)\n', encoding='utf-8')
        (r / 'test_needs_node.py').write_text('import shutil\nNODE = shutil.which("node")\n', encoding='utf-8')
        (r / 'test_from_which.py').write_text('from shutil import which\n', encoding='utf-8')
        (r / 'index.html').write_text('<html></html>', encoding='utf-8')
        (r / 'static' / 'sub').mkdir(parents=True)
        (r / 'static' / 'app.js').write_text('x', encoding='utf-8')
        (r / 'static' / 'sub' / 'b.css').write_text('y', encoding='utf-8')
        (r / 'static' / '__pycache__').mkdir()
        (r / 'static' / '__pycache__' / 'c.pyc').write_bytes(b'0')
        (r / 'extensions').mkdir()
        (r / 'extensions' / 'tool.py').write_text('def t():\n return 2\n', encoding='utf-8')
        (r / 'extensions' / 'test_tool.py').write_text('x=1\n', encoding='utf-8')
        (r / 'extensions' / 'notes.txt').write_text('n', encoding='utf-8')
        for d in ('.venv', 'proposals', 'upgrades', 'backups', 'skills', '__pycache__'):
            (r / d).mkdir()
            (r / d / 'x.py').write_text('SECRET=1\n', encoding='utf-8')
        for f in ('vector.db', 'central_brain.sqlite3', 'README.md', '.env', 'my-mod.py'):
            (r / f).write_text('data', encoding='utf-8')


class TargetValidationTests(Base):
    def test_extension_target_accepted(self):
        self.assertEqual(vu.safe_target('extensions/tool.py'), self.root / 'extensions' / 'tool.py')
        (self.root / 'extensions').mkdir()
        self.assertEqual(vu.safe_target('extensions/tool.py'), self.root / 'extensions' / 'tool.py')
        self.assertTrue(vu.is_extension('extensions/tool.py'))
        self.assertTrue(vu.auto_eligible('extensions/tool.py'))

    def test_bad_extension_targets_refused(self):
        bad = ['extensions/../server.py', 'extensions/../alpha.py', 'extensions/./tool.py', 'extensions\\tool.py',
               'extensions/a/tool.py', 'extensions//tool.py', 'extensions/', 'extensions', 'Extensions/tool.py',
               '/extensions/tool.py', './extensions/tool.py', 'extensions/tool.PY', 'extensions/to ol.py',
               'extensions/tool.py\n', 'extensions/test_x.py', 'extensions/TEST_x.py', 'extensions/testing.py',
               'skills/tool.py', 'upgrades/tool.py']
        bad += ['extensions/' + p for p in sorted(vu.PROTECTED)] + ['extensions/Server.py']
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    vu.safe_target(name)
                self.assertFalse(vu.auto_eligible(name))
                with self.assertRaises(ValueError):
                    vu.propose(name, NEW, 'x')
        self.assertEqual(vu.listing(), [])

    def test_extensions_folder_must_be_real_directory(self):
        (self.root / 'extensions').write_text('not a dir', encoding='utf-8')
        with self.assertRaises(ValueError):
            vu.safe_target('extensions/tool.py')

    def _symlink(self, link, target, directory=False):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('symlink oluşturulamadı: ' + type(exc).__name__)

    def test_symlinked_extension_file_refused(self):
        (self.root / 'extensions').mkdir()
        outside = self.tmp / 'outside.py'
        outside.write_text(NEW, encoding='utf-8')
        self._symlink(self.root / 'extensions' / 'tool.py', outside)
        with self.assertRaises(ValueError):
            vu.safe_target('extensions/tool.py')

    def test_symlinked_extensions_folder_refused(self):
        outside = self.tmp / 'elsewhere'
        outside.mkdir()
        self._symlink(self.root / 'extensions', outside, directory=True)
        with self.assertRaises(ValueError):
            vu.safe_target('extensions/tool.py')

    def test_top_level_still_works(self):
        self.assertEqual(vu.safe_target('alpha.py'), self.root / 'alpha.py')
        self.assertFalse(vu.auto_eligible('alpha.py'))

    def test_dunder_private_uppercase_and_stdlib_names_refused(self):
        bad = ['extensions/__init__.py', 'extensions/__main__.py', 'extensions/_x.py', 'extensions/Foo.py',
               'extensions/json.py', 'extensions/OS.py', '__init__.py', '__main__.py', '_private.py',
               'json.py', 'os.py', 'Json.py']
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    vu.safe_target(name)
                self.assertFalse(vu.auto_eligible(name))
                with self.assertRaises(ValueError):
                    vu.propose(name, NEW, 'x')
        self.assertEqual(vu.listing(), [])
        self.assertEqual(vu.safe_target('extensions/good_name.py'), self.root / 'extensions' / 'good_name.py')
        self.assertTrue(vu.auto_eligible('extensions/good_name.py'))
        self.assertEqual(vu.safe_target('my_module.py'), self.root / 'my_module.py')


class StagedSourceTests(Base):
    def test_copy_contents_and_exclusions_top_level(self):
        self.fake_tree()
        dest = self.tmp / 'copy'
        excluded = vu.stage_sources(dest, 'alpha.py', b'def a():\n return 42\n')
        self.assertEqual(excluded, ['test_from_which.py', 'test_needs_node.py'])
        files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file())
        self.assertEqual(files, ['alpha.py', 'extensions/tool.py', 'index.html', 'static/app.js',
                                 'static/sub/b.css', 'test_alpha.py'])
        self.assertEqual((dest / 'alpha.py').read_bytes(), b'def a():\n return 42\n')
        self.assertEqual((self.root / 'alpha.py').read_text(encoding='utf-8'), 'def a():\n return 1\n')

    def test_candidate_swapped_in_for_extension(self):
        self.fake_tree()
        dest = self.tmp / 'copy'
        vu.stage_sources(dest, 'extensions/tool.py', b'def t():\n return 99\n')
        self.assertEqual((dest / 'extensions' / 'tool.py').read_bytes(), b'def t():\n return 99\n')
        self.assertEqual((dest / 'alpha.py').read_text(encoding='utf-8'), 'def a():\n return 1\n')
        dest2 = self.tmp / 'copy2'
        vu.stage_sources(dest2, 'extensions/brand_new.py', b'def n():\n return 0\n')
        self.assertEqual((dest2 / 'extensions' / 'brand_new.py').read_bytes(), b'def n():\n return 0\n')

    def test_new_extension_without_extensions_folder(self):
        (self.root / 'alpha.py').write_text('x=1\n', encoding='utf-8')
        dest = self.tmp / 'copy'
        vu.stage_sources(dest, 'extensions/fresh.py', b'def n():\n return 0\n')
        self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()),
                         ['alpha.py', 'extensions/fresh.py'])

    def test_invalid_target_never_staged(self):
        dest = self.tmp / 'copy'
        with self.assertRaises(ValueError):
            vu.stage_sources(dest, 'extensions/../../evil.py', b'x')
        self.assertFalse((self.tmp / 'evil.py').exists())

    def test_host_program_rule(self):
        self.assertTrue(vu.needs_host_program('import shutil\nshutil.which("node")'))
        self.assertTrue(vu.needs_host_program('from shutil import which'))
        self.assertFalse(vu.needs_host_program('import shutil\nshutil.copy("a","b")'))
        self.assertFalse(vu.needs_host_program('def broken(:'))  # kept, so it fails the suite visibly


class ContainerTests(Base):
    def propose_ext(self, name='extensions/tool.py', cases=None):
        uid = vu.propose(name, NEW, 'kapsam testi')['id']
        if cases:
            vu.attach_behavior_cases(uid, cases)
        return uid

    def test_command_flags_mount_and_work_dir(self):
        self.fake_tree()
        uid = self.propose_ext(cases=[{'function': 'f', 'args': [], 'expected': 1}])
        seen = {}

        def capture(cmd, **kwargs):
            mount = cmd[cmd.index('--mount') + 1]
            work = Path(mount.split('src=', 1)[1].split(',dst=', 1)[0])
            seen['files'] = sorted(p.relative_to(work).as_posix() for p in work.rglob('*') if p.is_file())
            seen['candidate'] = (work / 'tool.py').read_bytes()
            seen['src_candidate'] = (work / 'src' / 'extensions' / 'tool.py').read_bytes()
            seen['runner'] = (work / 'test_behavior.py').read_text(encoding='utf-8')
            seen['cmd'], seen['kwargs'] = cmd, kwargs
        a, r, _ = self.docker(capture)
        with a, r:
            result = vu.verify(uid)
        self.assertTrue(result['passed'])
        cmd = seen['cmd']
        for x, y in (('--network', 'none'), ('--cap-drop', 'ALL'), ('--security-opt', 'no-new-privileges'),
                     ('--pids-limit', '64'), ('--memory', '512m'), ('--memory-swap', '512m'), ('--cpus', '1'),
                     ('--user', '65534:65534'), ('python', '-I'), ('-c', vu.VERIFY_SCRIPT)):
            self.assertTrue(_pair(cmd, x, y), (x, y))
        self.assertIn('--read-only', cmd)
        self.assertIn('--pull=never', cmd)  # a missing image must never be fetched from the network
        self.assertLess(cmd.index('--pull=never'), cmd.index(vu.IMAGE))
        self.assertEqual(cmd.count('--mount'), 1)
        mount = cmd[cmd.index('--mount') + 1]
        self.assertTrue(mount.startswith('type=bind,src='))
        self.assertTrue(mount.endswith(',dst=/work,readonly'))
        tmpfs = cmd[cmd.index('--tmpfs') + 1]
        self.assertEqual(tmpfs, '/tmp:rw,noexec,nosuid,size=256m')
        self.assertEqual(cmd[-2:], ['1', '1'])  # behavior cases present, suite enabled
        self.assertEqual(seen['kwargs']['timeout'], 180)
        self.assertIn('-i', cmd)  # nonces travel on stdin, never in argv or files
        nonces = seen['kwargs']['input'].split()
        self.assertEqual(len(nonces), 3)
        self.assertEqual(len(set(nonces)), 3)
        self.assertFalse(any(n in ' '.join(cmd) for n in nonces))
        self.assertEqual(sorted(seen['kwargs']['expect']),
                         sorted(f'AXIS-STAGE-OK {k} {n}' for k, n in zip(('CONTRACT', 'BEHAVIOR', 'SUITE'), nonces)))
        self.assertNotIn('extensions/tool.py', ' '.join(cmd))  # raw target never reaches the container command
        self.assertEqual(seen['candidate'], NEW.encode())
        self.assertEqual(seen['src_candidate'], NEW.encode())
        self.assertIn("'/work/tool.py'", seen['runner'])
        self.assertIn('src/test_alpha.py', seen['files'])
        self.assertNotIn('src/test_needs_node.py', seen['files'])
        self.assertFalse(any(f.startswith(('src/.venv', 'src/upgrades', 'src/skills', 'src/proposals',
                                           'src/backups')) or f.endswith(('.db', '.sqlite3', '.md'))
                             for f in seen['files']), seen['files'])
        compile(vu.VERIFY_SCRIPT, '<verify>', 'exec')

    def test_stage_lines_in_report(self):
        uid = self.propose_ext()
        for rc, expect, ok in ((0, ['PASS', 'CONTRACT: PASS', 'BEHAVIOR: SKIPPED (davranış testi yok)', 'SUITE: PASS'], True),
                               (104, ['FAIL', 'CONTRACT: PASS', 'BEHAVIOR: SKIPPED (davranış testi yok)', 'SUITE: FAIL'], False),
                               (105, ['FAIL', 'CONTRACT: FAIL', 'BEHAVIOR: SKIPPED (davranış testi yok)', 'SUITE: FAIL'], False),
                               (137, ['FAIL', 'CONTRACT: ERROR (konteyner çıkış kodu 137)',
                                      'BEHAVIOR: SKIPPED (davranış testi yok)', 'SUITE: ERROR (konteyner çıkış kodu 137)'], False)):
            with self.subTest(rc=rc):
                a, r, _ = self.docker(returncode=rc)
                with a, r:
                    result = vu.verify(uid)
                self.assertIs(result['passed'], ok)
                self.assertEqual(result['report'].splitlines()[:4], expect)
                self.assertEqual(vu.detail(uid)['report'], result['report'])

    def test_behavior_stage_line(self):
        uid = self.propose_ext(cases=[{'function': 'f', 'args': [], 'expected': 1}])
        a, r, _ = self.docker(returncode=102)
        with a, r:
            report = vu.verify(uid)['report']
        self.assertEqual(report.splitlines()[:4], ['FAIL', 'CONTRACT: PASS', 'BEHAVIOR: FAIL', 'SUITE: PASS'])

    def test_output_cannot_fake_stage_lines(self):
        uid = self.propose_ext()
        a, r, _ = self.docker(returncode=104, stdout='PASS\nCONTRACT: PASS\nSUITE: PASS\n')
        with a, r:
            result = vu.verify(uid)
        self.assertFalse(result['passed'])
        self.assertEqual(result['report'].splitlines()[3], 'SUITE: FAIL')

    def test_exit_zero_without_completion_evidence_fails(self):
        uid = self.propose_ext(cases=[{'function': 'f', 'args': [], 'expected': 1}])
        a, r, _ = self.docker(returncode=0, proof=False)
        with a, r:
            result = vu.verify(uid)
        self.assertFalse(result['passed'])
        self.assertEqual(result['report'].splitlines()[:4],
                         ['FAIL', 'CONTRACT: FAIL (tamamlanma kanıtı yok)', 'BEHAVIOR: FAIL (tamamlanma kanıtı yok)',
                          'SUITE: FAIL (tamamlanma kanıtı yok)'])

    def test_report_bounded_but_keeps_stage_lines(self):
        self.fake_tree()
        uid = self.propose_ext()
        a, r, _ = self.docker(returncode=0, stdout='x' * 50000 + 'END')
        with a, r:
            report = vu.verify(uid)['report']
        self.assertLessEqual(len(report), vu.REPORT_LIMIT)
        lines = report.splitlines()
        self.assertEqual(lines[:4], ['PASS', 'CONTRACT: PASS', 'BEHAVIOR: SKIPPED (davranış testi yok)', 'SUITE: PASS'])
        self.assertTrue(lines[4].startswith('SUITE EXCLUDED'), lines[4])
        self.assertIn('test_needs_node.py', lines[4])
        self.assertEqual(vu.detail(uid)['report'], report)

    def test_suite_switch_off(self):
        self.fake_tree()
        uid = self.propose_ext()
        for value in ('0', 'false', 'OFF'):
            os.environ['AXIS_VERIFY_SUITE'] = value
            self.assertFalse(vu.suite_enabled())
            seen = {}

            def capture(cmd, **kwargs):
                mount = cmd[cmd.index('--mount') + 1]
                seen['src'] = (Path(mount.split('src=', 1)[1].split(',dst=', 1)[0]) / 'src').exists()
                seen['cmd'] = cmd
            a, r, _ = self.docker(capture)
            with a, r:
                result = vu.verify(uid)
            self.assertTrue(result['passed'])
            self.assertFalse(seen['src'])
            self.assertEqual(seen['cmd'][-1], '0')
            self.assertIn('SUITE: SKIPPED (AXIS_VERIFY_SUITE=0)', result['report'].splitlines())
            self.assertFalse(vu.auto_status()['suite_enabled'])

    def test_blocked_lists_stages(self):
        uid = self.propose_ext()
        with mock.patch.object(vu, 'docker_available', return_value=False), \
                mock.patch.object(vu.subprocess, 'run') as run:
            report = vu.verify(uid)['report']
        run.assert_not_called()
        self.assertTrue(report.startswith('BLOCKED'))
        self.assertIn('CONTRACT: NOT RUN', report)
        self.assertIn('SUITE: NOT RUN', report)

    def test_container_script_dry_run_on_host(self):
        """Run VERIFY_SCRIPT with host Python and rewritten paths: exit-code protocol for each stage."""
        (self.root / 'alpha.py').write_text('def a():\n return 1\n', encoding='utf-8')
        (self.root / 'test_alpha.py').write_text('import unittest, alpha\nclass T(unittest.TestCase):\n'
                                                 ' def test_a(self): self.assertEqual(alpha.a(), 1)\n', encoding='utf-8')
        real_container_run = vu._container_run  # the real bounded reader, fed a host Python instead of docker
        outcomes = []

        def host(cmd, **kwargs):
            mount = cmd[cmd.index('--mount') + 1]
            work = Path(mount.split('src=', 1)[1].split(',dst=', 1)[0])
            scratch = Path(tempfile.mkdtemp(dir=self.tmp))
            for f in ('test_contract.py', 'test_behavior.py'):
                if (work / f).exists():
                    (work / f).write_text((work / f).read_text(encoding='utf-8').replace('/work', work.as_posix()), encoding='utf-8')
            script = cmd[cmd.index('-c') + 1].replace('/tmp/axis', (scratch / 'axis').as_posix()) \
                .replace('/tmp/.done-', (scratch / '.done-').as_posix()) \
                .replace("'/tmp'", repr(scratch.as_posix())).replace('/work', work.as_posix())
            proc = real_container_run([sys.executable, '-I', '-c', script] + cmd[-2:], **kwargs)
            outcomes.append(proc.returncode)
            return proc
        cases_ok = [{'function': 'f', 'args': [], 'expected': 1}]
        cases_bad = [{'function': 'f', 'args': [], 'expected': 2}]
        # Passes the AST contract (another reminder that it is not a boundary) and exits 0 at import time.
        early_exit = ('try:\n import posix as p\nexcept ImportError:\n import nt as p\np._exit(0)\n'
                      'def f():\n return 1\n')
        for code, cases, target, expect in (
                (NEW, cases_ok, 'extensions/tool.py', 0),
                (NEW, cases_bad, 'extensions/tool.py', 102),
                (early_exit, cases_ok, 'extensions/tool.py', 102),
                ('import os\ndef f():\n return 1\n', None, 'extensions/tool.py', 101),
                ('def a():\n return 5\ndef f():\n return 1\n', None, 'alpha.py', 104)):
            with self.subTest(expect=expect, code=code[:20]):
                uid = vu.propose(target, code, 'dry run')['id']
                if cases:
                    vu.attach_behavior_cases(uid, cases)
                with mock.patch.object(vu, 'docker_available', return_value=True), \
                        mock.patch.object(vu, '_container_run', side_effect=host):
                    result = vu.verify(uid)
                self.assertEqual(outcomes[-1], expect, result['report'])
                self.assertIs(result['passed'], expect == 0, result['report'])
                if expect == 0:
                    self.assertEqual(result['report'].splitlines()[1:4],
                                     ['CONTRACT: PASS', 'BEHAVIOR: PASS', 'SUITE: PASS'])

    def test_missing_image_blocked_without_pull(self):
        self.fake_tree()
        for text in ('docker: Error response from daemon: No such image: python:3.12-slim',
                     "Unable to find image 'python:3.12-slim' locally"):
            with self.subTest(text=text):
                uid = self.propose_ext(cases=[{'function': 'f', 'args': [], 'expected': 1}])
                a, r, run = self.docker(returncode=125, stdout=text, proof=False)
                with a, r:
                    result = vu.verify(uid)
                self.assertFalse(result['passed'])
                lines = result['report'].splitlines()
                self.assertEqual(lines[0], 'BLOCKED: python:3.12-slim imajı yerelde yok; internete çıkılmadı. '
                                           'Kendiniz indirin: docker pull python:3.12-slim')
                self.assertEqual(lines[1:4], ['CONTRACT: NOT RUN', 'BEHAVIOR: NOT RUN', 'SUITE: NOT RUN'])
                self.assertIn('--pull=never', run.call_args_list[0][0][0])
                self.assertEqual(vu.detail(uid)['status'], 'pending')
        # Exit 125 for any other reason stays an ordinary container error.
        uid = self.propose_ext(cases=[{'function': 'f', 'args': [], 'expected': 1}])
        a, r, _ = self.docker(returncode=125, stdout='docker: invalid reference format', proof=False)
        with a, r:
            result = vu.verify(uid)
        self.assertFalse(result['passed'])
        self.assertTrue(result['report'].startswith('FAIL'), result['report'])


class ReviewFindingTests(Base):
    """Regression tests for the 2026-11-11 independent review findings."""

    def _junction(self, link, target):
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, AttributeError, OSError) as exc:
            self.skipTest('junction oluşturulamadı: ' + type(exc).__name__)

    def test_junction_inside_static_is_not_followed(self):
        self.fake_tree()
        outside = self.tmp / 'host_secrets'
        outside.mkdir()
        (outside / 'id_rsa').write_text('SECRET', encoding='utf-8')
        self._junction(self.root / 'static' / 'linked', outside)
        dest = self.tmp / 'copy'
        vu.stage_sources(dest, 'alpha.py', b'def a():\n return 1\n')
        self.assertFalse((dest / 'static' / 'linked').exists())
        self.assertNotIn('SECRET', ''.join(p.read_text(encoding='utf-8', errors='replace')
                                           for p in dest.rglob('*') if p.is_file()))

    def test_junction_detection_is_used_for_dirs_and_targets(self):
        self.fake_tree()
        real = os.path.isjunction
        flagged = lambda p: Path(p).name in ('sub', 'extensions') or real(p)
        with mock.patch.object(vu.os.path, 'isjunction', side_effect=flagged):
            dest = self.tmp / 'copy'
            vu.stage_sources(dest, 'alpha.py', b'x=1\n')
            self.assertFalse((dest / 'static' / 'sub').exists())
            self.assertFalse((dest / 'extensions').exists())
            with self.assertRaises(ValueError):
                vu.safe_target('extensions/tool.py')

    def test_junctioned_extensions_folder_refused(self):
        outside = self.tmp / 'elsewhere'
        outside.mkdir()
        self._junction(self.root / 'extensions', outside)
        with self.assertRaises(ValueError):
            vu.safe_target('extensions/tool.py')

    def test_candidate_can_never_be_named_like_a_harness_file(self):
        for name in ('test_contract.py', 'test_behavior.py', 'extensions/test_contract.py',
                     'extensions/test_behavior.py', 'extensions/cases.json', 'cases.json', 'extensions/src.py/x.py'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    vu.safe_target(name)
        harness = {'test_contract.py', 'test_behavior.py', 'cases.json', 'src'}
        uid = vu.propose('extensions/contract.py', NEW, 'x')['id']
        vu.attach_behavior_cases(uid, [{'function': 'f', 'args': [], 'expected': 1}])
        seen = {}

        def capture(cmd, **kw):
            work = Path(cmd[cmd.index('--mount') + 1].split('src=', 1)[1].split(',dst=', 1)[0])
            seen['names'] = {p.name for p in work.iterdir()}
            seen['candidate'] = (work / 'contract.py').read_bytes()
        a, r, _ = self.docker(capture)
        with a, r:
            self.assertTrue(vu.verify(uid)['passed'])
        self.assertEqual(seen['names'], harness | {'contract.py'})
        self.assertEqual(seen['candidate'], NEW.encode())

    def test_deep_behavior_case_refused_before_serialising(self):
        deep = 1
        for _ in range(5000):  # json.dumps would hit the recursion limit on this
            deep = [deep]
        with mock.patch.object(vu.json, 'dumps', side_effect=AssertionError('serialised too early')):
            with self.assertRaisesRegex(ValueError, 'İç içe'):
                vu.validate_behavior_cases([{'function': 'f', 'args': [deep], 'expected': 1}])
            with self.assertRaisesRegex(ValueError, 'JSON literal'):
                vu.validate_behavior_cases([{'function': 'f', 'args': ['x' * 10 ** 6], 'expected': 1}])

    def test_sweep_is_capped_and_oldest_first(self):
        ids = [vu.propose(f'extensions/tool_{i:02d}.py', NEW, 'x', schedule=False)['id'] for i in range(vu.SWEEP_LIMIT + 5)]
        for i in range(vu.SWEEP_LIMIT + 3):
            vu.propose(f'top_{i:02d}.py', NEW, 'x', schedule=False)  # top-level never counts against the cap
        sched = mock.Mock()
        with mock.patch.object(vu, 'SCHEDULER', sched):
            queued = vu.sweep_untested()
        self.assertEqual(len(queued), vu.SWEEP_LIMIT)
        self.assertTrue(set(queued) <= set(ids))  # only extension proposals
        self.assertEqual(sched.call_count, vu.SWEEP_LIMIT)

    # ---- crash journal ----
    def _crash_after_replace(self, original):
        (self.root / 'extensions').mkdir(exist_ok=True)
        path = self.root / 'extensions' / 'tool.py'
        if original is not None:
            path.write_bytes(original)
        uid = vu.propose('extensions/tool.py', NEW, 'x')['id']
        a, r, _ = self.docker()

        class Crash(BaseException):
            pass
        real_write = vu._atomic_write

        def write_then_die(dest, data):
            real_write(dest, data)
            raise Crash()  # process "dies": the handler below never gets to undo anything
        with a, r, mock.patch.object(vu, '_atomic_write', side_effect=write_then_die), \
                mock.patch.object(vu.Path, 'unlink', autospec=True, side_effect=lambda self, missing_ok=False: None):
            with self.assertRaises(Crash):
                vu.decide(uid, 'approve', 'ONAYLIYORUM')
        return uid, path

    def test_recovery_restores_file_after_crash_between_replace_and_commit(self):
        for original in (b'def f():\n return 0\n', None):
            with self.subTest(original=original):
                uid, path = self._crash_after_replace(original)
                self.assertEqual(path.read_bytes(), NEW.encode())  # changed code on disk, status still pending
                self.assertEqual(vu.detail(uid)['status'], 'pending')
                self.assertEqual(vu.recover_interrupted(), [uid])
                if original is None:
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(path.read_bytes(), original)
                self.assertEqual(vu.detail(uid)['status'], 'pending')
                self.assertEqual(list((vu.DATA / 'journal').glob('*.json')), [])
                self.assertEqual(vu.recover_interrupted(), [])
                path.unlink(missing_ok=True)

    def test_recovery_finishes_interrupted_rollback_and_leaves_unclear_cases(self):
        (self.root / 'extensions').mkdir()
        path = self.root / 'extensions' / 'tool.py'
        path.write_bytes(b'def f():\n return 0\n')
        uid = vu.propose('extensions/tool.py', NEW, 'x')['id']
        a, r, _ = self.docker()
        with a, r:
            vu.decide(uid, 'approve', 'ONAYLIYORUM')
        # Simulate: journal written, file restored, process died before the commit.
        old_digest = vu.hashlib.sha256(b'def f():\n return 0\n').hexdigest()
        vu._journal(uid, {'op': 'rollback', 'target': 'extensions/tool.py', 'restored': old_digest})
        path.write_bytes(b'def f():\n return 0\n')
        sched = mock.Mock()
        with mock.patch.object(vu, 'SCHEDULER', sched):
            vu.sweep_untested()  # start-up hook runs the recovery first
        self.assertEqual(vu.detail(uid)['status'], 'rolled_back')
        # Unclear: file edited by someone after the interrupted apply → journal kept, file untouched.
        uid2 = vu.propose('extensions/tool.py', NEW, 'y')['id']
        vu._journal(uid2, {'op': 'apply', 'target': 'extensions/tool.py', 'backup': '', 'previous': old_digest})
        path.write_bytes(b'def f():\n return 42\n')
        self.assertEqual(vu.recover_interrupted(), [])
        self.assertEqual(path.read_bytes(), b'def f():\n return 42\n')
        self.assertTrue((vu.DATA / 'journal' / (uid2 + '.json')).exists())

    def test_successful_apply_and_rollback_leave_no_journal(self):
        uid = vu.propose('extensions/tool.py', NEW, 'x')['id']
        a, r, _ = self.docker()
        with a, r:
            vu.decide(uid, 'approve', 'ONAYLIYORUM')
        vu.rollback(uid, 'GERI_AL')
        self.assertEqual(list((vu.DATA / 'journal').glob('*.json')), [])


class ApplyRollbackTests(Base):
    def passes(self):
        return self.docker(returncode=0)

    def test_new_extension_created_and_rolled_back(self):
        self.assertFalse((self.root / 'extensions').exists())
        uid = vu.propose('extensions/fresh_tool.py', NEW, 'yeni')['id']
        a, r, _ = self.passes()
        with a, r:
            result = vu.decide(uid, 'approve', 'ONAYLIYORUM')
        self.assertEqual(result, {'status': 'applied', 'restart_required': True, 'backup': False})
        path = self.root / 'extensions' / 'fresh_tool.py'
        self.assertEqual(path.read_bytes(), NEW.encode())
        self.assertEqual(vu.rollback(uid, 'GERI_AL')['status'], 'rolled_back')
        self.assertFalse(path.exists())
        self.assertEqual(list((self.root / 'extensions').iterdir()), [])

    def test_existing_extension_backup_and_rollback(self):
        (self.root / 'extensions').mkdir()
        path = self.root / 'extensions' / 'tool.py'
        path.write_bytes(b'def f():\n return 0\n')
        uid = vu.propose('extensions/tool.py', NEW, 'degisiklik')['id']
        self.assertIn('current/extensions/tool.py', vu.detail(uid)['diff'])
        a, r, _ = self.passes()
        with a, r:
            self.assertTrue(vu.decide(uid, 'approve', 'ONAYLIYORUM')['backup'])
        self.assertEqual(path.read_bytes(), NEW.encode())
        path.write_bytes(b'def f():\n return 7\n')  # changed afterwards: rollback must refuse
        with self.assertRaisesRegex(ValueError, 'sonradan'):
            vu.rollback(uid, 'GERI_AL')
        path.write_bytes(NEW.encode())
        vu.rollback(uid, 'GERI_AL')
        self.assertEqual(path.read_bytes(), b'def f():\n return 0\n')
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['tool.py'])

    def test_failed_verification_applies_nothing(self):
        uid = vu.propose('extensions/tool.py', NEW, 'x')['id']
        a, r, _ = self.docker(returncode=104)
        with a, r:
            with self.assertRaisesRegex(ValueError, 'İzole test'):
                vu.decide(uid, 'approve', 'ONAYLIYORUM')
        self.assertFalse((self.root / 'extensions' / 'tool.py').exists())
        self.assertEqual(vu.detail(uid)['status'], 'pending')

    def test_auto_pipeline_scope(self):
        sched = mock.Mock()
        with mock.patch.object(vu, 'SCHEDULER', sched):
            ext = vu.propose('extensions/tool.py', NEW, 'x')
            top = vu.propose('alpha.py', NEW, 'x')
        self.assertTrue(ext['auto_apply_queued'])
        self.assertFalse(top['auto_apply_queued'])
        sched.assert_called_once_with(ext['id'])
        a, r, run = self.passes()
        with a, r:
            self.assertEqual(vu.auto_pipeline(top['id'])['outcome'], 'manual_only')
            run.assert_not_called()
            self.assertEqual(vu.auto_pipeline(ext['id'])['outcome'], 'applied')
        self.assertFalse((self.root / 'alpha.py').exists())


if __name__ == '__main__':
    unittest.main()
