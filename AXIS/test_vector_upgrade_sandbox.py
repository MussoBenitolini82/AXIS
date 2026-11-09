import tempfile, unittest
from pathlib import Path
from unittest import mock

import vector_upgrade as vu


def _pair(cmd, a, b):
    return any(cmd[i] == a and cmd[i + 1] == b for i in range(len(cmd) - 1))


class VectorUpgradeSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        tests = data / 'behavior_specs'
        tests.mkdir()
        for name, val in (('DATA', data), ('DB', data / 'upgrades.sqlite3'), ('TESTS', tests)):
            p = mock.patch.object(vu, name, val)
            p.start()
            self.addCleanup(p.stop)

    def _propose(self):
        return vu.propose('skills_helpers.py', 'def f():\n return 1\n', 'sandbox test')['id']

    def test_docker_command_is_locked_down(self):
        uid = self._propose()
        fake = mock.Mock(returncode=0, stdout='ok', stderr='')
        with mock.patch.object(vu, 'docker_available', return_value=True), \
             mock.patch.object(vu.subprocess, 'run', return_value=fake) as run:
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
        mount = cmd[cmd.index('--mount') + 1]
        self.assertIn('readonly', mount)
        self.assertIn('dst=/work', mount)
        tmpfs = cmd[cmd.index('--tmpfs') + 1]
        self.assertIn('noexec', tmpfs)
        self.assertIn('nosuid', tmpfs)

    def test_blocked_without_docker(self):
        uid = self._propose()
        with mock.patch.object(vu, 'docker_available', return_value=False), \
             mock.patch.object(vu.subprocess, 'run') as run:
            result = vu.verify(uid)
        self.assertFalse(result['passed'])
        self.assertTrue(result['report'].startswith('BLOCKED'))
        for call in run.call_args_list:
            args = call[0][0] if call[0] else []
            self.assertFalse(len(args) > 1 and args[:2] == ['docker', 'run'])


if __name__ == '__main__':
    unittest.main()
