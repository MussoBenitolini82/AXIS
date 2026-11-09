"""Approval-gated local skill changes. No arbitrary execution or core self-editing."""
import ast, difflib, hashlib, json, os, py_compile, shutil, sqlite3, tempfile, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SKILLS=ROOT/'skills'
PENDING=ROOT/'proposals'
BACKUPS=ROOT/'backups'
for d in (SKILLS,PENDING,BACKUPS): d.mkdir(exist_ok=True)
LOCK=threading.RLock()
DB=ROOT/'evolution.db'
def db():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, skill TEXT, status TEXT, created TEXT, sha256 TEXT, summary TEXT, test_result TEXT)');c.commit();return c
def valid_name(name):
 if not isinstance(name,str) or not (1<=len(name)<=64) or not name.isidentifier() or name.startswith('_'):raise ValueError('Geçersiz beceri adı')
 return name
# This is a syntax-and-policy check, not a secure sandbox. Proposed code is NEVER executed automatically.
BLOCKED={'subprocess','socket','ctypes','multiprocessing','winreg','pickle','marshal','importlib','os','sys','shutil','pathlib','requests','urllib','http','builtins'}
BLOCKED_CALLS={'eval','exec','compile','open','__import__','input','breakpoint'}
def check(code):
 if not isinstance(code,str) or not code.strip() or len(code)>30000:raise ValueError('Kod boş veya çok büyük')
 tree=ast.parse(code)
 for node in ast.walk(tree):
  if isinstance(node,(ast.Import,ast.ImportFrom)):
   names=([a.name.split('.')[0] for a in node.names] if isinstance(node,ast.Import) else [(node.module or '').split('.')[0]])
   if any(n in BLOCKED for n in names):raise ValueError('Engellenen modül kullanımı: '+str(names))
  if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in BLOCKED_CALLS:raise ValueError('Engellenen fonksiyon: '+node.func.id)
  if isinstance(node,ast.Attribute) and node.attr.startswith('__'):raise ValueError('Dunder erişimi engellendi')
 return 'Sözdizimi ve temel kural kontrolü başarılı; güvenli olduğu kanıtlanmadı. Kod çalıştırılmadı.'
def propose(skill,code,summary):
 skill=valid_name(skill);test=check(code)
 pid=uuid.uuid4().hex;digest=hashlib.sha256(code.encode()).hexdigest()
 with LOCK:
  (PENDING/(pid+'.py')).write_text(code,encoding='utf-8')
  with db() as c:c.execute('INSERT INTO proposals VALUES (?,?,?,?,?,?,?)',(pid,skill,'pending',datetime.now(timezone.utc).isoformat(),digest,str(summary)[:300],test))
 return {'id':pid,'skill':skill,'status':'pending','sha256':digest,'test_result':test,'diff':diff(skill,code)}
def diff(skill,code):
 old=(SKILLS/(skill+'.py')).read_text(encoding='utf-8') if (SKILLS/(skill+'.py')).exists() else ''
 return ''.join(difflib.unified_diff(old.splitlines(True),code.splitlines(True),fromfile='current/'+skill+'.py',tofile='proposed/'+skill+'.py'))[:20000]
def list_proposals():
 with LOCK,db() as c:return [dict(r) for r in c.execute('SELECT * FROM proposals ORDER BY created DESC LIMIT 50')]
def detail(pid):
 with LOCK,db() as c:
  r=c.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
  if not r:raise ValueError('Öneri bulunamadı')
  r=dict(r);f=PENDING/(pid+'.py')
  if f.exists():r['diff']=diff(r['skill'],f.read_text(encoding='utf-8'))
  return r
def decide(pid,action,confirmation):
 if action not in ('approve','reject'):raise ValueError('Geçersiz karar')
 if confirmation!='ONAYLIYORUM' and action=='approve':raise ValueError('Açık onay gerekiyor')
 with LOCK,db() as c:
  r=c.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
  if not r or r['status']!='pending':raise ValueError('Bekleyen öneri bulunamadı')
  staged=PENDING/(pid+'.py');code=staged.read_text(encoding='utf-8')
  if hashlib.sha256(code.encode()).hexdigest()!=r['sha256']:raise ValueError('Öneri değişmiş')
  if action=='approve':
   check(code)
   target=SKILLS/(r['skill']+'.py')
   if target.exists():shutil.copy2(target,BACKUPS/(pid+'_'+r['skill']+'.py'))
   tmp=SKILLS/(pid+'.tmp');tmp.write_text(code,encoding='utf-8')
   try:
    ast.parse(tmp.read_text(encoding='utf-8'));os.replace(tmp,target)
   finally:tmp.unlink(missing_ok=True)
  c.execute('UPDATE proposals SET status=? WHERE id=?',('approved' if action=='approve' else 'rejected',pid))
  staged.unlink(missing_ok=True)
  return {'id':pid,'status':'approved' if action=='approve' else 'rejected','note':'Beceri dosyası kaydedildi; otomatik çalıştırılmadı.'}