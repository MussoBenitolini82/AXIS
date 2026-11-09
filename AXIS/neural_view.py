"""Inspectable XOR neural network: real trained weights, activations and per-edge signals.

The network is a 2 -> 8 (tanh) -> 1 (sigmoid) MLP trained on the four XOR rows with
binary cross-entropy and full-batch Adam.

* Default backend is dependency-free pure Python (``backend == 'python'``): fixed seed,
  deterministic, trains in a few tens of milliseconds.
* PyTorch is an optional accelerator, opt-in via ``AXIS_NEURAL_BACKEND=torch`` (or
  ``auto``).  It starts from the *same* seeded initial weights and runs the same
  optimiser; if torch is missing or fails, the pure-Python result is used and the
  response says so in ``backend_note``.
* Whatever backend trained the weights, the response is built by one pure-Python
  forward pass over plain lists, so both backends share one schema and every number
  in the response can be recomputed from the returned weights and biases.
* ``trained`` is never hard-coded: it is True only if all four XOR rows are verified
  to be on the correct side of 0.5 with margin (error <= MAX_ERROR).
"""
import math
import os
import random
import threading
import time

ARCHITECTURE = [2, 8, 1]
SEED = 27
LEARNING_RATE = 0.06
MIN_EPOCHS = 200
MAX_EPOCHS = 5000
TARGET_ERROR = 0.02   # training stops once every row is within this of its target
MAX_ERROR = 0.1       # verification bound: |prediction - expected| must not exceed this
XOR_ROWS = ((0, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 0))
BACKENDS = ('python', 'torch', 'auto')

_LOCK = threading.Lock()
_CACHE = {}


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


def _initial_params(seed=SEED):
    """Seeded uniform init. random.Random is a platform-independent Mersenne Twister."""
    rng = random.Random(seed)
    n_in, n_hidden, _ = ARCHITECTURE
    return {
        'W1': [[rng.uniform(-1.0, 1.0) for _ in range(n_in)] for _ in range(n_hidden)],
        'b1': [rng.uniform(-0.5, 0.5) for _ in range(n_hidden)],
        'W2': [[rng.uniform(-1.0, 1.0) for _ in range(n_hidden)]],
        'b2': [0.0],
    }


def forward(params, inputs):
    """Pure-Python forward pass. Returns pre-activations and activations per layer."""
    x = [float(v) for v in inputs]
    z1 = [sum(w * v for w, v in zip(row, x)) + b for row, b in zip(params['W1'], params['b1'])]
    h = [math.tanh(z) for z in z1]
    z2 = [sum(w * v for w, v in zip(row, h)) + b for row, b in zip(params['W2'], params['b2'])]
    out = [_sigmoid(z) for z in z2]
    return {'pre': [None, z1, z2], 'act': [x, h, out]}


def _predictions(params):
    return [forward(params, (a, b))['act'][2][0] for a, b, _ in XOR_ROWS]


def _max_error(params):
    return max(abs(p - row[2]) for p, row in zip(_predictions(params), XOR_ROWS))


def _loss(params):
    """Mean binary cross-entropy over the four XOR rows."""
    eps = 1e-12
    total = 0.0
    for p, (_, _, y) in zip(_predictions(params), XOR_ROWS):
        p = min(1.0 - eps, max(eps, p))
        total -= y * math.log(p) + (1 - y) * math.log(1.0 - p)
    return total / len(XOR_ROWS)


def _train_python(seed=SEED):
    """Full-batch Adam on BCE with hand-written backprop. No third-party imports."""
    p = _initial_params(seed)
    n_hidden = ARCHITECTURE[1]
    flat = lambda q: [q['W1'][j] for j in range(n_hidden)] + [q['b1'], q['W2'][0], q['b2']]
    vecs = flat(p)
    m = [[0.0] * len(v) for v in vecs]
    s = [[0.0] * len(v) for v in vecs]
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    n = len(XOR_ROWS)
    epochs = 0
    while epochs < MAX_EPOCHS:
        gW1 = [[0.0, 0.0] for _ in range(n_hidden)]
        gb1 = [0.0] * n_hidden
        gW2 = [0.0] * n_hidden
        gb2 = [0.0]
        for a, b, y in XOR_ROWS:
            f = forward(p, (a, b))
            x, h, out = f['act']
            dz2 = (out[0] - y) / n            # d(BCE)/d(z2) for a sigmoid output
            gb2[0] += dz2
            for j in range(n_hidden):
                gW2[j] += dz2 * h[j]
                dz1 = dz2 * p['W2'][0][j] * (1.0 - h[j] * h[j])
                gb1[j] += dz1
                gW1[j][0] += dz1 * x[0]
                gW1[j][1] += dz1 * x[1]
        epochs += 1
        grads = gW1 + [gb1, gW2, gb2]
        c1 = 1.0 - beta1 ** epochs
        c2 = 1.0 - beta2 ** epochs
        for vec, g, mv, sv in zip(vecs, grads, m, s):
            for i in range(len(vec)):
                mv[i] = beta1 * mv[i] + (1.0 - beta1) * g[i]
                sv[i] = beta2 * sv[i] + (1.0 - beta2) * g[i] * g[i]
                vec[i] -= LEARNING_RATE * (mv[i] / c1) / (math.sqrt(sv[i] / c2) + eps)
        if epochs >= MIN_EPOCHS and _max_error(p) <= TARGET_ERROR:
            break
    return p, epochs


def _train_torch(seed=SEED):
    """Optional accelerator: same init, same optimiser, float64. Touches no global torch state."""
    import torch
    init = _initial_params(seed)
    t = {k: torch.tensor(v, dtype=torch.float64, requires_grad=True) for k, v in init.items()}
    x = torch.tensor([[r[0], r[1]] for r in XOR_ROWS], dtype=torch.float64)
    y = torch.tensor([[r[2]] for r in XOR_ROWS], dtype=torch.float64)
    opt = torch.optim.Adam(list(t.values()), lr=LEARNING_RATE)
    epochs = 0
    while epochs < MAX_EPOCHS:
        opt.zero_grad()
        hidden = torch.tanh(x @ t['W1'].T + t['b1'])
        logits = hidden @ t['W2'].T + t['b2']
        loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, y)
        loss.backward()
        opt.step()
        epochs += 1
        if epochs >= MIN_EPOCHS:
            with torch.no_grad():
                pred = torch.sigmoid(torch.tanh(x @ t['W1'].T + t['b1']) @ t['W2'].T + t['b2'])
                if float((pred - y).abs().max()) <= TARGET_ERROR:
                    break
    return {k: v.detach().tolist() for k, v in t.items()}, epochs


def _requested_backend(backend=None):
    value = (backend if backend is not None else os.getenv('AXIS_NEURAL_BACKEND', 'python'))
    value = str(value).strip().lower() or 'python'
    if value not in BACKENDS:
        raise ValueError(f"Bilinmeyen sinir ağı arka ucu: {value!r} (python, torch veya auto olmalı)")
    return value


def _build(requested):
    note = None
    result = None
    started = time.perf_counter()
    if requested in ('torch', 'auto'):
        try:
            params, epochs = _train_torch()
            if _max_error(params) <= MAX_ERROR and all(math.isfinite(v) for v in _flat(params)):
                import torch
                result = (params, epochs, 'torch', f'PyTorch {torch.__version__}')
            else:
                note = 'PyTorch eğitimi XOR doğrulamasını geçemedi; saf Python ağı kullanıldı.'
        except ImportError:
            if requested == 'torch':
                note = 'PyTorch kurulu değil; saf Python ağı kullanıldı.'
        except Exception as exc:  # torch is optional: never let it break the view
            note = f'PyTorch kullanılamadı ({type(exc).__name__}); saf Python ağı kullanıldı.'
    if result is None:
        started = time.perf_counter()
        params, epochs = _train_python()
        result = (params, epochs, 'python', 'pure-python')
    params, epochs, backend, framework = result
    max_error = _max_error(params)
    return {
        'params': params, 'epochs': epochs, 'backend': backend, 'framework': framework,
        'backend_note': note, 'loss': _loss(params), 'max_error': max_error,
        'converged': max_error <= MAX_ERROR,
        'training_ms': round((time.perf_counter() - started) * 1000.0, 3),
    }


def _flat(params):
    return [v for row in params['W1'] for v in row] + params['b1'] + params['W2'][0] + params['b2']


def _trained(backend=None):
    """Train once per backend. The lock makes the first concurrent calls train only once."""
    requested = _requested_backend(backend)
    with _LOCK:
        if requested not in _CACHE:
            _CACHE[requested] = _build(requested)
        return _CACHE[requested]


def reset_cache():
    """Forget trained weights (used by tests to prove retraining is deterministic)."""
    with _LOCK:
        _CACHE.clear()


def validate_inputs(inputs):
    """Return [a, b] as floats, each exactly 0.0 or 1.0; raise ValueError otherwise."""
    message = 'XOR girdileri yalnızca 0 veya 1 olabilir'
    if inputs is None:
        return [1.0, 0.0]
    if isinstance(inputs, (str, bytes)) or not isinstance(inputs, (list, tuple)) or len(inputs) != 2:
        raise ValueError(message + ' (tam olarak iki değer gerekir)')
    values = []
    for v in inputs:
        if isinstance(v, (str, bytes)) or not isinstance(v, (int, float)):
            raise ValueError(message)
        v = float(v)
        if not math.isfinite(v) or v not in (0.0, 1.0):
            raise ValueError(message)
        values.append(v)
    return values


def parse_query(query):
    """Turn a urllib.parse.parse_qs dict into validated inputs. Raises ValueError on bad input."""
    values = []
    for name, default in (('a', '1'), ('b', '0')):
        raw = (query.get(name) or [default])[0]
        raw = str(raw).strip()
        if raw not in ('0', '1'):
            raise ValueError(f"XOR girdisi '{name}' yalnızca 0 veya 1 olabilir")
        values.append(float(raw))
    return values


def http_response(query):
    """(status, payload) for GET /api/neural; never raises on bad user input."""
    try:
        return 200, model_graph(parse_query(query))
    except ValueError as exc:
        return 400, {'available': False, 'error': str(exc), 'reason': str(exc), 'nodes': [], 'edges': []}


def model_graph(inputs=None, backend=None):
    values = validate_inputs(inputs)   # validate first, independent of backend
    net = _trained(backend)
    params = net['params']
    f = forward(params, values)
    activations, pre = f['act'], f['pre']
    biases = [None, params['b1'], params['b2']]
    nodes = []
    edges = []
    for layer, vals in enumerate(activations):
        for j, value in enumerate(vals):
            node = {'id': f'neuron:{layer}:{j}', 'label': f'L{layer} N{j}', 'kind': 'neuron',
                    'description': f'Katman {layer}, nöron {j}; aktivasyon {value:.5f}',
                    'layer': layer, 'index': j, 'activation': round(value, 6)}
            if layer:
                node['bias'] = round(biases[layer][j], 6)
                node['pre_activation'] = round(pre[layer][j], 6)
                node['activation_fn'] = 'tanh' if layer == 1 else 'sigmoid'
            nodes.append(node)
    for layer, weights in enumerate((params['W1'], params['W2'])):
        for j, row in enumerate(weights):
            for i, w in enumerate(row):
                edges.append({'source': f'neuron:{layer}:{i}', 'target': f'neuron:{layer + 1}:{j}',
                              'relation': 'weight', 'weight': round(w, 6),
                              'signal': round(w * activations[layer][i], 6)})
    examples = [{'input': [a, b], 'prediction': round(p, 5), 'expected': y}
                for (a, b, y), p in zip(XOR_ROWS, _predictions(params))]
    trained = bool(net['converged'])
    engine = 'PyTorch' if net['backend'] == 'torch' else 'bağımlılıksız saf Python'
    if trained:
        description = (f'XOR üzerinde {engine} ile gerçekten eğitilmiş küçük ağ '
                       f'({net["epochs"]} adım, kayıp {net["loss"]:.4f}). Nöron aktivasyonları seçilen '
                       'girişe göre değişir; VECTOR LLM modeli değildir.')
    else:
        description = ('UYARI: ağ XOR doğrulamasını geçemedi; gösterilen ağırlıklar eğitilmiş sayılmaz '
                       f'(en büyük hata {net["max_error"]:.3f}).')
    return {
        'available': True, 'trained': trained, 'architecture': list(ARCHITECTURE),
        'description': description, 'nodes': nodes, 'edges': edges,
        'parameter_count': len(_flat(params)), 'inputs': values,
        'prediction': round(activations[2][0], 6), 'examples': examples,
        # additive, honest-labelling fields
        'backend': net['backend'], 'framework': net['framework'], 'backend_note': net['backend_note'],
        'converged': trained, 'loss': round(net['loss'], 8), 'max_error': round(net['max_error'], 6),
        'epochs': net['epochs'], 'seed': SEED, 'learning_rate': LEARNING_RATE, 'optimizer': 'adam',
        'loss_fn': 'binary_cross_entropy', 'activation_fns': ['tanh', 'sigmoid'],
        'training_ms': net['training_ms'],
        'predicted_class': int(activations[2][0] >= 0.5), 'expected': int(values[0]) ^ int(values[1]),
        'weights': {k: [list(r) for r in v] if k.startswith('W') else list(v) for k, v in params.items()},
    }
