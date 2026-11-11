"""Approval-gated, Docker-tested changes. Never execute generated code on the host during verification.

Honest limits: the AST contract test is a cheap first filter, not a security boundary (it is easy to bypass).
The Docker container isolates the TEST only; code that is applied later runs on the host like any other
AXIS file. Only 'extensions/<name>.py' targets may be applied automatically, and AXIS never imports
extension modules by itself. Top-level modules always need a human decision (decide(...,'ONAYLIYORUM')).
"""
from axis_sqlite import ClosingConnection
import ast, difflib, hashlib, json, os, re, secrets, shutil, sqlite3, subprocess, tempfile, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'upgrades'; DATA.mkdir(exist_ok=True)
DB=DATA/'upgrades.sqlite3'; LOCK=threading.RLock()
TESTS=DATA/'behavior_specs'; TESTS.mkdir(exist_ok=True)
# Any top-level AXIS Python module may be proposed EXCEPT the safety net itself: the update/test/rollback
# pipeline, the local-only model guard, the HTTP origin checks + approval endpoints, the SQLite factory,
# and every test file (an update must never be able to edit its own tests). Non-.py files (index.html
# holds the approval UI) and anything outside the AXIS top level / AXIS/extensions are refused too.
PROTECTED=frozenset({'vector_upgrade.py','local_models.py','server.py','axis_sqlite.py'})
_MODULE_NAME=re.compile(r'[A-Za-z_][A-Za-z0-9_]*\.py')
EXTENSIONS='extensions'
_EXT_TARGET=re.compile(r'extensions/([A-Za-z_][A-Za-z0-9_]*\.py)')
AUTO_SCOPE=EXTENSIONS+'/*.py'
VERIFY_TIMEOUT=180  # whole container run incl. the repository suite (~30 s on the host)
REPORT_LIMIT=4000
OUTPUT_LIMIT=2_000_000  # bytes of container output read before the run is killed (host memory bound)
_TAIL_BYTES=16000
SWEEP_LIMIT=20  # proposals queued per start-up sweep
def connection():
 c=sqlite3.connect(DB, factory=ClosingConnection,timeout=15);c.row_factory=sqlite3.Row
 try:
  c.execute('CREATE TABLE IF NOT EXISTS upgrades(id TEXT PRIMARY KEY, target TEXT, description TEXT, digest TEXT, status TEXT, report TEXT, backup TEXT, created TEXT)')
  c.execute('CREATE TABLE IF NOT EXISTS auto_events(id TEXT PRIMARY KEY, upgrade_id TEXT, target TEXT, description TEXT, outcome TEXT, detail TEXT, created TEXT)')
  c.commit()
 except BaseException:c.close();raise
 return c
def _is_link(p):
 # Windows directory junctions are not symlinks for is_symlink(); treat both as links.
 return p.is_symlink() or os.path.isjunction(p)
def safe_target(name):
 """Two accepted forms: '<module>.py' (AXIS top level) and 'extensions/<module>.py' (forward slash, no nesting).
 Names starting with 'test' are refused in both forms, so a candidate can never be named like a harness file."""
 refused='Bu çekirdek dosyası otomatik güncellemeye kapalı'
 scope=' (yalnızca AXIS üst düzey .py modülleri veya extensions/*.py)'
 if not isinstance(name,str):raise ValueError(refused+scope)
 m=_EXT_TARGET.fullmatch(name)
 if m:base=m.group(1)
 elif _MODULE_NAME.fullmatch(name):base=name
 else:raise ValueError(refused+scope)
 if base in PROTECTED or base.lower() in PROTECTED:raise ValueError(refused+' (korunan güvenlik dosyası)')
 if base.lower().startswith('test'):raise ValueError(refused+' (test dosyaları korunur)')
 root=ROOT.resolve()
 if m:
  folder=ROOT/EXTENSIONS;parent=root/EXTENSIONS
  if _is_link(folder) or (folder.exists() and (not folder.is_dir() or folder.resolve()!=parent)):raise ValueError(refused+' (extensions klasörü güvenli değil)')
  path=folder/base
 else:parent=root;path=ROOT/base
 if _is_link(path):raise ValueError(refused+' (sembolik bağlantı)')
 if path.resolve().parent!=parent:raise ValueError(refused+' (AXIS klasörü dışında)')
 return path
def is_extension(target):
 return isinstance(target,str) and _EXT_TARGET.fullmatch(target) is not None
def auto_eligible(target):
 """Only extensions/*.py may be applied without a human click; top-level modules are manual-only."""
 if not is_extension(target):return False
 try:safe_target(target);return True
 except ValueError:return False
def validate(code):
 if not isinstance(code,str) or not code.strip() or len(code)>100000:raise ValueError('Geçersiz kod')
 try:ast.parse(code)
 except SyntaxError as e:raise ValueError(f'Sözdizimi hatası: line {e.lineno}') from None
 return code
# Cheap first filter only, NOT a security boundary: e.g. `import io; io.open(...)` passes it.
CONTRACT_TEST = """import ast,pathlib,unittest
class Contract(unittest.TestCase):
 def test_ast_contract(self):
  files=list(pathlib.Path('/work').glob('*.py'))
  target=[p for p in files if not p.name.startswith('test_')][0]
  tree=ast.parse(target.read_text())
  forbidden={'eval','exec','compile','open','__import__','getattr','setattr','delattr','globals','locals'}
  forbidden_imports={'os','sys','subprocess','socket','ctypes','pickle','importlib','shutil','pathlib','urllib','requests'}
  for n in ast.walk(tree):
   if isinstance(n,(ast.Import,ast.ImportFrom)):
    names=([a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else [(n.module or '').split('.')[0]])
    self.assertFalse(set(names)&forbidden_imports)
   if isinstance(n,ast.Call) and isinstance(n.func,ast.Name):self.assertNotIn(n.func.id,forbidden)
   if isinstance(n,ast.Attribute):self.assertFalse(n.attr.startswith('__'))
  self.assertTrue(any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) for n in tree.body))
"""

def validate_behavior_cases(cases):
 """Only JSON literals, named top-level functions, and equality assertions are allowed.
 The bounded structural walk runs before json.dumps, so deep or huge data is refused without serialising it."""
 if not isinstance(cases,list) or not 1<=len(cases)<=30:raise ValueError('1-30 davranış testi gerekli')
 def literal(v,depth=0):
  if depth>6:raise ValueError('İç içe veri sınırı')
  if v is None or isinstance(v,(str,int,float,bool)):
   if isinstance(v,str) and len(v)>400:return False
   return True
  if isinstance(v,list):return len(v)<=30 and all(literal(x,depth+1) for x in v)
  if isinstance(v,dict):return len(v)<=30 and all(isinstance(k,str) and len(k)<=100 and literal(x,depth+1) for k,x in v.items())
  return False
 for case in cases:
  if not isinstance(case,dict) or set(case)!={'function','args','expected'}:raise ValueError('Test biçimi hatalı')
  name=case['function']
  if not isinstance(name,str) or not name.isidentifier() or name.startswith('_'):raise ValueError('Fonksiyon adı geçersiz')
  if not isinstance(case['args'],list) or len(case['args'])>12:raise ValueError('Argümanlar liste olmalı')
  if not literal(case['args']) or not literal(case['expected']):raise ValueError('JSON literal sınırı')
  if len(json.dumps(case,ensure_ascii=False))>3000:raise ValueError('Test çok büyük')
 return cases

def attach_behavior_cases(uid,cases):
 """Store independently inspectable behavior expectations before Docker verification."""
 with LOCK:
  r=detail(uid)
  if r['status']!='pending':raise ValueError('Yalnızca bekleyen öneriler test edilebilir')
  cases=validate_behavior_cases(cases)
  (TESTS/(uid+'.json')).write_text(json.dumps({'digest':r['digest'],'cases':cases},ensure_ascii=False,indent=2),encoding='utf-8')
  return {'id':uid,'case_count':len(cases),'cases':cases}

def behavior_cases(uid):

 with connection() as db:r=db.execute('SELECT digest FROM upgrades WHERE id=?',(uid,)).fetchone()
 if r is None:raise ValueError('Öneri bulunamadı')
 p=TESTS/(uid+'.json')
 if not p.exists():return {'id':uid,'cases':[]}
 data=json.loads(p.read_text(encoding='utf-8'))
 if data['digest']!=r['digest']:raise ValueError('Test edilen kod değişmiş')
 return {'id':uid,'cases':data['cases']}

# argv[1] is the completion marker path: written only after every assertion ran and passed.
BEHAVIOR_RUNNER = """import importlib.util,json,sys,unittest
from pathlib import Path
cases=json.loads(Path('/work/cases.json').read_text())
spec=importlib.util.spec_from_file_location('candidate','/work/CANDIDATE')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Behaviors(unittest.TestCase):
 def test_cases(self):
  for c in cases:
   with self.subTest(function=c['function'],args=c['args']):
    fn=getattr(module,c['function'])
    self.assertEqual(fn(*c['args']),c['expected'])
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Behaviors))
ok=result.wasSuccessful() and result.testsRun>0 and len(cases)>0
if ok and len(sys.argv)>1:Path(sys.argv[1]).write_text('ok')
sys.exit(0 if ok else 1)
"""
# Contract and suite stages: python -I -B -c STAGE_HARNESS <start> <top> <pattern> <marker>
STAGE_HARNESS = """import sys,unittest
from pathlib import Path
start,top,pattern,marker=sys.argv[1:5]
result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(start,pattern=pattern,top_level_dir=top))
ok=result.wasSuccessful() and result.testsRun>0
if ok:Path(marker).write_text('ok')
sys.exit(0 if ok else 1)
"""
# Container controller: python -I -c VERIFY_SCRIPT <behavior 0|1> <suite 0|1>, per-run nonces on stdin.
# Every stage runs in its own interpreter (stdin closed) and must exit 0 AND leave its random completion
# marker, which its harness writes only after the tests finished; only then does the controller print
# 'AXIS-STAGE-OK <stage> <nonce>'. The host requires that exact line for every stage that ran (scanned over
# the whole output stream) in addition to the exit-code bits (0 or 100+failed bits). This turns an
# accidental or trivial early exit (sys.exit(0), os._exit(0) at import) into FAIL. It does NOT prove anything
# against a deliberately hostile candidate: candidate code runs in the same container as the harness and can
# forge the marker. It is a regression gate for honest mistakes, not proof of safety.
VERIFY_SCRIPT = """import secrets,shutil,subprocess,sys
from pathlib import Path
behavior,suite=sys.argv[1]=='1',sys.argv[2]=='1'
nonce=dict(zip(('CONTRACT','BEHAVIOR','SUITE'),sys.stdin.readline().split()))
HARNESS="""+repr(STAGE_HARNESS)+"""
def stage(label,args,cwd):
 print('=== '+label,flush=True)
 marker=Path('/tmp/.done-'+secrets.token_hex(16))
 code=subprocess.run([sys.executable,'-I','-B']+args+[str(marker)],cwd=cwd,stdin=subprocess.DEVNULL).returncode
 ok=code==0 and marker.is_file() and marker.read_text()=='ok'
 marker.unlink(missing_ok=True)
 if ok:print('\\nAXIS-STAGE-OK '+label+' '+nonce.get(label,''),flush=True)
 return ok
bad=0
if not stage('CONTRACT',['-c',HARNESS,'/work','/work','test_contract.py'],'/tmp'):bad|=1
if behavior and not stage('BEHAVIOR',['/work/test_behavior.py'],'/tmp'):bad|=2
if suite:
 shutil.copytree('/work/src','/tmp/axis')
 if not stage('SUITE',['-c',HARNESS,'/tmp/axis','/tmp/axis','test*.py'],'/tmp/axis'):bad|=4
sys.exit(100+bad if bad else 0)
"""
_STAGE_BITS=(('CONTRACT',1),('BEHAVIOR',2),('SUITE',4))

def docker_available():
 try:
  p=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,encoding='utf-8',errors='replace',timeout=8)
  return p.returncode==0
 except (OSError,subprocess.TimeoutExpired):return False
def suite_enabled():
 return os.getenv('AXIS_VERIFY_SUITE','1').strip().lower() not in ('0','false','off')
def needs_host_program(source):
 """Suite exclusion rule: a test module that refers to shutil.which (node, docker, ... lookups) depends on a
 host program. python:3.12-slim ships only Python, so the WHOLE module is left out of the in-container suite
 and named in the report ('SUITE EXCLUDED: ...'). Deliberately coarse and visible; nothing else is skipped and
 no failure is ignored."""
 try:tree=ast.parse(source)
 except SyntaxError:return False  # keep it: a broken test file must fail the suite, not disappear
 for n in ast.walk(tree):
  if isinstance(n,ast.Attribute) and n.attr=='which' and isinstance(n.value,ast.Name) and n.value.id=='shutil':return True
  if isinstance(n,ast.ImportFrom) and n.module=='shutil' and any(a.name=='which' for a in n.names):return True
 return False
def _inside(p,base):
 """A real file/dir (no symlink, no junction) whose resolved path stays under the resolved base."""
 try:return not _is_link(p) and p.resolve().is_relative_to(base)
 except OSError:return False
def stage_sources(dest,target,raw):
 """Host-side copy of the AXIS sources with the candidate swapped in: top-level *.py, index.html, static/,
 extensions/*.py. Never databases, .venv, proposals, upgrades, backups, skills or __pycache__; no symlinks or
 junctions, and every copied path must resolve inside ROOT. Returns test modules excluded by needs_host_program()."""
 root=ROOT.resolve();dest=Path(dest);dest.mkdir()
 def plain(p,parent):return p.is_file() and _inside(p,root) and p.resolve().parent==parent
 for p in sorted(ROOT.iterdir()):
  if p.suffix=='.py' and _MODULE_NAME.fullmatch(p.name) and plain(p,root):shutil.copyfile(p,dest/p.name)
 if plain(ROOT/'index.html',root):shutil.copyfile(ROOT/'index.html',dest/'index.html')
 static=ROOT/'static'
 if static.is_dir() and _inside(static,root) and static.resolve()==root/'static':
  sroot=static.resolve()
  for base,dirs,files in os.walk(static):
   dirs[:]=sorted(d for d in dirs if d!='__pycache__' and _inside(Path(base)/d,sroot))
   out=dest/'static'/Path(base).relative_to(static);out.mkdir(parents=True,exist_ok=True)
   for f in files:
    s=Path(base)/f
    if s.is_file() and _inside(s,sroot):shutil.copyfile(s,out/f)
 ext=ROOT/EXTENSIONS
 if ext.is_dir() and _inside(ext,root) and ext.resolve()==root/EXTENSIONS:
  (dest/EXTENSIONS).mkdir()
  for p in sorted(ext.iterdir()):
   if p.suffix=='.py' and _MODULE_NAME.fullmatch(p.name) and not p.name.lower().startswith('test') and plain(p,root/EXTENSIONS):shutil.copyfile(p,dest/EXTENSIONS/p.name)
 # Path parts come from the validated Path object, never from the raw target string.
 candidate=dest.joinpath(*safe_target(target).relative_to(ROOT).parts)
 candidate.parent.mkdir(exist_ok=True);candidate.write_bytes(raw)
 excluded=[]
 for p in sorted(dest.glob('test*.py')):
  if needs_host_program(p.read_text(encoding='utf-8',errors='replace')):p.unlink();excluded.append(p.name)
 return excluded
def docker_command(name,src):
 return ['docker','run','--rm','--name',name,'-i','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','512m','--memory-swap','512m','--cpus','1','--user','65534:65534','--mount',f'type=bind,src={src},dst=/work,readonly','--tmpfs','/tmp:rw,noexec,nosuid,size=256m','python:3.12-slim','python','-I','-c',VERIFY_SCRIPT]
class OutputLimitExceeded(Exception):
 pass
def _container_run(cmd,input='',timeout=VERIFY_TIMEOUT,expect=()):
 """Run the container with stdout+stderr merged and read in chunks: only a small tail is kept, the whole stream
 is scanned for the expected sentinel lines, and the run is killed once OUTPUT_LIMIT bytes were read."""
 wanted={x.encode() for x in expect}
 st={'total':0,'tail':b'','line':b'','seen':set(),'over':False}
 proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 def reader():
  try:
   while True:
    chunk=proc.stdout.read1(65536)
    if not chunk:break
    st['total']+=len(chunk)
    if st['total']>OUTPUT_LIMIT:st['over']=True;proc.kill();break
    st['tail']=(st['tail']+chunk)[-_TAIL_BYTES:]
    parts=(st['line']+chunk).split(b'\n');st['line']=parts.pop()[-512:]
    for line in parts:
     if line.rstrip(b'\r') in wanted:st['seen'].add(line.rstrip(b'\r').decode())
  except (OSError,ValueError):pass
 t=threading.Thread(target=reader,daemon=True);t.start()
 try:
  try:proc.stdin.write(input.encode());proc.stdin.close()
  except OSError:pass  # the process may already be gone; the exit code tells
  proc.wait(timeout=timeout)
 except BaseException:
  proc.kill();proc.wait();raise
 finally:
  t.join(10)
  try:proc.stdout.close()
  except OSError:pass
 if st['line'].rstrip(b'\r') in wanted:st['seen'].add(st['line'].rstrip(b'\r').decode())
 if st['over']:raise OutputLimitExceeded()
 return SimpleNamespace(returncode=proc.returncode,stdout=st['tail'].decode('utf-8','replace'),stderr='',seen=frozenset(st['seen']))
def _stage_lines(ran,state):
 """state: one string for every stage that should have run (NOT RUN / ERROR ...), or a dict stage->PASS/FAIL."""
 out=[]
 for label,_ in _STAGE_BITS:
  if not ran[label]:out.append(label+': SKIPPED'+{'SUITE':' (AXIS_VERIFY_SUITE=0)','BEHAVIOR':' (davranış testi yok)'}.get(label,''))
  else:out.append(label+': '+(state[label] if isinstance(state,dict) else state))
 return out
def _report(head,stages,extra=(),tail=''):
 """Bounded report: first line + stage lines always survive; only the container output tail is cut."""
 header='\n'.join([head]+list(stages)+list(extra))
 room=REPORT_LIMIT-len(header)-1
 return header+('\n'+tail[-room:] if tail and room>0 else '')
def propose(target,code,description='',schedule=True):
 """schedule=False: the caller attaches behavior cases first and then calls schedule_auto(id) itself.
 Only extensions/*.py proposals are ever queued; top-level modules wait for a human decision."""
 safe_target(target);validate(code)
 uid=uuid.uuid4().hex;digest=hashlib.sha256(code.encode()).hexdigest()
 with LOCK:
  # Exact UTF-8 bytes: write_text would turn LF into CRLF on Windows and break the digest.
  (DATA/(uid+'.py')).write_bytes(code.encode())
  with connection() as db:db.execute('INSERT INTO upgrades VALUES (?,?,?,?,?,?,?,?)',(uid,target,str(description)[:500],digest,'pending','Henüz test edilmedi','',datetime.now(timezone.utc).isoformat()))
 result=detail(uid)
 result['auto_apply_queued']=schedule_auto(uid) if schedule else False  # background verify → decide() only when PASS
 return result
def detail(uid):
 with connection() as db:
  row=db.execute('SELECT * FROM upgrades WHERE id=?',(uid,)).fetchone()
 if not row:raise ValueError('Öneri bulunamadı')
 result=dict(row);staged=DATA/(uid+'.py');old=safe_target(row['target'])
 result['auto_eligible']=auto_eligible(row['target'])
 if staged.exists():
  result['behavior_cases']=behavior_cases(uid)['cases'] if (TESTS/(uid+'.json')).exists() else []
  result['diff']=''.join(difflib.unified_diff((old.read_text(encoding='utf-8') if old.exists() else '').splitlines(True),staged.read_text(encoding='utf-8').splitlines(True),fromfile='current/'+row['target'],tofile='proposed/'+row['target']))[:40000]
 return result
def listing():
 with connection() as db:return [dict(x) for x in db.execute('SELECT * FROM upgrades ORDER BY created DESC LIMIT 30')]
def verify(uid,_raw=None):
 """Docker: no network, read-only filesystem, dropped capabilities, resource and process limits; no host fallback.
 Stages: AST contract (cheap first filter, not a security boundary), behavior cases when attached, and the
 repository's own unittest suite against a copy of AXIS with the candidate swapped in (AXIS_VERIFY_SUITE=0
 disables only the suite). PASS needs, for every stage that ran, a zero failure bit AND its per-run completion
 sentinel. The container isolates the test only. _raw: bytes the caller already read and will apply.
 """
 with LOCK:
  r=detail(uid)
  if r['status']!='pending':raise ValueError('Öneri beklemede değil')
  cases=behavior_cases(uid)['cases'];suite=suite_enabled()
  ran={'CONTRACT':True,'BEHAVIOR':bool(cases),'SUITE':suite}
  def finish(passed,report):
   with connection() as db:db.execute('UPDATE upgrades SET report=? WHERE id=?',(report,uid))
   return {'passed':passed,'report':report}
  if not docker_available():
   return finish(False,_report('BLOCKED: Docker Engine bulunamadı; öneri çalıştırılmadı. Docker Desktop Linux containers gerekir.',_stage_lines(ran,'NOT RUN')))
  raw=(DATA/(uid+'.py')).read_bytes() if _raw is None else _raw
  if hashlib.sha256(raw).hexdigest()!=r['digest']:raise ValueError('Kod değişmiş')
  flat=safe_target(r['target']).name  # validated basename; the container never sees the raw target string
  # Windows: a lingering handle (AV scan, Docker file share) must not discard the recorded result.
  with tempfile.TemporaryDirectory(prefix='vector_test_',ignore_cleanup_errors=True) as tmp:
   p=Path(tmp);src=str(p.resolve())
   # Docker parses --mount as CSV key=value pairs; refuse paths that could add mount options.
   if any(ch in ',=' or ord(ch)<32 or 127<=ord(ch)<160 for ch in src):
    return finish(False,_report('FAIL: güvensiz bağlama yolu',_stage_lines(ran,'NOT RUN')))
   # Harness names start with 'test_' or are not .py; safe_target refuses 'test*' targets, so no clash.
   (p/flat).write_bytes(raw)
   (p/'test_contract.py').write_text(CONTRACT_TEST,encoding='utf-8')
   if cases:
    (p/'cases.json').write_text(json.dumps(cases),encoding='utf-8')
    (p/'test_behavior.py').write_text(BEHAVIOR_RUNNER.replace('CANDIDATE',flat),encoding='utf-8')
   extra=[]
   if suite:
    excluded=stage_sources(p/'src',r['target'],raw)
    if excluded:extra.append('SUITE EXCLUDED (shutil.which: host programı gerekir): '+', '.join(excluded))
   name=''.join(ch if ch.isalnum() and ch.isascii() or ch in '_.-' else '_' for ch in f'axis-verify-{uid[:12]}-{uuid.uuid4().hex[:8]}')
   cmd=docker_command(name,src)+['1' if cases else '0','1' if suite else '0']
   nonce={k:secrets.token_hex(16) for k,_ in _STAGE_BITS}
   sentinel={k:f'AXIS-STAGE-OK {k} {nonce[k]}' for k,_ in _STAGE_BITS}
   def remove_container(head):
    try:
     cleanup=subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=15)
     return head+('; konteyner kaldırıldı' if cleanup.returncode==0 else '; konteyner kaldırılamadı')
    except (OSError,subprocess.TimeoutExpired):
     return head+'; konteyner kaldırılamadı'
   try:
    proc=_container_run(cmd,input=' '.join(nonce[k] for k,_ in _STAGE_BITS)+'\n',timeout=VERIFY_TIMEOUT,expect=[sentinel[k] for k in ran if ran[k]])
    rc=proc.returncode;out=(proc.stdout or '')+('\n'+proc.stderr if proc.stderr else '')
    seen=set(proc.seen) if isinstance(getattr(proc,'seen',None),(set,frozenset)) else set()
    seen|={line.strip() for line in out.splitlines()}
    proof={k:sentinel[k] in seen for k,_ in _STAGE_BITS}
    if rc==0 or 101<=rc<=107:
     bits=rc-100 if rc else 0
     state={k:('FAIL' if bits&bit else 'PASS' if proof[k] else 'FAIL (tamamlanma kanıtı yok)') for k,bit in _STAGE_BITS}
    else:state=f'ERROR (konteyner çıkış kodu {rc})'
    passed=rc==0 and all(proof[k] for k in ran if ran[k])
    report=_report('PASS' if passed else 'FAIL',_stage_lines(ran,state),extra,out)
   except subprocess.TimeoutExpired:
    passed=False;report=_report(remove_container('FAIL: Docker test zaman aşımı'),_stage_lines(ran,'ERROR (zaman aşımı)'),extra)
   except OutputLimitExceeded:
    passed=False;report=_report(remove_container(f'FAIL: konteyner çıktısı {OUTPUT_LIMIT} bayt sınırını aştı'),_stage_lines(ran,'ERROR (çıktı sınırı)'),extra)
   except OSError as exc:passed=False;report=_report('FAIL: Docker çalıştırılamadı: '+type(exc).__name__,_stage_lines(ran,'NOT RUN'),extra)
  return finish(passed,report)
def _atomic_write(dest,data):
 """Write exactly `data`: exclusive temp file (mkstemp never reuses or follows an existing name) next to dest,
 fsync, then os.replace. Only the temp file this call created is ever removed."""
 fd,tmp=tempfile.mkstemp(dir=dest.parent,prefix='.'+dest.name+'.',suffix='.tmp')
 try:
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,dest)
 except BaseException:
  try:os.unlink(tmp)
  except OSError:pass
  raise
# Crash journal: the SQLite status change and the file change cannot be one transaction. Each apply/rollback
# writes DATA/journal/<id>.json (fsync) before touching the file and deletes it once the DB commit (or the
# in-process undo) finished. recover_interrupted() at start-up resolves leftovers; see its docstring.
def _journal(uid,entry):
 d=DATA/'journal';d.mkdir(exist_ok=True);p=d/(uid+'.json')
 with open(p,'w',encoding='utf-8') as f:json.dump(entry,f);f.flush();os.fsync(f.fileno())
 return p
def recover_interrupted():
 """Apply cut by a crash after the file replace but before the commit (status still 'pending', file has the
 new digest): restore the backup or remove the new file. Rollback cut the same way (status still 'applied',
 file already restored): record 'rolled_back'. Anything else only drops the journal. Unclear cases (e.g. the
 file was edited in between) keep their journal for a human and are not touched."""
 d=DATA/'journal'
 if not d.is_dir():return []
 fixed=[]
 with LOCK:
  for p in sorted(d.glob('*.json')):
   try:
    e=json.loads(p.read_text(encoding='utf-8'));uid=p.stem
    with connection() as db:row=db.execute('SELECT status,digest FROM upgrades WHERE id=?',(uid,)).fetchone()
    dest=safe_target(e['target'])
    cur=hashlib.sha256(dest.read_bytes()).hexdigest() if dest.exists() else None
    if row is not None and e['op']=='apply' and row['status']=='pending':
     if cur==row['digest']:  # file replaced, status never committed → back to the pre-change state
      if e['backup']:_atomic_write(dest,Path(e['backup']).read_bytes())
      else:dest.unlink()
      fixed.append(uid)
     elif cur!=e.get('previous'):continue  # edited since: leave for a human
    elif row is not None and e['op']=='rollback' and row['status']=='applied':
     if cur==e['restored'] and cur!=row['digest']:  # file restored, status never committed
      with connection() as db:db.execute('UPDATE upgrades SET status=? WHERE id=?',('rolled_back',uid))
      fixed.append(uid)
     elif cur!=row['digest']:continue
    p.unlink()
   except Exception:
    continue  # keep the journal; never guess
 return fixed
def decide(uid,action,confirmation=''):
 if action not in ('approve','reject'):raise ValueError('Geçersiz işlem')
 with LOCK:
  r=detail(uid)
  if r['status']!='pending':raise ValueError('Bekleyen öneri yok')
  if action=='reject':
   with connection() as db:db.execute('UPDATE upgrades SET status=? WHERE id=?',('rejected',uid))
   return {'status':'rejected'}
  if confirmation!='ONAYLIYORUM':raise ValueError('Açık onay gerekiyor')
  # One read: these exact bytes are digest-checked, container-tested and written; the staged file is never reopened for the copy.
  src=DATA/(uid+'.py');raw=src.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=r['digest']:raise ValueError('Kod değişmiş')
  # Must have a fresh, passing Docker verification in this operation; no bypass.
  test=verify(uid,_raw=raw)
  if not test['passed']:raise ValueError('İzole test başarılı değil: '+test['report'][:300])
  # A staged file touched during the test is treated as tampering, even though raw would be applied.
  if hashlib.sha256(src.read_bytes()).hexdigest()!=r['digest']:raise ValueError('Kod değişmiş')
  dest=safe_target(r['target'])
  if is_extension(r['target']) and not dest.parent.exists():
   dest.parent.mkdir();dest=safe_target(r['target'])  # re-validate the freshly created folder
  old=dest.read_bytes() if dest.exists() else None
  backup=''
  if old is not None:
   backup=str(DATA/(uid+'.backup'));Path(backup).unlink(missing_ok=True)
   with open(backup,'xb') as f:f.write(old);f.flush();os.fsync(f.fileno())
  journal=_journal(uid,{'op':'apply','target':r['target'],'backup':backup,'previous':hashlib.sha256(old).hexdigest() if old is not None else None})
  # The UPDATE runs first but is committed only after the atomic file replace; if the replace
  # fails the transaction rolls back, and if the commit fails the original file is restored.
  replaced=False
  try:
   with connection() as db:
    db.execute('UPDATE upgrades SET status=?,backup=? WHERE id=?',('applied',backup,uid))
    _atomic_write(dest,raw);replaced=True
  except BaseException:
   if replaced:
    if old is not None:_atomic_write(dest,old)
    else:dest.unlink(missing_ok=True)
   journal.unlink(missing_ok=True)
   raise
  journal.unlink(missing_ok=True)
  return {'status':'applied','restart_required':True,'backup':bool(backup)}
def rollback(uid,confirmation=''):
 if confirmation!='GERI_AL':raise ValueError('Geri alma onayı gerekiyor')
 with LOCK:
  r=detail(uid)
  if r['status']!='applied':raise ValueError('Geri alınabilir sürüm yok')
  dest=safe_target(r['target']);backup=Path(r['backup']) if r['backup'] else None
  if backup and not backup.exists():raise ValueError('Yedek bulunamadı')
  current=dest.read_bytes() if dest.exists() else None
  if current is None or hashlib.sha256(current).hexdigest()!=r['digest']:raise ValueError('Dosya sonradan değişmiş; geri alma başka değişiklikleri ezebilir')
  old=backup.read_bytes() if backup else None
  journal=_journal(uid,{'op':'rollback','target':r['target'],'restored':hashlib.sha256(old).hexdigest() if old is not None else None})
  # Same guarantee as decide(): commit only after the atomic file change, undo it (from memory) if the commit fails.
  changed=False
  try:
   with connection() as db:
    db.execute('UPDATE upgrades SET status=? WHERE id=?',('rolled_back',uid))
    if old is not None:_atomic_write(dest,old)
    else:dest.unlink()
    changed=True
  except BaseException:
   if changed:_atomic_write(dest,current)
   journal.unlink(missing_ok=True)
   raise
  journal.unlink(missing_ok=True)
  return {'status':'rolled_back','restart_required':True}

# ---------------- Automatic apply (user decision 2026-11-10, scope narrowed 2026-11-11) ----------------
# A pending upgrade is applied without a click ONLY when its target is extensions/*.py, and only through the
# normal decide() path, which re-runs a fresh Docker test, re-checks the digest and applies atomically.
# FAIL/BLOCKED leaves it pending. Top-level modules are manual-only. Kill switch: AXIS_AUTO_APPLY=0/false/off.
# AXIS does not import extensions/*.py by itself, so an applied extension is inert until a human wires it in.
SCHEDULER=None  # set by server.py at start-up: callable(uid) that queues auto_pipeline in the POOL
def auto_apply_enabled():
 return os.getenv('AXIS_AUTO_APPLY','1').strip().lower() not in ('0','false','off')
def _target_of(uid):
 with connection() as db:row=db.execute('SELECT target FROM upgrades WHERE id=?',(uid,)).fetchone()
 return row['target'] if row else None
def schedule_auto(uid):
 if SCHEDULER is None or not auto_apply_enabled() or not auto_eligible(_target_of(uid)):return False
 try:SCHEDULER(uid);return True
 except Exception:return False
def _audit(r,outcome,detail_text):
 summary=('Otomatik uygulandı: ' if outcome=='applied' else 'Otomatik uygulanmadı: ')+r['target']+' — '+(r.get('description') or '')[:300]
 with connection() as db:
  db.execute('INSERT INTO auto_events VALUES (?,?,?,?,?,?,?)',(uuid.uuid4().hex,r['id'],r['target'],(r.get('description') or '')[:500],outcome,str(detail_text)[:1000],datetime.now(timezone.utc).isoformat()))
 try:
  import central_brain
  central_brain.log('auto_upgrade','auto_apply' if outcome=='applied' else 'auto_not_applied','core_upgrade','success' if outcome=='applied' else 'failure',(summary+' · '+str(detail_text))[:1900],r['id'],{'target':r['target'],'outcome':outcome})
 except Exception:
  pass  # the auto_events row above is the authoritative audit record
 return summary
def auto_pipeline(uid):
 if not auto_apply_enabled():return {'id':uid,'outcome':'disabled'}
 r=detail(uid)
 if r['status']!='pending':return {'id':uid,'outcome':'skipped','status':r['status']}
 if not auto_eligible(r['target']):return {'id':uid,'outcome':'manual_only','status':r['status']}
 try:test=verify(uid)
 except ValueError as e:test={'passed':False,'report':'FAIL: '+str(e)}
 if not test['passed']:
  _audit(r,'not_applied','Test başarısız; öneri bekliyor, hiçbir şey uygulanmadı. '+test['report'][:300])
  return {'id':uid,'outcome':'not_applied','report':test['report']}
 if not auto_apply_enabled():return {'id':uid,'outcome':'disabled'}
 try:result=decide(uid,'approve','ONAYLIYORUM')  # fresh Docker test + digest check + atomic apply
 except Exception as e:
  _audit(r,'not_applied','Uygulama reddedildi: '+str(e)[:300])
  return {'id':uid,'outcome':'not_applied','error':str(e)[:300]}
 _audit(r,'applied','Docker testi PASS; yedek '+('alındı' if result.get('backup') else 'yok (yeni dosya)')+'; uzantı AXIS tarafından kendiliğinden içe aktarılmaz')
 return {'id':uid,'outcome':'applied','restart_required':True,'backup':result.get('backup')}
def sweep_untested():
 """Start-up hook: first resolve apply/rollback steps cut by a crash (recover_interrupted), then queue at most
 SWEEP_LIMIT pending, never-tested extensions/*.py proposals (oldest first); the rest wait for the next start."""
 try:recover_interrupted()
 except Exception:pass  # recovery problems must not block start-up; journals stay for inspection
 with connection() as db:
  rows=[(x['id'],x['target']) for x in db.execute("SELECT id,target FROM upgrades WHERE status='pending' AND report='Henüz test edilmedi' AND target LIKE 'extensions/%' ORDER BY created LIMIT ?",(SWEEP_LIMIT,))]
 return [uid for uid,target in rows if auto_eligible(target) and schedule_auto(uid)]
def auto_status(limit=20):
 with connection() as db:
  events=[dict(x) for x in db.execute('SELECT e.*,u.status AS upgrade_status FROM auto_events e LEFT JOIN upgrades u ON u.id=e.upgrade_id ORDER BY e.created DESC LIMIT ?',(max(1,min(int(limit),100)),))]
 return {'enabled':auto_apply_enabled(),'events':events,'protected':sorted(PROTECTED)+['test_*.py'],'auto_scope':AUTO_SCOPE,'manual_only':'*.py','suite_enabled':suite_enabled()}
