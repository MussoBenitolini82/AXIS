"""V10 central experience log and evidence-gated reusable workflow learning.
No LLM weights are updated. Proposed skills never execute arbitrary code.
"""
from axis_sqlite import open_db
import json, os, sqlite3, threading, uuid
from datetime import datetime, timezone
from pathlib import Path

DB=Path(os.getenv('VECTOR_BRAIN_DB',str(Path(__file__).with_name('central_brain.sqlite3'))))
LOCK=threading.RLock()
ROLES={'research','planner','coder','reviewer','tester','visual','orchestrator','system','assistant','auto_upgrade'}
TOOLS={'research','synthesize','search_memory','count_nodes','list_recent_research','agent_scan','agent_run','graph','neural_view','pdf_ingest','local_llm','core_upgrade'}

def now():return datetime.now(timezone.utc).isoformat()
def _setup(db):
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS experiences(id TEXT PRIMARY KEY,task_id TEXT,agent TEXT,action TEXT,tool TEXT,status TEXT,summary TEXT,evidence TEXT,created TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS learned_skills(id TEXT PRIMARY KEY,name TEXT,steps TEXT,evidence_ids TEXT,status TEXT,created TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS relations(source TEXT,target TEXT,kind TEXT,PRIMARY KEY(source,target,kind))')
    db.commit()
def conn():return open_db(DB,_setup,timeout=15)

def log(agent,action,tool,status,summary,task_id=None,evidence=None):
    if agent not in ROLES:raise ValueError('Geçersiz ajan')
    if tool not in TOOLS:raise ValueError('Tanımsız araç')
    if status not in ('success','failure','partial'):raise ValueError('Geçersiz durum')
    if not isinstance(summary,str) or not summary.strip() or len(summary)>2000:raise ValueError('Özet 1-2000 karakter olmalı')
    if not isinstance(action,str) or not 1<=len(action)<=120:raise ValueError('Geçersiz eylem')
    eid=uuid.uuid4().hex
    with LOCK,conn() as db:
        db.execute('INSERT INTO experiences VALUES (?,?,?,?,?,?,?,?,?)',(eid,str(task_id or uuid.uuid4().hex)[:100],agent,action,tool,status,summary,json.dumps(evidence or {},ensure_ascii=False)[:4000],now()))
        db.commit()
    return {'id':eid,'status':status}

def experiences(limit=60):
    with conn() as db:return [dict(x) for x in db.execute('SELECT * FROM experiences ORDER BY created DESC LIMIT ?', (max(1,min(int(limit),200)),))]

def propose(name,steps,evidence_ids):
    if not isinstance(name,str) or not 3<=len(name)<=100:raise ValueError('Beceri adı 3-100 karakter olmalı')
    if not isinstance(steps,list) or not 2<=len(steps)<=12 or any(x not in TOOLS for x in steps):raise ValueError('2-12 kayıtlı araç adımı gerekli')
    if not isinstance(evidence_ids,list) or len(set(evidence_ids))<2:raise ValueError('En az iki farklı başarılı deneyim gerekli')
    ids=list(dict.fromkeys(evidence_ids))
    with LOCK,conn() as db:
        rows=db.execute('SELECT id,tool,status FROM experiences WHERE id IN ('+','.join('?'*len(ids))+')',ids).fetchall()
        if len(rows)!=len(ids) or any(x['status']!='success' for x in rows):raise ValueError('Kanıtların tümü başarılı kayıt olmalı')
        observed={x['tool'] for x in rows}
        if not set(steps).issubset(observed):raise ValueError('Beceri adımlarının her biri başarılı deneyimle desteklenmeli')
        sid=uuid.uuid4().hex
        db.execute('INSERT INTO learned_skills VALUES (?,?,?,?,?,?)',(sid,name,json.dumps(steps),json.dumps(ids),'pending',now()))
        for eid in ids:db.execute('INSERT OR IGNORE INTO relations VALUES (?,?,?)',(eid,sid,'supports'))
        db.commit()
    return detail(sid)

def discover():
    """Conservative suggestion: repeated successful tools form a candidate, never auto-approved."""
    with conn() as db:
        rows=db.execute("SELECT tool,COUNT(*) n FROM experiences WHERE status='success' GROUP BY tool HAVING n>=2 ORDER BY n DESC").fetchall()
        return [{'tool':x['tool'],'successful_experiences':x['n'],'suggestion':'Bu araç için tekrar kullanılabilir beceri tasarlanabilir'} for x in rows]

def detail(sid):
    with conn() as db:r=db.execute('SELECT * FROM learned_skills WHERE id=?',(sid,)).fetchone()
    if not r:raise ValueError('Beceri bulunamadı')
    out=dict(r);out['steps']=json.loads(out['steps']);out['evidence_ids']=json.loads(out['evidence_ids']);return out

def skills():
    with conn() as db:ids=[x[0] for x in db.execute('SELECT id FROM learned_skills ORDER BY created DESC LIMIT 100')]
    return [detail(x) for x in ids]

def decide(sid,action,confirmation=''):
    if action not in ('approve','reject'):raise ValueError('Geçersiz karar')
    if action=='approve' and confirmation!='ONAYLIYORUM':raise ValueError('Açık onay gerekli')
    with LOCK,conn() as db:
        r=db.execute('SELECT status FROM learned_skills WHERE id=?',(sid,)).fetchone()
        if not r or r['status']!='pending':raise ValueError('Bekleyen beceri bulunamadı')
        db.execute('UPDATE learned_skills SET status=? WHERE id=?',('approved' if action=='approve' else 'rejected',sid));db.commit()
    return detail(sid)

def graph():
    with conn() as db:
        nodes=[{'id':'experience:'+r['id'],'label':r['agent']+': '+r['tool'],'kind':'experience','description':r['summary']} for r in db.execute('SELECT * FROM experiences ORDER BY created DESC LIMIT 250')]
        nodes += [{'id':'skill:'+r['id'],'label':r['name'],'kind':'skill','description':r['status']} for r in db.execute('SELECT * FROM learned_skills ORDER BY created DESC LIMIT 100')]
        edges=[{'source':'experience:'+r['source'],'target':'skill:'+r['target'],'relation':r['kind']} for r in db.execute('SELECT * FROM relations')]
    ids={x['id'] for x in nodes};return {'nodes':nodes,'edges':[x for x in edges if x['source'] in ids and x['target'] in ids]}
