"""AXIS V12: event-based shared memory, deterministic recovery, skill composition.
All automatic execution restricted to explicitly allowlisted read-only tools.
"""
from axis_sqlite import ClosingConnection
import json, sqlite3, threading, uuid
from pathlib import Path
from datetime import datetime, timezone
import central_brain as brain
import axis_executor as executor

DB=Path(__file__).with_name('axis_learning.sqlite3')
LOCK=threading.RLock()
ALLOWED=frozenset(executor.SAFE_TOOLS)

def connect():
    db=sqlite3.connect(DB, factory=ClosingConnection,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, task_id TEXT, agent TEXT, kind TEXT, tool TEXT, outcome TEXT, payload TEXT, created TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id)')
    db.execute('CREATE TABLE IF NOT EXISTS lessons (id TEXT PRIMARY KEY, signature TEXT UNIQUE, lesson TEXT, evidence TEXT, created TEXT)')
    db.commit()
    return db

def record(task_id,agent,kind,tool,outcome,payload=None):
    if not all(isinstance(v,str) and 0<len(v)<=120 for v in (task_id,agent,kind,tool)):
        raise ValueError('Geçersiz olay alanı')
    if outcome not in ('success','failure','partial'):raise ValueError('Geçersiz sonuç')
    raw=json.dumps(payload or {},ensure_ascii=False)
    if len(raw)>12000:raise ValueError('Olay çok büyük')
    event={'id':uuid.uuid4().hex,'task_id':task_id,'agent':agent,'kind':kind,'tool':tool,'outcome':outcome,'payload':raw,'created':datetime.now(timezone.utc).isoformat()}
    with LOCK,connect() as db:
        db.execute('INSERT INTO events VALUES (:id,:task_id,:agent,:kind,:tool,:outcome,:payload,:created)',event)
        db.commit()
    return event['id']

def events(task_id=None,limit=100):
    with connect() as db:
        if task_id:
            rows=db.execute('SELECT * FROM events WHERE task_id=? ORDER BY rowid DESC LIMIT ?',(task_id,min(200,max(1,int(limit)))))
        else:rows=db.execute('SELECT * FROM events ORDER BY rowid DESC LIMIT ?',(min(200,max(1,int(limit))),))
        return [dict(r) for r in rows]

def lessons():
    with connect() as db:return [dict(x) for x in db.execute('SELECT * FROM lessons ORDER BY rowid DESC LIMIT 100')]

def learn():
    """Promote repeatable evidence to a lesson; not an LLM weight update."""
    created=[]
    with LOCK,connect() as db:
        grouped=db.execute("SELECT tool,kind,outcome,COUNT(*) n FROM events GROUP BY tool,kind,outcome HAVING n>=2").fetchall()
        for r in grouped:
            sig='|'.join((r['tool'],r['kind'],r['outcome']))
            ids=[x['id'] for x in db.execute('SELECT id FROM events WHERE tool=? AND kind=? AND outcome=? ORDER BY rowid DESC LIMIT 10',(r['tool'],r['kind'],r['outcome']))]
            lesson=('Başarılı örüntü; yeniden kullanmadan önce bağlamı doğrula' if r['outcome']=='success' else 'Tekrarlanan sorun; araç girdilerini ve bağımlılıkları kontrol et')
            lid=uuid.uuid4().hex
            cur=db.execute('INSERT OR IGNORE INTO lessons VALUES (?,?,?,?,?)',(lid,sig,lesson,json.dumps(ids),datetime.now(timezone.utc).isoformat()))
            if cur.rowcount:created.append({'id':lid,'signature':sig,'evidence_ids':ids})
        db.commit()
    return created

def compose(name,skill_ids):
    """Compose only previously approved read-only skills; resulting skill requires fresh approval."""
    if not isinstance(skill_ids,list) or not 2<=len(skill_ids)<=5 or len(set(skill_ids))!=len(skill_ids):
        raise ValueError('2-5 farklı beceri gerekli')
    parts=[brain.detail(sid) for sid in skill_ids]
    if any(x['status']!='approved' for x in parts):raise ValueError('Bütün kaynak beceriler onaylı olmalı')
    steps=[step for part in parts for step in part['steps']]
    if not steps or len(steps)>12 or any(x not in ALLOWED for x in steps):raise ValueError('Güvenli yürütme sınırı aşıldı')
    evidence=list(dict.fromkeys(e for part in parts for e in part['evidence_ids']))
    proposal=brain.propose(name,steps,evidence)
    record(proposal['id'],'orchestrator','skill_composition','skill_catalog','success',{'parents':skill_ids,'steps':steps})
    return proposal

def run_with_recovery(skill_id,args,max_attempts=2):
    """Bounded retry; only retry read-only tools and never auto-approve a change."""
    if type(max_attempts) is not int or not 1<=max_attempts<=2:raise ValueError('En fazla iki deneme')
    task=uuid.uuid4().hex
    attempts=[]
    for i in range(max_attempts):
        try:
            result=executor.execute(skill_id,args)
            status=result['status']
            record(task,'orchestrator','skill_execution','skill_executor',status,{'attempt':i+1,'run_id':result['run_id']})
            attempts.append(result)
            if status=='success':break
        except (ValueError,KeyError) as exc:
            record(task,'orchestrator','skill_execution','skill_executor','failure',{'attempt':i+1,'error':str(exc)[:300]})
            raise
    return {'task_id':task,'status':attempts[-1]['status'],'attempts':attempts,'lessons_added':learn()}
