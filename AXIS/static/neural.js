/* AXIS XOR inspector (window.AxisNeural). Vanilla JS, no libraries; DOM via textContent only.
   Authors: PART 1 (math) and PARTS 2a/3 by GPT Astra (gpt-6-astra); PART 2b and review fixes by Claude. */
(function () {
  'use strict';

  function tok(name, fallback) {
    try {
      var value = getComputedStyle(document.documentElement)
        .getPropertyValue(name).trim();
      return value || fallback;
    } catch (_) {
      return fallback;
    }
  }

  function actFn(name) {
    if (name === 'tanh') return function (x) { return Math.tanh(x); };
    if (name === 'relu') return function (x) { return Math.max(0, x); };
    if (name === 'sigmoid') {
      return function (x) {
        return 1 / (1 + Math.exp(-Math.max(-60, Math.min(60, x))));
      };
    }
    return function (x) { return x; };
  }

  function normalizeWeights(w) {
    try {
      function vector(value, length) {
        return Array.isArray(value) && value.length === length &&
          value.every(function (v) {
            return typeof v === 'number' && Number.isFinite(v);
          });
      }

      if (!w || !Array.isArray(w.W1) || w.W1.length !== 8 ||
          !w.W1.every(function (row) { return vector(row, 2); }) ||
          !vector(w.b1, 8)) return null;

      var W2 = w.W2;
      if (vector(W2, 8)) W2 = [W2];
      /* fix (Claude): the brief allows W2 as 8x1 (column) as well as 1x8 */
      else if (Array.isArray(W2) && W2.length === 8 &&
          W2.every(function (row) { return vector(row, 1); })) {
        W2 = [W2.map(function (row) { return row[0]; })];
      }
      var b2 = Array.isArray(w.b2) ? w.b2 : [w.b2];
      if (!Array.isArray(W2) || W2.length !== 1 ||
          !vector(W2[0], 8) || !vector(b2, 1)) return null;

      return {
        W1: w.W1.map(function (row) { return row.slice(); }),
        b1: w.b1.slice(),
        W2: [W2[0].slice()],
        b2: b2.slice()
      };
    } catch (_) {
      return null;
    }
  }

  function forward(params, inputs, fns) {
    var p = normalizeWeights(params);
    if (!p) throw new TypeError('Geçersiz ağ ağırlıkları.');
    if (!Array.isArray(inputs) || inputs.length !== 2) {
      throw new TypeError('İki giriş değeri gereklidir.');
    }
    var x = inputs.map(function (v) { return Number(v); });
    if (!x.every(Number.isFinite)) {
      throw new TypeError('Girişler sonlu sayılar olmalıdır.');
    }

    // fns: {hidden, output}, [hidden, output] veya [null, hidden, output].
    var hidden = 'tanh';
    var output = 'sigmoid';
    if (Array.isArray(fns)) {
      var offset = fns.length === 3 ? 1 : 0;
      hidden = fns[offset] == null ? hidden : fns[offset];
      output = fns[offset + 1] == null ? output : fns[offset + 1];
    } else if (fns) {
      hidden = fns.hidden == null ? hidden : fns.hidden;
      output = fns.output == null ? output : fns.output;
    }
    var hiddenFn = typeof hidden === 'function' ? hidden : actFn(hidden);
    var outputFn = typeof output === 'function' ? output : actFn(output);

    function affine(matrix, bias, values) {
      return matrix.map(function (row, i) {
        var sum = 0;
        for (var j = 0; j < row.length; j++) sum += row[j] * values[j];
        return sum + bias[i];
      });
    }

    var z1 = affine(p.W1, p.b1, x);
    var h = z1.map(function (z) { return hiddenFn(z); });
    var z2 = affine(p.W2, p.b2, h);
    var out = z2.map(function (z) { return outputFn(z); });
    return { pre: [null, z1, z2], act: [x, h, out] };
  }

  function heatGrid(params, n, fns) {
    if (n === undefined) n = 48;
    if (!Number.isInteger(n) || n < 1) {
      throw new RangeError('Izgara boyutu pozitif bir tam sayı olmalıdır.');
    }
    var values = new Float32Array(n * n);
    for (var y = 0; y < n; y++) {
      var b = n === 1 ? 0.5 : -0.2 + 1.4 * y / (n - 1);
      for (var x = 0; x < n; x++) {
        var a = n === 1 ? 0.5 : -0.2 + 1.4 * x / (n - 1);
        values[y * n + x] = forward(params, [a, b], fns).act[2][0];
      }
    }
    return values;
  }

  function truthRows(params, fns) {
    return [[0, 0, 0], [0, 1, 1], [1, 0, 1], [1, 1, 0]]
      .map(function (row) {
        var prediction = forward(params, row.slice(0, 2), fns).act[2][0];
        return {
          a: row[0],
          b: row[1],
          expected: row[2],
          prediction: prediction,
          ok: Number.isFinite(prediction) &&
            Math.round(prediction) === row[2] &&
            (prediction >= 0.5 ? 1 : 0) === row[2]
        };
      });
  }

  function selfCheck(data, params) {
    var result = {
      ok: false,
      jsValue: null,
      pyValue: null,
      diff: null,
      checked: 0,
      passed: 0,
      failed: 0,
      examplesChecked: 0,
      examplesPassed: 0,
      examplesFailed: 0
    };

    /* fix (Claude): data.prediction is rounded to 6 decimals (tolerance 1e-5) but
       data.examples[].prediction to 5 decimals (tolerance 1e-4); the original 1e-6 for
       both made a correct network report "Ön hesap uyuşmuyor". Activation functions now
       come from data.nodes[].activation_fn instead of being assumed. */
    var fns = fnsFrom(data);
    function compare(inputs, value, example) {
      var jsValue = null;
      var diff = null;
      try {
        jsValue = forward(params, inputs, fns).act[2][0];
        if (Number.isFinite(jsValue) && Number.isFinite(value)) {
          var distance = Math.abs(jsValue - value);
          if (Number.isFinite(distance)) diff = distance;
        }
      } catch (_) {}
      var ok = diff !== null && diff <= (example ? 1e-4 : 1e-5);
      result.checked++;
      result[ok ? 'passed' : 'failed']++;
      if (example) {
        result.examplesChecked++;
        result[ok ? 'examplesPassed' : 'examplesFailed']++;
      } else {
        result.jsValue = Number.isFinite(jsValue) ? jsValue : null;
        result.pyValue = Number.isFinite(value) ? value : null;
        result.diff = diff;
      }
    }

    try {
      data = data || {};
      compare(data.inputs, data.prediction, false);
      var examples = Array.isArray(data.examples) ? data.examples : [];
      [[0, 0], [0, 1], [1, 0], [1, 1]].forEach(function (inputs) {
        var example = examples.find(function (entry) {
          return entry && Array.isArray(entry.input) &&
            entry.input.length === 2 &&
            entry.input[0] === inputs[0] && entry.input[1] === inputs[1];
        });
        compare(inputs, example ? example.prediction : undefined, true);
      });
      result.ok = result.checked === 5 && result.failed === 0;
    } catch (_) {
      result.ok = false;
    }
    return result;
  }

  /* added (Claude): activation functions per layer from data.nodes (brief: "act from nodes[].activation_fn") */
  function fnsFrom(data) {
    var fns = { hidden: 'tanh', output: 'sigmoid' };
    var nodes = data && Array.isArray(data.nodes) ? data.nodes : [];
    nodes.forEach(function (n) {
      if (!n || typeof n.activation_fn !== 'string') return;
      if (n.layer === 1) fns.hidden = n.activation_fn;
      else if (n.layer === 2) fns.output = n.activation_fn;
    });
    return fns;
  }

  function fmt3(x) {
    return Number.isFinite(x) ? x.toFixed(3) : '—';
  }

  var M = {
    tok: tok,
    actFn: actFn,
    forward: forward,
    normalizeWeights: normalizeWeights,
    heatGrid: heatGrid,
    truthRows: truthRows,
    selfCheck: selfCheck,
    fnsFrom: fnsFrom,
    fmt3: fmt3
  };


/* ---- PART 2a (GPT Astra): SVG helpers, theme, layout, network renderer ---- */
var SVGNS = 'http://www.w3.org/2000/svg';

function h(tag, cls, text) {
  var el = document.createElement(tag);
  if (cls != null) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

function sv(tag, attrs) {
  var el = document.createElementNS(SVGNS, tag);
  Object.keys(attrs || {}).forEach(function (key) {
    el.setAttribute(key, attrs[key]);
  });
  return el;
}

function readTheme() {
  return {
    pos: tok('--sig-pos', '#38BDF8'),
    neg: tok('--sig-neg', '#FB923C'),
    zero: tok('--sig-zero', '#334155'),
    bg: tok('--bg', '#090B10'),
    text: tok('--text', '#EDF1F7'),
    muted: tok('--muted', '#8A96AD'),
    border: tok('--border', '#252D3F'),
    success: tok('--success', '#10B981'),
    danger: tok('--danger', '#F43F5E'),
    warn: tok('--warn', '#F59E0B')
  };
}

function layoutNodes() {
  var pos = {
    'neuron:0:0': { x: 30, y: 70, layer: 0, index: 0 },
    'neuron:0:1': { x: 30, y: 140, layer: 0, index: 1 }
  };
  for (var j = 0; j < 8; j++) {
    pos['neuron:1:' + j] = {
      x: 150, y: 15 + j * 180 / 7, layer: 1, index: j
    };
  }
  pos['neuron:2:0'] = { x: 270, y: 105, layer: 2, index: 0 };
  return pos;
}

/* fix (Claude): Astra's renderNetwork removed and recreated every node <g> on each call.
   Hover/focus/select call it, so the focused node was destroyed (keyboard focus fell to
   <body>, arrow keys and Enter stopped working) and mouseover/mouseout looped. It now
   creates elements once per id and updates attributes in place; it also guards missing
   positions/activations and non-array nodes/edges. */
function renderNetwork(st) {
  var edgeLayer = st.refs.edgeLayer;
  var nodeLayer = st.refs.nodeLayer;
  var theme = st.theme;
  var focus = st.selected || st.hover;
  var max = 1e-9;
  var data = st.data || {};
  var edges = Array.isArray(data.edges) ? data.edges : [];
  var nodes = Array.isArray(data.nodes) ? data.nodes : [];
  var cache = st.svgCache || (st.svgCache = { edges: {}, nodes: {} });
  var seenE = {}, seenN = {};
  function num(v) { v = Number(v); return Number.isFinite(v) ? v : 0; }

  edges.forEach(function (edge) {
    var v = num(st.mode === 'weight' ? edge.weight : edge.signal);
    max = Math.max(max, Math.abs(v));
  });

  edges.forEach(function (edge) {
    var source = st.pos[edge.source];
    var target = st.pos[edge.target];
    if (!source || !target) return;
    var key = edge.source + '>' + edge.target;
    var v = num(st.mode === 'weight' ? edge.weight : edge.signal);
    var ratio = Math.abs(v) / max;
    var dim = focus && edge.source !== focus && edge.target !== focus;
    var line = cache.edges[key];
    if (!line) {
      line = cache.edges[key] = sv('line', { x1: source.x, y1: source.y, x2: target.x, y2: target.y });
      line.dataset.source = edge.source;
      line.dataset.target = edge.target;
      edgeLayer.appendChild(line);
    }
    seenE[key] = true;
    line.setAttribute('stroke', v > 0 ? theme.pos : v < 0 ? theme.neg : theme.zero);
    line.setAttribute('stroke-width', 1 + 5 * ratio);
    line.setAttribute('stroke-opacity', dim ? 0.08 : 0.25 + 0.6 * ratio);
    /* sign is also shown by dash, so colour is never the only cue */
    if (v < 0) line.setAttribute('stroke-dasharray', '4 3'); else line.removeAttribute('stroke-dasharray');
  });

  nodes.forEach(function (node) {
    var pos = st.pos[node.id];
    if (!pos) return;
    var act = num(node.activation);
    var selected = node.id === st.selected;
    var magnitude = Math.abs(act);
    var label = nodeLabel(node);
    var c = cache.nodes[node.id];
    if (!c) {
      var group = sv('g', { transform: 'translate(' + pos.x + ',' + pos.y + ')', tabindex: '0', role: 'button' });
      group.dataset.id = node.id;
      var circle = sv('circle', { r: node.layer === 2 ? 14 : 11 });
      var text = sv('text', { 'text-anchor': 'middle', dy: 3, 'font-size': 9, 'pointer-events': 'none' });
      text.textContent = label;
      group.appendChild(circle); group.appendChild(text); nodeLayer.appendChild(group);
      c = cache.nodes[node.id] = { g: group, circle: circle, text: text };
    }
    seenN[node.id] = true;
    c.g.setAttribute('aria-pressed', selected ? 'true' : 'false');
    c.g.setAttribute('aria-label', label + ', aktivasyon ' + act.toFixed(3));
    c.g.classList.toggle('axn-dim', node.layer === 1 && magnitude < 0.02);
    c.g.classList.toggle('axn-lit', !!st.lit && !!st.lit[node.id]);
    c.circle.setAttribute('fill', act >= 0 ? theme.pos : theme.neg);
    c.circle.setAttribute('fill-opacity', 0.15 + 0.85 * Math.min(1, magnitude));
    c.circle.setAttribute('stroke', selected ? theme.text : theme.border);
    c.circle.setAttribute('stroke-width', selected ? 2.5 : 1.2);
    c.circle.setAttribute('opacity', focus && !selected && node.id !== focus &&
      !edges.some(function (e) { return (e.source === focus && e.target === node.id) || (e.target === focus && e.source === node.id); }) ? 0.35 : 1);
    c.text.setAttribute('fill', theme.text);
  });

  Object.keys(cache.edges).forEach(function (k) {
    if (!seenE[k]) { var el = cache.edges[k]; if (el.parentNode) el.parentNode.removeChild(el); delete cache.edges[k]; }
  });
  Object.keys(cache.nodes).forEach(function (k) {
    if (!seenN[k]) { var el = cache.nodes[k].g; if (el.parentNode) el.parentNode.removeChild(el); delete cache.nodes[k]; }
  });
}

/* ---- PART 2b (Claude): DOM, readout, heatmap, truth table, detail, tooltip ---- */
var CSS = [
  '.axn{position:relative;display:flex;flex-direction:column;gap:var(--s3,12px);min-width:0;font-size:var(--fs-sm,12.5px);color:var(--text,#EDF1F7)}',
  '.axn-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px}',
  '.axn-row button{min-width:44px;min-height:36px;padding:2px 10px;font-family:var(--font-mono,Consolas,monospace)}',
  '.axn-row button[aria-pressed=true]{background:var(--accent-fill,var(--accent,#6366F1));border-color:var(--accent-fill,var(--accent,#6366F1));color:var(--accent-fg,#fff)}',
  '.axn-ro{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 10px;align-items:baseline;padding:var(--s3,12px);border:1px solid var(--border,#252D3F);border-radius:var(--r-md,10px);background:var(--bg,#090B10)}',
  '.axn[data-state=fail] .axn-ro{border-color:var(--danger,#F43F5E)}',
  '.axn-k{font-size:var(--fs-xs,11px);color:var(--muted,#8A96AD);text-transform:uppercase;letter-spacing:.06em}',
  '.axn-v{font:600 var(--fs-md,16px)/1.3 var(--font-mono,Consolas,monospace);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}',
  '.axn-meta{font:var(--fs-xs,11px)/1.4 var(--font-mono,Consolas,monospace);color:var(--muted,#8A96AD);overflow-wrap:anywhere}',
  '.axn-st{font-weight:600}.axn-st[data-ok=true]{color:var(--success,#10B981)}.axn-st[data-ok=false]{color:var(--danger,#F43F5E)}',
  '.axn-badge{display:inline-block;padding:1px 8px;border-radius:var(--r-pill,999px);border:1px solid currentColor;font-size:var(--fs-xs,11px)}',
  '.axn-badge[data-ok=true]{color:var(--success,#10B981)}.axn-badge[data-ok=false]{color:var(--warn,#F59E0B)}',
  '.axn-err{padding:var(--s2,8px) var(--s3,12px);border:1px solid var(--danger,#F43F5E);border-radius:var(--r-md,10px);color:var(--danger,#F43F5E);overflow-wrap:anywhere}',
  '.axn-svg{display:block;width:100%;height:auto;max-height:360px}',
  '.axn-svg g[data-id]{cursor:pointer;outline:none}',
  '.axn-svg g[data-id]:focus-visible circle{stroke:var(--focus,#22D3EE);stroke-width:3}',
  '.axn-svg g.axn-dim{opacity:.45}',
  '.axn-svg g.axn-lit circle{stroke:var(--text,#EDF1F7);stroke-width:2}',
  '.axn-tip{position:absolute;z-index:5;max-width:min(280px,100%);padding:6px 8px;white-space:pre-line;pointer-events:none;font:var(--fs-xs,11px)/1.45 var(--font-mono,Consolas,monospace);background:var(--glass,rgba(17,21,31,.92));border:1px solid var(--border,#252D3F);border-radius:var(--r-sm,6px);box-shadow:var(--sh-2,0 8px 24px rgba(0,0,0,.45))}',
  '.axn-detail{border:1px solid var(--border,#252D3F);border-radius:var(--r-md,10px);padding:var(--s3,12px);min-width:0}',
  '.axn-detail h4{margin:0 0 6px;font-size:var(--fs-md,16px)}',
  '.axn-detail dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 10px;margin:0 0 8px}',
  '.axn-detail dt{color:var(--muted,#8A96AD)}.axn-detail dd{margin:0;font-family:var(--font-mono,Consolas,monospace);overflow-wrap:anywhere}',
  '.axn-detail ol{margin:0;padding-left:20px;font-family:var(--font-mono,Consolas,monospace);font-size:var(--fs-xs,11px)}',
  '.axn-hint{color:var(--muted,#8A96AD)}',
  '.axn-heat{display:block;width:min(240px,100%);height:auto;aspect-ratio:1;border-radius:var(--r-md,10px);border:1px solid var(--border,#252D3F);margin:0 auto}',
  '.axn-cap{font-size:var(--fs-xs,11px);color:var(--muted,#8A96AD);text-align:center}',
  '.axn-table{border-collapse:collapse;width:100%;font:var(--fs-xs,11px) var(--font-mono,Consolas,monospace);font-variant-numeric:tabular-nums}',
  '.axn-table caption{text-align:left;color:var(--muted,#8A96AD);padding-bottom:4px}',
  '.axn-table th,.axn-table td{border-bottom:1px solid var(--border,#252D3F);padding:5px 6px;text-align:left}',
  '.axn-table tbody tr{cursor:pointer}.axn-table tbody tr:focus-visible{outline:2px solid var(--focus,#22D3EE);outline-offset:-2px}',
  '.axn-table tr.axn-cur{background:var(--elevated,#181E2C)}',
  '.axn-table td[data-ok=true]{color:var(--success,#10B981)}.axn-table td[data-ok=false]{color:var(--danger,#F43F5E)}',
  '@media (prefers-reduced-motion:reduce){.axn *{transition:none!important;animation:none!important}}'
].join('\n');
var styleEl = null;

function nodeLabel(node) {
  if (!node) return '—';
  if (node.layer === 0) return node.index === 0 ? 'a' : 'b';
  if (node.layer === 1) return 'h' + (node.index + 1);
  return 'y';
}
function fmtN(v, d) { return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—'; }
function findNode(st, id) {
  var list = st && st.data && Array.isArray(st.data.nodes) ? st.data.nodes : [];
  for (var i = 0; i < list.length; i++) if (list[i] && String(list[i].id) === String(id)) return list[i];
  return null;
}
function curInputs(data) {
  var v = data && Array.isArray(data.inputs) ? data.inputs : [];
  return [Number(v[0]), Number(v[1])];
}

function buildDom(root) {
  if (!styleEl) {
    styleEl = h('style');
    styleEl.textContent = CSS;
    (document.head || document.documentElement).appendChild(styleEl);
  }
  var refs = {};
  var wrap = refs.wrap = h('div', 'axn');
  wrap.dataset.state = 'unknown';

  var pairs = h('div', 'axn-row');
  pairs.setAttribute('role', 'group'); pairs.setAttribute('aria-label', 'XOR girdisi');
  refs.pairs = [[0, 0], [0, 1], [1, 0], [1, 1]].map(function (p) {
    var b = h('button', null, p[0] + ' ' + p[1]);
    b.type = 'button'; b.dataset.a = String(p[0]); b.dataset.b = String(p[1]);
    b.setAttribute('aria-pressed', 'false'); b.setAttribute('aria-label', 'a=' + p[0] + ', b=' + p[1]);
    pairs.appendChild(b); return b;
  });
  var mode = h('div', 'axn-row');
  mode.setAttribute('role', 'group'); mode.setAttribute('aria-label', 'Kenar gösterimi (W)');
  refs.modeBtns = [['weight', 'Ağırlık'], ['signal', 'Sinyal']].map(function (m) {
    var b = h('button', null, m[1]);
    b.type = 'button'; b.dataset.mode = m[0]; b.setAttribute('aria-pressed', 'false');
    mode.appendChild(b); return b;
  });
  var bar = h('div', 'axn-row'); bar.appendChild(pairs); bar.appendChild(mode);
  wrap.appendChild(bar);

  var ro = h('div', 'axn-ro'); ro.setAttribute('aria-live', 'polite');
  refs.ro = {};
  [['pred', 'Tahmin'], ['exp', 'Beklenen'], ['status', 'Durum'], ['meta', 'Eğitim']].forEach(function (r) {
    ro.appendChild(h('span', 'axn-k', r[1]));
    var v = h('span', r[0] === 'meta' ? 'axn-meta' : r[0] === 'status' ? 'axn-st' : 'axn-v', '—');
    ro.appendChild(v); refs.ro[r[0]] = v;
  });
  ro.appendChild(h('span', 'axn-k', 'Kontrol'));
  var chk = h('span'); refs.check = h('span', 'axn-badge', 'JS doğrulama bekleniyor'); chk.appendChild(refs.check);
  ro.appendChild(chk);
  wrap.appendChild(ro);

  refs.err = h('div', 'axn-err'); refs.err.setAttribute('role', 'alert'); refs.err.hidden = true;
  wrap.appendChild(refs.err);

  var svg = refs.svg = sv('svg', { viewBox: '0 0 300 210', 'class': 'axn-svg', role: 'group',
    'aria-label': 'XOR sinir ağı diyagramı: 2 giriş, 8 gizli, 1 çıkış nöronu' });
  refs.edgeLayer = sv('g', {}); refs.pulseLayer = sv('g', { 'pointer-events': 'none' }); refs.nodeLayer = sv('g', {});
  svg.appendChild(refs.edgeLayer); svg.appendChild(refs.pulseLayer); svg.appendChild(refs.nodeLayer);
  wrap.appendChild(svg);

  refs.tip = h('div', 'axn-tip'); refs.tip.setAttribute('role', 'tooltip'); refs.tip.id = 'axn-tip'; refs.tip.hidden = true;
  wrap.appendChild(refs.tip);

  refs.detail = h('div', 'axn-detail'); refs.detail.setAttribute('aria-live', 'polite');
  wrap.appendChild(refs.detail);

  refs.heat = h('canvas', 'axn-heat'); refs.heat.width = 240; refs.heat.height = 240;
  refs.heat.setAttribute('role', 'img');
  refs.heat.setAttribute('aria-label', 'Karar sınırı ısı haritası: yatay a, dikey b, turuncu 0, mavi 1');
  wrap.appendChild(refs.heat);
  wrap.appendChild(h('div', 'axn-cap', 'Karar sınırı (a yatay, b dikey · turuncu→0, mavi→1)'));

  var table = h('table', 'axn-table');
  table.appendChild(h('caption', null, 'Doğruluk tablosu (satıra tıklayınca girdi değişir)'));
  var thead = h('thead'), hr = h('tr');
  ['a', 'b', 'beklenen', 'tahmin', 'doğru?'].forEach(function (t) { var th = h('th', null, t); th.scope = 'col'; hr.appendChild(th); });
  thead.appendChild(hr); table.appendChild(thead);
  refs.truthBody = h('tbody'); table.appendChild(refs.truthBody);
  wrap.appendChild(table);

  root.appendChild(wrap);
  return refs;
}

function renderReadout(st) {
  var r = st.refs, d = st.data;
  r.modeBtns.forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.mode === st.mode)); });
  if (!d) return;
  var inp = curInputs(d);
  r.pairs.forEach(function (b) {
    b.setAttribute('aria-pressed', String(Number(b.dataset.a) === inp[0] && Number(b.dataset.b) === inp[1]));
  });
  var cls = d.predicted_class != null ? String(d.predicted_class) :
    (typeof d.prediction === 'number' ? String(d.prediction >= 0.5 ? 1 : 0) : '—');
  var exp = d.expected != null ? String(d.expected) :
    (Number.isFinite(inp[0]) && Number.isFinite(inp[1]) ? String(inp[0] ^ inp[1]) : '—');
  r.ro.pred.textContent = cls + ' (' + fmt3(d.prediction) + ')';
  r.ro.exp.textContent = exp;
  var trained = d.trained === true;
  var match = cls !== '—' && cls === exp;
  r.ro.status.textContent = trained ? 'eğitilmiş XOR' + (match ? ' · ✓ doğru' : ' · ✕ yanlış tahmin') : 'FAILED: eğitilmemiş';
  r.ro.status.dataset.ok = String(trained && match);
  st.refs.wrap.dataset.state = trained && match ? 'ok' : 'fail';
  var meta = [];
  if (d.backend != null) meta.push(String(d.backend));
  if (d.epochs != null) meta.push(d.epochs + ' adım');
  if (typeof d.loss === 'number') meta.push('kayıp ' + d.loss.toFixed(4));
  if (typeof d.max_error === 'number') meta.push('max hata ' + d.max_error.toFixed(4));
  r.ro.meta.textContent = meta.join(' · ') || '—';
  var c = st.check;
  r.check.textContent = !c ? 'JS doğrulama yok' : c.ok ? 'JS doğrulama ✓ (' + c.passed + '/' + c.checked + ')' : 'Ön hesap uyuşmuyor';
  r.check.dataset.ok = String(!!(c && c.ok));
  r.check.title = c && c.diff != null ? 'fark ' + c.diff.toExponential(2) : '';
}

function renderError(st, message) {
  var e = st.refs.err;
  if (message) {
    e.textContent = String(message); e.hidden = false; st.refs.wrap.dataset.state = 'fail';
  } else { e.textContent = ''; e.hidden = true; }
}

function parseColor(s) {
  s = String(s || '').trim();
  var m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (m) {
    var x = m[1];
    if (x.length === 3) x = x[0] + x[0] + x[1] + x[1] + x[2] + x[2];
    return [parseInt(x.slice(0, 2), 16), parseInt(x.slice(2, 4), 16), parseInt(x.slice(4, 6), 16)];
  }
  m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(s);
  if (m) return [+m[1], +m[2], +m[3]];
  return [128, 128, 128];
}
function ramp(t, neg, mid, pos) {
  var a = t < 0.5 ? neg : mid, b = t < 0.5 ? mid : pos, u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
}
function heatPx(v) { return (v + 0.2) / 1.4 * 240; }

function renderHeat(st) {
  var cv = st.refs.heat, ctx = null;
  try { ctx = cv.getContext && cv.getContext('2d'); } catch (_) { ctx = null; }
  if (!ctx) return;
  var key = st.params ? JSON.stringify(st.params) + '|' + JSON.stringify(st.theme) + '|' + st.fnsKey : '';
  try {
    if (!st.params) { ctx.clearRect(0, 0, 240, 240); st.heatKey = ''; return; }
    if (st.heatKey !== key || !st.heatBase) {
      var n = 48, g = heatGrid(st.params, n, st.fns), off = document.createElement('canvas');
      off.width = n; off.height = n;
      var octx = off.getContext('2d'), img = octx.createImageData(n, n);
      var neg = parseColor(st.theme.neg), mid = parseColor(st.theme.bg), pos = parseColor(st.theme.pos);
      for (var y = 0; y < n; y++) for (var x = 0; x < n; x++) {
        var c = ramp(Math.max(0, Math.min(1, g[y * n + x])), neg, mid, pos), i = ((n - 1 - y) * n + x) * 4;
        img.data[i] = c[0]; img.data[i + 1] = c[1]; img.data[i + 2] = c[2]; img.data[i + 3] = 255;
      }
      octx.putImageData(img, 0, 0);
      st.heatBase = off; st.heatKey = key;
    }
    ctx.clearRect(0, 0, 240, 240);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(st.heatBase, 0, 0, 240, 240);
    var p0 = heatPx(0.5);
    ctx.strokeStyle = st.theme.muted; ctx.globalAlpha = 0.35; ctx.setLineDash([3, 4]);
    ctx.beginPath(); ctx.moveTo(p0, 0); ctx.lineTo(p0, 240); ctx.moveTo(0, 240 - p0); ctx.lineTo(240, 240 - p0); ctx.stroke();
    ctx.setLineDash([]); ctx.globalAlpha = 1;
    truthRows(st.params, st.fns).forEach(function (r) {
      var x = heatPx(r.a), y = 240 - heatPx(r.b);
      ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2);
      ctx.lineWidth = 3; ctx.strokeStyle = r.ok ? st.theme.success : st.theme.danger; ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2);
      if (r.expected === 1) { ctx.fillStyle = st.theme.text; ctx.fill(); }
      else { ctx.lineWidth = 2; ctx.strokeStyle = st.theme.text; ctx.stroke(); }
    });
    var inp = curInputs(st.data);
    if (Number.isFinite(inp[0]) && Number.isFinite(inp[1])) {
      var cx = heatPx(inp[0]), cy = 240 - heatPx(inp[1]);
      ctx.strokeStyle = st.theme.text; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(cx - 14, cy); ctx.lineTo(cx - 10, cy); ctx.moveTo(cx + 10, cy); ctx.lineTo(cx + 14, cy);
      ctx.moveTo(cx, cy - 14); ctx.lineTo(cx, cy - 10); ctx.moveTo(cx, cy + 10); ctx.lineTo(cx, cy + 14); ctx.stroke();
    }
  } catch (_) { /* canvas unavailable: heatmap is decorative, the truth table carries the data */ }
}

function renderTruth(st) {
  var body = st.refs.truthBody;
  while (body.firstChild) body.removeChild(body.firstChild);
  if (!st.params) return;
  var inp = curInputs(st.data);
  truthRows(st.params, st.fns).forEach(function (r) {
    var tr = h('tr');
    tr.tabIndex = 0; tr.dataset.a = String(r.a); tr.dataset.b = String(r.b);
    tr.setAttribute('aria-label', 'a=' + r.a + ', b=' + r.b + ' girdisini seç');
    if (r.a === inp[0] && r.b === inp[1]) { tr.className = 'axn-cur'; tr.setAttribute('aria-current', 'true'); }
    [String(r.a), String(r.b), String(r.expected), fmt3(r.prediction)].forEach(function (t) { tr.appendChild(h('td', null, t)); });
    var ok = h('td', null, r.ok ? '✓ doğru' : '✕ yanlış'); ok.dataset.ok = String(r.ok);
    tr.appendChild(ok); body.appendChild(tr);
  });
}

function incoming(st, id) {
  var edges = st.data && Array.isArray(st.data.edges) ? st.data.edges : [];
  return edges.filter(function (e) { return e && e.target === id; }).sort(function (x, y) {
    return Math.abs(Number(y.signal) || 0) - Math.abs(Number(x.signal) || 0);
  });
}

function renderDetail(st) {
  var box = st.refs.detail;
  while (box.firstChild) box.removeChild(box.firstChild);
  var node = st.selected ? findNode(st, st.selected) : null;
  if (!node) { box.appendChild(h('p', 'axn-hint', 'Ayrıntı için bir nörona tıklayın (ok tuşları + Enter).')); return; }
  var layerName = ['giriş', 'gizli', 'çıkış'][node.layer] || String(node.layer);
  box.appendChild(h('h4', null, nodeLabel(node) + ' · ' + layerName + ' katmanı'));
  var dl = h('dl');
  function row(k, v) { dl.appendChild(h('dt', null, k)); dl.appendChild(h('dd', null, v)); }
  row('kimlik', String(node.id));
  if (node.layer === 0) {
    row('aktivasyon (girdi)', fmtN(node.activation, 5));
    box.appendChild(dl);
    var out = (st.data.edges || []).filter(function (e) { return e && e.source === node.id; }).length;
    box.appendChild(h('p', 'axn-hint', 'Giriş nöronu: ' + out + ' gizli nörona bağlı.'));
    return;
  }
  row('bias', fmtN(node.bias, 5));
  row('pre_activation (z)', fmtN(node.pre_activation, 5));
  row('activation_fn', node.activation_fn ? String(node.activation_fn) : '—');
  row('activation', fmtN(node.activation, 5));
  box.appendChild(dl);
  box.appendChild(h('p', 'axn-hint', 'Gelen katkılar (|sinyal| büyükten küçüğe):'));
  var ol = h('ol');
  incoming(st, node.id).forEach(function (e) {
    ol.appendChild(h('li', null, nodeLabel(findNode(st, e.source)) + ': w=' + fmtN(e.weight, 4) + ' · sinyal=' + fmtN(e.signal, 4)));
  });
  box.appendChild(ol);
}

function tipText(st, id) {
  var node = findNode(st, id);
  if (!node) return '';
  var lines = [nodeLabel(node) + ' · ' + String(node.id)];
  if (node.layer === 0) { lines.push('girdi = ' + fmtN(node.activation, 3)); return lines.join('\n'); }
  lines.push('fn: ' + (node.activation_fn || '—'));
  lines.push('bias ' + fmtN(node.bias, 4) + ' · z ' + fmtN(node.pre_activation, 4));
  lines.push('aktivasyon ' + fmtN(node.activation, 4));
  var inc = incoming(st, node.id);
  if (node.layer === 1 && inc.length) {
    var byIdx = {};
    inc.forEach(function (e) { var s = findNode(st, e.source); if (s) byIdx[s.index] = e; });
    var w1 = byIdx[0] ? byIdx[0].weight : NaN, w2 = byIdx[1] ? byIdx[1].weight : NaN, inp = curInputs(st.data);
    lines.push('z = ' + fmtN(w1, 3) + '·' + fmtN(inp[0], 0) + ' + ' + fmtN(w2, 3) + '·' + fmtN(inp[1], 0) +
      ' + ' + fmtN(node.bias, 3) + ' = ' + fmtN(node.pre_activation, 4));
  } else if (node.layer === 2) {
    lines.push('z = Σ w·h + b = ' + fmtN(node.pre_activation, 4));
  }
  return lines.join('\n');
}

/* ---- PART 3 (GPT Astra): interactions, animation, mount/update/destroy ---- */
var st = null, raf = 0, listeners = [], mo = null, mq = null;
function on(el, type, fn, o) {
  el.addEventListener(type, fn, o);
  listeners.push(function () { el.removeEventListener(type, fn, o); });
}
function reduced() {
  return typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
function renderAll() {
  if (!st || !st.data) return;
  renderNetwork(st); renderReadout(st); renderTruth(st);
  renderDetail(st); renderHeat(st);
}
function select(id) {
  if (!st || !st.data) return;
  st.selected = st.selected === id ? null : id;
  var node = st.data.nodes.find(function (n) { return String(n.id) === st.selected; });
  if (!node) st.selected = null;
  renderNetwork(st); renderDetail(st);
  try {
    if (typeof st.opts.onNodeSelect === 'function') st.opts.onNodeSelect(node || null);
  } catch (e) {}
}
function clearPulse() {
  if (raf) window.cancelAnimationFrame(raf);
  raf = 0;
  if (st) while (st.refs.pulseLayer.firstChild)
    st.refs.pulseLayer.removeChild(st.refs.pulseLayer.firstChild);
}
function pulse() {
  clearPulse();
  if (!st || !st.data || reduced()) return;
  var owner = st, edges = st.data.edges || [], incoming = Object.create(null);
  var dots = [], start = null, color = readTheme().text;
  function endpoint(edge, key, fallback) {
    var value = edge[key] == null ? edge[fallback] : edge[key];
    return value && typeof value === 'object' ? value.id : value;
  }
  edges.forEach(function (e) { incoming[endpoint(e, 'target', 'to')] = true; });
  edges.forEach(function (e) {
    var source = endpoint(e, 'source', 'from'), target = endpoint(e, 'target', 'to');
    var a = owner.pos[source], b = owner.pos[target];
    if (!a || !b) return;
    var circle = sv('circle', { r: 2.5, fill: color, visibility: 'hidden' });
    owner.refs.pulseLayer.appendChild(circle);
    dots.push({ el: circle, a: a, b: b, delay: incoming[source] ? 450 : 0 });
  });
  if (!dots.length) return;
  function frame(now) {
    if (st !== owner) { raf = 0; return; }
    if (start === null) start = now;
    var elapsed = now - start;
    if (elapsed >= 900 || reduced()) { clearPulse(); return; }
    dots.forEach(function (d) {
      var t = (elapsed - d.delay) / 450;
      d.el.setAttribute('visibility', t >= 0 && t < 1 ? 'visible' : 'hidden');
      t = Math.max(0, Math.min(1, t)); t = 1 - (1 - t) * (1 - t);
      d.el.setAttribute('cx', d.a.x + (d.b.x - d.a.x) * t);
      d.el.setAttribute('cy', d.a.y + (d.b.y - d.a.y) * t);
    });
    raf = window.requestAnimationFrame(frame);
  }
  raf = window.requestAnimationFrame(frame);
}
/* fix (Claude): Astra pulsed here AND again in update() when the new data arrived, so every
   change animated twice. With onInputChange the pulse now comes from update() (new data);
   only without a callback is there nothing to wait for, so pulse immediately. */
function setInputs(a, b) {
  if (!st) return;
  if (typeof st.opts.onInputChange === 'function') {
    try { st.opts.onInputChange(+a, +b); } catch (e) { console.warn('AxisNeural onInputChange:', e); }
  } else pulse();
}
function inputs(data) {
  var v = data && data.inputs;
  return v ? [+(v.a == null ? v[0] : v.a), +(v.b == null ? v[1] : v.b)] : [];
}
function update(data) {
  if (!st) throw Error('AxisNeural.mount önce çağrılmalı');
  var previous = st.data, before = inputs(previous), after = inputs(data);
  if (!data || data.available === false) {
    clearPulse(); st.data = null;
    renderError(st, (data && (data.reason || data.error)) || 'Sinir ağı verisi alınamadı');
    return;
  }
  /* fix (Claude): guard non-array nodes/edges (Astra called data.nodes.some unguarded) */
  if (!Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
    clearPulse(); st.data = null;
    renderError(st, 'Sinir ağı verisi eksik (nodes/edges)');
    return;
  }
  var params = M.normalizeWeights(data.weights);
  st.fns = M.fnsFrom(data); st.fnsKey = st.fns.hidden + '/' + st.fns.output;
  if (!data.nodes.some(function (n) { return String(n.id) === st.selected; })) st.selected = null;
  st.check = params ? M.selfCheck(data, params) : null;
  if (st.check && !st.check.ok) console.warn('AxisNeural: Ön hesap uyuşmuyor', st.check);
  renderError(st, params ? null : 'Ağırlıklar okunamadı; ısı haritası çizilemiyor');
  st.data = data; st.params = params; renderAll();
  if (previous && (before[0] !== after[0] || before[1] !== after[1])) pulse();
}
function mount(el, opts) {
  destroy();
  if (!(el instanceof Element)) throw TypeError('Kök bir Element olmalı');
  var refs = buildDom(el);
  st = { refs: refs, data: null, params: null, check: null, mode: 'weight',
    selected: null, hover: null, theme: readTheme(), pos: layoutNodes(), opts: opts || {} };
  function nodeAt(target) {
    var node = target && target.closest ? target.closest('g[data-id]') : null;
    return node && refs.nodeLayer.contains(node) ? node : null;
  }
  function hideTip() {
    if (!st) return;
    st.hover = null; refs.tip.hidden = true; renderNetwork(st);
  }
  function showTip(e) {
    var node = nodeAt(e.target);
    if (!node || !st || !st.data) return;
    st.hover = node.dataset.id;
    refs.tip.textContent = tipText(st, st.hover); refs.tip.hidden = false;
    var wrap = refs.wrap.getBoundingClientRect(), box = node.getBoundingClientRect();
    refs.tip.style.maxWidth = Math.max(0, wrap.width) + 'px';
    var width = refs.tip.getBoundingClientRect().width;
    refs.tip.style.left = Math.max(0, Math.min(wrap.width - width,
      box.left - wrap.left + box.width / 2 - width / 2)) + 'px';
    refs.tip.style.top = Math.max(0, box.bottom - wrap.top + 8) + 'px';
    renderNetwork(st);
  }
  refs.pairs.forEach(function (button) {
    on(button, 'click', function () { setInputs(+button.dataset.a, +button.dataset.b); });
  });
  function truthEvent(e) {
    var row = e.target.closest && e.target.closest('tr[data-a][data-b]');
    if (!row || !refs.truthBody.contains(row)) return;
    if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault(); setInputs(+row.dataset.a, +row.dataset.b);
  }
  on(refs.truthBody, 'click', truthEvent); on(refs.truthBody, 'keydown', truthEvent);
  refs.modeBtns.forEach(function (button) {
    on(button, 'click', function () {
      st.mode = button.dataset.mode; renderNetwork(st); renderReadout(st);
    });
  });
  on(refs.nodeLayer, 'click', function (e) { var n = nodeAt(e.target); if (n) select(n.dataset.id); });
  on(refs.nodeLayer, 'keydown', function (e) {
    if (!st || !st.data) return;
    var n = nodeAt(e.target), keys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
    /* fix (Claude): stopPropagation so Esc only deselects and does not also close the shell pane */
    if (e.key === 'Escape' && st.selected !== null) { e.preventDefault(); e.stopPropagation(); select(null); }
    else if (n && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); select(n.dataset.id); }
    else if (n && keys.indexOf(e.key) !== -1) {
      e.preventDefault();
      var nodes = st.data.nodes, i = nodes.findIndex(function (v) { return String(v.id) === n.dataset.id; });
      if (!nodes.length) return;
      var id = String(nodes[(i + (e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 1) + nodes.length) % nodes.length].id);
      Array.prototype.some.call(refs.nodeLayer.querySelectorAll('g[data-id]'), function (g) {
        if (g.dataset.id !== id) return false;
        g.focus(); return true;
      });
    }
  });
  on(refs.nodeLayer, 'mouseover', showTip); on(refs.nodeLayer, 'focusin', showTip);
  on(refs.nodeLayer, 'mouseout', hideTip); on(refs.nodeLayer, 'focusout', hideTip);
  on(refs.wrap, 'keydown', function (e) {
    /* fix (Claude): ignore modified keys (shell uses Ctrl+1..5) and missing e.key */
    if (!st || !st.data || typeof e.key !== 'string' || e.ctrlKey || e.metaKey || e.altKey ||
        /^(INPUT|TEXTAREA|SELECT)$/i.test(e.target.tagName)) return;
    var key = e.key.toLowerCase(), v = inputs(st.data);
    if (key === 'w') { st.mode = st.mode === 'weight' ? 'signal' : 'weight'; renderNetwork(st); renderReadout(st); }
    else if (key === 'a') setInputs(v[0] ? 0 : 1, v[1]);
    else if (key === 'b') setInputs(v[0], v[1] ? 0 : 1);
  });
  function themeChanged() { if (st) { st.theme = readTheme(); renderAll(); } }
  mo = new MutationObserver(themeChanged);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
  if (typeof window.matchMedia === 'function') {
    mq = window.matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) on(mq, 'change', themeChanged);
    else { var media = mq; media.addListener(themeChanged); listeners.push(function () { media.removeListener(themeChanged); }); }
  }
  return window.AxisNeural;
}
function destroy() {
  clearPulse();
  listeners.forEach(function (remove) { remove(); }); listeners = [];
  if (mo) mo.disconnect();
  mo = null; mq = null;
  if (st && st.refs.wrap.parentNode) st.refs.wrap.parentNode.removeChild(st.refs.wrap);
  /* added (Claude): also remove the injected stylesheet */
  if (styleEl && styleEl.parentNode) styleEl.parentNode.removeChild(styleEl);
  styleEl = null;
  st = null;
}
window.AxisNeural = { mount: mount, update: update, destroy: destroy, _math: M };
})();