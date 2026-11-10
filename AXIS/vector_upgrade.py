"""Approval-gated, Docker-tested changes. Never execute generated code on the host."""
from axis_sqlite import ClosingConnection
import ast, difflib, hashlib, json, os, re, shutil, sqlite3, subprocess, tempfile, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'upgrades'; DATA.mkdir(exist_ok=True)
DB=DATA/'upgrades.sqlite3'; LOCK=threading.RLock()
TESTS=DATA/'behavior_specs'; TESTS.mkdir(exist_ok=True)
# Any top-level AXIS Python module may be upgraded EXCEPT the safety net itself: the update/test/rollback
# pipeline, the local-only model guard, the HTTP origin checks + approval endpoints, the SQLite factory,
# and every test file (an update must never be able to edit its own tests). Non-.py files (index.html
# holds the approval UI) and anything outside the AXIS top level are refused too.
PROTECTED=frozenset({'vector_upgrade.py','local_models.py','server.py','axis_sqlite.py'})
_MODULE_NAME=re.compile(r'[A-Za-z_][A-Za-z0-9_]*\.py')
def connection():
 c=sqlite3.connect(DB, factory=ClosingConnection,timeout=15);c.row_factory=sqlite3.Row
 try:
  c.execute('CREATE TABLE IF NOT EXISTS upgrades(id TEXT PRIMARY KEY, target TEXT, description TEXT, digest TEXT, status TEXT, report TEXT, backup TEXT, created TEXT)')
  c.execute('CREATE TABLE IF NOT EXISTS auto_events(id TEXT PRIMARY KEY, upgrade_id TEXT, target TEXT, description TEXT, outcome TEXT, detail TEXT, created TEXT)')
  c.commit()
 except BaseException:c.close();raise
 return c
def safe_target(name):
 refused='Bu çekirdek dosyası otomatik güncellemeye kapalı'
 if not isinstance(name,str) or not _MODULE_NAME.fullmatch(name):raise ValueError(refused+' (yalnızca AXIS üst düzey .py modülleri)')
 if name in PROTECTED or name.lower() in PROTECTED:raise ValueError(refused+' (korunan güvenlik dosyası)')
 if name.lower().startswith('test'):raise ValueError(refused+' (test dosyaları korunur)')
 root=ROOT.resolve();path=ROOT/name
 if path.is_symlink():raise ValueError(refused+' (sembolik bağlantı)')
 if path.resolve().parent!=root:raise ValueError(refused+' (AXIS klasörü dışında)')
 return path
def validate(code):
 if not isinstance(code,str) or not code.strip() or len(code)>100000:raise ValueError('Geçersiz kod')
 try:ast.parse(code)
 except SyntaxError as e:raise ValueError(f'Sözdizimi hatası: line {e.lineno}') from None
 return code
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
 """Only JSON literals, named top-level functions, and equality assertions are allowed."""
 if not isinstance(cases,list) or not 1<=len(cases)<=30:raise ValueError('1-30 davranış testi gerekli')
 for case in cases:
  if not isinstance(case,dict) or set(case)!={'function','args','expected'}:raise ValueError('Test biçimi hatalı')
  name=case['function']
  if not isinstance(name,str) or not name.isidentifier() or name.startswith('_'):raise ValueError('Fonksiyon adı geçersiz')
  if not isinstance(case['args'],list) or len(case['args'])>12:raise ValueError('Argümanlar liste olmalı')
  if len(json.dumps(case,ensure_ascii=False))>3000:raise ValueError('Test çok büyük')
  def literal(v,depth=0):
   if depth>6:raise ValueError('İç içe veri sınırı')
   if v is None or isinstance(v,(str,int,float,bool)):
    if isinstance(v,str) and len(v)>400:return False
    return True
   if isinstance(v,list):return len(v)<=30 and all(literal(x,depth+1) for x in v)
   if isinstance(v,dict):return len(v)<=30 and all(isinstance(k,str) and len(k)<=100 and literal(x,depth+1) for k,x in v.items())
   return False
  if not literal(case['args']) or not literal(case['expected']):raise ValueError('JSON literal sınırı')
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
sys.exit(0 if result.wasSuccessful() and len(cases)>0 else 1)
"""

def docker_available():
 try:
  p=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,encoding='utf-8',errors='replace',timeout=8)
  return p.returncode==0
 except (OSError,subprocess.TimeoutExpired):return False
def propose(target,code,description='',schedule=True):
 """schedule=False: the caller attaches behavior cases first and then calls schedule_auto(id) itself."""
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
 if staged.exists():
  result['behavior_cases']=behavior_cases(uid)['cases'] if (TESTS/(uid+'.json')).exists() else []
  result['diff']=''.join(difflib.unified_diff((old.read_text(encoding='utf-8') if old.exists() else '').splitlines(True),staged.read_text(encoding='utf-8').splitlines(True),fromfile='current/'+row['target'],tofile='proposed/'+row['target']))[:40000]
 return result
def listing():
 with connection() as db:return [dict(x) for x in db.execute('SELECT * FROM upgrades ORDER BY created DESC LIMIT 30')]
def verify(uid):
 """Docker: no network, read-only filesystem, dropped capabilities, resource and process limits.
 Only syntax and user-supplied isolated unittest tests run; no host fallback.
 """
 with LOCK:
  r=detail(uid)
  if r['status']!='pending':raise ValueError('Öneri beklemede değil')
  if not docker_available():
   report='BLOCKED: Docker Engine bulunamadı; öneri çalıştırılmadı. Docker Desktop Linux containers gerekir.'
   with connection() as db:db.execute('UPDATE upgrades SET report=? WHERE id=?',(report,uid))
   return {'passed':False,'report':report}
  staged=DATA/(uid+'.py');raw=staged.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=r['digest']:raise ValueError('Kod değişmiş')
  # Windows: a lingering handle (AV scan, Docker file share) must not discard the recorded result.
  with tempfile.TemporaryDirectory(prefix='vector_test_',ignore_cleanup_errors=True) as tmp:
   p=Path(tmp);src=str(p.resolve())
   # Docker parses --mount as CSV key=value pairs; refuse paths that could add mount options.
   if any(ch in ',=' or ord(ch)<32 or 127<=ord(ch)<160 for ch in src):
    report='FAIL: güvensiz bağlama yolu'
    with connection() as db:db.execute('UPDATE upgrades SET report=? WHERE id=?',(report,uid))
    return {'passed':False,'report':report}
   (p/r['target']).write_bytes(raw)
   (p/'test_contract.py').write_text(CONTRACT_TEST,encoding='utf-8')
   cases=behavior_cases(uid)['cases']
   if cases:
    (p/'cases.json').write_text(json.dumps(cases),encoding='utf-8')
    (p/'test_behavior.py').write_text(BEHAVIOR_RUNNER.replace('CANDIDATE',r['target']),encoding='utf-8')
   # Deterministic built-in behavior tests; never accept agent-written tests as proof of safety.
   script='import ast,pathlib,unittest; p=pathlib.Path("/work/'+r['target']+'"); tree=ast.parse(p.read_text()); assert len(tree.body)>0; print("SYNTAX_OK"); result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover("/work",pattern="test_*.py")); raise SystemExit(0 if result.wasSuccessful() and result.testsRun>0 else 1)'
   name=''.join(ch if ch.isalnum() and ch.isascii() or ch in '_.-' else '_' for ch in f'axis-verify-{uid[:12]}-{uuid.uuid4().hex[:8]}')
   cmd=['docker','run','--rm','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','512m','--memory-swap','512m','--cpus','1','--user','65534:65534','--mount',f'type=bind,src={src},dst=/work,readonly','--tmpfs','/tmp:rw,noexec,nosuid,size=32m','python:3.12-slim','python','-I','-c',script]
   try:
    # Container output is UTF-8; the Windows locale codec (e.g. cp1254) must not crash decoding.
    proc=subprocess.run(cmd,capture_output=True,encoding='utf-8',errors='replace',timeout=35)
    report=('PASS' if proc.returncode==0 else 'FAIL')+'\n'+(proc.stdout+'\n'+proc.stderr)[-4000:]
    passed=proc.returncode==0
   except subprocess.TimeoutExpired:
    passed=False;report='FAIL: Docker test zaman aşımı'
    try:
     cleanup=subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=15)
     report+='; konteyner kaldırıldı' if cleanup.returncode==0 else '; konteyner kaldırılamadı'
    except (OSError,subprocess.TimeoutExpired):
     report+='; konteyner kaldırılamadı'
   except OSError as exc:passed=False;report='FAIL: Docker çalıştırılamadı: '+type(exc).__name__
  with connection() as db:db.execute('UPDATE upgrades SET report=? WHERE id=?',(report,uid))
  return {'passed':passed,'report':report}
def _replace_from(src,dest,tag):
 """Atomic copy: write a sibling temp file, then os.replace onto dest."""
 temp=dest.with_name(dest.name+'.'+tag+'.tmp')
 try:shutil.copy2(src,temp);os.replace(temp,dest)
 finally:temp.unlink(missing_ok=True)
def decide(uid,action,confirmation=''):
 if action not in ('approve','reject'):raise ValueError('Geçersiz işlem')
 with LOCK:
  r=detail(uid)
  if r['status']!='pending':raise ValueError('Bekleyen öneri yok')
  if action=='reject':
   with connection() as db:db.execute('UPDATE upgrades SET status=? WHERE id=?',('rejected',uid))
   return {'status':'rejected'}
  if confirmation!='ONAYLIYORUM':raise ValueError('Açık onay gerekiyor')
  # Must have a fresh, passing Docker verification in this operation; no bypass.
  test=verify(uid)
  if not test['passed']:raise ValueError('İzole test başarılı değil: '+test['report'][:300])
  dest=safe_target(r['target']);src=DATA/(uid+'.py')
  if hashlib.sha256(src.read_bytes()).hexdigest()!=r['digest']:raise ValueError('Kod değişmiş')
  backup=''
  if dest.exists():
   backup=str(DATA/(uid+'.backup'))
   shutil.copy2(dest,backup)
  # The UPDATE runs first but is committed only after the atomic file replace; if the replace
  # fails the transaction rolls back, and if the commit fails the original file is restored.
  replaced=False
  try:
   with connection() as db:
    db.execute('UPDATE upgrades SET status=?,backup=? WHERE id=?',('applied',backup,uid))
    _replace_from(src,dest,uid);replaced=True
  except BaseException:
   if replaced:
    if backup:_replace_from(Path(backup),dest,uid+'.undo')
    else:dest.unlink(missing_ok=True)
   raise
  return {'status':'applied','restart_required':True,'backup':bool(backup)}
def rollback(uid,confirmation=''):
 if confirmation!='GERI_AL':raise ValueError('Geri alma onayı gerekiyor')
 with LOCK:
  r=detail(uid)
  if r['status']!='applied':raise ValueError('Geri alınabilir sürüm yok')
  dest=safe_target(r['target']);backup=Path(r['backup']) if r['backup'] else None
  if backup and not backup.exists():raise ValueError('Yedek bulunamadı')
  if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest()!=r['digest']:raise ValueError('Dosya sonradan değişmiş; geri alma başka değişiklikleri ezebilir')
  # Same guarantee as decide(): commit only after the atomic file change, undo it if the commit fails.
  undo=dest.with_name(dest.name+'.'+uid+'.undo');changed=False
  try:
   with connection() as db:
    db.execute('UPDATE upgrades SET status=? WHERE id=?',('rolled_back',uid))
    if backup:shutil.copy2(dest,undo);_replace_from(backup,dest,uid+'.rb')
    else:os.replace(dest,undo)
    changed=True
  except BaseException:
   if changed:os.replace(undo,dest)
   else:undo.unlink(missing_ok=True)
   raise
  undo.unlink(missing_ok=True)
  return {'status':'rolled_back','restart_required':True}

# ---------------- Automatic apply (user decision 2026-11-10) ----------------
# A pending upgrade is applied without a click ONLY through the normal decide() path, which re-runs a
# fresh Docker test, re-checks the digest and applies atomically. FAIL/BLOCKED leaves it pending.
# Kill switch: AXIS_AUTO_APPLY=0 / false / off.
SCHEDULER=None  # set by server.py at start-up: callable(uid) that queues auto_pipeline in the POOL
def auto_apply_enabled():
 return os.getenv('AXIS_AUTO_APPLY','1').strip().lower() not in ('0','false','off')
def schedule_auto(uid):
 if SCHEDULER is None or not auto_apply_enabled():return False
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
 _audit(r,'applied','Docker testi PASS; yedek '+('alındı' if result.get('backup') else 'yok (yeni dosya)')+'; yeniden başlatma gerekli')
 return {'id':uid,'outcome':'applied','restart_required':True,'backup':result.get('backup')}
def sweep_untested():
 """Queue every pending, never-tested proposal (e.g. created before auto-apply existed)."""
 with connection() as db:
  ids=[x['id'] for x in db.execute("SELECT id FROM upgrades WHERE status='pending' AND report='Henüz test edilmedi' ORDER BY created")]
 return [uid for uid in ids if schedule_auto(uid)]
def auto_status(limit=20):
 with connection() as db:
  events=[dict(x) for x in db.execute('SELECT e.*,u.status AS upgrade_status FROM auto_events e LEFT JOIN upgrades u ON u.id=e.upgrade_id ORDER BY e.created DESC LIMIT ?',(max(1,min(int(limit),100)),))]
 return {'enabled':auto_apply_enabled(),'events':events,'protected':sorted(PROTECTED)+['test_*.py']}
