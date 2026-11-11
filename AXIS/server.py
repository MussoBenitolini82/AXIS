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
import axis_memory
import axis_feedback
import axis_trace as trace
"""VECTOR Brain V2: local-first research and source-linked knowledge graph."""
import json, os, re, sqlite3, threading, urllib.error, urllib.parse, urllib.request, uuid
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

def fetch_text(url,timeout=60,limit=8_000_000):
    req=urllib.request.Request(url,headers={'User-Agent':'VECTORBrain/0.2 (research prototype; local application)','Accept':'application/atom+xml'})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        return resp.read(limit)

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
    q={'search':topic,'per-page':limit,'select':'id,title,publication_year,doi,primary_location,abstract_inverted_index,concepts'}
    if os.getenv('OPENALEX_API_KEY'): q['api_key']=os.getenv('OPENALEX_API_KEY')  # optional free key; without it OpenAlex has a small daily quota
    params=urllib.parse.urlencode(q)
    data=fetch_json('https://api.openalex.org/works?'+params,timeout=60)  # up to 200 abstracts: larger body than the 18 s default allows
    out=[]
    for w in data.get('results',[]):
        loc=w.get('primary_location') or {}
        url=(loc.get('landing_page_url') or w.get('doi') or w.get('id') or '')
        # OpenAlex may send "concepts": null or entries without a name/score; neither may abort the whole search.
        concepts=[x['display_name'] for x in (w.get('concepts') or []) if isinstance(x,dict) and x.get('display_name') and (x.get('score') or 0)>=.5][:8]
        out.append({'id':w.get('id') or str(uuid.uuid4()),'title':w.get('title') or 'Başlıksız','year':w.get('publication_year'),'doi':w.get('doi'),'url':url,'abstract':clean_abstract(w.get('abstract_inverted_index')),'concepts':concepts})
    return out

ATOM='{http://www.w3.org/2005/Atom}'

def search_arxiv(topic,limit=RESEARCH_DEFAULT_LIMIT):
    """Fallback source: arXiv API (free, no key). Returns the same record shape as search_openalex."""
    import xml.etree.ElementTree as ET
    words=[w for w in re.findall(r'[\w\-]+',topic) if len(w)>1][:8]
    if not words: return []
    query=' AND '.join('all:'+w for w in words)
    params=urllib.parse.urlencode({'search_query':query,'start':0,'max_results':limit,'sortBy':'relevance'})
    root=ET.fromstring(fetch_text('https://export.arxiv.org/api/query?'+params))
    out=[]
    for e in root.findall(ATOM+'entry'):
        rid=(e.findtext(ATOM+'id') or '').strip()
        if not rid: continue
        title=' '.join((e.findtext(ATOM+'title') or 'Başlıksız').split())
        year=(e.findtext(ATOM+'published') or '')[:4]
        out.append({'id':rid,'title':title,'year':int(year) if year.isdigit() else None,'doi':None,'url':rid.replace('http://','https://',1),
                    'abstract':' '.join((e.findtext(ATOM+'summary') or '').split())[:5500],
                    'concepts':[c.get('term') for c in e.findall(ATOM+'category') if c.get('term')][:8]})
    return out

def friendly_error(e,source='OpenAlex'):
    if isinstance(e,urllib.error.HTTPError) and e.code==429:
        wait=e.headers.get('Retry-After') if e.headers else None
        hours=f' (yaklaşık {round(int(wait)/3600,1)} saat sonra sıfırlanır)' if wait and wait.isdigit() else ''
        return (source+' günlük ücretsiz kotası doldu' if source=='OpenAlex' else source+' istek sınırına ulaşıldı')+hours
    return f'{type(e).__name__}: {e}'

def find_works(topic,limit):
    """OpenAlex first; on any failure fall back to arXiv. Returns (works, source_name, note)."""
    try:
        return search_openalex(topic,limit),'OpenAlex',''
    except Exception as e:
        first=friendly_error(e)
    try:
        return search_arxiv(topic,limit),'arXiv',first+' → arXiv kullanıldı'
    except Exception as e:
        raise RuntimeError(first+'; arXiv de başarısız: '+friendly_error(e,'arXiv')) from None

class _SafeSpan:
    """Best-effort tracing: a failure while opening, annotating or closing a span never changes the traced block's result or exception."""
    def __init__(self,*a):self.a=a;self.cm=None;self.sp=None
    def __enter__(self):
        try:self.cm=trace.span(*self.a);self.sp=self.cm.__enter__()
        except Exception:self.cm=self.sp=None
        return self
    def note(self,k,v):
        try:self.sp.note(k,v)
        except Exception:pass
    def partial(self):
        try:self.sp.partial()
        except Exception:pass
    def __exit__(self,t,v,tb):
        if self.cm is not None:
            try:self.cm.__exit__(t,v,tb)
            except Exception:pass  # the original exception (if any) propagates because we return False
        return False

def safe_span(*a): return _SafeSpan(*a)

def research(topic,job_id,limit=RESEARCH_DEFAULT_LIMIT):
    try:
        with safe_span(job_id,'research','literature_search') as sp:
            works,source,note=find_works(topic,limit)
            sp.note('source',source);sp.note('records',len(works))
            if not works: sp.partial()
            with LOCK,connect() as db:
                root=add_node(db,topic,'topic','Araştırma konusu; kaynaklardan otomatik oluşturuldu')
                to_index=[{'id':root,'kind':'topic','label':topic,'text':'Araştırma konusu; kaynaklardan otomatik oluşturuldu'}]
                for w in works:
                    sid=w['id']
                    db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)',(sid,w['title'],w['url'],w['doi'],w['year'],w['abstract'],now()))
                    paper=add_node(db,w['title'],'paper',w['abstract'][:350])
                    to_index.append({'id':paper,'kind':'paper','label':w['title'],'text':w['abstract']})
                    link(db,root,paper,'literatür')
                    db.execute('INSERT OR REPLACE INTO evidence VALUES (?,?,?)',(paper,sid,w['abstract'][:350]))
                    for concept in w['concepts']:
                        c=add_node(db,concept,'concept',source+' tarafından etiketlenen kavram; doğrulanmış çıkarım değildir')
                        link(db,paper,c,'etiket')
                db.execute('UPDATE jobs SET status=?,details=? WHERE id=?',('completed',f'{source}: {limit} kayıt istendi · {len(works)} akademik kayıt işlendi'+(f' · {note}' if note else ''),job_id))
                db.commit()
    except Exception as e:
        # Mark the job first: a failing audit log must never leave it "running" forever.
        reason=(str(e) or type(e).__name__)
        with LOCK,connect() as db:
            db.execute('UPDATE jobs SET status=?,details=? WHERE id=?',('failed',reason[:400],job_id));db.commit()
        try:brain.log('research','literature_search','research','failure',reason[:1000],job_id)
        except Exception:pass
        return
    # The job is already committed as completed; the semantic index and the audit log are best-effort.
    index_memory(to_index)
    try:brain.log('research',source.lower()+'_search','research','success' if works else 'partial',f'{topic}: {len(works)} akademik kayıt ({source})',job_id,{'source_ids':[w['id'] for w in works]})
    except Exception:pass
    if AFTER_RESEARCH: AFTER_RESEARCH()  # running server only: embed new abstracts in the background

def fail_stale_jobs():
    """At start-up no research thread is alive, so any job still 'running' was cut off by a restart."""
    with LOCK,connect() as db:
        n=db.execute("UPDATE jobs SET status='failed',details='Sunucu yeniden başlatıldı; araştırma tamamlanamadı' WHERE status='running'").rowcount
        db.commit()
    return n

AFTER_RESEARCH=None  # set in __main__; tests and imports never start background embedding

# ---------------- Semantic memory index (axis_memory) ----------------
MEMORY_INDEXING=False  # switched on in __main__: imports and tests must never write to the real index
MEMORY_BATCH=64
MEMORY_MAX_BATCHES=200
_MEM_WAKE=threading.Event()
_MEM_THREAD=[None]
_MEM_STOP=threading.Event()

def index_memory(items):
    """Upsert items into axis_memory and wake the worker; returns how many were stored (0 when off or failed). Never raises."""
    if not MEMORY_INDEXING or not items: return 0
    try: axis_memory.upsert_many(items)
    except Exception: return 0
    _MEM_WAKE.set()
    return len(items)

def memory_sync_once():
    """One pass: graph nodes -> axis_memory rows, then embed what is pending in bounded batches."""
    with LOCK,connect() as db:
        rows=[dict(x) for x in db.execute('SELECT n.id,n.kind,n.label,n.description,(SELECT s.abstract FROM evidence e JOIN sources s ON s.id=e.source_id WHERE e.node_id=n.id LIMIT 1) AS abstract FROM nodes n')]
    # A paper's text is its abstract (the same text research indexes), so the two writers never flip the digest.
    items=[{'id':r['id'],'kind':r['kind'],'label':r['label'],'text':(r['abstract'] if r['kind']=='paper' and r['abstract'] else r['description']) or ''} for r in rows]
    synced=0
    for i in range(0,len(items),500): synced+=axis_memory.upsert_many(items[i:i+500])
    embedded=pending=0;available=None
    for _ in range(MEMORY_MAX_BATCHES):
        r=axis_memory.backfill(MEMORY_BATCH)
        embedded+=r['embedded'];pending=r['pending'];available=r['available']
        if not pending or not r['available'] or not r['embedded']: break
    return {'synced':synced,'embedded':embedded,'pending':pending,'available':available}

def _memory_worker():
    while not _MEM_STOP.is_set():
        try: memory_sync_once()
        except Exception: pass
        _MEM_WAKE.wait(600);_MEM_WAKE.clear()  # nudged after research/PDF; otherwise retry every 10 min

def start_memory_worker():
    """One daemon thread (not POOL, never blocks start-up) that keeps axis_memory in step with the graph."""
    t=_MEM_THREAD[0]
    if t and t.is_alive(): return False
    _MEM_STOP.clear()
    _MEM_THREAD[0]=threading.Thread(target=_memory_worker,daemon=True,name='axis-memory-index')
    _MEM_THREAD[0].start()
    return True

def stop_memory_worker(timeout=5):
    _MEM_STOP.set();_MEM_WAKE.set()
    t=_MEM_THREAD[0]
    if t: t.join(timeout)

def start_rag_embedding():
    try:
        import rag
        return rag.start_embedding()
    except Exception as e:  # retrieval index is optional: never fail research because of it
        print('RAG gömme başlatılamadı:',type(e).__name__)
        return False

def start_research(topic,limit=RESEARCH_DEFAULT_LIMIT):
    topic=topic.strip()[:180]
    if len(topic)<3: raise ValueError('Konu en az 3 karakter olmalı')
    limit=parse_limit(limit)
    jid=str(uuid.uuid4())
    with LOCK,connect() as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',(jid,topic,'running',f'Literatür aranıyor (OpenAlex, gerekirse arXiv) · {limit} kayıt istendi',now()));db.commit()
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
        with safe_span(job_id,'assistant','answer_question',vi.MODEL) as sp:
            result=vi.answer_question(question)
            sp.note('memory',len(result.get('used_memory') or ()));sp.note('semantic',result.get('semantic',False));sp.note('feedback',result.get('used_feedback',0))
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
    def local_host(self):
        """DNS-rebinding guard: a browser that reached us through a foreign host name is refused.
        Only the name is checked (tests and tools use other ports); a missing Host header is a non-browser client."""
        host=self.headers.get('Host','').strip().lower()
        if not host: return True
        name=host[:host.index(']')+1] if host.startswith('[') and ']' in host else host.rsplit(':',1)[0] if ':' in host else host
        return name in ('127.0.0.1','localhost','[::1]')
    def do_GET(self):
        if not self.local_host(): return self.send(403,{'error':'Yalnızca yerel adresten erişilebilir'})
        # Lookups such as /api/upgrade-detail?id=… raise ValueError for unknown ids: answer with JSON, not a dropped connection.
        try: self.route_get()
        except ValueError as e: self.send(400,{'error':str(e)})
        except (BrokenPipeError,ConnectionError): pass
        except Exception as e: self.send(500,{'error':str(e)[:350]})
    def route_get(self):
        p=urllib.parse.urlsplit(self.path)
        if p.path=='/': return self.send(200,(ROOT/'index.html').read_bytes(),'text/html')
        if p.path=='/api/capabilities': return self.send(200,{'ollama_model':local_models.model_name(),'local_only':True,'auto_apply_upgrades':upgrades.auto_apply_enabled(),'embed_model':axis_memory.EMBED_MODEL,'features':['question_answering','literature_synthesis','llm_skill_proposal','parallel_readonly_tools','pdf_upload','approval_gate','semantic_memory','feedback_learning','task_trace','skill_run']})
        if p.path=='/api/neural':
            # http_response validates a/b and returns (400, error) instead of raising on bad input.
            return self.send(*neural_view.http_response(urllib.parse.parse_qs(p.query)))
        if p.path=='/api/ask-result':
            job=ask_result(urllib.parse.parse_qs(p.query).get('id',[''])[0])
            return self.send(200,job) if job else self.send(404,{'error':'Soru işi bulunamadı (sunucu yeniden başlatılmış olabilir)'})
        if p.path=='/api/feedback-stats': return self.send(200,axis_feedback.stats())
        if p.path=='/api/task-traces': return self.send(200,{'tasks':trace.tasks(int(urllib.parse.parse_qs(p.query).get('limit',['30'])[0])),'summary':trace.summary()})
        if p.path=='/api/task-trace': return self.send(200,trace.trace(urllib.parse.parse_qs(p.query).get('id',[''])[0]))
        if p.path=='/api/skills-runnable':
            import skill_runner
            return self.send(200,skill_runner.runnable())
        if p.path=='/api/memory-status': return self.send(200,axis_memory.status())
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
        if p.path=='/api/rag-status':
            import rag
            return self.send(200,rag.status())
        if p.path=='/api/sources': return self.send(200,sources(urllib.parse.parse_qs(p.query).get('node',[''])[0]))
        if p.path.startswith('/static/'):
            body,ctype=static_file(p.path[len('/static/'):])
            if body is not None: return self.send(200,body,ctype)
        self.send(404,{'error':'Not found'})
    def do_POST(self):
        self._axis_post=True
        self._axis_task=__import__('uuid').uuid4().hex
        if not self.local_host(): return self.send(403,{'error':'Yalnızca yerel adresten erişilebilir'})
        # Reject browser cross-origin writes to the local management API.
        origin=self.headers.get('Origin','')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'):
            return self.send(403,{'error':'Cross-origin istek reddedildi'})
        if self.headers.get('Sec-Fetch-Site','')=='cross-site':
            return self.send(403,{'error':'Cross-site istek reddedildi'})
        if self.path not in ('/api/research','/api/ask','/api/propose','/api/decision','/api/synthesize','/api/generate-skill','/api/parallel','/api/pdf','/api/upgrade-propose','/api/upgrade-test','/api/upgrade-decision','/api/upgrade-rollback','/api/agent-run','/api/behavior-cases','/api/agent-scan','/api/agent-decision','/api/agent-parallel','/api/brain-log','/api/brain-propose','/api/brain-decision','/api/axis-run','/api/axis-record','/api/axis-learn','/api/axis-compose','/api/axis-recover','/api/axis-v13-develop','/api/axis-v13-repair','/api/axis-v13-models','/api/feedback','/api/skill-run','/api/memory-backfill'): return self.send(404,{'error':'Not found'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<0: raise ValueError('Geçersiz Content-Length')  # read(-1) would block until the client hangs up
            if length>11500000: raise ValueError('İstek çok büyük')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError('JSON nesnesi bekleniyor')
            if self.path=='/api/ask': return self.send(202,start_ask(data.get('question')))
            if self.path=='/api/axis-v13-develop': return self.send(201,axis_v13.development(str(data.get('request','')),str(data.get('target','extensions/research_extensions.py'))))
            if self.path=='/api/axis-v13-repair': return self.send(201,axis_v13.repair(str(data.get('error','')),str(data.get('target','extensions/research_extensions.py'))))
            if self.path=='/api/feedback':
                jid=str(data.get('job_id',''))
                job=ask_result(jid)
                if not job: return self.send(404,{'error':'Soru işi bulunamadı (sunucu yeniden başlatılmış olabilir)'})
                if job.get('status')!='completed' or job.get('action_refused') or not isinstance(job.get('answer'),str): raise ValueError('Yalnızca tamamlanmış bir yanıt için geri bildirim verilebilir')
                # Question and answer come from the server's own record, never from the client.
                return self.send(201,axis_feedback.record(jid,job['question'],job['answer'],data.get('rating'),data.get('correction','')))
            if self.path=='/api/skill-run':
                import skill_runner
                return self.send(200,skill_runner.run(data.get('skill'),data.get('data')))
            if self.path=='/api/memory-backfill': return self.send(200,axis_memory.backfill(64))
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
                with safe_span(self._axis_task,'coder','agent_run') as sp:
                    result=vector_agents.run(str(data.get('request','')),str(data.get('target','extensions/research_extensions.py')))
                    sp.note('status',result.get('status','unknown') if isinstance(result,dict) else '?')
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
    # Run as a script this module is '__main__'; vector_intelligence does 'import server'. Without the alias
    # that would load a second copy with its own LOCK, POOL and ASK_JOBS.
    import sys
    sys.modules.setdefault('server',sys.modules[__name__])
    with connect(): pass
    stale=fail_stale_jobs()
    if stale: print('Yarım kalan araştırma işi kapatıldı:',stale)
    # Auto-apply of core upgrades (user decision 2026-11-10; kill switch AXIS_AUTO_APPLY=0).
    upgrades.SCHEDULER=lambda uid: POOL.submit(upgrades.auto_pipeline,uid)
    queued=upgrades.sweep_untested()
    print('Otomatik güncelleme:',('açık' if upgrades.auto_apply_enabled() else 'kapalı (AXIS_AUTO_APPLY)'),'· kuyruğa alınan:',len(queued))
    AFTER_RESEARCH=start_rag_embedding
    MEMORY_INDEXING=True
    start_memory_worker()
    print('Anlamsal dizin (bge-m3):','arka planda güncelleniyor' if start_rag_embedding() else 'başlatılamadı')
    print('AXIS Brain: http://127.0.0.1:8765')
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
