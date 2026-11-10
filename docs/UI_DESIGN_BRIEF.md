# AXIS UI Design Brief (modernisation)

Scope: `AXIS/index.html` (shell) + `AXIS/static/app.css`, `AXIS/static/graph.js` (unified "AXIS ağı" view), `AXIS/static/neural.js` (XOR inspector).
Constraints: vanilla JS, no libraries, no external resources (system fonts only), Canvas 2D / SVG, Turkish UI strings, Windows 11 feel (Mica-like depth, Segoe UI Variable).
Three workstreams can run in parallel: (A) shell + CSS, (B) neural.js, (C) graph.js. Only the contracts below couple them.

## 1. Design tokens (`:root` = dark, `[data-theme="light"]` overrides; follow `prefers-color-scheme` until the user chooses)

```css
:root{
  --bg:#090B10; --surface:#11151F; --elevated:#181E2C; --border:#252D3F;
  --text:#EDF1F7; --muted:#8A96AD;
  --accent:#6366F1; --accent-2:#22D3EE; --accent-fg:#fff;
  --success:#10B981; --warn:#F59E0B; --danger:#F43F5E;
  --sig-pos:#38BDF8; --sig-neg:#FB923C; --sig-zero:#334155;   /* colour-blind-safe blue/orange */
  /* unified network layers (colour + shape, see section 4) */
  --layer-neural:#22D3EE; --layer-knowledge:#6366F1; --layer-skills:#F59E0B; --layer-learning:#10B981;
  --glass:rgba(17,21,31,.78); --edge-hi:rgba(255,255,255,.07); --focus:#22D3EE;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --s7:48px;
  --r-sm:6px; --r-md:10px; --r-lg:14px; --r-pill:999px;
  --sh-1:0 1px 0 var(--edge-hi) inset,0 1px 2px rgba(0,0,0,.35);
  --sh-2:0 1px 0 var(--edge-hi) inset,0 8px 24px rgba(0,0,0,.45);
  --sh-3:0 16px 48px rgba(0,0,0,.55);
  --t-fast:120ms; --t-base:220ms; --t-slow:320ms;
  --ease-out:cubic-bezier(.22,1,.36,1); --ease-cam:cubic-bezier(.16,1,.3,1); --ease-spring:cubic-bezier(.34,1.56,.64,1);
  --font-ui:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  --font-display:"Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;
  --font-mono:"Cascadia Mono",Consolas,ui-monospace,monospace;
  --fs-xs:11px; --fs-sm:12.5px; --fs-base:14px; --fs-md:16px; --fs-lg:20px; --fs-xl:26px;
  --rail-w:56px; --rail-w-open:200px;
}
[data-theme="light"]{
  --bg:#F4F6FA; --surface:#FFFFFF; --elevated:#EEF2F8; --border:#D8E0ED;
  --text:#0F172A; --muted:#5B6880; --accent:#4F46E5; --accent-2:#0891B2;
  --success:#059669; --warn:#B45309; --danger:#E11D48;
  --sig-pos:#0284C7; --sig-neg:#EA580C; --sig-zero:#CBD5E1;
  --layer-neural:#0891B2; --layer-knowledge:#4F46E5; --layer-skills:#B45309; --layer-learning:#059669;
  --glass:rgba(255,255,255,.78); --edge-hi:rgba(255,255,255,.9); --focus:#0E7490;
  --sh-1:0 1px 2px rgba(15,23,42,.08); --sh-2:0 8px 24px rgba(15,23,42,.10); --sh-3:0 16px 48px rgba(15,23,42,.16);
}
@media (prefers-reduced-motion:reduce){:root{--t-fast:0ms;--t-base:0ms;--t-slow:0ms}}
```
Type scale (size/line-height/weight/tracking): xs 11/1.3/500/+.02em (badges, axes) - sm 12.5/1.4/400 (controls, tables) - base 14/1.55/400 (chat) - md 16/1.35/600/-.01em - lg 20/1.25/600/-.015em - xl 26/1.15/700/-.02em (KPIs). Metrics use `--font-mono` + `font-variant-numeric:tabular-nums`. Turkish diacritics (ğ ü ş ı İ ö ç) must render in every stack; case-insensitive matching uses `toLocaleLowerCase('tr-TR')`.
Glass only on floating HUDs over canvases: `background:var(--glass); backdrop-filter:blur(12px) saturate(140%); border:1px solid var(--border)`. Never stack glass on glass.

## 2. Layout and components

**Decision: left collapsible icon rail** (56 px collapsed / 200 px expanded), not top tabs: canvases need vertical space, Turkish labels vary in width, rail supports `Ctrl+1..5`. Items: **Sohbet, Ağ, Güncellemeler, Sistem, Araçlar** (the former Sinir ağı and Bellek tabs are merged into "Ağ"). Theme toggle + collapse at the bottom. Active item: 3 px accent bar that slides vertically (transform, `--t-base`) + tinted bg.

Shell: grid `rail | main`; main = `header(48px: title, backend/model status chip, theme toggle) / view`. The Ağ view = `canvas | inspector panel (340px)`.
Responsive:
- >=1280: rail expanded, inspector docked right.
- 768-1279: rail collapsed (icons + tooltips), inspector docked 300 px, overlays canvas if narrower.
- 380-767: rail becomes a bottom bar (5 icons, 56 px, safe-area padding); inspector is a bottom sheet (drag handle, 60% height); compact header; chat composer sticks above the bar. No horizontal page scroll at 380 px; touch targets >= 44 px.
- >=1920: chat column capped at 860 px; canvas fills.

Components (tokens only; states default/hover/active/focus-visible/disabled):
- **Button**: primary (accent fill), secondary (surface+border), ghost, icon-only (36x36, `aria-label` required). Height 36, `--r-md`, press `scale(.97)` with `--ease-spring`.
- **Input/textarea**: surface bg, 1px border, focus = 2 px `--focus` ring; composer autogrows to 6 lines, Enter sends, Shift+Enter newline, send icon button inside.
- **Card**: surface, `--r-lg`, `--sh-1`; clickable cards lift 1 px with `--sh-2`.
- **Chip**: pill, 28 px, toggle via `aria-pressed`; selected = tinted bg + accent text. Layer/kind filters use chips with a colour dot + shape glyph.
- **Badge**: 11 px pill, semantic tints, dot variant for status.
- **Tooltip**: elevated + border, 12.5 px, 120 ms fade, on hover and keyboard focus, max 260 px, non-interactive.
- **Toast**: bottom-right (top on mobile), `role="status"`, 4 s (errors 8 s), slide+fade 220 ms.
- **Empty**: centred 48 px muted icon, one-line title, hint, one CTA, e.g. "Henüz ağ verisi yok" / "Sohbet ettikçe ve öğrendikçe katmanlar burada belirir."
- **Loading**: skeleton shimmer (1.4 s sweep; static under reduced motion); canvas shows "Yükleniyor…" overlay.
- **Error**: inline card, danger left border, message + "Yeniden dene"; no raw stack traces; `role="alert"`. A failing layer shows a per-layer error chip, the other layers still render.
Micro-interactions: tab cross-fade 160 ms; message bubbles rise 8 px on enter; streaming caret; numeric readouts tween 200 ms; copy button on code "Kopyalandı" toast.

## 3. Unified network view (`AXIS/static/graph.js`, "AXIS ağı")

Canvas 2D, force-directed, no libraries. One canvas shows every network AXIS has, layered together.

### Contract
```js
window.AxisGraph = {
  mount(el, {onNodeSelect, onLayerFocus}),            // builds canvas + HUD (search, layer chips/legend, zoom, minimap)
  setLayers({neural, knowledge, skills, learning}),   // each {nodes, edges} in the source's own shape; may be called repeatedly; any key may be missing/null
  toggleLayer(name, on),                               // show/hide a layer (animated 200 ms fade, physics keeps positions)
  focus(idOrLayer),                                    // node id (namespaced or raw) or layer name; camera transition 320 ms --ease-cam
  destroy()
};
```
`onNodeSelect(info|null)`: `{id, layer, label, kind, description, neighbors:[{id,label,layer,relation}], raw}`. `onLayerFocus(name|null)`: fired when the user focuses a layer (legend click, double-click cluster, `focus('neural')`). The shell reacts to `onLayerFocus('neural')` by opening the XOR inspector (section 4).

### Sources and normalisation (graph.js owns this; never mutate inputs)
| layer | endpoint | expected shape | normalised kind |
|---|---|---|---|
| neural | `/api/neural` | `nodes[{id,layer,activation,bias,pre_activation,activation_fn}]`, `edges[{source,target,weight,signal}]` + `weights`, `inputs`, `prediction`, `trained`... | `input` / `hidden` / `output` |
| knowledge | `/api/graph` | nodes topic/paper/concept, edges with relation | topic / paper / concept |
| skills | `/api/brain-graph` | skill/brain nodes + edges | skill (or its own kind field) |
| learning | V13 learning dashboard | learning events / goals / progress items | event / goal / ... |
Internal node id = `layer + ':' + rawId` (avoids collisions). Normaliser is defensive: accepts `id|name|key` for id, `label|title|name` for label, `source|from` / `target|to` for edges, `relation|type|label` for relations; unknown fields kept in `raw`. Drop edges with unknown endpoints and dedupe. Shell-side adapters are NOT needed, but the shell must pass the raw API payloads unchanged.

### Cross-layer links (real data only)
Create a cross-layer edge ONLY when the data states it: (1) an edge in a layer whose endpoint id resolves to a node in another layer (resolve raw id against all layers, exact match, unambiguous only), or (2) an explicit reference field on a node (`concepts`, `topics`, `skills`, `skill_ids`, `concept_ids`, `refs`, `used_skills`) whose values are existing node ids/labels (exact id, or exact case-insensitive label match). Never link by guessing, fuzzy matching or proximity. Typical results: skill -> concept/topic it uses, learning event -> skill. Cross-layer edges are drawn dashed, in a neutral `--muted`, relation label "kullanır" only when the source data has no relation text. A debug counter in the HUD ("12 katmanlar arası bağ") lets us verify nothing is invented.

### Layers: colour, shape, legend
| layer | name (TR) | colour | node shape |
|---|---|---|---|
| neural | Sinir ağı | `--layer-neural` | circle with ring (input/hidden/output) |
| knowledge | Bilgi | `--layer-knowledge` | circle (kind sub-tint via lightness) |
| skills | Beceriler | `--layer-skills` | diamond |
| learning | Öğrenme | `--layer-learning` | rounded square |
Legend/HUD (top-left, glass): 4 layer chips (colour dot + shape glyph + count, `aria-pressed`), toggles call `toggleLayer`. Click chip = toggle; double-click or the small "odaklan" button = `focus(layer)` (camera fits the layer, other layers dim to 15%, `onLayerFocus(name)`; click again or Esc restores). Kind sub-filter popover per layer (e.g. topic/paper/concept).

### XOR cluster
The 2->8->1 net is a compact recognisable sub-graph: 3 columns (a,b | h1..h8 | y) kept in fixed relative layout by internal constraints (pinned to a local frame, whole cluster draggable as a unit); nodes are the neurons, edges are weights (width ~ |w|, `--sig-pos` positive, `--sig-neg` negative). Collapsed: small cluster with a label chip "XOR ağı · kayıp 0.002"; neuron nodes radius 3-5, edges thin. Focused (`focus('neural')`, or zoom > 1.5 over the cluster): expands smoothly (320 ms) to full size, shows node fills by `activation`, edges by `signal`, and the shell opens the neural.js inspector. Cluster is attached to the rest of the graph only through real cross-layer links (usually none; it floats near the centre).

### Interaction and performance
- Camera: wheel zoom about cursor (0.1-6x), background drag pans, pinch on touch, double-click empty = fit all, buttons +, -, "Sığdır"; minimap 140x100 (idle redraw, draggable viewport; hidden < 768 px).
- Node drag pins while held; double-click a node toggles pin. Hover: highlight node + 1-hop neighbours (including cross-layer), dim rest to 20%; tooltip: label, layer + kind badge, degree, 120 chars of description. Click: select ring, `onNodeSelect`, inspector fills; Esc/background click clears. Cursor `pointer` on hover.
- Search (`/` focuses): input "Düğüm ara…", `tr-TR` normalised substring, dropdown <= 8 results with layer glyph, arrows + Enter = `focus(id)`; matches glow, others dim.
- Physics: flat `Float32Array`s, Barnes-Hut (theta 0.8), spring on edges (rest ~60 px, k 0.04; cross-layer rest ~120 px, weaker), gravity to per-layer centroids (soft, keeps layers loosely grouped but overlapping, so the view reads as ONE layered network), velocity decay 0.85, alpha cooling 0.99, loop sleeps < 0.001, wakes on drag/filter/data. Pre-tick 80 iterations for > 500 nodes. `setLayers` merges positions by internal id so refreshes do not jump.
- LOD: zoom < 0.4: 2 px marks, edges only between hubs (top 15% degree) and cross-layer edges, <= 10 hub labels, layer halo labels ("Bilgi", "Beceriler"...); 0.4-1.2: shapes, edges alpha .18, labels by screen-space occupancy grid (cell 80x24, higher degree claims first, <= 120 labels); > 1.2: badges, relation labels on the selected node's edges, pill-backed labels. Frustum-cull; batch draws per colour/alpha; spatial-hash hit-test (cell 48 world px, 3x3 lookup); offscreen cache of the settled base layer while highlighting; HiDPI with DPR capped at 2. Target 60 fps with 2000+ nodes / 4000+ edges.
- "Focus on layer" transition: camera tween + non-focused layers fade to 15% over 320 ms (`--ease-cam`).
- Reduced motion: no camera tweens or fades (instant), no pulsing; physics pre-solved and frozen (drag still moves nodes).
- Empty: "Ağ boş. Sohbet ederek veya kaynak ekleyerek başlayın." Missing layers appear greyed in the legend with a "yok" tooltip.

## 4. XOR inspector (`AXIS/static/neural.js`)

Standalone detailed inspector for the XOR net, Canvas 2D (SVG/HTML overlay for text). Opens in the inspector panel (or full overlay on mobile) when the user focuses the neural cluster.
```js
window.AxisNeural = {
  mount(el, {onNodeSelect}),   // build DOM in el; RAF only while animating
  update(data),                // /api/neural JSON; idempotent; keeps UI state (inputs, mode, selection)
  destroy()                    // cancel RAF, remove listeners/observers/DOM
};
```
`data`: `nodes[{id,layer,activation,bias,pre_activation,activation_fn}]`, `edges[{source,target,weight,signal}]`, `inputs`, `prediction`, `predicted_class`, `expected`, `trained`, `backend`, `epochs`, `loss`, `max_error`, `weights{W1(8x2),b1(8),W2(8x1 or 1x8: accept both),b2}`. `onNodeSelect(node|null)`. Re-reads tokens on theme change (MutationObserver on `data-theme`); HiDPI + ResizeObserver.

**Forward pass (JS must match backend):** `z1_k=W1[k][0]*a+W1[k][1]*b+b1[k]; h_k=act(z1_k); z2=sum_k W2[k]*h_k+b2; y=act_out(z2)`; `act` from `nodes[].activation_fn` (tanh/sigmoid/relu; output node separately). On `update()` check the 4 truth-table rows and the current `inputs` against `prediction` (tolerance 1e-4); on mismatch show warn badge "Ön hesap uyuşmuyor" and `console.warn`.

**Network drawing:** 3 columns (a,b | h1..h8 | y). Edge width `1+5*|v|/max|v|`, colour `--sig-pos` (v>0) / `--sig-neg` (v<0), alpha .25+.6*|v|/max, negative edges also dashed in the "Renk körü" mode. v = weight in **Ağırlık** mode, signal (weight*source activation) in **Sinyal** mode; segmented toggle "Ağırlık | Sinyal" (key `W`). Node fill by activation (tanh: diverging blue/orange), thin inner bar bias vs pre-activation, output node ring gauge with `predicted_class`. Hidden units with |activation| < 0.02 drawn dim ("sönük").

**Inputs and animation:** pill switches a / b (0/1; keys `A`, `B`); clicking a truth-table row sets both. Change triggers signal propagation: particles along bezier edges input->hidden (0-450 ms) then hidden->output (450-900 ms), staggered, count/size ~ |signal|, nodes light up on arrival (200 ms ease); final state persists.

**Interactions:** hover node = tooltip (id, layer, activation_fn, bias, pre-activation, activation, math line `z = w1·a + w2·b + b = …`) and fan-in/fan-out highlight, rest 25%; hover edge = weight, signal, source -> target. Click node = select + inspector card (incoming weight table, activation across the 4 inputs); Esc deselects. Arrow keys move selection between nodes, Enter selects, `aria-live="polite"` announces prediction changes. Hit-test: node distance, edge point-to-segment < 6 px.

**Decision-boundary heatmap (240x240):** computed in JS from `weights`: 48x48 grid over (a,b) in [-0.2,1.2]^2 via `forward`, `ImageData`, smoothed scale-up; palette `--sig-neg` (0) -> `--bg` (.5) -> `--sig-pos` (1). Overlay the 4 XOR points (hollow 0 / filled 1, ring colour = correct/incorrect), draggable crosshair setting real-valued inputs (toggles show "~"), 8 faint dashed hidden zero-lines `w1·a+w2·b+b=0` (selected one bright). Recomputed only on weight/theme/size change.

**Truth-table panel:** `a b | beklenen | tahmin | doğru?` (3 decimals, tick/cross glyph + success/danger badge), row highlight for current inputs, footer KPI chips `trained`, `backend`, `epochs`, `loss`, `max_error` (mono). Untrained: banner "Ağ henüz eğitilmedi".
**Reduced motion:** no particles/easing, state jumps instantly; no autoplay.

## 5. Shell responsibilities (`index.html` + `AXIS/static/app.css`)
- `app.css`: all tokens, shell and components of section 2. `<head>` bootstraps the theme from `localStorage.theme` in try/catch to avoid flash. Add `<link rel="stylesheet" href="/static/app.css">`, `<script src="/static/graph.js" defer></script>`, `<script src="/static/neural.js" defer></script>`; backend must serve `/static`.
- Tabs: Sohbet, **Ağ** (merged Sinir ağı + Bellek), Güncellemeler, Sistem, Araçlar; hash routing `#sohbet #ag #guncellemeler #sistem #araclar`; `Ctrl+1..5`.
- Ağ tab: on first open `AxisGraph.mount(canvasEl,{onNodeSelect,onLayerFocus})`, then fetch `/api/neural`, `/api/graph`, `/api/brain-graph`, V13 learning dashboard endpoint (existing) with `Promise.allSettled`; pass whatever succeeded as `setLayers({neural,knowledge,skills,learning})`, failed layers become per-layer error chips + toast. Refetch on tab focus and after train/reset/learning actions.
- `onLayerFocus('neural')`: mount `AxisNeural` in the inspector (once), call `update(neuralData)`, open panel (sheet on mobile). `onLayerFocus(null)` closes it. `onNodeSelect(info)` for other layers fills a generic inspector card (label, layer badge, kind, description, neighbours as clickable list -> `AxisGraph.focus(id)`). Memory list/search UI elsewhere calls `AxisGraph.focus(id)`.
- Guard `if(!window.AxisGraph)` with the Error component. Keep modules alive across tab switches; pause RAF when hidden (`visibilitychange` + tab hidden); `destroy()` on `beforeunload`.
- Remove the old pseudo-3D canvas code once graph.js works; keep chat streaming and existing API calls unchanged.

## 6. Icons (24x24; `fill:none; stroke:currentColor; stroke-width:1.75; stroke-linecap:round; stroke-linejoin:round`)
Authored by the synthesiser (the GPT Astra call timed out); Lucide-style conventions, safe area 2..22. "neural" doubles as the "Ağ" tab icon; "memory" stays for the knowledge layer chip.
```
chat     <path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4A8 8 0 1 1 20 12z"/><path d="M9 11h6M9 14h3.5"/>
neural   <circle cx="5" cy="7" r="2"/><circle cx="5" cy="17" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="12" r="2"/><path d="M7 7l3.2-1.6M7 7l3 4M7 17l3-4M7 17l3.2 1.6M14 5.6l3.2 5M14 12h3M14 18.4l3.2-5"/>
memory   <ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>
updates  <path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 20v-4h-4"/>
system   <rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="M7 12l2.5-3 2.5 2 3-4"/>
tools    <path d="M14.5 6.5a4 4 0 0 0 4.9 4.9L20 12l-8 8a2.1 2.1 0 0 1-3-3l8-8z"/><path d="M14.5 6.5l1.8-1.8a4 4 0 0 1 3 3L17.5 9.5"/>
send     <path d="M21 3L10.5 13.5"/><path d="M21 3l-6.5 18-4-7.5L3 9.5z"/>
settings <circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1"/>
```
Ship as an inline `<svg><symbol id="i-chat">…</symbol></svg>` sprite in index.html, used via `<svg class="ic"><use href="#i-chat"/></svg>`; `.ic{width:20px;height:20px}` (24 px in the mobile bar). Engineers must eyeball each at 20 px in both themes and adjust paths that render unevenly.

## 7. Accessibility
- WCAG AA: text >= 4.5:1, UI/graphic parts >= 3:1 in both themes (check `--muted` on `--surface`, layer colours and `--sig-*` against canvas bg).
- Never colour alone: layers differ by shape (circle/diamond/square) and legend glyph; edge sign by dash in "Renk körü" mode; truth-table uses tick/cross glyphs.
- Focus: visible 2 px `--focus` ring (offset 2 px) on all interactive elements; no trapping; sheets/overlays restore focus on close.
- Keyboard: rail uses roving tabindex + arrows, `Ctrl+1..5`; graph: `/` search, `+`/`-` zoom, arrows pan, Tab cycles legend chips, Enter selects, Esc clears/unfocuses layer; neural: `A`, `B`, `W`, arrows, Enter, Esc. A "?" popover documents shortcuts.
- Screen readers: landmarks (`nav`, `main`), `aria-current="page"` on the active tab, canvases `role="img"` with text summary (counts per layer, selection) and `aria-live` updates; tables are real `<table>`; a visually hidden "Düğüm listesi" (top 50 by degree) gives a non-canvas way to select nodes.
- Reduced motion: honour `prefers-reduced-motion` in CSS (durations 0) and JS (`matchMedia` + live listener) as specified per module. Touch targets >= 44 px; zoom/pan have button alternatives.

## 8. Attribution
Gemini (`gemini-4-argon-medium`, responded) supplied the left-rail decision, colour/type/motion tokens, the colour-blind-safe blue/orange signal palette, the MLP ideas (signal-flow circuit, heatmap with hidden-neuron half-plane lines) and the Barnes-Hut/LOD/occupancy-grid/spatial-hash graph techniques. GPT Astra (`gpt-6-astra`, as recorded in the newest Codex rollout `2026/11/10/rollout-2026-11-10T15-13-25-...jsonl`) timed out without an answer, so the icon set and all decisions are the synthesiser's (Claude). The unified-network concept came from the user via the coordinator.
