"""Approval-gated, Docker-tested changes. Never execute generated code on the host."""
import ast, difflib, hashlib, json, os, shutil, sqlite3, subprocess, tempfile, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'upgrades'; DATA.mkdir(exist_ok=True)
DB=DATA/'upgrades.sqlite3'; LOCK=threading.RLock()
TESTS=DATA/'behavior_specs'; TESTS.mkdir(exist_ok=True)
# Only opt-in, narrowly scoped Python modules. server.py and approval/security code excluded.
ALLOWED={'research_extensions.py','skills_helpers.py'}
def connection():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS upgrades(id TEXT PRIMARY KEY, target TEXT, description TEXT, digest TEXT, status TEXT, report TEXT, backup TEXT, created TEXT)');c.commit();return c
def safe_target(name):
 if name not in ALLOWED:raise ValueError('Bu çekirdek dosyası otomatik güncellemeye kapalı')
 return ROOT/name
def validate(code):
 if not isinstance(code,str) or not code.strip() or len(code)>100000:raise ValueError('Geçersiz kod')
 ast.parse(code)
 return code
CONTRACT_TEST = """import ast,pathlib,unittest
class Contract(unittest.TestCase):
 def test_ast_contract(self):
  files=list(pathlib.Path('/work').glob('*.py'))
  target=[p for p in files if p.name!='test_contract.py'][0]
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
  p=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True,timeout=8)
  return p.returncode==0
 except (OSError,subprocess.TimeoutExpired):return False
def propose(target,code,description=''):
 safe_target(target);validate(code)
 uid=uuid.uuid4().hex;digest=hashlib.sha256(code.encode()).hexdigest()
 with LOCK:
  (DATA/(uid+'.py')).write_text(code,encoding='utf-8')
  with connection() as db:db.execute('INSERT INTO upgrades VALUES (?,?,?,?,?,?,?,?)',(uid,target,str(description)[:500],digest,'pending','Henüz test edilmedi','',datetime.now(timezone.utc).isoformat()))
 return detail(uid)
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
  staged=DATA/(uid+'.py');code=staged.read_text(encoding='utf-8')
  if hashlib.sha256(code.encode()).hexdigest()!=r['digest']:raise ValueError('Kod değişmiş')
  with tempfile.TemporaryDirectory(prefix='vector_test_') as tmp:
   p=Path(tmp);(p/r['target']).write_text(code,encoding='utf-8')
   (p/'test_contract.py').write_text(CONTRACT_TEST,encoding='utf-8')
   cases=behavior_cases(uid)['cases']
   if cases:
    (p/'cases.json').write_text(json.dumps(cases),encoding='utf-8')
    (p/'test_behavior.py').write_text(BEHAVIOR_RUNNER.replace('CANDIDATE',r['target']),encoding='utf-8')
   # Deterministic built-in behavior tests; never accept agent-written tests as proof of safety.
   script='import ast,pathlib,unittest; p=pathlib.Path("/work/'+r['target']+'"); tree=ast.parse(p.read_text()); assert len(tree.body)>0; print("SYNTAX_OK"); result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover("/work",pattern="test_*.py")); raise SystemExit(0 if result.wasSuccessful() and result.testsRun>0 else 1)'
   cmd=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','512m','--cpus','1','--user','65534:65534','--mount',f'type=bind,src={p.resolve()},dst=/work,readonly','--tmpfs','/tmp:rw,noexec,nosuid,size=32m','python:3.12-slim','python','-I','-c',script]
   try:
    proc=subprocess.run(cmd,capture_output=True,text=True,timeout=35)
    report=('PASS' if proc.returncode==0 else 'FAIL')+'\n'+(proc.stdout+'\n'+proc.stderr)[-4000:]
    passed=proc.returncode==0
   except subprocess.TimeoutExpired:passed=False;report='FAIL: Docker test zaman aşımı'
  with connection() as db:db.execute('UPDATE upgrades SET report=? WHERE id=?',(report,uid))
  return {'passed':passed,'report':report}
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
  temp=dest.with_name(dest.name+'.'+uid+'.tmp')
  try:
   shutil.copy2(src,temp);os.replace(temp,dest)
   with connection() as db:db.execute('UPDATE upgrades SET status=?,backup=? WHERE id=?',('applied',backup,uid))
  finally:temp.unlink(missing_ok=True)
  return {'status':'applied','restart_required':True,'backup':bool(backup)}
def rollback(uid,confirmation=''):
 if confirmation!='GERI_AL':raise ValueError('Geri alma onayı gerekiyor')
 with LOCK:
  r=detail(uid)
  if r['status']!='applied':raise ValueError('Geri alınabilir sürüm yok')
  dest=safe_target(r['target']);backup=Path(r['backup']) if r['backup'] else None
  if backup and not backup.exists():raise ValueError('Yedek bulunamadı')
  if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest()!=r['digest']:raise ValueError('Dosya sonradan değişmiş; geri alma başka değişiklikleri ezebilir')
  if backup:shutil.copy2(backup,dest)
  else:dest.unlink(missing_ok=True)
  with connection() as db:db.execute('UPDATE upgrades SET status=? WHERE id=?',('rolled_back',uid))
  return {'status':'rolled_back','restart_required':True}