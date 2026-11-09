"""Research, local LLM synthesis, reviewed proposals, and parallel read-only tools."""
import json, os, re, urllib.request, urllib.parse, concurrent.futures, hashlib
from pathlib import Path
import server
import self_evolution
import local_models
MODEL=os.getenv('VECTOR_MODEL',local_models.DEFAULT_MODEL)
OLLAMA=os.getenv('OLLAMA_URL',local_models.BASE+'/api/chat')

def ask(messages, temperature=0.2):
    base=OLLAMA.rsplit('/api/',1)[0]
    local_models.ensure_local(MODEL,base)  # refuses cloud-backed models before any chat request
    req=urllib.request.Request(local_models.api_url('chat',base), data=json.dumps({'model':MODEL,'stream':False,'messages':messages,'options':{'temperature':temperature}}).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=180) as r:
        result=json.load(r)
    return result['message']['content']

def literature_summary(topic):
    with server.connect() as db:
        rows=[dict(x) for x in db.execute("SELECT s.title,s.year,s.doi,s.url,s.abstract FROM sources s JOIN evidence e ON s.id=e.source_id JOIN edges l ON l.target=e.node_id WHERE l.source=? ORDER BY s.year DESC LIMIT 12",(server.node_id('topic',topic),))]
    if not rows: raise ValueError('Önce bu konuyu Araştır düğmesiyle tarat.')
    snippets=[{'title':x['title'],'year':x['year'],'doi':x['doi'],'abstract':x['abstract'][:1800]} for x in rows]
    system='Türkçe bilimsel araştırma asistanısın. Yalnızca verilen kayıtlar ve özetleri kullan. Tam metin görmediysen gördüğünü iddia etme. Kanıt düzeyini belirt; belirsizlikleri ve çelişkileri açıkla. [1] gibi kaynak numaralarıyla referans ver. Bilgi uydurma.'
    answer=ask([{'role':'system','content':system},{'role':'user','content':'Konu: '+topic+'\nKaynaklar: '+json.dumps(snippets,ensure_ascii=False)+'\nKısa ama derin literatür sentezi, temel kavramlar, açık sorular ve sonraki araştırma önerilerini yaz.'}])
    return {'topic':topic,'answer':answer,'sources':rows,'note':'Özet temelli sentez; tam metin incelemesi değildir.'}

def propose_from_llm(description, skill):
    self_evolution.valid_name(skill)
    if not isinstance(description,str) or not 8<=len(description)<=1500:raise ValueError('Açıklama 8-1500 karakter olmalı')
    prompt="Sadece Python kaynak kodu döndür. Bir tane def run(data): fonksiyonu olsun; girdi JSON uyumlu, çıktı JSON uyumlu. Standart kütüphane ile basit, saf hesaplama yap. Dosya, ağ, komut, subprocess, eval, exec, importlib, dış sistem erişimi veya import kullanma. Güvenilmeyen kod çalıştırılmayacak; kullanıcı inceleyecek. Kod bloğu işaretleri yazma."
    code=ask([{'role':'system','content':prompt},{'role':'user','content':'Beceri: '+skill+'\nİstek: '+description}],0.1).strip()
    code=re.sub(r'^```(?:python)?\s*|\s*```$','',code).strip()
    return self_evolution.propose(skill,code,'LLM önerisi: '+description[:220])

def ingest_pdf(filename, raw):
    if not filename.lower().endswith('.pdf') or len(raw)>8_000_000 or len(raw)<100:raise ValueError('PDF 8 MB altında olmalı')
    try:import fitz
    except ImportError:raise ValueError('PDF okumak için: py -m pip install pymupdf')
    doc=fitz.open(stream=raw,filetype='pdf')
    if doc.page_count>100:raise ValueError('En fazla 100 sayfa')
    pages=[p.get_text() for p in doc]
    text='\n'.join(pages).strip()[:120000]
    if not text:raise ValueError('Metin çıkarılamadı; taranmış PDF için OCR gerekir')
    digest=hashlib.sha256(raw).hexdigest()[:16]
    title=Path(filename).name[:140]
    with server.LOCK,server.connect() as db:
        sid='local-pdf:'+digest
        db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)',(sid,title,'','','',text[:5500],server.now()))
        nid=server.add_node(db,title,'paper',text[:350]);db.execute('INSERT OR REPLACE INTO evidence VALUES (?,?,?)',(nid,sid,text[:350]))
        for token in set(re.findall(r'(?u)\b[A-Za-zÇĞİÖŞÜçğıöşü]{6,}\b',text[:8000].lower())):
            if token in {'olarak','because','between','through','these','those','which','their'}:continue
            # Explicitly no fabricated semantic links: PDF is connected to a document node only.
        db.commit()
    return {'node_id':nid,'pages':len(pages),'characters':len(text),'note':'Metin çıkarıldı; içerik doğrulanmadı. Yalnızca ilk 5500 karakter kaynak özeti olarak saklandı.'}

TOOLS={
 'count_nodes': lambda arg: {'nodes':len(server.graph()['nodes']),'edges':len(server.graph()['edges'])},
 'list_recent_research': lambda arg: server.status()['jobs'][:10],
 'search_memory': lambda arg: search_memory(str(arg.get('query',''))),
}
def search_memory(query):
    if not query.strip():return []
    with server.connect() as db:
        return [dict(x) for x in db.execute('SELECT id,label,kind,description FROM nodes WHERE label LIKE ? LIMIT 20',('%'+query[:80]+'%',))]
def run_parallel(tasks):
    if not isinstance(tasks,list) or not 1<=len(tasks)<=8:raise ValueError('1-8 görev gönder')
    for t in tasks:
        if not isinstance(t,dict) or t.get('tool') not in TOOLS or not isinstance(t.get('args',{}),dict):raise ValueError('Bilinmeyen araç')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(TOOLS[t['tool']],t.get('args',{})) for t in tasks]
        return [{'tool':t['tool'],'result':f.result(timeout=15)} for t,f in zip(tasks,futures)]