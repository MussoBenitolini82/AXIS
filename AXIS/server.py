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

def connect():
    db=sqlite3.connect(DB,timeout=20)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,label TEXT NOT NULL,kind TEXT NOT NULL,description TEXT DEFAULT "",created TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS edges(source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL,PRIMARY KEY(source,target,relation))')
    db.execute('CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,title TEXT,url TEXT,doi TEXT,year INTEGER,abstract TEXT,retrieved TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS evidence(node_id TEXT,source_id TEXT,quote TEXT,PRIMARY KEY(node_id,source_id))')
    db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,topic TEXT,status TEXT,details TEXT,created TEXT)')
    db.commit()
    return db

def now(): return datetime.now(timezone.utc).isoformat()
def node_id(kind,label): return kind+':'+re.sub(r'[^\w-]+','-',label.casefold()).strip('-')[:100]
def add_node(db,label,kind,description=''):
    nid=node_id(kind,label)
    db.execute('INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?)',(nid,label,kind,description,now()))
    return nid

def link(db,a,b,relation):
    if a!=b: db.execute('INSERT OR IGNORE INTO edges VALUES (?,?,?)',(a,b,relation))

def fetch_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'VECTORBrain/0.2 (research prototype; local application)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=18) as resp:
        return json.load(resp)

def clean_abstract(inv):
    if not inv: return ''
    words=[]
    for token,positions in inv.items():
        for pos in positions: words.append((pos,token))
    return ' '.join(w for _,w in sorted(words))[:5500]

def search_openalex(topic,limit=7):
    params=urllib.parse.urlencode({'search':topic,'per-page':limit,'select':'id,title,publication_year,doi,primary_location,abstract_inverted_index,concepts'})
    data=fetch_json('https://api.openalex.org/works?'+params)
    out=[]
    for w in data.get('results',[]):
        loc=w.get('primary_location') or {}
        url=(loc.get('landing_page_url') or w.get('doi') or w.get('id') or '')
        out.append({'id':w.get('id') or str(uuid.uuid4()),'title':w.get('title') or 'Başlıksız','year':w.get('publication_year'),'doi':w.get('doi'),'url':url,'abstract':clean_abstract(w.get('abstract_inverted_index')),'concepts':[x['display_name'] for x in w.get('concepts',[]) if x.get('score',0)>=.5][:8]})
    return out

def research(topic,job_id):
    try:
        works=search_openalex(topic)
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
            db.execute('UPDATE jobs SET status=?,details=? WHERE id=?',('completed',f'{len(works)} akademik kayıt işlendi',job_id))
            db.commit()
        brain.log('research','openalex_search','research','success' if works else 'partial',f'{topic}: {len(works)} akademik kayıt',job_id,{'source_ids':[w['id'] for w in works]})
    except Exception as e:
        brain.log('research','openalex_search','research','failure',str(e)[:1000],job_id)
        with LOCK,connect() as db:
            db.execute('UPDATE jobs SET status=?,details=? WHERE id=?',('failed',str(e)[:400],job_id));db.commit()

def start_research(topic):
    topic=topic.strip()[:180]
    if len(topic)<3: raise ValueError('Konu en az 3 karakter olmalı')
    jid=str(uuid.uuid4())
    with LOCK,connect() as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',(jid,topic,'running','OpenAlex aranıyor',now()));db.commit()
    POOL.submit(research,topic,jid)
    return {'job_id':jid,'status':'running'}

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
        if p.path=='/api/capabilities': return self.send(200,{'ollama_model':__import__('os').getenv('VECTOR_MODEL','qwen3:8b'),'features':['literature_synthesis','llm_skill_proposal','parallel_readonly_tools','pdf_upload','approval_gate']})
        if p.path=='/api/neural':
            q=urllib.parse.parse_qs(p.query)
            return self.send(200,neural_view.model_graph([float(q.get('a',['1'])[0]),float(q.get('b',['0'])[0])]))
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
        if self.path not in ('/api/research','/api/propose','/api/decision','/api/synthesize','/api/generate-skill','/api/parallel','/api/pdf','/api/upgrade-propose','/api/upgrade-test','/api/upgrade-decision','/api/upgrade-rollback','/api/agent-run','/api/behavior-cases','/api/agent-scan','/api/agent-decision','/api/agent-parallel','/api/brain-log','/api/brain-propose','/api/brain-decision','/api/axis-run','/api/axis-record','/api/axis-learn','/api/axis-compose','/api/axis-recover','/api/axis-v13-develop','/api/axis-v13-repair','/api/axis-v13-models'): return self.send(404,{'error':'Not found'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>11500000: raise ValueError('İstek çok büyük')
            data=json.loads(self.rfile.read(length))
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
            self.send(202,start_research(str(data.get('topic',''))))
        except (ValueError,TypeError,json.JSONDecodeError) as e: self.send(400,{'error':str(e)})
        except Exception as e: self.send(503,{'error':str(e)[:350]})
    def log_message(self,*args): pass

if __name__=='__main__':
    with connect(): pass
    print('AXIS Brain: http://127.0.0.1:8765')
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()