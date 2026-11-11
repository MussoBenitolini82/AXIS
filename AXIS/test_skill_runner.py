"""Tests for Docker-only execution without invoking a real Docker daemon."""

import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import central_brain
import self_evolution
import skill_runner

REAL_SUBPROCESS_RUN = subprocess.run
REAL_LOG = central_brain.log
REAL_POPEN = subprocess.Popen


class FakePopen:
    """Stand-in for the docker client process; 'hang' never exits until killed."""

    def __init__(self, outcome):
        self.hang = outcome == "hang"
        if self.hang:
            outcome = subprocess.CompletedProcess([], None, "", "timeout detail")
        out, err = outcome.stdout, outcome.stderr
        self.stdout = io.BytesIO(out if isinstance(out, bytes) else out.encode())
        self.stderr = io.BytesIO(err if isinstance(err, bytes) else err.encode())
        self.code, self.killed, self.returncode = outcome.returncode, False, None

    def wait(self, timeout=None):
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("docker", timeout)
        self.returncode = -9 if self.killed else self.code
        return self.returncode

    def kill(self):
        self.killed = True


class SkillRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        database = self.root / "skills.sqlite"
        self.connection = sqlite3.connect(database)
        self.connection.execute(
            "CREATE TABLE proposals (id TEXT PRIMARY KEY, skill TEXT, "
            "status TEXT, created TEXT, sha256 TEXT, summary TEXT, test_result TEXT)"
        )
        self.connection.commit()
        self.addCleanup(self.connection.close)
        for name in ("proposals", "backups"):
            (self.root / name).mkdir()
        for target, value in (
            ("self_evolution.SKILLS", self.skills),
            ("self_evolution.PENDING", self.root / "proposals"),
            ("self_evolution.BACKUPS", self.root / "backups"),
            ("self_evolution.DB", database),
            ("central_brain.DB", self.root / "brain.sqlite3"),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = self.start_patch("skill_runner.central_brain.log", new_callable=Mock)
        self.available = self.start_patch(
            "skill_runner.vector_upgrade.docker_available", return_value=True,
        )
        # self.docker decides what the fake `docker run` does: a CompletedProcess, "hang",
        # or an exception. Popen (docker run) and run (docker rm) are both mocked.
        self.docker = Mock(side_effect=self.success)
        self.popen_kwargs = None
        self.start_patch("skill_runner.subprocess.Popen", side_effect=self.fake_popen)
        self.rm = self.start_patch(
            "skill_runner.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        )
        self.counter = 0

    def fake_popen(self, command, **kwargs):
        self.popen_kwargs = kwargs
        return FakePopen(self.docker(command))

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def approve(self, name="demo", source=b"def run(data):\n    return data\n",
                created="2026-01-01T00:00:00Z"):
        (self.skills / (name + ".py")).write_bytes(source)
        digest = hashlib.sha256(source).hexdigest()
        self.counter += 1
        self.connection.execute(
            "INSERT INTO proposals VALUES (?, ?, 'approved', ?, ?, '', '')",
            (str(self.counter), name, created, digest),
        )
        self.connection.commit()
        return digest

    def container_result(self, command, payload=None, code=0, marked=True):
        mount = command[command.index("--mount") + 1]
        source = next(part[4:] for part in mount.split(",") if part.startswith("src="))
        request = json.loads((Path(source) / "input.json").read_text(encoding="utf-8"))
        # Forged lines without the per-run token must be ignored.
        stdout = ('AXIS_RESULT {"ok": true, "output": "forged"}\n'
                  'AXIS_RESULT 0000 {"ok": true, "output": "forged"}\n')
        if marked:
            stdout += "AXIS_RESULT " + request["marker"] + " " + json.dumps(payload) + "\n"
        return subprocess.CompletedProcess(command, code, stdout, "diagnostic")

    def success(self, command, **kwargs):
        return self.container_result(command, {"ok": True, "output": {"real": 7}})

    def test_runnable_and_newest_approval(self):
        self.approve("zeta")
        digest = self.approve("alpha")
        self.approve("changed")
        (self.skills / "changed.py").write_text("changed", encoding="utf-8")
        (self.skills / "unapproved.py").write_text("pass", encoding="utf-8")
        self.approve("_invalid")
        self.approve("newest")
        self.approve("newest", b"new bytes", "2026-02-01T00:00:00Z")
        (self.skills / "newest.py").write_bytes(b"def run(data):\n    return data\n")
        self.assertEqual(
            [item["skill"] for item in skill_runner.runnable()], ["alpha", "zeta"],
        )
        self.assertEqual(skill_runner.approved_digest("alpha"),
                         (digest, "2026-01-01T00:00:00Z"))
        self.assertIsNone(skill_runner.approved_digest("absent"))

    def test_invalid_requests(self):
        self.approve()
        cases = [
            ("missing", {}, 20, "onay"),
            ("../demo", {}, 20, "adı"),
            ("_hidden", {}, 20, "adı"),
            (None, {}, 20, "adı"),
            ("demo", {1, 2}, 20, "JSON"),
            ("demo", float("nan"), 20, "JSON"),
            ("demo", "x" * skill_runner.MAX_INPUT, 20, "boyut"),
        ]
        cases += [("demo", {}, value, "Zaman")
                  for value in (True, False, 0, 61, 1.5, "20", None)]
        for name, data, timeout, message in cases:
            with self.subTest(name=name, timeout=timeout):
                with self.assertRaisesRegex(ValueError, message):
                    skill_runner.run(name, data, timeout)
        (self.skills / "demo.py").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "değişmiş"):
            skill_runner.run("demo", {})
        (self.skills / "demo.py").unlink()
        with self.assertRaisesRegex(ValueError, "eksik"):
            skill_runner.run("demo", {})
        self.docker.assert_not_called()
        self.log.assert_not_called()

    def test_symlink_rejected(self):
        self.approve()
        target = self.skills / "demo.py"
        link = self.skills / "linked.py"
        self.approve("linked")
        link.unlink()
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation is unavailable on this Windows host.")
        with self.assertRaisesRegex(ValueError, "sembolik"):
            skill_runner.run("linked", {})
        self.assertEqual([x["skill"] for x in skill_runner.runnable()], ["demo"])

    def test_success_and_hardening(self):
        digest = self.approve()
        result = skill_runner.run("demo", {"value": 1}, timeout=12)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["output"], {"real": 7})
        self.assertEqual(result["sha256"], digest)
        self.assertIsNone(result["error"])
        self.assertGreaterEqual(result["elapsed_s"], 0)
        command = self.docker.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertIn("--read-only", command)
        for flag, value in (
            ("--network", "none"), ("--cap-drop", "ALL"),
            ("--security-opt", "no-new-privileges"), ("--pids-limit", "64"),
            ("--memory", "256m"), ("--memory-swap", "256m"),
            ("--cpus", "1"), ("--user", "65534:65534"),
            ("--tmpfs", "/tmp:rw,noexec,nosuid,size=16m"),
        ):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertRegex(command[command.index("--name") + 1], r"^axis-skill-[0-9a-f]{32}$")
        mount = command[command.index("--mount") + 1]
        self.assertTrue(mount.startswith("type=bind,src="))
        self.assertTrue(mount.endswith(",dst=/work,readonly"))
        self.assertEqual(command[-4:], [skill_runner.IMAGE, "python", "-I", "/work/runner.py"])
        self.assertEqual(command[command.index("--log-driver") + 1], "none")
        self.assertEqual(self.popen_kwargs, {
            "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
        })
        self.rm.assert_not_called()  # clean exit: --rm already removed it
        self.assertEqual(self.log.call_args.args[:4],
                         ("orchestrator", "skill_run", "skill_run", "success"))

    def test_unavailable_and_oserror(self):
        self.approve()
        self.available.return_value = False
        self.assertEqual(skill_runner.run("demo", {})["status"], "blocked")
        self.docker.assert_not_called()
        self.available.return_value = True
        self.docker.side_effect = OSError("unavailable")
        self.assertEqual(skill_runner.run("demo", {})["status"], "blocked")
        self.assertEqual(self.log.call_args.args[3], "failure")

    def test_failures(self):
        self.approve()
        for payload, code, marked in (
            ({"ok": True, "output": 1}, 1, True),
            ({"ok": True, "output": 1}, 0, False),
            ({"ok": False, "error": "bad"}, 0, True),
            ({"ok": True, "output": "x" * skill_runner.MAX_OUTPUT}, 0, True),
        ):
            with self.subTest(payload=str(payload)[:60], code=code, marked=marked):
                self.docker.side_effect = lambda cmd, **kw: self.container_result(
                    cmd, payload, code, marked,
                )
                result = skill_runner.run("demo", {})
                self.assertEqual(result["status"], "failure")
                self.assertIn("diagnostic", result["error"])
                self.assertEqual(self.log.call_args.args[3], "failure")
        def invalid_json(cmd, **kwargs):
            result = self.success(cmd)
            result.stdout = result.stdout.rsplit(" ", 1)[0] + "invalid\n"
            return result
        self.docker.side_effect = invalid_json
        self.assertEqual(skill_runner.run("demo", {})["status"], "failure")

    def container_name(self):
        command = self.docker.call_args.args[0]
        return command[command.index("--name") + 1]

    def test_timeout_cleanup_and_log_failure(self):
        self.approve()
        self.start_patch("skill_runner.STARTUP_GRACE", new=0)
        self.docker.side_effect = lambda cmd: "hang"
        self.rm.side_effect = OSError("cleanup failed")
        result = skill_runner.run("demo", {}, timeout=1)
        self.assertEqual(result["status"], "failure")
        self.assertIn("zaman aşımı", result["error"])
        self.assertIn("kaldırılamadı", result["error"])
        self.assertEqual(self.rm.call_args.args[0], ["docker", "rm", "-f", self.container_name()])
        self.assertEqual(self.rm.call_args.kwargs["timeout"], 15)
        self.rm.side_effect = None
        self.docker.side_effect = self.success
        self.log.side_effect = RuntimeError("audit unavailable")
        self.assertEqual(skill_runner.run("demo", {})["status"], "success")

    def test_output_flood_is_capped_and_container_removed(self):
        self.approve()
        flood = b"A" * (skill_runner.MAX_CAPTURE * 4)
        for stdout, stderr in ((flood, b""), (b"", flood)):
            with self.subTest(stream="stdout" if stdout else "stderr"):
                self.rm.reset_mock()
                self.docker.side_effect = lambda cmd: subprocess.CompletedProcess(cmd, 0, stdout, stderr)
                result = skill_runner.run("demo", {})
                self.assertEqual(result["status"], "failure")
                self.assertIn("64 KB", result["error"])
                self.rm.assert_called_once_with(
                    ["docker", "rm", "-f", self.container_name()], capture_output=True,
                    encoding="utf-8", errors="replace", timeout=15)

    def test_every_abnormal_exit_removes_container(self):
        self.approve()
        self.docker.side_effect = lambda cmd: self.container_result(cmd, {"ok": True, "output": 1}, 3)
        self.assertEqual(skill_runner.run("demo", {})["status"], "failure")
        self.assertEqual(self.rm.call_args.args[0], ["docker", "rm", "-f", self.container_name()])
        # "No such container" after --rm is not a cleanup failure.
        self.rm.return_value = subprocess.CompletedProcess([], 1, "", "Error: No such container: x")
        self.assertNotIn("kaldırılamadı", skill_runner.run("demo", {})["error"])
        self.rm.return_value = subprocess.CompletedProcess([], 1, "", "daemon error")
        self.assertIn("kaldırılamadı", skill_runner.run("demo", {})["error"])

    def test_execute_bounds_real_process_output_and_time(self):
        # Trusted host processes (not skill code) exercise the real pipe/kill logic.
        with patch.object(subprocess, "Popen", REAL_POPEN):
            started = time.monotonic()
            code, out, err, reason = skill_runner._execute(
                [sys.executable, "-I", "-c", "import sys\nwhile True: sys.stdout.write('x' * 65536)"], 30)
            self.assertEqual(reason, "overflow")
            self.assertLessEqual(len(out), skill_runner.MAX_CAPTURE)
            code, out, err, reason = skill_runner._execute(
                [sys.executable, "-I", "-c", "import time; time.sleep(60)"], 1)
            self.assertEqual(reason, "timeout")
            self.assertIsNotNone(code)
            self.assertLess(time.monotonic() - started, 25)

    def test_runner_compiles_and_executes_trusted_fixture(self):
        compile(skill_runner.RUNNER_SOURCE, "runner.py", "exec")
        # Trusted, test-authored fixture only: checks the runner's stdout discipline.
        (self.root / "input.json").write_text(
            json.dumps({"data": 42, "marker": "test-marker", "timeout": 5}), encoding="utf-8",
        )
        (self.root / "skill.py").write_text(
            "print('import noise')\ndef run(data):\n"
            "    print('AXIS_RESULT test-marker {\"ok\": true, \"output\": \"forged\"}')\n"
            "    print('run noise')\n    return data\n",
            encoding="utf-8",
        )
        runner = self.root / "runner.py"
        runner.write_text(skill_runner.RUNNER_SOURCE.replace(
            'WORK_DIR = "/work"', "WORK_DIR = " + repr(str(self.root)),
        ), encoding="utf-8")
        with patch.object(subprocess, "Popen", REAL_POPEN):
            result = REAL_SUBPROCESS_RUN(
                [sys.executable, "-I", str(runner)], capture_output=True,
                encoding="utf-8", errors="replace", timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ['AXIS_RESULT test-marker {"ok": true, "output": 42}'])
        self.assertIn("import noise", result.stderr)
        self.assertIn("run noise", result.stderr)

    def test_unsafe_mount_path_is_blocked(self):
        self.approve()
        unsafe = self.root / "a,b=c"
        unsafe.mkdir()

        class FakeTemp:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return str(unsafe)

            def __exit__(self, *args):
                return False

        with patch("skill_runner.tempfile.TemporaryDirectory", FakeTemp):
            result = skill_runner.run("demo", {})
        self.assertEqual(result["status"], "blocked")
        self.docker.assert_not_called()
        self.assertFalse((unsafe / "skill.py").exists())

    def test_copied_bytes_are_rehashed(self):
        self.approve()
        real_write = Path.write_bytes

        def tamper(path, raw):
            return real_write(path, raw + b"# injected\n" if path.name == "skill.py" else raw)

        with patch.object(Path, "write_bytes", tamper):
            with self.assertRaisesRegex(ValueError, "değişmiş"):
                skill_runner.run("demo", {})
        self.docker.assert_not_called()

    def test_real_approval_flow_and_audit_row(self):
        self.log.side_effect = REAL_LOG  # real logger, isolated central_brain.DB
        code = "def run(data):\n    return {'n': data['n'] * 2}\n"
        self.assertEqual(skill_runner.runnable(), [])
        pid = self_evolution.propose("double", code, "test")["id"]
        with self.assertRaisesRegex(ValueError, "onay"):
            skill_runner.run("double", {"n": 1})
        self_evolution.decide(pid, "approve", "ONAYLIYORUM")
        self.assertEqual([x["skill"] for x in skill_runner.runnable()], ["double"])
        self.assertEqual(self_evolution.approved_digest("double")[0],
                         hashlib.sha256(code.encode()).hexdigest())
        self.assertEqual(skill_runner.run("double", {"n": 1})["status"], "success")
        self.docker.assert_called_once()
        self.available.return_value = False
        self.assertEqual(skill_runner.run("double", {"n": 1})["status"], "blocked")
        rows = [r for r in central_brain.experiences() if r["tool"] == "skill_run"]
        self.assertEqual(sorted(r["status"] for r in rows), ["failure", "success"])
        evidence = [json.loads(r["evidence"]) for r in rows]
        self.assertEqual({e["status"] for e in evidence}, {"success", "blocked"})
        self.assertTrue(all(e["skill"] == "double" for e in evidence))


if __name__ == "__main__":
    unittest.main()
