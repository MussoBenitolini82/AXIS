'use strict';
/* AXIS v14 UI: answer feedback, task trace, runnable skills, memory index tile.
   Loaded before the inline shell script; it only uses the shell's helpers ($, el, btn, getJSON, postJSON,
   readJSON, toast, feed, setSt, currentTab) at call time. Server data is inserted with textContent only. */
window.AxisV14=(function(){
const T=(tag,cls,text)=>el(tag,cls,text);
function dur(ms){
  if(typeof ms!=='number'||!isFinite(ms)||ms<0)return '—';
  if(ms<1000)return Math.round(ms)+' ms';
  const s=ms/1000;
  if(s<10)return s.toFixed(1)+' sn';
  if(s<60)return Math.round(s)+' sn';
  const m=Math.floor(s/60),r=Math.round(s%60);
  return m+' dk '+r+' sn';
}
function when(v){
  const t=typeof v==='number'?(v<1e12?v*1000:v):Date.parse(String(v||''));
  return isFinite(t)?t:null;
}
function rel(v){
  const t=when(v);if(t===null)return '—';
  const d=Math.max(0,Math.round((Date.now()-t)/1000));
  if(d<10)return 'az önce';if(d<60)return d+' sn önce';
  if(d<3600)return Math.floor(d/60)+' dk önce';
  if(d<86400)return Math.floor(d/3600)+' sa önce';
  return Math.floor(d/86400)+' gün önce';
}
function hms(v){const t=when(v);return t===null?'—':new Date(t).toLocaleTimeString('tr-TR',{hour12:false})}
const STATUS_TR={success:'Başarılı',partial:'Kısmi',failure:'Başarısız'};
const STATUS_ST={success:'ok',partial:'warn',failure:'fail'};
function pillFor(status){const p=T('span','pill',STATUS_TR[status]||String(status||'—'));p.dataset.state=STATUS_ST[status]||'';return p}

/* ======================= 1. Feedback on answers ======================= */
function fbEligible(e){
  if(!e||e.status!=='completed'||!e.id||!e.result)return false;
  const r=e.result;return !r.action_refused&&!!r.model;
}
function fbSig(f){return [f.rating,f.open,f.busy,f.msg,f.err,f.dead,f.sentCorr].join('|')}
async function fbSend(entry,rating){
  const f=entry.fb;if(f.busy||f.dead)return;
  const correction=rating==='down'?String(f.draft||'').trim().slice(0,1000):'';
  const payload={job_id:entry.id,rating};if(correction)payload.correction=correction;
  f.busy=true;f.err='';f.msg='';fbRender(entry,true);
  try{
    const r=await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await readJSON(r);
    if(!r.ok){
      const m=(j&&j.error)||('HTTP '+r.status);
      if(r.status===404){f.dead=true;f.err='Sunucu yeniden başlatılmış olabilir; bu yanıt artık değerlendirilemez. ('+m+')'}
      else f.err=m;
    }else{
      f.rating=rating;f.open=rating==='down';f.sentCorr=!!correction;
      f.msg=rating==='up'?'Kaydedildi: beğendim':'Kaydedildi: beğenmedim'+(correction?' · düzeltmen iletildi':'');
      feed('Yanıt geri bildirimi kaydedildi ('+(rating==='up'?'beğendim':'beğenmedim')+')','ok');
    }
  }catch(e){f.err=(e&&e.message)||'Gönderilemedi'}
  f.busy=false;f.focus=rating==='down'&&!f.err&&!f.dead?'fb-input':'fb-'+rating;
  fbRender(entry,true);
}
function fbRender(entry,force){
  const box=$('#answerFb');if(!box)return;
  if(!fbEligible(entry)||asks[0]!==entry){box.hidden=true;box.replaceChildren();box._key=null;return}
  const f=entry.fb||(entry.fb={rating:null,open:false,draft:'',busy:false,msg:'',err:'',dead:false,sentCorr:false,focus:null});
  const key=entry.id+'#'+fbSig(f);
  if(!force&&box._key===key)return;
  box._key=key;box.hidden=false;box.replaceChildren();
  const row=T('div','fb-row');row.append(T('span','fb-q','Bu yanıt işine yaradı mı?'));
  for(const [rt,label] of [['up','Beğendim'],['down','Beğenmedim']]){
    const b=T('button','fb-btn',label);b.type='button';b.dataset.fb='fb-'+rt;
    b.setAttribute('aria-pressed',String(f.rating===rt));b.disabled=f.busy||f.dead;
    b.addEventListener('click',()=>{if(rt==='up'){fbSend(entry,'up')}else{f.open=true;f.focus='fb-input';fbRender(entry,true)}});
    row.append(b);
  }
  const status=T('span','fb-status');status.setAttribute('role','status');
  if(f.busy)status.textContent='Gönderiliyor…';else if(f.msg)status.textContent=f.msg;
  row.append(status);box.append(row);
  if(f.err){const er=T('p','fb-err',f.err);er.setAttribute('role','alert');box.append(er)}
  if(f.open&&!f.dead){
    const line=T('div','fb-correct');
    const lab=T('label','vh','Doğrusu neydi? (isteğe bağlı)');lab.htmlFor='fb-input';
    const inp=T('input');inp.id='fb-input';inp.type='text';inp.maxLength=1000;inp.placeholder='Doğrusu neydi? (isteğe bağlı)';inp.value=f.draft||'';inp.dataset.fb='fb-input';inp.disabled=f.busy;
    inp.addEventListener('input',()=>{f.draft=inp.value});
    inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();fbSend(entry,'down')}});
    const go=T('button','fb-btn primary',f.rating==='down'?'Güncelle':'Gönder');go.type='button';go.disabled=f.busy;
    go.addEventListener('click',()=>fbSend(entry,'down'));
    line.append(lab,inp,go);box.append(line);
  }
  if(f.focus){const t=box.querySelector('[data-fb="'+f.focus+'"]');f.focus=null;if(t&&!t.disabled)t.focus({preventScroll:true})}
}

/* ======================= 2. Task trace ======================= */
const tr={sel:null,listSeq:0,detSeq:0,tasks:[],sig:'',detSig:'',loaded:false};
function tile(id,state,val,note){
  const li=document.getElementById(id);if(!li)return;
  li.dataset.state=state;li.querySelector('.st-val').textContent=val;li.querySelector('.st-note').textContent=note||'';
}
function traceStepLabel(s){const k=[s.kind,s.tool].filter(x=>x&&x!=='').map(String);return k.length?k.join(' · '):'—'}
function renderTimeline(d){
  const box=$('#traceDetail');box.replaceChildren();
  const h=T('div','tl-head');h.append(pillFor(d.status),T('span','tl-meta',dur(d.duration_ms)+' · '+(Array.isArray(d.steps)?d.steps.length:0)+' adım · '+rel(d.finished||d.started)));
  box.append(h);
  const steps=Array.isArray(d.steps)?d.steps:[];
  if(!steps.length){box.append(T('p','empty','Bu görev için adım kaydı yok.'));return}
  const ol=T('ol','tl');ol.setAttribute('aria-label','Görev adımları');
  for(const s of steps){
    const li=T('li','tl-step');li.dataset.state=({success:'ok',partial:'warn',failure:'fail'})[s.outcome]||'';
    const top=T('div','tl-top');
    top.append(T('time','tl-time',hms(s.t)),T('span','tl-agent',s.agent||'—'),T('span','tl-stage',traceStepLabel(s)));
    if(s.outcome){const o=T('span','pill',STATUS_TR[s.outcome]||s.outcome);o.dataset.state=STATUS_ST[s.outcome]||'';top.append(o)}
    top.append(T('span','tl-dur',dur(typeof s.duration_ms==='number'?s.duration_ms:null)));
    li.append(top);
    const sub=[];if(s.model)sub.push('model: '+s.model);if(s.source)sub.push(s.source==='experience'?'deneyim kaydı':'olay kaydı');
    if(sub.length)li.append(T('p','tl-sub',sub.join(' · ')));
    if(s.summary)li.append(T('p','tl-sum',String(s.summary).slice(0,600)));
    ol.append(li);
  }
  box.append(ol);
}
async function traceSelect(id,focus){
  tr.sel=id;paintList();
  const seq=++tr.detSeq,box=$('#traceDetail');
  if(!id){box.replaceChildren(T('p','empty','Ayrıntı için soldan bir görev seç.'));return}
  if(tr.detId!==id){box.replaceChildren(T('p','loading','Yükleniyor…'));tr.detSig=''}
  tr.detId=id;
  try{
    const d=await getJSON('/api/task-trace?id='+encodeURIComponent(id));
    if(seq!==tr.detSeq||tr.sel!==id)return;/* a newer selection or refresh owns the view */
    const sig=JSON.stringify(d);if(sig!==tr.detSig){tr.detSig=sig;renderTimeline(d)}
    if(focus)$('#traceDetail').focus({preventScroll:false});
  }catch(e){
    if(seq!==tr.detSeq||tr.sel!==id)return;
    const p=T('p','fb-err','Ayrıntı yüklenemedi: '+e.message);p.setAttribute('role','alert');box.replaceChildren(p);tr.detSig='';
  }
}
function paintList(){
  const root=$('#traceList'),ae=document.activeElement,keep=ae&&ae.classList&&ae.classList.contains('trace-item')&&root.contains(ae)?ae.dataset.id:null;
  root.replaceChildren();
  if(!tr.tasks.length){root.append(T('p','empty','Henüz kayıtlı görev yok. Ajanlar çalıştıkça adımları burada görünür.'));return}
  const ul=T('ul','trace-list');
  for(const t of tr.tasks){
    const li=T('li'),b=T('button','trace-item');b.type='button';b.dataset.state=STATUS_ST[t.status]||'';
    b.setAttribute('aria-pressed',String(t.task_id===tr.sel));b.dataset.id=String(t.task_id);if(keep!==null&&keep===String(t.task_id))setTimeout(()=>b.focus({preventScroll:true}),0);
    const top=T('span','ti-top');top.append(T('span','ti-title',t.title||t.task_id||'—'),pillFor(t.status));
    const agents=Array.isArray(t.agents)?t.agents.join(', '):'';
    const meta=T('span','ti-meta',[dur(t.duration_ms),(t.steps||0)+' adım',agents,rel(t.finished||t.started)].filter(Boolean).join(' · '));
    b.append(top,meta);b.addEventListener('click',()=>traceSelect(t.task_id,false));li.append(b);ul.append(li);
  }
  root.append(ul);
}
async function traceLoad(){
  if(!document.getElementById('panel-trace'))return;
  const seq=++tr.listSeq;
  try{
    const j=await getJSON('/api/task-traces?limit=50');
    if(seq!==tr.listSeq)return;
    const s=j.summary||{},slow=Array.isArray(s.slowest)&&s.slowest[0]?s.slowest[0]:null;
    tile('tt-count','ok',String(s.tasks||0),'');
    tile('tt-failed',s.failed?'fail':'ok',String(s.failed||0),s.failed?'incelemeye değer':'');
    tile('tt-avg','unknown',dur(s.avg_duration_ms),'');
    tile('tt-slow','unknown',slow?dur(slow.duration_ms):'—',slow?String(slow.title||slow.task_id||'').slice(0,60):'');
    tr.tasks=Array.isArray(j.tasks)?j.tasks:[];
    const sig=JSON.stringify(tr.tasks.map(t=>[t.task_id,t.status,t.duration_ms,t.steps,t.finished]));
    const first=!tr.loaded;tr.loaded=true;
    if(sig!==tr.sig||first){tr.sig=sig;paintList()}
    $('#traceErr').hidden=true;
    if(tr.sel&&!tr.tasks.some(t=>t.task_id===tr.sel)){tr.sel=null;tr.detId=null;traceSelect(null)}
    else if(tr.sel)traceSelect(tr.sel,false);
    else if(first)traceSelect(null);
  }catch(e){
    if(seq!==tr.listSeq)return;
    const er=$('#traceErr');er.textContent='Görev izi yüklenemedi: '+e.message;er.hidden=false;
  }
}
function traceTick(){if(typeof currentTab!=='undefined'&&currentTab==='trace')return traceLoad()}

/* ======================= 3. Runnable skills ======================= */
const rs={sig:'',state:new Map(),nodes:new Map()};
function rsState(name){let s=rs.state.get(name);if(!s){s={input:'{}',busy:false,err:'',result:null};rs.state.set(name,s)}return s}
function paintRun(name){
  const n=rs.nodes.get(name);if(!n||!n.root.isConnected)return;
  const s=rsState(name);
  n.go.disabled=s.busy;n.go.textContent=s.busy?'Çalışıyor…':"Docker'da çalıştır";n.input.disabled=s.busy;
  n.err.textContent=s.err;n.err.hidden=!s.err;
  const out=n.out;out.replaceChildren();
  const r=s.result;if(!r){out.hidden=true;return}
  out.hidden=false;
  const head=T('div','rs-head');const p=T('span','pill',({success:'Başarılı',failure:'Başarısız',blocked:'Engellendi'})[r.status]||String(r.status||'—'));
  p.dataset.state=({success:'ok',failure:'fail',blocked:'warn'})[r.status]||'';
  head.append(p,T('span','rs-meta',(typeof r.elapsed_s==='number'?r.elapsed_s.toFixed(1)+' sn':'')+(r.sha256?' · '+String(r.sha256).slice(0,12):'')));
  out.append(head);
  if(r.status==='blocked'){
    out.append(T('p','rs-note','Docker motoru çalışmıyor. Docker Desktop açık olmalı; AXIS beceri kodunu asla ana makinede çalıştırmaz, bu yüzden Docker olmadan çalıştırma yapılamaz.'));
    if(r.error)out.append(T('p','rs-err',String(r.error).slice(0,400)));
    return;
  }
  if(r.error){const e=T('p','rs-err','Hata: '+String(r.error).slice(0,2000));out.append(e)}
  if(r.output!==undefined&&r.output!==null&&r.output!==''){
    out.append(T('p','rs-label','Beceri çıktısı (güvenilmeyen veri — yalnızca metin olarak gösterilir)'));
    out.append(T('pre','console rs-pre',typeof r.output==='string'?r.output:JSON.stringify(r.output,null,2)));
  }else if(r.status==='success')out.append(T('p','rs-note','Beceri çıktı üretmedi.'));
}
async function runSkill(name){
  const s=rsState(name);if(s.busy)return;
  let data;
  try{data=JSON.parse(s.input===''?'{}':s.input)}
  catch(e){s.err='Geçersiz JSON: '+e.message;s.result=null;paintRun(name);const n=rs.nodes.get(name);if(n)n.input.focus();return}
  s.err='';s.busy=true;s.result=null;paintRun(name);
  try{
    const r=await fetch('/api/skill-run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({skill:name,data})});
    const j=await readJSON(r);
    if(!r.ok)s.err=(j&&j.error)||('HTTP '+r.status);else{s.result=j;feed('Beceri Docker\'da çalıştırıldı: '+name+' → '+j.status,j.status==='success'?'ok':j.status==='blocked'?'warn':'fail',true)}
  }catch(e){s.err=(e&&e.message)||'İstek başarısız'}
  s.busy=false;paintRun(name);
}
async function runnableLoad(){
  const root=document.getElementById('apRunnable');if(!root)return;
  try{
    const list=await getJSON('/api/skills-runnable');
    const items=Array.isArray(list)?list:[];
    const sig=JSON.stringify(items.map(x=>[x.skill,x.sha256]));
    if(sig===rs.sig&&root.children.length)return;
    rs.sig=sig;root.replaceChildren();rs.nodes.clear();
    if(!items.length){root.append(T('p','empty','Çalıştırılabilir (onaylı) beceri yok. Bir beceri dosyası onaylandığında burada görünür.'));return}
    items.forEach((x,i)=>{
      const name=String(x.skill),st=rsState(name);
      const c=card('Çalıştırılabilir beceri',name,'sha256: '+String(x.sha256||'').slice(0,12)+(x.approved_at?' · onay: '+String(x.approved_at).slice(0,16).replace('T',' '):''),'approved');
      c.d.classList.add('rs-item');
      const id='rs-in-'+i;
      const lab=T('label','rs-lab','Girdi (JSON)');lab.htmlFor=id;
      const input=T('textarea','rs-input');input.id=id;input.rows=2;input.spellcheck=false;input.value=st.input;input.setAttribute('aria-describedby',id+'-e');
      input.addEventListener('input',()=>{st.input=input.value;if(st.err){st.err='';paintRun(name)}});
      const err=T('p','rs-err');err.id=id+'-e';err.setAttribute('role','alert');err.hidden=true;
      const go=T('button','primary','Docker\'da çalıştır');go.type='button';go.addEventListener('click',()=>runSkill(name));
      c.acts.append(go);
      const out=T('div','rs-out');out.setAttribute('aria-live','polite');out.hidden=true;
      c.d.insertBefore(err,c.acts);c.d.insertBefore(input,err);c.d.insertBefore(lab,input);c.d.append(out);
      root.append(c.d);rs.nodes.set(name,{root:c.d,input,go,err,out});paintRun(name);
    });
  }catch(e){
    root.replaceChildren(T('p','empty','Beceri listesi yüklenemedi: '+e.message));rs.sig='';
  }
}

/* ======================= 4. Memory index tile ======================= */
async function memoryTick(){
  try{
    const m=await getJSON('/api/memory-status');
    const items=+m.items||0,emb=+m.embedded||0,pending=Math.max(0,items-emb);
    const val=emb+' / '+items,model=m.model?String(m.model):'';
    if(m.available===false)setSt('memory','fail',val,'Gömme modeli erişilemiyor'+(model?' ('+model+')':''));
    else if(pending>0)setSt('memory','warn',val,pending+' kayıt bekliyor'+(model?' · '+model:''));
    else if(m.available===true)setSt('memory','ok',val,model);
    else setSt('memory','unknown',val,(model?model+' · ':'')+'henüz denetlenmedi');
  }catch(e){setSt('memory','unknown','—',e.message)}
}
async function memoryBackfill(){
  feed('Bellek dizini güncelleniyor…','info');
  try{
    const r=await postJSON('/api/memory-backfill',{});
    const emb=+r.embedded||0,pen=+r.pending||0;
    const msg=r.available===false?'Gömme modeline ulaşılamıyor; dizin güncellenemedi ('+pen+' kayıt bekliyor)':(emb===0&&pen===0)?'Dizin zaten güncel; bekleyen kayıt yok':emb+' kayıt gömüldü, '+pen+' bekliyor';
    toast(msg,r.available===false?'fail':'ok');feed(msg,r.available===false?'fail':'ok',true);
  }catch(e){toast('Dizin güncellenemedi: '+e.message,'fail');feed('Dizin güncellenemedi: '+e.message,'fail',true)}
  await memoryTick();
}

return {dur,rel,fbRender,fbEligible,traceLoad,traceTick,runnableLoad,memoryTick,memoryBackfill};
})();
