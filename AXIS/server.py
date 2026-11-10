from axis_sqlite import open_db
import local_models
import axis_v13
import axis_learning
import axis_executor
import central_brain as brain
import vector_discovery as discovery
import self_evolution as evolution
import vector_upgrade as upgrades
import neural_view
import vector_agents
"""VECTOR Brain V2: local-first research and source-linked knowledge graph."""
import json, os, re, sqlite3, threading, urllib.parse, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DB=Path(os.getenv('VECTOR_DB',str(ROOT/'vector.db')))
LOCK=threading.RLock()
POOL=ThreadPoolExecutor(max_workers=3)

def _setup(db):
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,label TEXT NOT NULL,kind TEXT NOT NULL,description TEXT DEFAULT "",created TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS edges(source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL,PRIMARY KEY(source,target,relation))')
    db.execute('CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,title TEXT,url TEXT,doi TEXT,year INTEGER,abstract TEXT,retrieved TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS evidence(node_id TEXT,source_id TEXT,quote TEXT,PRIMARY KEY(node_id,source_id))')
    db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,topic TEXT,status TEXT,details TEXT,created TEXT)')
    db.commit()

def connect():
    return open_db(DB,_setup,timeout=20)

def now(): return datetime.now(timezone.utc).isoformat()
def node_id(kind,label): return kind+':'+re.sub(r'[^\w-]+','-',label.casefold()).strip('-')[:100]
def add_node(db,label,kind,description=''):
    nid=node_id(kind,label)
    db.execute('INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?)',(nid,label,kind,description,now()))
    return nid

def link(db,a,b,relation):
    if a!=b: db.execute('INSERT OR IGNORE INTO edges VALUES (?,?,?)',(a,b,relation))

def fetch_json(url,timeout=18):
    req=urllib.request.Request(url,headers={'User-Agent':'VECTORBrain/0.2 (research prototype; local application)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        return json.load(resp)

def clean_abstract(inv):
    if not inv: return ''
    words=[]
    for token,positions in inv.items():
        for pos in positions: words.append((pos,token))
    return ' '.join(w for _,w in sorted(words))[:5500]

RESEARCH_DEFAULT_LIMIT=50
RESEARCH_MAX_LIMIT=200   # OpenAlex per-page maximum

def parse_limit(value):
    """Validated record count for a research job: a real int (not bool) within 1..200."""
    if isinstance(value,bool) or not isinstance(value,int): raise ValueError(f'Kayıt sayısı 1 ile {RESEARCH_MAX_LIMIT} arasında bir tam sayı olmalı')
    if not 1<=value<=RESEARCH_MAX_LIMIT: raise ValueError(f'Kayıt sayısı 1 ile {RESEARCH_MAX_LIMIT} arasında olmalı')
    return value

def search_openalex(topic,limit=RESEARCH_DEFAULT_LIMIT):
    params=urllib.parse.urlencode({'search':topic,'per-page':limit,'select':'id,title,publication_year,doi,primary_location,abstract_inverted_index,concepts'})
    data=fetch_json('https://api.openalex.org/works?'+params,timeout=60)  # up to 200 abstracts: larger body than the 18 s default allows
    out=[]
    for w in data.get('results',[]):
        loc=w.get('primary_location') or {}
        url=(loc.get('landing_page_url') or w.get('doi') or w.get('id') or '')
        out.append({'id':w.get('id') or str(uuid.uuid4()),'title':w.get('title') or 'Başlıksız','year':w.get('publication_year'),'doi':w.get('doi'),'url':url,'abstract':clean_abstract(w.get('abstract_inverted_index')),'concepts':[x['display_name'] for x in w.get('concepts',[]) if x.get('score',0)>=.5][:8]})
    return out

def research(topic,job_id,limit=RESEARCH_DEFAULT_LIMIT):
    try:
        works=search_openalex(topic,limit)
        with LOCK,connect() as db:
            root=add_node(db,topic,'topic','Araştırma konusu; kaynaklardan otomatik oluşturuldu')
            for w in works:
                sid=w['id']
                db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)',(sid,w['title'],w['url'],w['doi'],w['year'],w['abstract'],now()))
                paper=add_node(db,w['title'],'paper',w['abstract'][:350])
                link(db,root,paper,'literatür')
                db.execute('INSERT OR REPLACE INTO evidence VALUES (?,?,?)',(paper,sid,w['abstract'][:350]))
                for concept in w['concepts']:
                    c=add_node(db,concept,'concept','OpenAlex tarafından etiketlenen kavram; doğrulanmış çıkarım değildir')
                    link(db,paper,c,'etiket')
            db.execute('UPDATE jobs SET status=?,details=? WHERE id=?',('completed',f'{limit} kayıt istendi · {len(works)} akademik kayıt işlendi',job_id))
            db.commit()
        brain.log('research','openalex_search','research','success' if works else 'partial',f'{topic}: {len(works)} akademik kayıt',job_id,{'source_ids':[w['id'] for w in works]})
    except Exception as e:
        brain.log('research','openalex_search','research','failure',str(e)[:1000],job_id)
        with LOCK,connect() as db:
            db.execute('UPDATE jobs SET status=?,details=? WHERE id=?',('failed',str(e)[:400],job_id));db.commit()

def start_research(topic,limit=RESEARCH_DEFAULT_LIMIT):
    topic=topic.strip()[:180]
    if len(topic)<3: raise ValueError('Konu en az 3 karakter olmalı')
    limit=parse_limit(limit)
    jid=str(uuid.uuid4())
    with LOCK,connect() as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',(jid,topic,'running',f'OpenAlex aranıyor · {limit} kayıt istendi',now()));db.commit()
    POOL.submit(research,topic,jid,limit)
    return {'job_id':jid,'status':'running'}

# ---------------- Questions answered by the local model (async: CPU answers take minutes) ----------------
ASK_JOBS={}            # job_id -> result dict; in memory only, answers are not stored as knowledge
ASK_LOCK=threading.Lock()
ASK_MAX_JOBS=50
ASK_MAX_RUNNING=2

def ask_error_message(e):
    """Turkish, user-facing reason. Never suggests or falls back to a cloud model."""
    import socket, urllib.error
    text=str(e)
    if isinstance(e,local_models.CloudModelError):return 'Yerel model kullanılamadı: '+text[:300]
    if isinstance(e,(TimeoutError,socket.timeout)) or 'timed out' in text.lower():return 'Yerel model zaman aşımına uğradı (180 sn). Model CPU üzerinde yavaş olabilir; daha kısa bir soru dene.'
    if isinstance(e,urllib.error.HTTPError):return 'Yerel Ollama hata döndürdü (HTTP '+str(e.code)+'). Model kurulu mu? ('+local_models.model_name()+')'
    if isinstance(e,urllib.error.URLError):return 'Yerel Ollama sunucusuna ulaşılamadı: '+str(e.reason)[:200]
    return 'Yanıt üretilemedi: '+text[:300]

def run_ask(question,job_id):
    import vector_intelligence as vi
    try:
        result=vi.answer_question(question)
        update={'status':'completed','error':None,**result}
        try:brain.log('assistant','answer_question','local_llm','success',('Soru yanıtlandı: '+question)[:500],job_id,{'used_memory':[m['id'] for m in result['used_memory']],'elapsed_s':result['elapsed_s']})
        except Exception:pass
    except Exception as e:
        update={'status':'failed','error':ask_error_message(e)}
        try:brain.log('assistant','answer_question','local_llm','failure',update['error'][:1000],job_id)
        except Exception:pass
    with ASK_LOCK:
        if job_id in ASK_JOBS:ASK_JOBS[job_id].update(update,finished=now())

def start_ask(question):
    import vector_intelligence as vi
    q=vi.validate_question(question)
    jid=str(uuid.uuid4())
    with ASK_LOCK:
        if sum(1 for j in ASK_JOBS.values() if j['status']=='running')>=ASK_MAX_RUNNING:
            raise ValueError('Yerel model hâlâ önceki soruları yanıtlıyor; biraz bekle.')
        while len(ASK_JOBS)>=ASK_MAX_JOBS:  # drop the oldest finished job (dicts keep insertion order)
            old=next((k for k,v in ASK_JOBS.items() if v['status']!='running'),None)
            if old is None:raise ValueError('Çok fazla bekleyen soru')
            del ASK_JOBS[old]
        ASK_JOBS[jid]={'id':jid,'status':'running','question':q,'created':now(),'error':None}
    POOL.submit(run_ask,q,jid)
    return {'job_id':jid,'status':'running'}

def ask_result(jid):
    with ASK_LOCK:
        job=ASK_JOBS.get(jid)
        return dict(job) if job else None

def graph():
    with LOCK,connect() as db:
        nodes=[dict(x) for x in db.execute('SELECT * FROM nodes ORDER BY created DESC LIMIT 500')]
        ids={n['id'] for n in nodes}
        edges=[dict(x) for x in db.execute('SELECT * FROM edges') if x['source'] in ids and x['target'] in ids]
        return {'nodes':nodes,'edges':edges}

def sources(nid):
    with LOCK,connect() as db:
        return [dict(x) for x in db.execute('SELECT s.*,e.quote FROM evidence e JOIN sources s ON s.id=e.source_id WHERE e.node_id=?',(nid,))]

def status():
    with LOCK,connect() as db:
        return {'jobs':[dict(x) for x in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 15')], 'nodes':db.execute('SELECT COUNT(*) FROM nodes').fetchone()[0]}

STATIC=ROOT/'static'
STATIC_NAME=re.compile(r'[a-z0-9_-]{1,40}\.(js|css)')
STATIC_TYPES={'js':'text/javascript','css':'text/css'}   # send() appends '; charset=utf-8' and Cache-Control: no-store

def static_file(name):
    """(bytes, content type) for a UI asset in AXIS/static, or (None, None). Raw (undecoded) name must be a plain lowercase js/css file name."""
    m=STATIC_NAME.fullmatch(name)
    if not m: return None,None
    try:
        base=STATIC.resolve(strict=True)
        path=(base/name).resolve(strict=True)
    except (OSError,RuntimeError):
        return None,None
    if path.parent!=base or not path.is_file(): return None,None
    return path.read_bytes(),STATIC_TYPES[m.group(1)]

class Handler(BaseHTTPRequestHandler):
    def send(self,code,payload,ctype='application/json'):
        body=(json.dumps(payload,ensure_ascii=False).encode() if ctype=='application/json' else payload)
        if getattr(self,'_axis_post',False):
            try:
                axis_learning.record(self._axis_task,'orchestrator','api_request',self.path.split('?')[0][:120], 'success' if code < 400 else 'failure',{'http_status':code})
            except Exception:
                pass
        self.send_response(code);self.send_header('Content-Type',ctype+'; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        p=urllib.parse.urlsplit(self.path)
        if p.path=='/': return self.send(200,(ROOT/'index.html').read_bytes(),'text/html')
        if p.path=='/api/capabilities': return self.send(200,{'ollama_model':local_models.model_name(),'local_only':True,'auto_apply_upgrades':upgrades.auto_apply_enabled(),'features':['question_answering','literature_synthesis','llm_skill_proposal','parallel_readonly_tools','pdf_upload','approval_gate']})
        if p.path=='/api/neural':
            # http_response validates a/b and returns (400, error) instead of raising on bad input.
            return self.send(*neural_view.http_response(urllib.parse.parse_qs(p.query)))
        if p.path=='/api/ask-result':
            job=ask_result(urllib.parse.parse_qs(p.query).get('id',[''])[0])
            return self.send(200,job) if job else self.send(404,{'error':'Soru işi bulunamadı (sunucu yeniden başlatılmış olabilir)'})
        if p.path=='/api/upgrade-auto': return self.send(200,upgrades.auto_status())
        if p.path=='/api/agent-catalog': return self.send(200,discovery.listing())
        if p.path=='/api/agent-health': return self.send(200,discovery.health())
        if p.path=='/api/agents': return self.send(200,vector_agents.listing())
        if p.path=='/api/agent-detail': return self.send(200,vector_agents.detail(urllib.parse.parse_qs(p.query).get('id',[''])[0]))
        if p.path=='/api/behavior-cases': return self.send(200,upgrades.behavior_cases(urllib.parse.parse_qs(p.query).get('id',[''])[0]))
        if p.path=='/api/upgrades': return self.send(200,upgrades.listing())
        if p.path=='/api/upgrade-detail': return self.send(200,upgrades.detail(urllib.parse.parse_qs(p.query).get('id',[''])[0]))
        if p.path=='/api/proposals': return self.send(200,evolution.list_proposals())
        if p.path=='/api/brain-experiences': return self.send(200,brain.experiences())
        if p.path=='/api/brain-skills': return self.send(200,brain.skills())
        if p.path=='/api/brain-discover': return self.send(200,brain.discover())
        if p.path=='/api/brain-graph': return self.send(200,brain.graph())
        if p.path=='/api/axis-v13-dashboard': return self.send(200,axis_v13.dashboard())
        if p.path=='/api/axis-events': return self.send(200,axis_learning.events())
        if p.path=='/api/axis-lessons': return self.send(200,axis_learning.lessons())
        if p.path=='/api/axis-runs': return self.send(200,axis_executor.history())
        if p.path=='/api/graph': return self.send(200,graph())
        if p.path=='/api/status': return self.send(200,status())
        if p.path=='/api/sources': return self.send(200,sources(urllib.parse.parse_qs(p.query).get('node',[''])[0]))
        if p.path.startswith('/static/'):
            body,ctype=static_file(p.path[len('/static/'):])
            if body is not None: return self.send(200,body,ctype)
        self.send(404,{'error':'Not found'})
    def do_POST(self):
        self._axis_post=True
        self._axis_task=__import__('uuid').uuid4().hex
        # Reject browser cross-origin writes to the local management API.
        origin=self.headers.get('Origin','')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'):
            return self.send(403,{'error':'Cross-origin istek reddedildi'})
        if self.headers.get('Sec-Fetch-Site','')=='cross-site':
            return self.send(403,{'error':'Cross-site istek reddedildi'})
        if self.path not in ('/api/research','/api/ask','/api/propose','/api/decision','/api/synthesize','/api/generate-skill','/api/parallel','/api/pdf','/api/upgrade-propose','/api/upgrade-test','/api/upgrade-decision','/api/upgrade-rollback','/api/agent-run','/api/behavior-cases','/api/agent-scan','/api/agent-decision','/api/agent-parallel','/api/brain-log','/api/brain-propose','/api/brain-decision','/api/axis-run','/api/axis-record','/api/axis-learn','/api/axis-compose','/api/axis-recover','/api/axis-v13-develop','/api/axis-v13-repair','/api/axis-v13-models'): return self.send(404,{'error':'Not found'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>11500000: raise ValueError('İstek çok büyük')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError('JSON nesnesi bekleniyor')
            if self.path=='/api/ask': return self.send(202,start_ask(data.get('question')))
            if self.path=='/api/axis-v13-develop': return self.send(201,axis_v13.development(str(data.get('request','')),str(data.get('target','research_extensions.py'))))
            if self.path=='/api/axis-v13-repair': return self.send(201,axis_v13.repair(str(data.get('error','')),str(data.get('target','research_extensions.py'))))
            if self.path=='/api/axis-v13-models': return self.send(200,axis_v13.model_suggestions(str(data.get('request',''))))
            if self.path=='/api/axis-record': return self.send(201,{'id':axis_learning.record(str(data.get('task_id','')),str(data.get('agent','')),str(data.get('kind','')),str(data.get('tool','')),str(data.get('outcome','')),data.get('payload',{}))})
            if self.path=='/api/axis-learn': return self.send(200,axis_learning.learn())
            if self.path=='/api/axis-compose': return self.send(201,axis_learning.compose(str(data.get('name','')),data.get('skill_ids',[])))
            if self.path=='/api/axis-recover': return self.send(200,axis_learning.run_with_recovery(str(data.get('skill_id','')),data.get('args',{}),data.get('max_attempts',2)))
            if self.path=='/api/axis-run': return self.send(200,axis_executor.execute(str(data.get('skill_id','')),data.get('args',{})))
            if self.path=='/api/brain-log': return self.send(201,brain.log(str(data.get('agent','')),str(data.get('action','')),str(data.get('tool','')),str(data.get('status','')),str(data.get('summary','')),data.get('task_id'),data.get('evidence')))
            if self.path=='/api/brain-propose': return self.send(201,brain.propose(data.get('name'),data.get('steps'),data.get('evidence_ids')))
            if self.path=='/api/brain-decision': return self.send(200,brain.decide(str(data.get('id','')),str(data.get('action','')),str(data.get('confirmation',''))))
            if self.path=='/api/agent-scan':
                result=discovery.scan(str(data.get('request','')))
                brain.log('planner','capability_scan','agent_scan','success','Ajan yetenek taraması tamamlandı')
                return self.send(200,result)
            if self.path=='/api/agent-decision': return self.send(200,discovery.decision(str(data.get('id','')),str(data.get('action','')),str(data.get('confirmation',''))))
            if self.path=='/api/agent-parallel': return self.send(200,discovery.parallel_readonly(str(data.get('request',''))))
            if self.path=='/api/agent-run':
                result=vector_agents.run(str(data.get('request','')),str(data.get('target','research_extensions.py')))
                brain.log('coder','multi_agent_run','agent_run','success' if result.get('status')=='awaiting_tests_and_approval' else 'failure','Çok ajanlı geliştirme: '+str(result.get('status','unknown')),result.get('id'),{'proposal_id':result.get('proposal_id')})
                return self.send(201,result)
            if self.path=='/api/upgrade-propose': return self.send(201,upgrades.propose(data.get('target'),data.get('code'),data.get('description','')))
            if self.path=='/api/behavior-cases': return self.send(200,upgrades.attach_behavior_cases(str(data.get('id','')),data.get('cases')))
            if self.path=='/api/upgrade-test': return self.send(200,upgrades.verify(str(data.get('id',''))))
            if self.path=='/api/upgrade-decision': return self.send(200,upgrades.decide(str(data.get('id','')),str(data.get('action','')),str(data.get('confirmation',''))))
            if self.path=='/api/upgrade-rollback': return self.send(200,upgrades.rollback(str(data.get('id','')),str(data.get('confirmation',''))))
            if self.path in ('/api/synthesize','/api/generate-skill','/api/parallel','/api/pdf','/api/upgrade-propose','/api/upgrade-test','/api/upgrade-decision','/api/upgrade-rollback'):
                import vector_intelligence as vi
                if self.path=='/api/synthesize': return self.send(200,vi.literature_summary(str(data.get('topic',''))))
                if self.path=='/api/generate-skill': return self.send(201,vi.propose_from_llm(str(data.get('description','')),str(data.get('skill',''))))
                if self.path=='/api/parallel':
                    result=vi.run_parallel(data.get('tasks',[]))
                    brain.log('orchestrator','parallel_tools','count_nodes','success','Paralel hafıza araçları çağrıldı')
                    return self.send(200,result)
                if self.path=='/api/pdf':
                    import base64
                    return self.send(201,vi.ingest_pdf(str(data.get('filename','')),base64.b64decode(data.get('content_base64',''),validate=True)))
            if self.path=='/api/propose': return self.send(201,evolution.propose(data.get('skill'),data.get('code'),data.get('summary','')))
            if self.path=='/api/decision': return self.send(200,evolution.decide(data.get('id'),data.get('action'),data.get('confirmation','')))
            self.send(202,start_research(str(data.get('topic','')),data.get('limit',RESEARCH_DEFAULT_LIMIT)))
        except (ValueError,TypeError,json.JSONDecodeError) as e: self.send(400,{'error':str(e)})
        except Exception as e: self.send(503,{'error':str(e)[:350]})
    def log_message(self,*args): pass

if __name__=='__main__':
    with connect(): pass
    # Auto-apply of core upgrades (user decision 2026-11-10; kill switch AXIS_AUTO_APPLY=0).
    upgrades.SCHEDULER=lambda uid: POOL.submit(upgrades.auto_pipeline,uid)
    queued=upgrades.sweep_untested()
    print('Otomatik güncelleme:',('açık' if upgrades.auto_apply_enabled() else 'kapalı (AXIS_AUTO_APPLY)'),'· kuyruğa alınan:',len(queued))
    print('AXIS Brain: http://127.0.0.1:8765')
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
