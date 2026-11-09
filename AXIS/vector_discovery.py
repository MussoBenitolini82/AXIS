"""V9: capability audit, explicit agent proposals, parallel read-only agent tasks.
No remote code/model installation and no arbitrary tool execution.
"""
from axis_sqlite import ClosingConnection
import json, os, sqlite3, threading, uuid, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent
DB=ROOT/'discovered_agents.sqlite3'
LOCK=threading.RLock()
BUILTINS={
 'literature':('Literatür araştırmacısı','Akademik kaynak taraması ve kaynak analizi'),
 'memory':('Bilgi grafiği analisti','Kayıtlı kavramlar ve ilişkiler'),
 'coding':('Kod geliştirme ajanı','Python modülü önerisi ve test planı'),
 'review':('Kod inceleme ajanı','Kod riskleri ve kalite incelemesi'),
 'testing':('Test tasarım ajanı','Davranış testi örnekleri'),
 'neural':('Sinir ağı analisti','PyTorch örnek ağını inceleme'),
}
KEYWORDS={
 'literature':('araştır','literatür','makale','kaynak','research','paper'),
 'memory':('hafıza','bilgi','ilişki','graph','memory'),
 'coding':('kod','program','uygulama','geliştir','yazılım','script'),
 'review':('incele','güvenlik','denetle','review'),
 'testing':('test','doğrula','hata','debug'),
 'neural':('sinir','nöron','model','eğit','neural'),
 'vision':('görsel','resim','fotoğraf','kamera','image','vision'),
 'audio':('ses','konuşma tanıma','mikrofon','audio','speech'),
 'browser':('tarayıcı','web sitesi','browser','otomasyon'),
}
CANDIDATES={
 'vision':('Görsel analiz uzmanı','Görsel içeriği analiz etme','Yerel görsel model ve izinli dosya erişimi gerekir'),
 'audio':('Ses işleme uzmanı','Konuşma tanıma ve ses üretme','Ses modeli ve mikrofon izni gerekir'),
 'browser':('Tarayıcı otomasyon uzmanı','Web arayüzü üzerinde kontrollü işlem','Tarayıcı aracı ve her yazma işlemi için kullanıcı onayı gerekir'),
}
def conn():
 db=sqlite3.connect(DB, factory=ClosingConnection,timeout=15);db.row_factory=sqlite3.Row
 db.execute('CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,capability TEXT UNIQUE,name TEXT,description TEXT,requirements TEXT,status TEXT,created TEXT)')
 db.execute('CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,request TEXT,report TEXT,created TEXT)')
 db.commit();return db
def now():return datetime.now(timezone.utc).isoformat()
def installed():
 with conn() as db: return [dict(r) for r in db.execute("SELECT * FROM agents WHERE status='approved'")]
def scan(request):
 if not isinstance(request,str) or not 4<=len(request.strip())<=1500:raise ValueError('Görev 4-1500 karakter olmalı')
 s=request.casefold(); matched=[k for k,terms in KEYWORDS.items() if any(x in s for x in terms)]
 if not matched:matched=['memory']
 active={x['capability'] for x in installed()}
 available=[{'capability':k,'name':BUILTINS[k][0],'origin':'built_in'} for k in matched if k in BUILTINS]
 available +=[{'capability':k,'name':CANDIDATES[k][0],'origin':'approved_custom'} for k in matched if k in active and k in CANDIDATES]
 missing=[k for k in matched if k not in BUILTINS and k not in active]
 suggestions=[]
 with LOCK,conn() as db:
  for cap in missing:
   name,desc,req=CANDIDATES[cap]
   existing=db.execute('SELECT * FROM agents WHERE capability=?',(cap,)).fetchone()
   if existing and existing['status']=='rejected':continue
   if existing: aid=existing['id']
   else:
    aid=uuid.uuid4().hex
    db.execute('INSERT INTO agents VALUES (?,?,?,?,?,?,?)',(aid,cap,name,desc,req,'pending',now()))
   suggestions.append({'id':aid,'capability':cap,'name':name,'requirements':req,'status':'pending'})
  result={'request':request,'matched':matched,'available':available,'missing':missing,'proposals':suggestions,'note':'Tarama yerel beceri kataloğunu analiz eder; internette model araması veya indirmesi yapmaz. Onay sadece rolü kaydeder, entegrasyonu otomatik kurmaz.'}
  db.execute('INSERT INTO scans VALUES (?,?,?,?)',(uuid.uuid4().hex,request,json.dumps(result,ensure_ascii=False),now()))
  db.commit()
 return result
def listing():
 with conn() as db:return [dict(x) for x in db.execute('SELECT * FROM agents ORDER BY created DESC')]
def decision(aid,action,confirmation=''):
 if action not in ('approve','reject'):raise ValueError('Geçersiz karar')
 if action=='approve' and confirmation!='ONAYLIYORUM':raise ValueError('Açık onay gerekli')
 with LOCK,conn() as db:
  row=db.execute('SELECT * FROM agents WHERE id=?',(aid,)).fetchone()
  if not row or row['status']!='pending':raise ValueError('Bekleyen ajan önerisi bulunamadı')
  status='approved' if action=='approve' else 'rejected'
  db.execute('UPDATE agents SET status=? WHERE id=?',(status,aid));db.commit()
  return {'id':aid,'status':status,'note':'Ajan rolü kaydedildi; dış model veya kod kurulmadı.'}
def health():
 import importlib.util
 def module(name):return importlib.util.find_spec(name) is not None
 ollama=False
 try:
  with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=1.5) as r:ollama=r.status==200
 except Exception:pass
 return {'ollama_reachable':ollama,'torch_installed':module('torch'),'pypdf_installed':module('pypdf'),'docker_check':'Docker kontrolü yalnızca güncelleme testi sırasında yapılır','builtin_agents':list(BUILTINS),'approved_agents':[a['capability'] for a in installed()]}
def parallel_readonly(request):
 """Run only the existing safe read-only tools concurrently, never untrusted generated code."""
 result=scan(request)
 import vector_intelligence as vi
 tasks=[{'tool':'count_nodes'},{'tool':'list_recent_research'}]
 if 'memory' in result['matched']:tasks.append({'tool':'search_memory','args':{'query':request[:100]}})
 # Existing tool runner owns its own tool allowlist.
 return {'scan':result,'tools':vi.run_parallel(tasks)}
