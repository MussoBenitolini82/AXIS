/* AXIS ağı — unified interactive network view (Canvas 2D, no libraries).
   Contract: window.AxisGraph = { mount(el,{onNodeSelect,onLayerFocus}), setLayers({neural,knowledge,skills,learning}),
                                  toggleLayer(name,on), focus(idOrLayer), destroy() }
   Security: all text reaches the page through canvas fillText or textContent only. */
(function () {
  'use strict';

  var LAYERS = ['neural', 'knowledge', 'skills', 'learning'];
  var LNAME = { neural: 'Sinir ağı', knowledge: 'Bilgi', skills: 'Beceriler', learning: 'Öğrenme' };
  var REF_FIELDS = ['concepts', 'topics', 'skills', 'skill_ids', 'concept_ids', 'refs', 'used_skills'];
  var MAX_NODES_PER_LAYER = 6000;
  var DARK = {
    bg: '#090B10', surface: '#11151F', elevated: '#181E2C', border: '#252D3F', text: '#EDF1F7', muted: '#8A96AD',
    accent: '#6366F1', accent2: '#22D3EE', focus: '#22D3EE', sigPos: '#38BDF8', sigNeg: '#FB923C', sigZero: '#334155',
    neural: '#22D3EE', knowledge: '#6366F1', skills: '#F59E0B', learning: '#10B981'
  };
  var LIGHT = {
    bg: '#F4F6FA', surface: '#FFFFFF', elevated: '#EEF2F8', border: '#D8E0ED', text: '#0F172A', muted: '#5B6880',
    accent: '#4F46E5', accent2: '#0891B2', focus: '#0E7490', sigPos: '#0284C7', sigNeg: '#EA580C', sigZero: '#CBD5E1',
    neural: '#0891B2', knowledge: '#4F46E5', skills: '#B45309', learning: '#059669'
  };
  var TOKEN_VARS = {
    bg: '--bg', surface: '--surface', elevated: '--elevated', border: '--border', text: '--text', muted: '--muted',
    accent: '--accent', accent2: '--accent-2', focus: '--focus', sigPos: '--sig-pos', sigNeg: '--sig-neg', sigZero: '--sig-zero',
    neural: '--layer-neural', knowledge: '--layer-knowledge', skills: '--layer-skills', learning: '--layer-learning'
  };

  /* ------------------------------------------------------------------ helpers */
  function str(v) {
    if (v == null) return '';
    if (typeof v === 'string') return v;
    if (typeof v === 'number' && isFinite(v)) return String(v);
    if (typeof v === 'boolean') return String(v);
    return '';
  }
  function arr(v) { return Array.isArray(v) ? v : []; }
  function num(v) { var n = typeof v === 'number' ? v : (typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN); return isFinite(n) ? n : null; }
  function rawIdOf(o) {
    if (o == null) return '';
    if (typeof o !== 'object') return str(o);
    return str(o.id) || str(o.name) || str(o.key);
  }
  function lc(s) { try { return s.toLocaleLowerCase('tr-TR'); } catch (e) { return s.toLowerCase(); } }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967296; }
  function trunc(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function bezier(p1x, p1y, p2x, p2y) {
    var cx = 3 * p1x, bx = 3 * (p2x - p1x) - cx, ax = 1 - cx - bx, cy = 3 * p1y, by = 3 * (p2y - p1y) - cy, ay = 1 - cy - by;
    return function (x) {
      if (x <= 0) return 0; if (x >= 1) return 1;
      var t = x;
      for (var i = 0; i < 8; i++) {
        var e = ((ax * t + bx) * t + cx) * t - x; if (Math.abs(e) < 1e-5) break;
        var d = (3 * ax * t + 2 * bx) * t + cx; if (Math.abs(d) < 1e-6) break; t -= e / d;
      }
      t = clamp(t, 0, 1); return ((ay * t + by) * t + cy) * t;
    };
  }
  var easeCam = bezier(0.16, 1, 0.3, 1), easeOut = bezier(0.22, 1, 0.36, 1);

  /* ------------------------------------------------------------- normalisers */
  function parts(p) {
    if (!p || typeof p !== 'object') return null;
    if (Array.isArray(p)) return { nodes: p, edges: [] };
    var edges = arr(p.edges).length ? arr(p.edges) : arr(p.links);
    return { nodes: arr(p.nodes), edges: edges };
  }
  function edgeEnd(e, a, b) { var v = e[a] != null ? e[a] : e[b]; return rawIdOf(v); }
  function parseJSON(v) { if (v && typeof v === 'object') return v; if (typeof v !== 'string') return null; try { return JSON.parse(v); } catch (e) { return null; } }

  // V13 dashboard: prefer its nodes/edges; if absent, derive them from events/lessons exactly as axis_v13.dashboard() does.
  function deriveLearning(p) {
    var nodes = {}, order = [], edges = [];
    function add(n) { if (!nodes[n.id]) { nodes[n.id] = n; order.push(n); } }
    var ev = arr(p.events), byId = {};
    ev.forEach(function (e) {
      if (!e || typeof e !== 'object') return;
      var ag = str(e.agent), tk = str(e.task_id); if (!ag || !tk) return;
      byId[str(e.id)] = e;
      add({ id: 'agent:' + ag, label: ag, kind: 'agent' }); add({ id: 'task:' + tk, label: tk.slice(0, 8), kind: 'task' });
      edges.push({ source: 'agent:' + ag, target: 'task:' + tk, relation: str(e.outcome) });
    });
    arr(p.lessons).slice(0, 40).forEach(function (l) {
      if (!l || typeof l !== 'object' || !str(l.id)) return;
      var lid = 'lesson:' + str(l.id); add({ id: lid, label: str(l.signature).slice(0, 35), kind: 'lesson' });
      arr(parseJSON(l.evidence)).forEach(function (eid) { var e = byId[str(eid)]; if (e) edges.push({ source: 'task:' + str(e.task_id), target: lid, relation: 'learned_from' }); });
    });
    return { nodes: order, edges: edges };
  }

  // Returns {nodes:[{rawId,label,kind,desc,raw,col,row,short}], edges:[{s,t,relation,signal,weight,raw}], meta}
  function normalise(layer, payload) {
    var P = parts(payload);
    if (!P) return null;
    if (layer === 'learning' && !P.nodes.length && (arr(payload.events).length || arr(payload.lessons).length)) P = deriveLearning(payload);
    var out = { nodes: [], edges: [], meta: {} }, seen = {};
    var nodes = P.nodes.slice(0, MAX_NODES_PER_LAYER);
    var maxL = 0;
    if (layer === 'neural') nodes.forEach(function (n) { var L = n && num(n.layer); if (L != null && L > maxL) maxL = L; });
    nodes.forEach(function (n, i) {
      if (n == null) return;
      if (typeof n !== 'object') n = { id: n };
      var id = rawIdOf(n); if (!id || seen[id]) return; seen[id] = 1;
      var label = str(n.label) || str(n.title) || str(n.name) || id;
      var kind = str(n.kind) || str(n.type);
      var node = { rawId: id, label: label, kind: kind, desc: str(n.description) || str(n.summary) || str(n.desc), raw: n };
      if (layer === 'neural') {
        var L = num(n.layer), sl = lc(str(n.layer));
        if (/input|giriş/.test(sl)) { node.kind = 'input'; node.col = 0; }
        else if (/output|çıkış/.test(sl)) { node.kind = 'output'; node.col = 2; }
        else if (/hidden|gizli/.test(sl)) { node.kind = 'hidden'; node.col = 1; }
        else if (L != null) { node.kind = L === 0 ? 'input' : (L === maxL ? 'output' : 'hidden'); node.col = L; }
        else { node.kind = 'hidden'; node.col = 1; }
        node.row = num(n.index);
      } else if (!node.kind) node.kind = layer === 'knowledge' ? 'concept' : layer === 'skills' ? 'skill' : 'event';
      out.nodes.push(node);
    });
    if (layer === 'neural') {
      // column layout + short names a,b | h1..h8 | y
      var cols = {};
      out.nodes.forEach(function (n) { (cols[n.col] = cols[n.col] || []).push(n); });
      var keys = Object.keys(cols).map(Number).sort(function (a, b) { return a - b; });
      keys.forEach(function (k, ci) {
        var list = cols[k].slice().sort(function (a, b) { return (a.row == null ? 0 : a.row) - (b.row == null ? 0 : b.row); });
        list.forEach(function (n, r) {
          n.colIdx = ci; n.rowIdx = r; n.colSize = list.length;
          n.short = n.kind === 'input' ? (list.length <= 26 ? String.fromCharCode(97 + r) : 'x' + (r + 1)) : n.kind === 'output' ? (list.length === 1 ? 'y' : 'y' + (r + 1)) : 'h' + (r + 1);
        });
      });
      out.meta.cols = Math.max(1, keys.length);
      out.meta.maxRows = keys.reduce(function (m, k) { return Math.max(m, cols[k].length); }, 1);
      out.meta.loss = num(payload.loss); out.meta.trained = payload.trained; out.meta.prediction = num(payload.prediction);
    }
    P.edges.forEach(function (e) {
      if (!e || typeof e !== 'object') return;
      var s = edgeEnd(e, 'source', 'from'), t = edgeEnd(e, 'target', 'to');
      if (!s || !t) return;
      out.edges.push({ s: s, t: t, relation: str(e.relation) || str(e.type) || str(e.label), signal: num(e.signal), weight: num(e.weight), raw: e });
    });
    if (layer === 'learning') {
      // V13 skill_composition events carry their parent skill ids in payload.parents (axis_learning.compose).
      arr(payload && payload.events).forEach(function (ev) {
        if (!ev || typeof ev !== 'object' || str(ev.kind) !== 'skill_composition') return;
        var pl = parseJSON(ev.payload); if (!pl) return;
        arr(pl.parents).forEach(function (sid) { if (str(sid)) out.edges.push({ s: 'task:' + str(ev.task_id), t: str(sid), relation: 'skill_composition', alt: 'skill:' + str(sid), raw: ev }); });
      });
    }
    return out;
  }

  /* ---------------------------------------------------------------- styles */
  var CSS = [
    '.axg-root{position:relative;width:100%;height:100%;min-height:260px;overflow:hidden;background:var(--bg,#090B10);color:var(--text,#EDF1F7);font:12.5px/1.4 var(--font-ui,"Segoe UI",system-ui,sans-serif);-webkit-user-select:none;user-select:none}',
    '.axg-canvas{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;outline:none;cursor:grab}',
    '.axg-canvas:focus-visible{box-shadow:inset 0 0 0 2px var(--focus,#22D3EE)}',
    '.axg-glass{background:var(--glass,rgba(17,21,31,.78));-webkit-backdrop-filter:blur(12px) saturate(140%);backdrop-filter:blur(12px) saturate(140%);border:1px solid var(--border,#252D3F);border-radius:var(--r-md,10px);box-shadow:var(--sh-2,0 8px 24px rgba(0,0,0,.45))}',
    '.axg-hud{position:absolute;top:8px;left:8px;width:min(320px,calc(100% - 16px));padding:8px;display:flex;flex-direction:column;gap:6px;z-index:2;box-sizing:border-box}',
    '.axg-search{position:relative}',
    '.axg-search input{width:100%;box-sizing:border-box;height:32px;padding:0 10px;border-radius:var(--r-sm,6px);border:1px solid var(--border,#252D3F);background:var(--surface,#11151F);color:var(--text,#EDF1F7);font:inherit;outline:none}',
    '.axg-search input:focus-visible{box-shadow:0 0 0 2px var(--focus,#22D3EE)}',
    '.axg-results{list-style:none;margin:4px 0 0;padding:4px;position:absolute;left:0;right:0;top:100%;z-index:3;max-height:280px;overflow:auto}',
    '.axg-results[hidden]{display:none}',
    '.axg-results li{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:var(--r-sm,6px);cursor:pointer;min-height:28px}',
    '.axg-results li[aria-selected=true],.axg-results li:hover{background:color-mix(in srgb,var(--accent,#6366F1) 18%,transparent)}',
    '.axg-results .axg-lbl{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.axg-results .axg-sub{color:var(--muted,#8A96AD);font-size:11px}',
    '.axg-chips{display:flex;flex-wrap:wrap;gap:4px}',
    '.axg-chip{display:inline-flex;align-items:center;border-radius:var(--r-pill,999px);border:1px solid var(--border,#252D3F);background:var(--surface,#11151F);overflow:hidden}',
    '.axg-chip button{all:unset;box-sizing:border-box;display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 9px;cursor:pointer;color:var(--muted,#8A96AD);font-size:12px}',
    '.axg-chip button.axg-f{padding:0 7px;border-left:1px solid var(--border,#252D3F)}',
    '.axg-chip button:focus-visible{box-shadow:inset 0 0 0 2px var(--focus,#22D3EE)}',
    '.axg-chip button[aria-pressed=true]{color:var(--text,#EDF1F7);background:color-mix(in srgb,var(--c) 16%,transparent)}',
    '.axg-chip.axg-missing{opacity:.45}',
    '.axg-chip.axg-focused{border-color:var(--c)}',
    '.axg-glyph{width:9px;height:9px;background:var(--c);flex:none}',
    '.axg-g-circle{border-radius:50%}.axg-g-ring{border-radius:50%;box-shadow:0 0 0 2px color-mix(in srgb,var(--c) 45%,transparent)}',
    '.axg-g-diamond{transform:rotate(45deg) scale(.85)}.axg-g-square{border-radius:2px}',
    '.axg-cnt{font-family:var(--font-mono,Consolas,monospace);font-variant-numeric:tabular-nums;font-size:11px}',
    '.axg-meta{color:var(--muted,#8A96AD);font-size:11px;display:flex;justify-content:space-between;gap:8px}',
    '.axg-zoom{position:absolute;right:8px;bottom:8px;display:flex;flex-direction:column;gap:4px;padding:4px;z-index:2}',
    '.axg-zoom button{all:unset;box-sizing:border-box;width:36px;height:36px;display:grid;place-items:center;border-radius:var(--r-sm,6px);cursor:pointer;color:var(--text,#EDF1F7);font-size:16px}',
    '.axg-zoom button.axg-fit{font-size:10.5px}',
    '.axg-zoom button:hover{background:color-mix(in srgb,var(--text,#EDF1F7) 8%,transparent)}',
    '.axg-zoom button:focus-visible{box-shadow:0 0 0 2px var(--focus,#22D3EE)}',
    '.axg-mini{position:absolute;left:8px;bottom:8px;width:140px;height:100px;z-index:2;cursor:pointer;touch-action:none;padding:0}',
    '.axg-root.axg-narrow .axg-mini{display:none}',
    '.axg-root.axg-narrow .axg-chip button,.axg-root.axg-narrow .axg-search input{min-height:40px}',
    '.axg-root.axg-narrow .axg-zoom button{width:44px;height:44px}',
    '.axg-root.axg-narrow .axg-nm{display:none}',
    '.axg-tip{position:absolute;z-index:4;pointer-events:none;max-width:260px;padding:8px 10px;background:var(--elevated,#181E2C);border:1px solid var(--border,#252D3F);border-radius:var(--r-md,10px);box-shadow:var(--sh-2,0 8px 24px rgba(0,0,0,.45));font-size:12.5px;opacity:0;transition:opacity var(--t-fast,120ms)}',
    '.axg-tip.axg-on{opacity:1}',
    '.axg-tip b{display:block;font-weight:600;margin-bottom:2px;overflow-wrap:anywhere}',
    '.axg-tip .axg-badge{display:inline-block;font-size:11px;padding:0 6px;border-radius:999px;margin:2px 4px 2px 0;background:color-mix(in srgb,var(--c,#6366F1) 20%,transparent)}',
    '.axg-tip .axg-desc{color:var(--muted,#8A96AD);margin-top:3px;overflow-wrap:anywhere}',
    '.axg-empty{position:absolute;inset:0;display:grid;place-items:center;text-align:center;color:var(--muted,#8A96AD);padding:24px;pointer-events:none;font-size:14px}',
    '.axg-empty[hidden]{display:none}',
    '.axg-sr{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}',
    '.axg-list:focus-within{position:absolute!important;width:auto;height:auto;clip:auto;margin:0;white-space:normal;left:8px;bottom:8px;max-height:50%;max-width:calc(100% - 16px);overflow:auto;z-index:5;padding:8px;background:var(--elevated,#181E2C);border:1px solid var(--border,#252D3F);border-radius:10px}',
    '.axg-list ul{list-style:none;margin:0;padding:0}.axg-list button{all:unset;display:block;padding:4px 6px;cursor:pointer;border-radius:4px}',
    '.axg-list button:focus-visible{box-shadow:0 0 0 2px var(--focus,#22D3EE)}'
  ].join('\n');

  /* -------------------------------------------------------------- instance */
  function Instance(host, opts) {
    opts = opts || {};
    var doc = host.ownerDocument || document, win = doc.defaultView || window;
    var listeners = [];
    function on(t, type, fn, o) { t.addEventListener(type, fn, o); listeners.push([t, type, fn, o]); }
    function mk(tag, cls, parent) { var e = doc.createElement(tag); if (cls) e.className = cls; if (parent) parent.appendChild(e); return e; }
    var uid = 'axg' + Math.floor(Math.random() * 1e9).toString(36);

    /* ---- DOM */
    var styleEl = mk('style'); styleEl.textContent = CSS; (doc.head || doc.documentElement).appendChild(styleEl);
    var root, canvas, movedCanvas = null;
    if (host.tagName === 'CANVAS') {
      canvas = host; root = doc.createElement('div'); root.className = 'axg-root';
      movedCanvas = { parent: host.parentNode, next: host.nextSibling, cls: host.className };
      host.parentNode.insertBefore(root, host); root.appendChild(host); canvas.classList.add('axg-canvas');
    } else {
      root = mk('div', 'axg-root', host); canvas = mk('canvas', 'axg-canvas', root);
    }
    canvas.setAttribute('role', 'img'); canvas.tabIndex = 0;
    canvas.setAttribute('aria-label', 'AXIS ağı');
    var ctx = canvas.getContext('2d');

    var hud = mk('div', 'axg-hud axg-glass', root);
    var searchWrap = mk('div', 'axg-search', hud);
    var search = mk('input', '', searchWrap);
    search.type = 'search'; search.placeholder = 'Düğüm ara…'; search.setAttribute('aria-label', 'Düğüm ara');
    search.setAttribute('role', 'combobox'); search.setAttribute('aria-autocomplete', 'list'); search.setAttribute('aria-expanded', 'false');
    search.setAttribute('aria-controls', uid + '-res'); search.autocomplete = 'off'; search.spellcheck = false;
    var results = mk('ul', 'axg-results axg-glass', searchWrap); results.id = uid + '-res'; results.setAttribute('role', 'listbox'); results.hidden = true;
    results.setAttribute('aria-label', 'Arama sonuçları');
    var chipsEl = mk('div', 'axg-chips', hud); chipsEl.setAttribute('role', 'group'); chipsEl.setAttribute('aria-label', 'Katmanlar');
    var metaEl = mk('div', 'axg-meta', hud); var crossEl = mk('span', '', metaEl); var zoomTxt = mk('span', 'axg-cnt', metaEl);
    var chips = {};
    LAYERS.forEach(function (L) {
      var c = mk('div', 'axg-chip', chipsEl); c.style.setProperty('--c', 'var(--layer-' + L + ',' + DARK[L] + ')');
      var b = mk('button', '', c); b.type = 'button'; b.setAttribute('aria-pressed', 'true');
      var g = mk('span', 'axg-glyph ' + (L === 'neural' ? 'axg-g-ring' : L === 'knowledge' ? 'axg-g-circle' : L === 'skills' ? 'axg-g-diamond' : 'axg-g-square'), b);
      g.setAttribute('aria-hidden', 'true');
      var nm = mk('span', 'axg-nm', b); nm.textContent = LNAME[L];
      var cnt = mk('span', 'axg-cnt', b); cnt.textContent = '0';
      var f = mk('button', 'axg-f', c); f.type = 'button'; f.textContent = '◎'; f.setAttribute('aria-label', LNAME[L] + ' katmanına odaklan'); f.title = 'odaklan';
      chips[L] = { wrap: c, btn: b, cnt: cnt, focusBtn: f };
      on(b, 'click', function () { toggleLayer(L); });
      on(b, 'dblclick', function (e) { e.preventDefault(); focusLayer(L, true); });
      on(f, 'click', function () { focusLayer(L, true); });
    });
    var zoomBox = mk('div', 'axg-zoom axg-glass', root);
    var zIn = mk('button', '', zoomBox); zIn.type = 'button'; zIn.textContent = '+'; zIn.setAttribute('aria-label', 'Yakınlaştır');
    var zOut = mk('button', '', zoomBox); zOut.type = 'button'; zOut.textContent = '−'; zOut.setAttribute('aria-label', 'Uzaklaştır');
    var zFit = mk('button', 'axg-fit', zoomBox); zFit.type = 'button'; zFit.textContent = 'Sığdır'; zFit.setAttribute('aria-label', 'Tümünü sığdır');
    var mini = mk('canvas', 'axg-mini axg-glass', root); mini.setAttribute('aria-hidden', 'true');
    var mctx = mini.getContext('2d');
    var tip = mk('div', 'axg-tip', root); tip.setAttribute('aria-hidden', 'true');
    var empty = mk('div', 'axg-empty', root); empty.textContent = 'Ağ boş. Sohbet ederek veya kaynak ekleyerek başlayın.';
    var live = mk('div', 'axg-sr', root); live.setAttribute('aria-live', 'polite');
    var listBox = mk('nav', 'axg-sr axg-list', root); listBox.setAttribute('aria-label', 'Düğüm listesi');
    var listTitle = mk('div', '', listBox); listTitle.textContent = 'Düğüm listesi (en çok bağlantılı 50)';
    var listUl = mk('ul', '', listBox);

    /* ---- state */
    var W = 300, H = 200, dpr = 1;
    var cam = { x: 0, y: 0, k: 1 }, userMovedCam = false;
    var reduced = false, mqReduced = win.matchMedia ? win.matchMedia('(prefers-reduced-motion: reduce)') : null;
    var mqDark = win.matchMedia ? win.matchMedia('(prefers-color-scheme: dark)') : null;
    reduced = !!(mqReduced && mqReduced.matches);
    var theme = {}, fontUi = '"Segoe UI",system-ui,sans-serif', fontMono = 'Consolas,monospace';
    var N = 0, nodes = [], X = new Float32Array(0), Y = X, VX = X, VY = X, SIM = new Uint8Array(0), PIN = SIM;
    var E = 0, ES = new Int32Array(0), ET = ES, edges = [], adj = [];
    var simIdx = new Int32Array(0), alpha = 0, simOn = false;
    var idIndex = new Map(), rawIndex = new Map();
    var layerCount = { neural: 0, knowledge: 0, skills: 0, learning: 0 }, layerPresent = {}, crossCount = 0;
    var layerOn = { neural: 1, knowledge: 1, skills: 1, learning: 1 }, layerVis = { neural: 1, knowledge: 1, skills: 1, learning: 1 };
    var layerDim = { neural: 1, knowledge: 1, skills: 1, learning: 1 }, focusedLayer = null, camBeforeFocus = null;
    var anchors = {}, byDeg = [], hubDeg = 1;
    var neural = { cx: 0, cy: 0, scale: 1, cols: 1, rows: 1, meta: {}, idx: [], maxAbs: 1, halfW: 50, halfH: 50 };
    var hover = -1, selected = -1, kbIdx = -1, searchSet = null, searchList = [], searchActive = -1;
    var tweens = new Map(), raf = 0, destroyed = false, frameCount = 0, miniDirty = true;
    var hashDirty = true, hashMap = new Map(), HCELL = 48;
    var labelW = new Map();
    var highlight = null;

    /* ---- theme */
    function normColor(c, fb) {
      if (!c) return fb;
      var probe = normColor.ctx || (normColor.ctx = doc.createElement('canvas').getContext('2d'));
      probe.fillStyle = '#000'; probe.fillStyle = c; var a = probe.fillStyle;
      probe.fillStyle = '#fff'; probe.fillStyle = c; return a === probe.fillStyle ? a : fb;
    }
    function rgbOf(c) {
      var m = /^#([0-9a-f]{6})$/i.exec(c); if (m) { var v = parseInt(m[1], 16); return [v >> 16 & 255, v >> 8 & 255, v & 255]; }
      m = /rgba?\(([^)]+)\)/.exec(c); if (m) { var p = m[1].split(',').map(Number); return [p[0] | 0, p[1] | 0, p[2] | 0]; }
      return [128, 128, 128];
    }
    function mix(a, b, t) { var A = rgbOf(a), B = rgbOf(b); return 'rgb(' + Math.round(A[0] + (B[0] - A[0]) * t) + ',' + Math.round(A[1] + (B[1] - A[1]) * t) + ',' + Math.round(A[2] + (B[2] - A[2]) * t) + ')'; }
    function readTheme() {
      var cs = win.getComputedStyle(root), de = doc.documentElement;
      var dt = (de.getAttribute('data-theme') || (doc.body && doc.body.getAttribute('data-theme')) || '');
      var light = dt === 'light' || (!dt && mqDark && !mqDark.matches);
      var fb = light ? LIGHT : DARK;
      Object.keys(TOKEN_VARS).forEach(function (k) { theme[k] = normColor(cs.getPropertyValue(TOKEN_VARS[k]).trim(), fb[k]); });
      theme.light = rgbOf(theme.bg).reduce(function (a, b) { return a + b; }, 0) > 382;
      fontUi = cs.getPropertyValue('--font-ui').trim() || fontUi; fontMono = cs.getPropertyValue('--font-mono').trim() || fontMono;
      theme.kindTint = {
        topic: mix(theme.knowledge, theme.light ? '#000000' : '#ffffff', 0.32),
        paper: mix(theme.knowledge, theme.light ? '#ffffff' : '#000000', 0.3)
      };
      labelW.clear(); miniDirty = true; invalidate();
    }

    /* ---- data */
    function setLayers(data) {
      data = data || {};
      var old = new Map();
      for (var i = 0; i < N; i++) old.set(nodes[i].id, [X[i], Y[i], PIN[i]]);
      var oldSel = selected >= 0 ? nodes[selected].id : null;
      var norm = {};
      LAYERS.forEach(function (L) {
        var v = data[L];
        var n = null; try { n = normalise(L, v); } catch (e) { n = null; if (win.console) console.warn('AxisGraph: ' + L + ' normalisation failed', e); }
        norm[L] = n; layerPresent[L] = !!n;
      });
      // nodes
      nodes = []; idIndex = new Map(); rawIndex = new Map();
      LAYERS.forEach(function (L, li) {
        layerCount[L] = 0;
        if (!norm[L]) return;
        norm[L].nodes.forEach(function (n) {
          var id = L + ':' + n.rawId;
          if (idIndex.has(id)) return;
          var o = { id: id, rawId: n.rawId, layer: L, li: li, kind: n.kind, label: n.label, labelLc: lc(n.label), desc: n.desc, raw: n.raw, deg: 0, r: 4,
            short: n.short, colIdx: n.colIdx, rowIdx: n.rowIdx, colSize: n.colSize, lx: 0, ly: 0 };
          idIndex.set(id, nodes.length); nodes.push(o); layerCount[L]++;
          var a = rawIndex.get(n.rawId); if (a) a.push(nodes.length - 1); else rawIndex.set(n.rawId, [nodes.length - 1]);
        });
      });
      N = nodes.length;
      var labelIndex = new Map();
      nodes.forEach(function (n, i) { var a = labelIndex.get(n.labelLc); if (a) a.push(i); else labelIndex.set(n.labelLc, [i]); });
      // edge resolution
      function resolve(L, ref, alt) {
        if (!ref) return -1;
        var i = idIndex.get(L + ':' + ref); if (i != null) return i;
        i = idIndex.get(ref); if (i != null) return i;                       // already namespaced
        var c = rawIndex.get(ref); if (c && c.length === 1) return c[0];   // unique raw id in another layer
        if (alt) { c = rawIndex.get(alt); if (c && c.length === 1) return c[0]; }
        return -1;
      }
      var eList = [], seenE = new Set();
      function addEdge(s, t, rel, extra) {
        if (s < 0 || t < 0 || s === t) return;
        var key = s + '>' + t + '|' + rel; if (seenE.has(key)) return; seenE.add(key);
        var cross = nodes[s].layer !== nodes[t].layer;
        eList.push({ s: s, t: t, relation: rel, cross: cross, signal: extra ? extra.signal : null, weight: extra ? extra.weight : null, neural: !cross && nodes[s].layer === 'neural' });
      }
      LAYERS.forEach(function (L) {
        if (!norm[L]) return;
        norm[L].edges.forEach(function (e) { addEdge(resolve(L, e.s), resolve(L, e.t, e.alt), e.relation, e); });
      });
      // explicit reference fields on nodes
      nodes.forEach(function (n, i) {
        var raw = n.raw; if (!raw || typeof raw !== 'object') return;
        REF_FIELDS.forEach(function (f) {
          var v = raw[f]; if (v == null) return;
          var vals = Array.isArray(v) ? v : [v];
          vals.forEach(function (x) {
            var ref = rawIdOf(x); if (!ref) return;
            var j = resolve(n.layer, ref);
            if (j < 0) { var c = labelIndex.get(lc(ref)); if (c && c.length === 1) j = c[0]; }
            addEdge(i, j, (x && typeof x === 'object' && str(x.relation)) || 'kullanır');
          });
        });
      });
      E = eList.length; edges = eList; ES = new Int32Array(E); ET = new Int32Array(E);
      adj = new Array(N); for (i = 0; i < N; i++) adj[i] = [];
      crossCount = 0;
      eList.forEach(function (e, k) { ES[k] = e.s; ET[k] = e.t; adj[e.s].push(k); adj[e.t].push(k); nodes[e.s].deg++; nodes[e.t].deg++; if (e.cross) crossCount++; });
      // degree, hubs, radius
      byDeg = nodes.map(function (_, i) { return i; }).sort(function (a, b) { return nodes[b].deg - nodes[a].deg || (nodes[a].label < nodes[b].label ? -1 : 1); });
      var simCount = 0; nodes.forEach(function (n) { if (n.layer !== 'neural') simCount++; });
      var degs = byDeg.filter(function (i) { return nodes[i].layer !== 'neural'; }).map(function (i) { return nodes[i].deg; });
      hubDeg = degs.length ? Math.max(1, degs[Math.floor(degs.length * 0.15)] || 1) : 1;
      nodes.forEach(function (n) { n.r = n.layer === 'neural' ? 4 : Math.min(14, 3.2 + Math.sqrt(n.deg) * 1.4); n.hub = n.deg >= hubDeg; });
      edges.forEach(function (e) { e.hub = e.cross || (nodes[e.s].hub && nodes[e.t].hub); });
      // arrays
      X = new Float32Array(N); Y = new Float32Array(N); VX = new Float32Array(N); VY = new Float32Array(N);
      SIM = new Uint8Array(N); PIN = new Uint8Array(N);
      var R = 90 + 6 * Math.sqrt(Math.max(1, simCount));
      anchors = { knowledge: [0, 0], skills: [R * 0.9, -R * 0.35], learning: [-R * 0.9, R * 0.35], neural: [0, 0] };
      if (layerCount.knowledge === 0) { anchors.skills = [R * 0.5, -R * 0.2]; anchors.learning = [-R * 0.5, R * 0.2]; }
      // neural cluster frame
      neural.idx = []; neural.meta = norm.neural ? norm.neural.meta : {};
      neural.cols = neural.meta.cols || 1; neural.rows = neural.meta.maxRows || 1;
      neural.halfW = Math.max(1, neural.cols - 1) * 46 / 2 + 18; neural.halfH = Math.max(1, neural.rows - 1) * 12 / 2 + 18;
      if (!old.size || !norm.neural) { neural.cx = 0; neural.cy = 0; }
      var reused = 0, simList = [];
      nodes.forEach(function (n, i) {
        if (n.layer === 'neural') {
          neural.idx.push(i);
          n.lx = (n.colIdx - (neural.cols - 1) / 2) * 46; n.ly = (n.rowIdx - (n.colSize - 1) / 2) * 12;
          return;
        }
        SIM[i] = 1; simList.push(i);
        var o = old.get(n.id);
        if (o) { X[i] = o[0]; Y[i] = o[1]; PIN[i] = o[2]; reused++; return; }
        n._new = true;
      });
      // place new nodes: next to an already-placed neighbour, else on a phyllotaxis spiral around the layer anchor
      var spiral = {};
      simList.forEach(function (i) {
        var n = nodes[i]; if (!n._new) return; delete n._new;
        var placed = false;
        for (var k = 0; k < adj[i].length && !placed; k++) {
          var e = edges[adj[i][k]], j = e.s === i ? e.t : e.s;
          if (SIM[j] && !nodes[j]._new && (X[j] || Y[j])) { var a = hash(n.id) * 6.283; X[i] = X[j] + Math.cos(a) * 30; Y[i] = Y[j] + Math.sin(a) * 30; placed = true; }
        }
        if (!placed) {
          var s = spiral[n.layer] = (spiral[n.layer] || 0) + 1, an = anchors[n.layer] || [0, 0];
          var rr = 14 * Math.sqrt(s + 8), th = s * 2.39996;
          X[i] = an[0] + Math.cos(th) * rr; Y[i] = an[1] + Math.sin(th) * rr;
        }
      });
      simIdx = Int32Array.from(simList);
      // neural signal scale
      neural.maxAbs = 0; edges.forEach(function (e) { if (e.neural) { var v = Math.abs(e.signal != null ? e.signal : (e.weight || 0)); if (v > neural.maxAbs) neural.maxAbs = v; } });
      if (!neural.maxAbs) neural.maxAbs = 1;
      // selection survives refresh by id
      hover = -1; kbIdx = -1; selected = oldSel && idIndex.has(oldSel) ? idIndex.get(oldSel) : -1;
      if (oldSel && selected < 0) emitSelect(null);
      hashDirty = true; miniDirty = true; labelW.clear();
      layoutNeural();
      // physics
      var fresh = simIdx.length - reused;
      alpha = fresh > simIdx.length * 0.2 || !reused ? 1 : 0.3;
      if (simIdx.length) {
        if (reduced) presolve(400, 900);
        else if (simIdx.length > 500 && fresh) presolve(80, 400);
        simOn = !reduced && alpha > 0.001;
      } else simOn = false;
      updateHud();
      if (searchSet) runSearch(search.value);
      if (!userMovedCam) fitAll(false);
      invalidate();
    }

    /* ---- physics: Barnes-Hut quadtree in flat typed arrays */
    var qCap = 0, qN = 0, qX0, qY0, qS, qM, qCX, qCY, qBody, qChild, qStack = new Int32Array(64);
    function qEnsure(n) {
      if (n <= qCap) return;
      var c = Math.max(n, qCap * 2, 512);
      function g(A, T, m) { var b = new T(c * (m || 1)); if (A) b.set(A.subarray(0, qN * (m || 1))); return b; }
      qX0 = g(qX0, Float64Array); qY0 = g(qY0, Float64Array); qS = g(qS, Float64Array); qM = g(qM, Float64Array);
      qCX = g(qCX, Float64Array); qCY = g(qCY, Float64Array); qBody = g(qBody, Int32Array); qChild = g(qChild, Int32Array, 4); qCap = c;
    }
    function qNew(x0, y0, s) {
      qEnsure(qN + 1); var c = qN++;
      qX0[c] = x0; qY0[c] = y0; qS[c] = s; qM[c] = 0; qCX[c] = 0; qCY[c] = 0; qBody[c] = -1;
      qChild[4 * c] = qChild[4 * c + 1] = qChild[4 * c + 2] = qChild[4 * c + 3] = -1; return c;
    }
    function qChildOf(c, x, y) {
      var h = qS[c] / 2, q = (x >= qX0[c] + h ? 1 : 0) | (y >= qY0[c] + h ? 2 : 0), ch = qChild[4 * c + q];
      if (ch < 0) { ch = qNew(qX0[c] + (q & 1 ? h : 0), qY0[c] + (q & 2 ? h : 0), h); qChild[4 * c + q] = ch; }
      return ch;
    }
    function qBuild() {
      qN = 0; var n = simIdx.length; if (!n) return false;
      var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, k, i;
      for (k = 0; k < n; k++) { i = simIdx[k]; if (X[i] < x0) x0 = X[i]; if (X[i] > x1) x1 = X[i]; if (Y[i] < y0) y0 = Y[i]; if (Y[i] > y1) y1 = Y[i]; }
      qEnsure(n * 3 + 16); qNew(x0 - 1, y0 - 1, Math.max(x1 - x0, y1 - y0) + 2);
      for (k = 0; k < n; k++) {
        i = simIdx[k]; var x = X[i], y = Y[i], c = 0, depth = 0;
        for (;;) {
          qM[c] += 1; qCX[c] += x; qCY[c] += y;
          var b = qBody[c];
          if (b === -1) { qBody[c] = i; break; }
          if (b >= 0) {
            if (depth >= 24) break;                 // coincident points: bucket in this leaf
            qBody[c] = -2;
            var ch = qChildOf(c, X[b], Y[b]); qM[ch] += 1; qCX[ch] += X[b]; qCY[ch] += Y[b]; qBody[ch] = b;
          }
          c = qChildOf(c, x, y); depth++;
        }
      }
      return true;
    }
    var THETA2 = 0.64, CHARGE = -34;
    function tick() {
      var n = simIdx.length; if (!n) return;
      var k, i, j;
      if (qBuild()) {
        if (qStack.length < qN + 8) qStack = new Int32Array(qN * 2 + 8);
        var ca = CHARGE * alpha;
        for (k = 0; k < n; k++) {
          i = simIdx[k]; var x = X[i], y = Y[i], fx = 0, fy = 0, sp = 0; qStack[sp++] = 0;
          while (sp) {
            var c = qStack[--sp], m = qM[c]; if (!m) continue;
            var dx = qCX[c] / m - x, dy = qCY[c] / m - y, d2 = dx * dx + dy * dy, s = qS[c], body = qBody[c];
            if (body !== -2 || s * s < THETA2 * d2) {
              if (body === i && m === 1) continue;
              if (d2 < 1) { if (d2 === 0) { dx = (hash(nodes[i].id) - 0.5); dy = (hash(nodes[i].id + '#') - 0.5); } d2 = 1; }
              var w = ca * m / d2; fx += dx * w; fy += dy * w;
            } else {
              for (j = 0; j < 4; j++) { var ch = qChild[4 * c + j]; if (ch >= 0) qStack[sp++] = ch; }
            }
          }
          VX[i] += fx; VY[i] += fy;
        }
      }
      // springs (d3-style, degree-biased)
      for (k = 0; k < E; k++) {
        var e = edges[k]; if (e.neural) continue;
        var a = ES[k], b = ET[k], sa = SIM[a], sb = SIM[b];
        if (!sa && !sb) continue;
        var ddx = X[b] + VX[b] - X[a] - VX[a], ddy = Y[b] + VY[b] - Y[a] - VY[a], l = Math.sqrt(ddx * ddx + ddy * ddy) || 1;
        var rest = e.cross ? 120 : 42, str_ = e.cross ? 0.12 : 0.7 / Math.max(1, Math.min(nodes[a].deg, nodes[b].deg));
        l = (l - rest) / l * alpha * str_; ddx *= l; ddy *= l;
        var bias = sa && sb ? nodes[a].deg / (nodes[a].deg + nodes[b].deg) : (sb ? 1 : 0);
        if (sb) { VX[b] -= ddx * bias; VY[b] -= ddy * bias; }
        if (sa) { VX[a] += ddx * (1 - bias); VY[a] += ddy * (1 - bias); }
      }
      // soft gravity to layer anchors + keep the XOR cluster's area clear
      var rc = Math.sqrt(neural.halfW * neural.halfW + neural.halfH * neural.halfH) + 26, hasNeural = neural.idx.length > 0;
      for (k = 0; k < n; k++) {
        i = simIdx[k]; var an = anchors[nodes[i].layer] || [0, 0];
        VX[i] += (an[0] - X[i]) * 0.018 * alpha; VY[i] += (an[1] - Y[i]) * 0.018 * alpha;
        if (hasNeural) {
          var ox = X[i] - neural.cx, oy = Y[i] - neural.cy, od = Math.sqrt(ox * ox + oy * oy);
          if (od < rc) { if (od < 0.01) { ox = 1; od = 1; } var p = (rc - od) / od * 0.25; VX[i] += ox * p; VY[i] += oy * p; }
        }
      }
      for (k = 0; k < n; k++) {
        i = simIdx[k];
        if (PIN[i] || i === dragIdx) { VX[i] = VY[i] = 0; continue; }
        VX[i] *= 0.6; VY[i] *= 0.6; X[i] += VX[i]; Y[i] += VY[i];
      }
      alpha *= 0.982; hashDirty = true;
      if (alpha < 0.001) { alpha = 0; simOn = false; miniDirty = true; if (!userMovedCam) fitAll(true); }
    }
    function presolve(maxTicks, budgetMs) {
      var t0 = performance.now();
      for (var t = 0; t < maxTicks && alpha > 0.001; t++) { tick(); if (performance.now() - t0 > budgetMs) break; }
      if (reduced) { alpha = 0; simOn = false; for (var i = 0; i < N; i++) { VX[i] = VY[i] = 0; } }
    }
    function reheat(a) { if (reduced || !simIdx.length) return; alpha = Math.max(alpha, a); simOn = true; invalidate(); }

    function layoutNeural() {
      var s = neural.scale;
      for (var k = 0; k < neural.idx.length; k++) { var i = neural.idx[k], n = nodes[i]; X[i] = neural.cx + n.lx * s; Y[i] = neural.cy + n.ly * s; }
    }
    function neuralRect(scale) {
      var s = scale == null ? neural.scale : scale;
      return { x0: neural.cx - neural.halfW * s, y0: neural.cy - neural.halfH * s, x1: neural.cx + neural.halfW * s, y1: neural.cy + neural.halfH * s };
    }

    /* ---- camera */
    function toScreenX(x) { return (x - cam.x) * cam.k + W / 2; }
    function toScreenY(y) { return (y - cam.y) * cam.k + H / 2; }
    function toWorld(sx, sy) { return [(sx - W / 2) / cam.k + cam.x, (sy - H / 2) / cam.k + cam.y]; }
    function tween(key, dur, apply) {
      if (reduced || dur <= 0) { tweens.delete(key); apply(1); invalidate(); return; }
      tweens.set(key, { t0: performance.now(), dur: dur, apply: apply }); invalidate();
    }
    function moveCam(x, y, k, animate) {
      k = clamp(k, 0.1, 6);
      if (!animate) { tweens.delete('cam'); cam.x = x; cam.y = y; cam.k = k; miniDirty = true; invalidate(); return; }
      var fx = cam.x, fy = cam.y, fk = Math.log(cam.k), tk = Math.log(k);
      tween('cam', 320, function (p) { var e = easeCam(p); cam.x = fx + (x - fx) * e; cam.y = fy + (y - fy) * e; cam.k = Math.exp(fk + (tk - fk) * e); miniDirty = true; });
    }
    function fitBox(b, animate, pad) {
      if (!b) return; pad = pad == null ? 40 : pad;
      var w = Math.max(20, b.x1 - b.x0), h = Math.max(20, b.y1 - b.y0);
      var k = Math.min((W - pad * 2) / w, (H - pad * 2) / h);
      moveCam((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, clamp(k, 0.1, 4), animate);
    }
    function bbox(filter) {
      var b = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity }, any = false;
      for (var i = 0; i < N; i++) {
        if (!filter(i)) continue; any = true;
        if (X[i] < b.x0) b.x0 = X[i]; if (X[i] > b.x1) b.x1 = X[i]; if (Y[i] < b.y0) b.y0 = Y[i]; if (Y[i] > b.y1) b.y1 = Y[i];
      }
      return any ? b : null;
    }
    function fitAll(animate) {
      var b = bbox(function (i) { return layerOn[nodes[i].layer]; });
      if (b) { if (neural.idx.length && layerOn.neural) { var r = neuralRect(); b.x0 = Math.min(b.x0, r.x0); b.y0 = Math.min(b.y0, r.y0 - 24); b.x1 = Math.max(b.x1, r.x1); b.y1 = Math.max(b.y1, r.y1); } fitBox(b, animate); }
      else moveCam(0, 0, 1, animate);
    }
    function zoomAt(sx, sy, factor) {
      var w = toWorld(sx, sy), k = clamp(cam.k * factor, 0.1, 6);
      tweens.delete('cam'); cam.k = k; cam.x = w[0] - (sx - W / 2) / k; cam.y = w[1] - (sy - H / 2) / k;
      userMovedCam = true; miniDirty = true; invalidate();
    }

    /* ---- layer visibility / focus */
    function visible(i) { var L = nodes[i].layer; return layerOn[L] && layerVis[L] > 0.01; }
    function toggleLayer(name, onState) {
      if (LAYERS.indexOf(name) < 0) return;
      var want = onState == null ? !layerOn[name] : !!onState;
      if (!!layerOn[name] === want) return;
      layerOn[name] = want ? 1 : 0;
      chips[name].btn.setAttribute('aria-pressed', String(want));
      var from = layerVis[name], to = want ? 1 : 0;
      tween('vis:' + name, 200, function (p) { layerVis[name] = from + (to - from) * easeOut(p); });
      if (!want) {
        if (selected >= 0 && nodes[selected].layer === name) { selected = -1; emitSelect(null); }
        if (hover >= 0 && nodes[hover].layer === name) hover = -1;
        if (kbIdx >= 0 && nodes[kbIdx].layer === name) kbIdx = -1;
        if (focusedLayer === name) unfocusLayer();
      }
      if (searchSet) runSearch(search.value);
      buildNodeList(); updateAria(); miniDirty = true; invalidate();
    }
    function setDims(target) {
      LAYERS.forEach(function (L) {
        var from = layerDim[L], to = target == null || target === L ? 1 : 0.15;
        if (from === to) return;
        tween('dim:' + L, 320, function (p) { layerDim[L] = from + (to - from) * easeCam(p); });
      });
    }
    function setClusterScale(to) {
      var from = neural.scale; if (from === to) return;
      tween('cluster', 320, function (p) { neural.scale = from + (to - from) * easeCam(p); layoutNeural(); hashDirty = true; });
    }
    function focusLayer(name, toggleIfSame) {
      if (LAYERS.indexOf(name) < 0) return;
      if (focusedLayer === name) { if (toggleIfSame) unfocusLayer(); return; }
      if (!layerOn[name]) toggleLayer(name, true);
      if (!focusedLayer) camBeforeFocus = { x: cam.x, y: cam.y, k: cam.k };
      focusedLayer = name; setDims(name);
      LAYERS.forEach(function (L) { chips[L].wrap.classList.toggle('axg-focused', L === name); });
      if (name === 'neural' && neural.idx.length) {
        setClusterScale(2.4);
        var r = neuralRect(2.4); fitBox({ x0: r.x0, y0: r.y0 - 30, x1: r.x1, y1: r.y1 }, true, 30);
      } else {
        setClusterScale(1);
        var b = bbox(function (i) { return nodes[i].layer === name; }); if (b) fitBox(b, true);
      }
      userMovedCam = true;
      if (typeof opts.onLayerFocus === 'function') safeCall(opts.onLayerFocus, name);
      updateAria();
    }
    function unfocusLayer() {
      if (!focusedLayer) return;
      focusedLayer = null; setDims(null); setClusterScale(1);
      LAYERS.forEach(function (L) { chips[L].wrap.classList.remove('axg-focused'); });
      if (camBeforeFocus) { moveCam(camBeforeFocus.x, camBeforeFocus.y, camBeforeFocus.k, true); camBeforeFocus = null; }
      if (typeof opts.onLayerFocus === 'function') safeCall(opts.onLayerFocus, null);
      updateAria();
    }
    function safeCall(fn, a, b) { try { fn(a, b); } catch (e) { if (win.console) console.error(e); } }

    /* ---- selection */
    function info(i) {
      var n = nodes[i], nb = [];
      for (var k = 0; k < adj[i].length && nb.length < 200; k++) {
        var e = edges[adj[i][k]], j = e.s === i ? e.t : e.s;
        nb.push({ id: nodes[j].id, label: nodes[j].label, layer: nodes[j].layer, relation: e.relation || (e.cross ? 'kullanır' : '') });
      }
      return { id: n.id, rawId: n.rawId, layer: n.layer, label: n.label, kind: n.kind, description: n.desc, neighbors: nb, raw: n.raw };
    }
    function emitSelect(i) {
      if (typeof opts.onNodeSelect === 'function') { if (i == null || i < 0) safeCall(opts.onNodeSelect, null, null); else { var inf = info(i); safeCall(opts.onNodeSelect, inf, inf.layer); } }
    }
    function select(i, fromClick) {
      selected = i;
      emitSelect(i);
      if (i >= 0) {
        live.textContent = 'Seçildi: ' + nodes[i].label + ' (' + LNAME[nodes[i].layer] + ', ' + nodes[i].kind + ')';
        if (fromClick && nodes[i].layer === 'neural' && focusedLayer !== 'neural') focusLayer('neural');
      }
      updateAria(); invalidate();
    }
    function resolveId(id) {
      id = str(id); if (!id) return -1;
      if (idIndex.has(id)) return idIndex.get(id);
      var c = rawIndex.get(id); return c && c.length ? c[0] : -1;
    }
    function focusNode(i) {
      if (i < 0) return;
      var L = nodes[i].layer; if (!layerOn[L]) toggleLayer(L, true);
      if (focusedLayer && focusedLayer !== L) unfocusLayer();
      if (L === 'neural' && focusedLayer !== 'neural') focusLayer('neural');
      else moveCam(X[i], Y[i], Math.max(cam.k, 1.6), true);
      userMovedCam = true; select(i, false);
    }

    /* ---- hit testing (spatial hash, 48 world px cells, 3x3 lookup) */
    function rebuildHash() {
      hashMap.clear();
      for (var i = 0; i < N; i++) {
        if (!SIM[i]) continue;
        var key = (Math.floor(X[i] / HCELL) + 32768) * 65536 + (Math.floor(Y[i] / HCELL) + 32768);
        var a = hashMap.get(key); if (a) a.push(i); else hashMap.set(key, [i]);
      }
      hashDirty = false;
    }
    function hit(sx, sy) {
      var w = toWorld(sx, sy), wx = w[0], wy = w[1], best = -1, bd = Infinity, k;
      if (neural.idx.length && visible(neural.idx[0])) {
        for (k = 0; k < neural.idx.length; k++) {
          var i = neural.idx[k], rr = nodeR(i) / cam.k + 4 / cam.k, dx = X[i] - wx, dy = Y[i] - wy, d = dx * dx + dy * dy;
          if (d <= rr * rr && d < bd) { bd = d; best = i; }
        }
        if (best >= 0) return { node: best };
        var r = neuralRect(); if (wx >= r.x0 && wx <= r.x1 && wy >= r.y0 - 22 / cam.k && wy <= r.y1) return { plate: true };
      }
      if (hashDirty) rebuildHash();
      var cx = Math.floor(wx / HCELL), cy = Math.floor(wy / HCELL);
      for (var ox = -1; ox <= 1; ox++) for (var oy = -1; oy <= 1; oy++) {
        var a = hashMap.get((cx + ox + 32768) * 65536 + (cy + oy + 32768)); if (!a) continue;
        for (k = 0; k < a.length; k++) {
          var j = a[k]; if (!visible(j)) continue;
          var rad = Math.max(nodeR(j), 6) / cam.k, ddx = X[j] - wx, ddy = Y[j] - wy, dd = ddx * ddx + ddy * ddy;
          if (dd <= rad * rad && dd < bd) { bd = dd; best = j; }
        }
      }
      return best >= 0 ? { node: best } : null;
    }
    function nodeR(i) {   // screen radius
      var n = nodes[i];
      if (n.layer === 'neural') return (neural.scale > 1.3 ? 3 + 2.6 * neural.scale : 3.5) * Math.min(cam.k, 3);
      if (cam.k < 0.4) return n.hub ? 2.6 : 1.6;
      return Math.max(2, n.r * cam.k);
    }

    /* ---- drawing */
    function invalidate() { if (!raf && !destroyed && !doc.hidden) raf = win.requestAnimationFrame(frame); }
    function frame() {
      raf = 0; if (destroyed) return;
      var now = performance.now();
      tweens.forEach(function (t, key) { var p = Math.min(1, (now - t.t0) / t.dur); t.apply(p); if (p >= 1) tweens.delete(key); });
      if (simOn) {
        var t0 = performance.now(), ticks = 0;
        do { tick(); ticks++; } while (simOn && ticks < 3 && simIdx.length < 1500 && performance.now() - t0 < 6);
      }
      layoutNeural();
      draw();
      frameCount++;
      if (simOn || tweens.size) invalidate();
    }
    function computeHighlight() {
      var src = hover >= 0 ? hover : (kbIdx >= 0 ? kbIdx : -1);
      if (src < 0 && searchSet && searchSet.size) return { set: searchSet, search: true };
      if (src < 0) return null;
      var s = new Set([src]);
      for (var k = 0; k < adj[src].length; k++) { var e = edges[adj[src][k]]; s.add(e.s); s.add(e.t); }
      return { set: s, src: src };
    }
    function layerAlpha(L) { return layerVis[L] * layerDim[L]; }
    function shapePath(c, L, x, y, r) {
      if (L === 'skills') { c.moveTo(x, y - r * 1.25); c.lineTo(x + r * 1.25, y); c.lineTo(x, y + r * 1.25); c.lineTo(x - r * 1.25, y); c.closePath(); }
      else if (L === 'learning') {
        var s = r * 0.95, q = Math.min(s * 0.45, 3);
        c.moveTo(x - s + q, y - s); c.lineTo(x + s - q, y - s); c.quadraticCurveTo(x + s, y - s, x + s, y - s + q); c.lineTo(x + s, y + s - q);
        c.quadraticCurveTo(x + s, y + s, x + s - q, y + s); c.lineTo(x - s + q, y + s); c.quadraticCurveTo(x - s, y + s, x - s, y + s - q);
        c.lineTo(x - s, y - s + q); c.quadraticCurveTo(x - s, y - s, x - s + q, y - s); c.closePath();
      } else { c.moveTo(x + r, y); c.arc(x, y, r, 0, 6.2832); }
    }
    function nodeColor(n) {
      if (n.layer === 'knowledge') return theme.kindTint[n.kind] || theme.knowledge;
      return theme[n.layer];
    }
    var buckets = new Map();
    function draw() {
      var c = ctx, k = cam.k;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.globalAlpha = 1; c.fillStyle = theme.bg; c.fillRect(0, 0, W, H);
      if (!N) { drawMini(); return; }
      highlight = computeHighlight();
      var hs = highlight && highlight.set;
      var vx0 = cam.x - W / 2 / k - 20, vx1 = cam.x + W / 2 / k + 20, vy0 = cam.y - H / 2 / k - 20, vy1 = cam.y + H / 2 / k + 20;
      var lowZoom = k < 0.4, i, e, a, L, x, y;
      // ---- edges (intra-layer batched per layer; cross-layer dashed muted)
      c.lineCap = 'round';
      for (var pass = 0; pass < 2; pass++) {       // pass 0: dimmed / normal, pass 1: highlighted
        if (pass === 1 && !hs) break;
        LAYERS.forEach(function (Ly) {
          if (Ly === 'neural') return;
          var la = layerAlpha(Ly); if (la < 0.01) return;
          c.beginPath(); var cnt = 0;
          for (var q = 0; q < E; q++) {
            var ed = edges[q]; if (ed.cross || nodes[ed.s].layer !== Ly) continue;
            if (lowZoom && !ed.hub) continue;
            var s = ES[q], t = ET[q];
            var hl = hs && hs.has(s) && hs.has(t) && (!highlight.src && highlight.src !== 0 ? false : (s === highlight.src || t === highlight.src));
            if ((pass === 1) !== !!hl) continue;
            if ((X[s] < vx0 && X[t] < vx0) || (X[s] > vx1 && X[t] > vx1) || (Y[s] < vy0 && Y[t] < vy0) || (Y[s] > vy1 && Y[t] > vy1)) continue;
            c.moveTo(toScreenX(X[s]), toScreenY(Y[s])); c.lineTo(toScreenX(X[t]), toScreenY(Y[t])); cnt++;
          }
          if (!cnt) return;
          c.strokeStyle = pass ? theme[Ly] : theme[Ly];
          c.globalAlpha = la * (pass ? 0.9 : (hs ? 0.05 : (lowZoom ? 0.22 : 0.18)));
          c.lineWidth = pass ? 1.4 : (k > 1.2 ? 1 : 0.8);
          c.stroke();
        });
      }
      // cross-layer
      c.setLineDash([4, 4]); c.strokeStyle = theme.muted; c.lineWidth = 1.1;
      for (var q = 0; q < E; q++) {
        e = edges[q]; if (!e.cross) continue;
        var s = ES[q], t = ET[q]; if (!visible(s) || !visible(t)) continue;
        if ((X[s] < vx0 && X[t] < vx0) || (X[s] > vx1 && X[t] > vx1) || (Y[s] < vy0 && Y[t] < vy0) || (Y[s] > vy1 && Y[t] > vy1)) continue;
        var hl2 = hs && hs.has(s) && hs.has(t);
        c.globalAlpha = Math.min(layerAlpha(nodes[s].layer), layerAlpha(nodes[t].layer)) * (hs ? (hl2 ? 0.95 : 0.12) : 0.6);
        c.beginPath(); c.moveTo(toScreenX(X[s]), toScreenY(Y[s])); c.lineTo(toScreenX(X[t]), toScreenY(Y[t])); c.stroke();
      }
      c.setLineDash([]);
      // ---- nodes, batched by colour and alpha group
      buckets.forEach(function (b) { b.n.length = 0; b.d.length = 0; });
      for (i = 0; i < N; i++) {
        if (!SIM[i]) continue;
        var n = nodes[i]; if (layerAlpha(n.layer) < 0.01 || !layerOn[n.layer] && layerVis[n.layer] < 0.01) continue;
        x = X[i]; y = Y[i]; if (x < vx0 || x > vx1 || y < vy0 || y > vy1) continue;
        var col = nodeColor(n), key = n.layer + '|' + col, bk = buckets.get(key);
        if (!bk) { bk = { L: n.layer, col: col, n: [], d: [] }; buckets.set(key, bk); }
        (hs && !hs.has(i) ? bk.d : bk.n).push(i);
      }
      buckets.forEach(function (bk) {
        var la = layerAlpha(bk.L);
        [bk.d, bk.n].forEach(function (list, gi) {
          if (!list.length) return;
          c.globalAlpha = la * (gi === 0 ? 0.2 : 1); c.fillStyle = bk.col; c.beginPath();
          for (var m = 0; m < list.length; m++) {
            var j = list[m], sx = toScreenX(X[j]), sy = toScreenY(Y[j]);
            if (lowZoom) { var sz = nodes[j].hub ? 2.6 : 1.6; c.rect(sx - sz, sy - sz, sz * 2, sz * 2); }
            else shapePath(c, bk.L, sx, sy, Math.max(2, nodes[j].r * k));
          }
          c.fill();
        });
      });
      // search glow + pins
      c.globalAlpha = 1;
      if (searchSet && searchSet.size) {
        c.strokeStyle = theme.accent2; c.lineWidth = 2; c.beginPath();
        searchSet.forEach(function (j) { if (!SIM[j] || !visible(j)) return; var sx = toScreenX(X[j]), sy = toScreenY(Y[j]), r = nodeR(j) + 4; c.moveTo(sx + r, sy); c.arc(sx, sy, r, 0, 6.2832); });
        c.globalAlpha = 0.85; c.stroke(); c.globalAlpha = 1;
      }
      if (!lowZoom) {
        c.strokeStyle = theme.muted; c.lineWidth = 1; c.beginPath(); var pc = 0;
        for (i = 0; i < N; i++) if (PIN[i] && SIM[i] && visible(i)) { var px = toScreenX(X[i]), py = toScreenY(Y[i]), pr = nodeR(i) + 2.5; c.moveTo(px + pr, py); c.arc(px, py, pr, 0, 6.2832); pc++; }
        if (pc) c.stroke();
      }
      // ---- XOR cluster (drawn on top)
      if (neural.idx.length && layerAlpha('neural') > 0.01) drawNeural(hs);
      // ---- selection / hover / keyboard rings
      ringAt(selected, theme.focus, 2.2, false);
      ringAt(hover, theme.text, 1.4, false);
      ringAt(kbIdx, theme.focus, 2, true);
      // ---- labels
      drawLabels(hs, lowZoom);
      if (lowZoom) drawHalos();
      zoomTxt.textContent = Math.round(k * 100) + '%';
      if (miniDirty || (simOn && frameCount % 15 === 0)) drawMini();
    }
    function ringAt(i, col, w, dashed) {
      if (i < 0 || i >= N || !visible(i)) return;
      var c = ctx, sx = toScreenX(X[i]), sy = toScreenY(Y[i]), r = nodeR(i) + 4;
      c.globalAlpha = 1; c.strokeStyle = col; c.lineWidth = w; if (dashed) c.setLineDash([3, 3]);
      c.beginPath(); c.arc(sx, sy, r, 0, 6.2832); c.stroke(); c.setLineDash([]);
    }
    function drawNeural(hs) {
      var c = ctx, la = layerAlpha('neural'), s = neural.scale, k = cam.k, expanded = s > 1.3;
      var r = neuralRect(), x0 = toScreenX(r.x0), y0 = toScreenY(r.y0), x1 = toScreenX(r.x1), y1 = toScreenY(r.y1);
      if (x1 < 0 || x0 > W || y1 < -30 || y0 > H) return;
      c.globalAlpha = la * 0.92; c.fillStyle = theme.surface; c.strokeStyle = theme.neural; c.lineWidth = 1;
      c.beginPath(); roundRect(c, x0, y0, x1 - x0, y1 - y0, 8); c.fill(); c.globalAlpha = la * 0.55; c.stroke();
      // edges: colour = sign of signal, width = |signal|
      var wscale = Math.min(k, 3) * (expanded ? 1.4 : 0.7);
      for (var q = 0; q < E; q++) {
        var e = edges[q]; if (!e.neural) continue;
        var v = e.signal != null ? e.signal : (e.weight || 0), m = Math.abs(v) / neural.maxAbs, a = ES[q], b = ET[q];
        var dim = hs && !(hs.has(a) && hs.has(b));
        c.globalAlpha = la * (dim ? 0.12 : 0.3 + 0.65 * m);
        c.strokeStyle = v > 0 ? theme.sigPos : v < 0 ? theme.sigNeg : theme.sigZero;
        c.lineWidth = Math.max(0.5, (0.4 + 3.2 * m) * wscale);
        c.beginPath(); c.moveTo(toScreenX(X[a]), toScreenY(Y[a])); c.lineTo(toScreenX(X[b]), toScreenY(Y[b])); c.stroke();
      }
      for (var j = 0; j < neural.idx.length; j++) {
        var i = neural.idx[j], n = nodes[i], sx = toScreenX(X[i]), sy = toScreenY(Y[i]), rr = nodeR(i);
        var act = num(n.raw && n.raw.activation), fill = theme.neural;
        if (expanded && act != null) {
          var fnName = str(n.raw.activation_fn), sv = fnName === 'sigmoid' ? act * 2 - 1 : clamp(act, -1, 1);
          fill = sv >= 0 ? mix(theme.sigZero, theme.sigPos, sv) : mix(theme.sigZero, theme.sigNeg, -sv);
        }
        c.globalAlpha = la * (hs && !hs.has(i) ? 0.25 : 1);
        c.fillStyle = fill; c.beginPath(); c.arc(sx, sy, rr, 0, 6.2832); c.fill();
        c.strokeStyle = theme.neural; c.lineWidth = expanded ? 1.6 : 1; c.beginPath(); c.arc(sx, sy, rr + (expanded ? 2 : 1.2), 0, 6.2832); c.stroke();
        if (expanded && rr > 6) {
          c.fillStyle = theme.text; c.font = '600 ' + Math.round(clamp(rr * 0.9, 9, 13)) + 'px ' + fontUi; c.textAlign = 'center'; c.textBaseline = 'middle';
          c.fillText(n.short || '', sx, sy + rr + 11);
        }
      }
      // label chip "XOR ağı · kayıp 0.002"
      var meta = neural.meta || {}, txt = 'XOR ağı';
      if (meta.trained === false) txt += ' · eğitilmedi'; else if (meta.loss != null) txt += ' · kayıp ' + (meta.loss < 0.001 ? meta.loss.toExponential(1) : meta.loss.toFixed(3));
      c.font = '600 11px ' + fontUi; c.textAlign = 'left'; c.textBaseline = 'middle';
      var tw = c.measureText(txt).width, cx0 = (x0 + x1) / 2 - tw / 2 - 8, cy0 = y0 - 22;
      c.globalAlpha = la; c.fillStyle = theme.elevated; c.beginPath(); roundRect(c, cx0, cy0, tw + 16, 18, 9); c.fill();
      c.strokeStyle = theme.neural; c.lineWidth = 1; c.stroke();
      c.fillStyle = theme.text; c.fillText(txt, cx0 + 8, cy0 + 9.5);
    }
    function roundRect(c, x, y, w, h, r) {
      r = Math.min(r, w / 2, h / 2);
      c.moveTo(x + r, y); c.lineTo(x + w - r, y); c.quadraticCurveTo(x + w, y, x + w, y + r); c.lineTo(x + w, y + h - r);
      c.quadraticCurveTo(x + w, y + h, x + w - r, y + h); c.lineTo(x + r, y + h); c.quadraticCurveTo(x, y + h, x, y + h - r);
      c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y); c.closePath();
    }
    function textW(i, font, text) {
      var key = i + '|' + font, w = labelW.get(key);
      if (w == null) { ctx.font = font; w = ctx.measureText(text).width; labelW.set(key, w); }
      return w;
    }
    function drawLabels(hs, lowZoom) {
      var c = ctx, k = cam.k, big = k > 1.2, font = (big ? '12px ' : '11px ') + fontUi;
      var occ = new Set(), CW = 80, CH = 24, drawn = 0, limit = lowZoom ? 10 : big ? 250 : 120;
      var prio = [], plate = null;
      if (neural.idx.length && layerAlpha('neural') > 0.01) { var nr = neuralRect(); plate = [toScreenX(nr.x0), toScreenY(nr.y0), toScreenX(nr.x1), toScreenY(nr.y1)]; }
      [selected, hover, kbIdx].forEach(function (i) { if (i >= 0) prio.push(i); });
      if (searchList.length) searchList.slice(0, 8).forEach(function (i) { prio.push(i); });
      if (hs && highlight.src != null) hs.forEach(function (i) { prio.push(i); });
      var done = new Set();
      c.textBaseline = 'middle'; c.textAlign = 'left'; c.font = font;
      function place(i, forced) {
        if (done.has(i) || nodes[i].layer === 'neural' || !visible(i)) return; done.add(i);
        var n = nodes[i], sx = toScreenX(X[i]), sy = toScreenY(Y[i]);
        if (sx < -50 || sx > W + 50 || sy < -20 || sy > H + 20) return;
        var text = trunc(n.label, 34), w = textW(i, font, text), r = nodeR(i);
        if (!forced && plate && sx + r + 4 + w > plate[0] && sx < plate[2] && sy > plate[1] - 26 && sy < plate[3]) return;  // never over the XOR plate
        var lx = sx + r + 4, ly = sy, bx0 = Math.floor(lx / CW), bx1 = Math.floor((lx + w) / CW), by = Math.floor((ly - 7) / CH), by1 = Math.floor((ly + 7) / CH);
        if (!forced) { for (var gx = bx0; gx <= bx1; gx++) for (var gy = by; gy <= by1; gy++) if (occ.has(gx + ',' + gy)) return; }
        for (gx = bx0; gx <= bx1; gx++) for (gy = by; gy <= by1; gy++) occ.add(gx + ',' + gy);
        var la = layerAlpha(n.layer) * (hs && !hs.has(i) ? 0.3 : 1);
        if (big || forced) {
          c.globalAlpha = la * 0.85; c.fillStyle = theme.surface; c.beginPath(); roundRect(c, lx - 4, ly - 9, w + 8, 18, 9); c.fill();
        }
        c.globalAlpha = la; c.fillStyle = forced ? theme.text : (big ? theme.text : theme.muted); c.fillText(text, lx, ly + 0.5);
        drawn++;
      }
      for (var p = 0; p < prio.length && p < 60; p++) place(prio[p], p < 3);
      if (!(hs && highlight.search)) for (var q = 0; q < byDeg.length && drawn < limit; q++) {
        var i = byDeg[q]; if (lowZoom && !nodes[i].hub) break;
        place(i, false);
      }
      // relation labels on selected node's edges
      if (big && selected >= 0 && visible(selected)) {
        c.font = '10.5px ' + fontUi; c.fillStyle = theme.muted; c.textAlign = 'center'; c.globalAlpha = 0.95;
        adj[selected].slice(0, 40).forEach(function (q) {
          var e = edges[q], rel = e.relation || (e.cross ? 'kullanır' : ''); if (!rel || !visible(e.s) || !visible(e.t)) return;
          c.fillText(trunc(rel, 24), toScreenX((X[e.s] + X[e.t]) / 2), toScreenY((Y[e.s] + Y[e.t]) / 2) - 6);
        });
      }
      c.globalAlpha = 1;
    }
    function drawHalos() {
      var c = ctx; c.textAlign = 'center'; c.textBaseline = 'middle'; c.font = '600 15px ' + fontUi;
      LAYERS.forEach(function (L) {
        if (L === 'neural' || !layerOn[L] || !layerCount[L]) return;
        var sx = 0, sy = 0, n = 0;
        for (var i = 0; i < N; i++) if (nodes[i].layer === L) { sx += X[i]; sy += Y[i]; n++; }
        if (!n) return;
        var b = bbox(function (i) { return nodes[i].layer === L; });
        c.globalAlpha = 0.8 * layerAlpha(L); c.fillStyle = theme[L];
        c.fillText(LNAME[L] + ' · ' + layerCount[L], toScreenX(sx / n), toScreenY(b.y0) - 14);
      });
      c.globalAlpha = 1;
    }
    var miniBox = null;
    function drawMini() {
      miniDirty = false;
      if (root.classList.contains('axg-narrow')) return;
      var mw = 140, mh = 100, c = mctx;
      c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, mw, mh);
      var b = bbox(function (i) { return layerOn[nodes[i].layer]; });
      if (!b) { miniBox = null; return; }
      var pad = 8, s = Math.min((mw - pad * 2) / Math.max(1, b.x1 - b.x0), (mh - pad * 2) / Math.max(1, b.y1 - b.y0));
      var ox = pad + ((mw - pad * 2) - (b.x1 - b.x0) * s) / 2 - b.x0 * s, oy = pad + ((mh - pad * 2) - (b.y1 - b.y0) * s) / 2 - b.y0 * s;
      miniBox = { s: s, ox: ox, oy: oy };
      LAYERS.forEach(function (L) {
        if (!layerOn[L]) return; c.fillStyle = theme[L]; c.globalAlpha = 0.85; c.beginPath();
        for (var i = 0; i < N; i++) if (nodes[i].layer === L) c.rect(X[i] * s + ox - 0.75, Y[i] * s + oy - 0.75, 1.5, 1.5);
        c.fill();
      });
      var w0 = toWorld(0, 0), w1 = toWorld(W, H);
      c.globalAlpha = 1; c.strokeStyle = theme.focus; c.lineWidth = 1;
      c.strokeRect(w0[0] * s + ox, w0[1] * s + oy, (w1[0] - w0[0]) * s, (w1[1] - w0[1]) * s);
    }

    /* ---- HUD / a11y */
    function updateHud() {
      LAYERS.forEach(function (L) {
        chips[L].cnt.textContent = String(layerCount[L]);
        chips[L].wrap.classList.toggle('axg-missing', !layerPresent[L]);
        chips[L].btn.title = layerPresent[L] ? LNAME[L] + ' (' + layerCount[L] + ')' : LNAME[L] + ': yok';
      });
      crossEl.textContent = crossCount + ' katmanlar arası bağ';
      empty.hidden = N > 0;
      buildNodeList(); updateAria();
    }
    function updateAria() {
      var parts_ = LAYERS.filter(function (L) { return layerOn[L]; }).map(function (L) { return LNAME[L] + ' ' + layerCount[L]; });
      var s = 'AXIS ağı: ' + (N ? parts_.join(', ') + ' düğüm; ' + crossCount + ' katmanlar arası bağ' : 'boş');
      if (focusedLayer) s += '; odak: ' + LNAME[focusedLayer];
      if (selected >= 0) s += '; seçili: ' + nodes[selected].label;
      s += '. Ok tuşları kaydırır, + ve - yakınlaştırır, Tab düğümleri dolaşır, Enter seçer, / arama.';
      canvas.setAttribute('aria-label', s);
    }
    function buildNodeList() {
      listUl.replaceChildren();
      var n = 0;
      for (var q = 0; q < byDeg.length && n < 50; q++) {
        var i = byDeg[q]; if (!visible(i) && !layerOn[nodes[i].layer]) continue;
        var li = mk('li', '', listUl), b = mk('button', '', li); b.type = 'button';
        b.textContent = nodes[i].label + ' — ' + LNAME[nodes[i].layer] + ', ' + nodes[i].kind + ', ' + nodes[i].deg + ' bağ';
        (function (id) { b.addEventListener('click', function () { api.focus(id); }); })(nodes[i].id);
        n++;
      }
    }
    function showTip(i, sx, sy) {
      if (i < 0) { tip.classList.remove('axg-on'); return; }
      var n = nodes[i];
      tip.replaceChildren();
      var b = mk('b', '', tip); b.textContent = n.label;
      var bd = mk('span', 'axg-badge', tip); bd.textContent = LNAME[n.layer]; bd.style.setProperty('--c', theme[n.layer]);
      var kd = mk('span', 'axg-badge', tip); kd.textContent = n.kind; kd.style.setProperty('--c', theme.muted);
      var dg = mk('span', 'axg-badge', tip); dg.textContent = n.deg + ' bağ'; dg.style.setProperty('--c', theme.muted);
      if (n.layer === 'neural' && n.raw) {
        var d0 = mk('div', 'axg-desc', tip), r = n.raw, bits = [];
        if (num(r.activation) != null) bits.push('aktivasyon ' + num(r.activation).toFixed(4));
        if (num(r.bias) != null) bits.push('bias ' + num(r.bias).toFixed(4));
        if (num(r.pre_activation) != null) bits.push('z ' + num(r.pre_activation).toFixed(4));
        if (str(r.activation_fn)) bits.push(str(r.activation_fn));
        d0.textContent = bits.join(' · ');
      }
      if (n.desc) { var d = mk('div', 'axg-desc', tip); d.textContent = trunc(n.desc, 120); }
      if (PIN[i]) { var p = mk('div', 'axg-desc', tip); p.textContent = 'sabitlendi (çift tık çözer)'; }
      tip.classList.add('axg-on');
      var tw = tip.offsetWidth, th = tip.offsetHeight, x = sx + 14, y = sy + 14;
      if (x + tw > W - 4) x = sx - tw - 14; if (y + th > H - 4) y = sy - th - 14;
      tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
    }

    /* ---- search */
    function runSearch(q) {
      q = lc(str(q).trim());
      results.replaceChildren(); searchActive = -1; search.removeAttribute('aria-activedescendant');
      if (!q) { searchSet = null; searchList = []; results.hidden = true; search.setAttribute('aria-expanded', 'false'); invalidate(); return; }
      var all = [];
      for (var t = 0; t < byDeg.length; t++) {
        var i = byDeg[t]; if (!layerOn[nodes[i].layer]) continue;
        var n = nodes[i]; if (n.labelLc.indexOf(q) >= 0 || lc(n.rawId).indexOf(q) >= 0) all.push(i);
      }
      searchSet = new Set(all); searchList = all;
      all.slice(0, 8).forEach(function (i, idx) {
        var li = mk('li', '', results); li.id = uid + '-o' + idx; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', 'false');
        var g = mk('span', 'axg-glyph ' + (nodes[i].layer === 'neural' ? 'axg-g-ring' : nodes[i].layer === 'knowledge' ? 'axg-g-circle' : nodes[i].layer === 'skills' ? 'axg-g-diamond' : 'axg-g-square'), li);
        g.style.setProperty('--c', theme[nodes[i].layer]); g.setAttribute('aria-hidden', 'true');
        var l = mk('span', 'axg-lbl', li); l.textContent = nodes[i].label;
        var s = mk('span', 'axg-sub', li); s.textContent = LNAME[nodes[i].layer] + ' · ' + nodes[i].kind;
        li.addEventListener('mousedown', function (ev) { ev.preventDefault(); });
        li.addEventListener('click', function () { pickResult(idx); });
      });
      if (!all.length) { var li = mk('li', '', results); li.setAttribute('role', 'option'); li.setAttribute('aria-disabled', 'true'); li.textContent = 'Sonuç yok'; }
      results.hidden = false; search.setAttribute('aria-expanded', 'true');
      live.textContent = all.length + ' sonuç';
      invalidate();
    }
    function setActive(idx) {
      var opts_ = results.querySelectorAll('li[id]'); if (!opts_.length) return;
      searchActive = (idx + opts_.length) % opts_.length;
      opts_.forEach(function (o, j) { o.setAttribute('aria-selected', String(j === searchActive)); });
      search.setAttribute('aria-activedescendant', opts_[searchActive].id);
      opts_[searchActive].scrollIntoView({ block: 'nearest' });
    }
    function pickResult(idx) {
      var i = searchList[idx < 0 ? 0 : idx]; if (i == null) return;
      results.hidden = true; search.setAttribute('aria-expanded', 'false');
      focusNode(i);
    }
    on(search, 'input', function () { runSearch(search.value); });
    on(search, 'keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (results.hidden && search.value) runSearch(search.value); setActive(searchActive + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(searchActive - 1); }
      else if (e.key === 'Enter') { e.preventDefault(); pickResult(searchActive); }
      else if (e.key === 'Escape') { e.preventDefault(); if (search.value) { search.value = ''; runSearch(''); } else canvas.focus(); }
    });
    on(search, 'blur', function () { results.hidden = true; search.setAttribute('aria-expanded', 'false'); });
    on(search, 'focus', function () { if (search.value) runSearch(search.value); });

    /* ---- pointer interaction */
    var pointers = new Map(), down = null, dragIdx = -1, pinch = null, lastTap = 0;
    function local(e) { var r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
    on(canvas, 'pointerdown', function (e) {
      if (e.button !== 0 && e.pointerType === 'mouse') return;
      canvas.setPointerCapture(e.pointerId);
      var p = local(e); pointers.set(e.pointerId, p);
      if (pointers.size === 2) {
        var ps = Array.from(pointers.values());
        pinch = { d: Math.hypot(ps[0][0] - ps[1][0], ps[0][1] - ps[1][1]) || 1, k: cam.k, mid: [(ps[0][0] + ps[1][0]) / 2, (ps[0][1] + ps[1][1]) / 2] };
        if (dragIdx >= 0) { dragIdx = -1; }
        down = null; return;
      }
      var h = hit(p[0], p[1]);
      down = { x: p[0], y: p[1], h: h, moved: false, cam: { x: cam.x, y: cam.y }, w: toWorld(p[0], p[1]), ncx: neural.cx, ncy: neural.cy };
      if (h && h.node != null) { down.ox = X[h.node]; down.oy = Y[h.node]; }
    });
    on(canvas, 'pointermove', function (e) {
      var p = local(e);
      if (pointers.has(e.pointerId)) pointers.set(e.pointerId, p);
      if (pinch && pointers.size >= 2) {
        var ps = Array.from(pointers.values()), d = Math.hypot(ps[0][0] - ps[1][0], ps[0][1] - ps[1][1]) || 1, mid = [(ps[0][0] + ps[1][0]) / 2, (ps[0][1] + ps[1][1]) / 2];
        var w = toWorld(pinch.mid[0], pinch.mid[1]); cam.k = clamp(pinch.k * d / pinch.d, 0.1, 6);
        cam.x = w[0] - (mid[0] - W / 2) / cam.k; cam.y = w[1] - (mid[1] - H / 2) / cam.k; pinch.mid = mid; pinch.k = cam.k; pinch.d = d;
        userMovedCam = true; miniDirty = true; invalidate(); return;
      }
      if (down) {
        var dx = p[0] - down.x, dy = p[1] - down.y;
        if (!down.moved && dx * dx + dy * dy > 16) {
          down.moved = true; showTip(-1);
          if (down.h && down.h.node != null && nodes[down.h.node].layer !== 'neural') { dragIdx = down.h.node; canvas.style.cursor = 'grabbing'; }
        }
        if (!down.moved) return;
        var wp = toWorld(p[0], p[1]);
        if (down.h && (down.h.plate || (down.h.node != null && nodes[down.h.node].layer === 'neural'))) {
          neural.cx = down.ncx + (wp[0] - down.w[0]); neural.cy = down.ncy + (wp[1] - down.w[1]); layoutNeural(); hashDirty = true; reheat(0.08); invalidate();
        } else if (dragIdx >= 0) {
          X[dragIdx] = down.ox + (wp[0] - down.w[0]); Y[dragIdx] = down.oy + (wp[1] - down.w[1]); VX[dragIdx] = VY[dragIdx] = 0; hashDirty = true;
          reheat(0.12); invalidate();
        } else {
          tweens.delete('cam'); cam.x = down.cam.x - dx / cam.k; cam.y = down.cam.y - dy / cam.k; userMovedCam = true; miniDirty = true; canvas.style.cursor = 'grabbing'; invalidate();
        }
        return;
      }
      var h = hit(p[0], p[1]), nh = h && h.node != null ? h.node : -1;
      canvas.style.cursor = h ? 'pointer' : 'grab';
      if (nh !== hover) { hover = nh; invalidate(); }
      showTip(nh, p[0], p[1]);
    });
    function endPointer(e) {
      pointers.delete(e.pointerId);
      if (pinch) { if (pointers.size < 2) pinch = null; return; }
      if (!down) return;
      var d = down; down = null; canvas.style.cursor = 'grab';
      if (dragIdx >= 0) { dragIdx = -1; miniDirty = true; invalidate(); return; }
      if (d.moved || e.type === 'pointercancel') return;
      if (d.h && d.h.node != null) select(d.h.node, true);
      else if (d.h && d.h.plate) { focusLayer('neural'); }
      else if (selected >= 0) select(-1);
    }
    on(canvas, 'pointerup', endPointer); on(canvas, 'pointercancel', endPointer);
    on(canvas, 'pointerleave', function () { if (!down && hover >= 0) { hover = -1; invalidate(); } showTip(-1); });
    on(canvas, 'dblclick', function (e) {
      var p = local(e), h = hit(p[0], p[1]);
      if (h && h.node != null && nodes[h.node].layer !== 'neural') { PIN[h.node] = PIN[h.node] ? 0 : 1; if (!PIN[h.node]) reheat(0.05); invalidate(); }
      else if (h) focusLayer('neural');
      else { if (focusedLayer) unfocusLayer(); fitAll(true); userMovedCam = false; }
    });
    on(canvas, 'wheel', function (e) {
      e.preventDefault();
      var p = local(e), dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      zoomAt(p[0], p[1], Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)));
    }, { passive: false });
    on(canvas, 'contextmenu', function (e) { if (dragIdx >= 0) e.preventDefault(); });

    /* ---- keyboard */
    function tabOrder() {
      var list = [];
      for (var q = 0; q < byDeg.length; q++) {
        var i = byDeg[q]; if (!visible(i)) continue;
        var sx = toScreenX(X[i]), sy = toScreenY(Y[i]); if (sx < 0 || sx > W || sy < 0 || sy > H) continue;
        list.push(i); if (list.length >= 400) break;
      }
      return list;
    }
    on(canvas, 'keydown', function (e) {
      var k = e.key, step = 60 / cam.k;
      if (k === 'ArrowLeft' || k === 'ArrowRight' || k === 'ArrowUp' || k === 'ArrowDown') {
        e.preventDefault(); tweens.delete('cam');
        if (k === 'ArrowLeft') cam.x -= step; if (k === 'ArrowRight') cam.x += step; if (k === 'ArrowUp') cam.y -= step; if (k === 'ArrowDown') cam.y += step;
        userMovedCam = true; miniDirty = true; invalidate();
      } else if (k === '+' || k === '=') { e.preventDefault(); zoomAt(W / 2, H / 2, 1.25); }
      else if (k === '-' || k === '_') { e.preventDefault(); zoomAt(W / 2, H / 2, 0.8); }
      else if (k === 'Tab') {
        var list = tabOrder(), pos = list.indexOf(kbIdx), next = e.shiftKey ? (pos < 0 ? list.length - 1 : pos - 1) : pos + 1;
        if (next < 0 || next >= list.length) { kbIdx = -1; showTip(-1); invalidate(); return; }   // let focus leave: no trap
        e.preventDefault(); kbIdx = list[next];
        live.textContent = nodes[kbIdx].label + ', ' + LNAME[nodes[kbIdx].layer] + ', ' + nodes[kbIdx].deg + ' bağ';
        showTip(kbIdx, toScreenX(X[kbIdx]), toScreenY(Y[kbIdx])); invalidate();
      } else if (k === 'Enter' || k === ' ') {
        if (kbIdx >= 0) { e.preventDefault(); select(kbIdx, true); }
      } else if (k === 'Escape') {
        if (kbIdx >= 0 || selected >= 0) { kbIdx = -1; showTip(-1); if (selected >= 0) select(-1); }
        else if (focusedLayer) unfocusLayer();
        else if (searchSet) { search.value = ''; runSearch(''); }
        invalidate();
      } else if (k === '/') { e.preventDefault(); search.focus(); }
    });
    on(canvas, 'blur', function () { if (kbIdx >= 0) { kbIdx = -1; showTip(-1); invalidate(); } });
    on(root, 'keydown', function (e) {
      if (e.key === '/' && e.target !== search && e.target !== canvas) { e.preventDefault(); search.focus(); }
      if (e.key === 'Escape' && e.target !== search && e.target !== canvas && focusedLayer) unfocusLayer();
    });

    /* ---- buttons, minimap */
    on(zIn, 'click', function () { zoomAt(W / 2, H / 2, 1.3); });
    on(zOut, 'click', function () { zoomAt(W / 2, H / 2, 1 / 1.3); });
    on(zFit, 'click', function () { if (focusedLayer) unfocusLayer(); fitAll(true); userMovedCam = false; });
    var miniDrag = false;
    function miniMove(e) {
      if (!miniBox) return; var r = mini.getBoundingClientRect();
      var wx = (e.clientX - r.left - miniBox.ox) / miniBox.s, wy = (e.clientY - r.top - miniBox.oy) / miniBox.s;
      tweens.delete('cam'); cam.x = wx; cam.y = wy; userMovedCam = true; miniDirty = true; invalidate();
    }
    on(mini, 'pointerdown', function (e) { miniDrag = true; mini.setPointerCapture(e.pointerId); miniMove(e); });
    on(mini, 'pointermove', function (e) { if (miniDrag) miniMove(e); });
    on(mini, 'pointerup', function () { miniDrag = false; });
    on(mini, 'pointercancel', function () { miniDrag = false; });

    /* ---- environment */
    function resize() {
      var r = root.getBoundingClientRect();
      W = Math.max(1, r.width); H = Math.max(1, r.height); dpr = Math.min(2, win.devicePixelRatio || 1);
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      mini.width = Math.round(140 * dpr); mini.height = Math.round(100 * dpr);
      root.classList.toggle('axg-narrow', W < 768);
      miniDirty = true; invalidate();
    }
    var ro = win.ResizeObserver ? new win.ResizeObserver(resize) : null;
    if (ro) ro.observe(root); else on(win, 'resize', resize);
    var mo = win.MutationObserver ? new win.MutationObserver(readTheme) : null;
    if (mo) { mo.observe(doc.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] }); if (doc.body) mo.observe(doc.body, { attributes: true, attributeFilter: ['data-theme', 'class'] }); }
    function mqOn(mq, fn) { if (!mq) return; if (mq.addEventListener) { mq.addEventListener('change', fn); listeners.push([mq, 'change', fn]); } else if (mq.addListener) { mq.addListener(fn); listeners.push([mq, '__legacy', fn]); } }
    mqOn(mqDark, readTheme);
    mqOn(mqReduced, function () {
      reduced = !!mqReduced.matches;
      if (reduced) { tweens.forEach(function (t) { t.apply(1); }); tweens.clear(); if (simOn) { presolve(400, 900); } }
      invalidate();
    });
    on(doc, 'visibilitychange', function () { if (doc.hidden) { if (raf) { win.cancelAnimationFrame(raf); raf = 0; } } else invalidate(); });

    readTheme(); resize(); updateHud();

    /* ---- public */
    var api = {
      setLayers: setLayers,
      toggleLayer: function (name, onState) { toggleLayer(name, onState); },
      focus: function (idOrLayer) {
        if (idOrLayer == null || idOrLayer === '') { unfocusLayer(); return; }
        if (LAYERS.indexOf(idOrLayer) >= 0) { focusLayer(idOrLayer, false); return; }
        var i = resolveId(idOrLayer); if (i >= 0) focusNode(i);
      },
      destroy: function () {
        destroyed = true;
        if (raf) win.cancelAnimationFrame(raf); raf = 0;
        listeners.forEach(function (l) {
          if (l[1] === '__legacy') l[0].removeListener(l[2]); else l[0].removeEventListener(l[1], l[2], l[3]);
        });
        listeners = [];
        if (ro) ro.disconnect(); if (mo) mo.disconnect();
        tweens.clear();
        if (movedCanvas) {
          canvas.classList.remove('axg-canvas'); canvas.removeAttribute('role'); canvas.removeAttribute('aria-label'); canvas.removeAttribute('tabindex');
          if (movedCanvas.parent) movedCanvas.parent.insertBefore(canvas, movedCanvas.next && movedCanvas.next.parentNode === movedCanvas.parent ? movedCanvas.next : null);
        }
        if (root.parentNode) root.parentNode.removeChild(root);
        if (styleEl.parentNode) styleEl.parentNode.removeChild(styleEl);
        nodes = []; edges = []; N = E = 0;
      }
    };
    return api;
  }

  var current = null;
  window.AxisGraph = {
    mount: function (el, opts) {
      if (!el || !el.ownerDocument) throw new Error('AxisGraph.mount: element required');
      if (current) current.destroy();
      current = Instance(el, opts);
    },
    setLayers: function (layers) { if (current) current.setLayers(layers); },
    toggleLayer: function (name, on) { if (current) current.toggleLayer(name, on); },
    focus: function (idOrLayer) { if (current) current.focus(idOrLayer); },
    destroy: function () { if (current) { current.destroy(); current = null; } }
  };
})();
