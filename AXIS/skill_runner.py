"""Run approved, untrusted AXIS skills exclusively in isolated Docker containers.

Trust model: the container limits what a skill can do to the host, nothing more.
The 'output' of run() is untrusted data produced by untrusted code. The per-run
marker only keeps the skill's ordinary prints from being mistaken for the result;
it does NOT authenticate the result, because the skill runs in the same process as
the runner and can write any line itself. Callers must validate 'output' like any
other external input and never treat 'success' as proof of correct behaviour.
"""

import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import tempfile
import threading
import time

import central_brain
import self_evolution
import vector_upgrade

IMAGE = vector_upgrade.IMAGE
MAX_INPUT = 20000
MAX_OUTPUT = 20000
MAX_CAPTURE = 65536
STARTUP_GRACE = 10  # seconds for container start on top of the skill timeout

RESULT_TAG = 'AXIS_RESULT'

# Runs inside the container only. Everything the skill prints goes to a capped buffer,
# so the real stdout carries exactly one line: AXIS_RESULT <per-run token> <json>.
RUNNER_SOURCE = r'''
import importlib.util
import json
from pathlib import Path
import signal
import sys
import traceback

sys.dont_write_bytecode = True
WORK_DIR = "/work"
NOISE_LIMIT = 32768
OUTPUT_LIMIT = 20000


class Capped:
    def __init__(self):
        self.parts, self.size = [], 0

    def write(self, text):
        text = str(text)
        room = NOISE_LIMIT - self.size
        if room > 0:
            self.parts.append(text[:room])
            self.size += min(len(text), room)
        return len(text)

    def flush(self):
        pass

    def text(self):
        return "".join(self.parts)


def on_alarm(signum, frame):
    raise TimeoutError("beceri zaman sınırını aştı")


def main():
    request = json.loads((Path(WORK_DIR) / "input.json").read_text(encoding="utf-8"))
    prefix = "AXIS_RESULT " + request["marker"] + " "
    channel, errors, encode = sys.stdout, sys.stderr, json.dumps
    noise = Capped()
    sys.stdout = sys.stderr = noise
    if hasattr(signal, "alarm"):
        signal.signal(signal.SIGALRM, on_alarm)
        signal.alarm(int(request["timeout"]))
    try:
        spec = importlib.util.spec_from_file_location("axis_skill", Path(WORK_DIR) / "skill.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.run(request["data"])
        if hasattr(signal, "alarm"):
            signal.alarm(0)
        payload = encode({"ok": True, "output": result}, allow_nan=False)
        if len(payload) > OUTPUT_LIMIT + 100:
            payload = encode({"ok": False, "error": "output too large"})
    except BaseException as exc:
        if hasattr(signal, "alarm"):
            signal.alarm(0)
        try:
            message = (type(exc).__name__ + ": " + str(exc))[:300]
            noise.write(traceback.format_exc())
        except BaseException:
            message = "Exception"
        payload = encode({"ok": False, "error": message}, allow_nan=False)
    errors.write(noise.text()[-NOISE_LIMIT:])
    errors.flush()
    channel.write(prefix + payload + "\n")
    channel.flush()


if __name__ == "__main__":
    main()
'''


def approved_digest(skill):
    return self_evolution.approved_digest(skill)


def _read_skill(skill):
    path = Path(self_evolution.SKILLS) / (skill + ".py")
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise ValueError("Beceri dosyası sembolik bağlantı.")
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Beceri yolu normal bir dosya değil.")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            after = path.lstat()
            if stat.S_ISLNK(after.st_mode):
                raise ValueError("Beceri dosyası sembolik bağlantı.")
            if not stat.S_ISREG(opened.st_mode) or not (
                os.path.samestat(before, opened)
                and os.path.samestat(opened, after)
            ):
                raise ValueError("Beceri dosyası okuma sırasında değişti.")
            return stream.read()
    except FileNotFoundError as exc:
        raise ValueError("Beceri dosyası eksik.") from exc


def runnable():
    result = []
    for path in Path(self_evolution.SKILLS).glob("*.py"):
        name = path.stem
        try:
            self_evolution.valid_name(name)
            approved = approved_digest(name)
            if approved is None:
                continue
            digest = hashlib.sha256(_read_skill(name)).hexdigest()
            if digest == approved[0]:
                result.append({
                    "skill": name, "sha256": digest, "approved_at": approved[1],
                })
        except (ValueError, OSError):
            continue
    return sorted(result, key=lambda item: item["skill"])


def _text(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return (value or "")[-MAX_CAPTURE:]


def _reject_constant(value):
    raise ValueError("Geçersiz JSON sabiti: " + value)


def _parse_result(process, marker):
    stdout, stderr = _text(process.stdout), _text(process.stderr)
    # Only the token-bearing line counts; the skill never sees real stdout.
    prefix = RESULT_TAG + " " + marker + " "
    lines = [line for line in stdout.splitlines() if line.startswith(prefix)]
    error = None
    output = None
    if process.returncode != 0:
        error = "Konteyner başarısız çıkış kodu döndürdü."
    elif not lines:
        error = "İşaretli sonuç satırı bulunamadı."
    else:
        try:
            payload = json.loads(
                lines[-1][len(prefix):], parse_constant=_reject_constant,
            )
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                detail = payload.get("error", "") if isinstance(payload, dict) else ""
                error = "Beceri başarısız: " + str(detail)[:300]
            elif "output" not in payload:
                error = "Sonuç çıktısı eksik."
            else:
                output = payload["output"]
                if len(json.dumps(output, allow_nan=False)) > MAX_OUTPUT:
                    error = "Sonuç izin verilen boyutu aşıyor."
        except (ValueError, TypeError, RecursionError):
            error = "Geçersiz JSON sonucu."
    if error:
        return "failure", None, error + ("\n" + stderr[-600:] if stderr else "")
    return "success", output, None


def _pump(stream, sink, overflow):
    # Stop reading at the cap: the host never buffers more than MAX_CAPTURE per pipe.
    try:
        while True:
            chunk = stream.read1(8192)
            if not chunk:
                return
            room = MAX_CAPTURE - len(sink)
            sink.extend(chunk[:max(room, 0)])
            if len(chunk) > room:
                overflow.set()
                return
    except (OSError, ValueError):
        return


def _execute(command, limit_s):
    """Run the docker client with bounded output and a hard deadline.

    Returns (returncode, stdout, stderr, reason); reason is None, 'timeout' or 'overflow'.
    """
    out, err = bytearray(), bytearray()
    overflow = threading.Event()
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    readers = [
        threading.Thread(target=_pump, args=(process.stdout, out, overflow), daemon=True),
        threading.Thread(target=_pump, args=(process.stderr, err, overflow), daemon=True),
    ]
    for reader in readers:
        reader.start()
    reason = None
    deadline = time.monotonic() + limit_s
    try:
        while True:
            try:
                process.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                pass
            if overflow.is_set():
                reason = 'overflow'
                break
            if time.monotonic() >= deadline:
                reason = 'timeout'
                break
    finally:
        if process.returncode is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        for reader in readers:
            reader.join(timeout=5)
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
    if reason is None and overflow.is_set():
        reason = 'overflow'
    decode = lambda raw: bytes(raw).decode('utf-8', errors='replace')
    return process.returncode, decode(out), decode(err), reason


def _remove_container(name):
    """Best effort; True when the container is gone (or never existed)."""
    try:
        done = subprocess.run(
            ['docker', 'rm', '-f', name], capture_output=True,
            encoding='utf-8', errors='replace', timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 or 'no such container' in (done.stderr or '').lower()


def run(skill, data, timeout=20):
    """Run an approved skill in Docker. The returned 'output' is untrusted data."""
    started = time.monotonic()
    if not isinstance(skill, str):
        raise ValueError("Geçersiz beceri adı.")
    try:
        self_evolution.valid_name(skill)
    except ValueError as exc:
        raise ValueError("Geçersiz beceri adı.") from exc
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError("Zaman sınırı 1 ile 60 arasında bir tam sayı olmalı.")
    approved = approved_digest(skill)
    if approved is None:
        raise ValueError("Beceri için onaylanmış öneri yok.")
    source = _read_skill(skill)
    digest = hashlib.sha256(source).hexdigest()
    if digest != approved[0]:
        raise ValueError("Beceri dosyası onaydan sonra değişmiş.")
    try:
        encoded_data = json.dumps(data, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("Veri JSON biçiminde serileştirilemiyor.") from exc
    if len(encoded_data) > MAX_INPUT:
        raise ValueError("JSON girdisi izin verilen boyutu aşıyor.")

    def finish(status, output=None, error=None):
        result = {
            "skill": skill, "status": status, "output": output, "error": error,
            "elapsed_s": round(time.monotonic() - started, 2), "sha256": digest,
        }
        # The audit trail is best effort; it must never change the run result.
        try:
            central_brain.log(
                'orchestrator', 'skill_run', 'skill_run',
                'success' if status == 'success' else 'failure',
                f"Beceri '{skill}' çalıştırma durumu: {status}",
                None, {'skill': skill, 'sha256': digest, 'status': status},
            )
        except Exception:
            pass
        return result

    try:
        if not vector_upgrade.docker_available():
            # No host fallback, ever: skill code is untrusted.
            return finish("blocked", error="Docker Engine kullanılamıyor; beceri çalıştırılmadı. "
                                           "Güvenlik nedeniyle ana makinede çalıştırma yapılmaz.")
        with tempfile.TemporaryDirectory(
            prefix="axis_skill_", ignore_cleanup_errors=True,
        ) as temporary:
            work = Path(temporary).resolve()
            if any(ch in ",=" or ord(ch) < 32 or 127 <= ord(ch) < 160
                   for ch in str(work)):
                return finish("blocked", error="Geçici dizin Docker bağlaması için güvensiz.")
            marker = secrets.token_hex(16)
            copied = work / "skill.py"
            copied.write_bytes(source)
            # The container must get exactly the approved bytes; re-hash what landed on disk.
            if hashlib.sha256(copied.read_bytes()).hexdigest() != approved[0]:
                raise ValueError("Beceri dosyası onaydan sonra değişmiş (kopya doğrulanamadı).")
            (work / "input.json").write_text(
                json.dumps({"data": data, "marker": marker, "timeout": timeout},
                           allow_nan=False),
                encoding="utf-8",
            )
            (work / "runner.py").write_text(RUNNER_SOURCE, encoding="utf-8")
            name = "axis-skill-" + secrets.token_hex(16)
            command = [
                'docker', 'run', '--rm', '--pull=never', '--name', name,
                '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--pids-limit', '64',
                '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
                '--user', '65534:65534', '--log-driver', 'none', '--mount',
                f'type=bind,src={work},dst=/work,readonly',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                IMAGE, 'python', '-I', '/work/runner.py',
            ]
            clean_exit = False
            try:
                code, stdout, stderr, reason = _execute(command, timeout + STARTUP_GRACE)
                clean_exit = reason is None and code == 0
            finally:
                # --rm covers a normal exit; every other path removes the named container.
                removed = True if clean_exit else _remove_container(name)
            note = "" if removed else "\nUyarı: konteyner kaldırılamadı (" + name + ")."
            if reason == 'timeout':
                return finish("failure", error="Beceri çalıştırmada zaman aşımı."
                              + note + ("\n" + stderr[-600:] if stderr else ""))
            if reason == 'overflow':
                return finish("failure", error="Beceri çıktısı 64 KB sınırını aştı; konteyner durduruldu."
                              + note)
            if reason is None and vector_upgrade.image_missing(code, (stdout or "") + (stderr or "")):
                return finish("blocked", error=vector_upgrade.IMAGE_MISSING + note)
            process = subprocess.CompletedProcess(command, code, stdout, stderr)
            status, output, error = _parse_result(process, marker)
            return finish(status, output, error + note if error else error)
    except OSError:
        return finish("blocked", error="Docker veya çalışma dosyaları kullanılamıyor.")
