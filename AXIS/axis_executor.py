"""AXIS V11: approved read-only workflow executor. No eval, shell, arbitrary Python or network writes."""
import json, sqlite3, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
import central_brain as brain

DB=Path(__file__).with_name('axis_runs.sqlite3')
LOCK=threading.RLock()
SAFE_TOOLS={'count_nodes','list_recent_research','search_memory'}

def _conn():
    db=sqlite3.connect(DB,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, skill_id TEXT, status TEXT, args TEXT, results TEXT, created TEXT)')
    db.commit()
    return db

def history(limit=50):
    with _conn() as db:
        return [dict(x) for x in db.execute('SELECT * FROM runs ORDER BY rowid DESC LIMIT ?', (max(1,min(int(limit),100)),))]

def execute(skill_id,args):
    if not isinstance(args,dict): raise ValueError('args nesne olmalı')
    if len(json.dumps(args,ensure_ascii=False))>5000:raise ValueError('Parametreler çok büyük')
    skill=brain.detail(skill_id)
    if skill['status']!='approved':raise ValueError('Yalnızca onaylı beceriler çalıştırılır')
    steps=skill['steps']
    if not steps or len(steps)>12 or any(x not in SAFE_TOOLS for x in steps):
        raise ValueError('Beceri güvenli salt-okunur araç listesine uygun değil')
    # The catalog is trusted only for these known read-only functions.
    import vector_intelligence as vi
    run_id=uuid.uuid4().hex
    results=[]
    status='success'
    for i,tool in enumerate(steps):
        try:
            params=args.get(tool,{})
            if not isinstance(params,dict):raise ValueError('Araç parametreleri nesne olmalı')
            if tool=='search_memory' and (not isinstance(params.get('query',''),str) or len(params.get('query',''))>80):
                raise ValueError('Arama metni geçersiz')
            output=vi.TOOLS[tool](params)
            results.append({'step':i+1,'tool':tool,'status':'success','output':output})
            brain.log('orchestrator','skill_step',tool,'success',f'{skill["name"]}: {tool} başarılı',run_id,{'skill_id':skill_id})
        except Exception as exc:
            status='failure'
            results.append({'step':i+1,'tool':tool,'status':'failure','error':str(exc)[:300]})
            brain.log('orchestrator','skill_step',tool,'failure',f'{skill["name"]}: {tool} başarısız',run_id,{'skill_id':skill_id})
            break
    record={'id':run_id,'skill_id':skill_id,'status':status,'args':json.dumps(args,ensure_ascii=False),'results':json.dumps(results,ensure_ascii=False),'created':datetime.now(timezone.utc).isoformat()}
    with LOCK,_conn() as db:
        db.execute('INSERT INTO runs VALUES (:id,:skill_id,:status,:args,:results,:created)',record)
        db.commit()
    return {'run_id':run_id,'skill_id':skill_id,'status':status,'steps':results}