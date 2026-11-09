"""Tests for neural_view that run WITHOUT torch or numpy (pure-Python backend)."""
import json
import math
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import neural_view as nv

ROWS = [((0, 0), 0), ((0, 1), 1), ((1, 0), 1), ((1, 1), 0)]
LEGACY_KEYS = {'available', 'trained', 'architecture', 'description', 'nodes', 'edges',
               'parameter_count', 'inputs', 'prediction', 'examples'}
NEW_KEYS = {'backend', 'framework', 'backend_note', 'converged', 'loss', 'max_error', 'epochs',
            'seed', 'weights', 'training_ms', 'predicted_class', 'expected'}


def recompute(d):
    """Independent forward pass using only numbers found in the API response."""
    w = d['weights']
    x = [float(v) for v in d['inputs']]
    z1 = [sum(wi * xi for wi, xi in zip(row, x)) + b for row, b in zip(w['W1'], w['b1'])]
    h = [math.tanh(z) for z in z1]
    z2 = sum(wi * hi for wi, hi in zip(w['W2'][0], h)) + w['b2'][0]
    return x, z1, h, z2, 1.0 / (1.0 + math.exp(-z2))


class ConvergenceTests(unittest.TestCase):
    def test_all_four_rows_on_correct_side_with_margin(self):
        for (a, b), expected in ROWS:
            d = nv.model_graph([a, b], backend='python')
            self.assertEqual(d['expected'], expected)
            self.assertEqual(d['predicted_class'], expected)
            self.assertLess(abs(d['prediction'] - expected), 0.1)
        d = nv.model_graph([1, 0], backend='python')
        self.assertIs(d['trained'], True)
        self.assertIs(d['converged'], True)
        self.assertLessEqual(d['max_error'], nv.MAX_ERROR)
        self.assertEqual([e['expected'] for e in d['examples']], [0, 1, 1, 0])
        for e in d['examples']:
            self.assertLess(abs(e['prediction'] - e['expected']), 0.1)

    def test_training_really_changes_the_weights_and_lowers_loss(self):
        init = nv._initial_params()
        trained = nv._trained('python')['params']
        self.assertNotEqual(init['W1'], trained['W1'])
        self.assertGreater(nv._max_error(init), 0.3)      # untrained net does not solve XOR
        self.assertGreater(nv._loss(init), 0.5)
        self.assertLess(nv._loss(trained), 0.05)
        d = nv.model_graph(backend='python')
        self.assertAlmostEqual(d['loss'], nv._loss(trained), places=7)
        self.assertTrue(nv.MIN_EPOCHS <= d['epochs'] <= nv.MAX_EPOCHS)

    def test_trained_flag_is_not_hardcoded(self):
        """An unconverged network must be labelled as not trained."""
        original = nv.MAX_EPOCHS, nv.MIN_EPOCHS
        nv.reset_cache()
        try:
            nv.MAX_EPOCHS, nv.MIN_EPOCHS = 1, 1
            d = nv.model_graph([1, 0], backend='python')
            self.assertIs(d['trained'], False)
            self.assertIs(d['converged'], False)
            self.assertEqual(d['epochs'], 1)
            self.assertIn('UYARI', d['description'])
        finally:
            nv.MAX_EPOCHS, nv.MIN_EPOCHS = original
            nv.reset_cache()
        self.assertIs(nv.model_graph([1, 0], backend='python')['trained'], True)

    def test_other_seeds_also_converge(self):
        for seed in range(12):
            params, epochs = nv._train_python(seed)
            self.assertLessEqual(nv._max_error(params), nv.MAX_ERROR, seed)
            self.assertLessEqual(epochs, nv.MAX_EPOCHS)


class ForwardConsistencyTests(unittest.TestCase):
    def test_activations_recomputed_from_returned_weights(self):
        for (a, b), _ in ROWS:
            d = nv.model_graph([a, b], backend='python')
            x, z1, h, z2, out = recompute(d)
            node = {(n['layer'], n['index']): n for n in d['nodes']}
            self.assertEqual(len(node), 2 + 8 + 1)
            for i in range(2):
                self.assertEqual(node[0, i]['activation'], x[i])
                self.assertNotIn('bias', node[0, i])
            for j in range(8):
                self.assertAlmostEqual(node[1, j]['activation'], h[j], places=5)
                self.assertAlmostEqual(node[1, j]['pre_activation'], z1[j], places=5)
                self.assertAlmostEqual(node[1, j]['bias'], d['weights']['b1'][j], places=5)
            self.assertAlmostEqual(node[2, 0]['activation'], out, places=5)
            self.assertAlmostEqual(node[2, 0]['pre_activation'], z2, places=5)
            self.assertAlmostEqual(d['prediction'], out, places=5)
            self.assertEqual(d['prediction'], node[2, 0]['activation'])

    def test_edges_match_weights_and_signals_sum_to_pre_activation(self):
        for (a, b), _ in ROWS:
            d = nv.model_graph([a, b], backend='python')
            node = {n['id']: n for n in d['nodes']}
            incoming = {}
            for e in d['edges']:
                self.assertEqual(e['relation'], 'weight')
                _, sl, si = e['source'].split(':')
                _, tl, ti = e['target'].split(':')
                self.assertEqual(int(tl), int(sl) + 1)
                matrix = d['weights']['W1' if sl == '0' else 'W2']
                self.assertAlmostEqual(e['weight'], matrix[int(ti)][int(si)], places=5)
                self.assertAlmostEqual(e['signal'], e['weight'] * node[e['source']]['activation'], places=4)
                incoming.setdefault(e['target'], []).append(e['signal'])
            self.assertEqual(len(d['edges']), 2 * 8 + 8 * 1)
            self.assertEqual(len({(e['source'], e['target']) for e in d['edges']}), 24)
            for target, signals in incoming.items():
                n = node[target]
                self.assertAlmostEqual(sum(signals) + n['bias'], n['pre_activation'], places=4)
                fn = math.tanh if n['layer'] == 1 else (lambda z: 1 / (1 + math.exp(-z)))
                self.assertAlmostEqual(fn(n['pre_activation']), n['activation'], places=4)

    def test_activations_depend_on_input(self):
        seen = set()
        for (a, b), _ in ROWS:
            d = nv.model_graph([a, b], backend='python')
            seen.add(tuple(n['activation'] for n in d['nodes']))
        self.assertEqual(len(seen), 4)


class DeterminismTests(unittest.TestCase):
    def test_retraining_gives_identical_response(self):
        strip = lambda d: {k: v for k, v in d.items() if k != 'training_ms'}
        first = strip(nv.model_graph([0, 1], backend='python'))
        nv.reset_cache()
        second = strip(nv.model_graph([0, 1], backend='python'))
        self.assertEqual(first, second)
        self.assertEqual(nv._train_python(), nv._train_python())
        self.assertEqual(first['seed'], nv.SEED)

    def test_cached_calls_do_not_retrain_or_mutate(self):
        a = nv.model_graph([1, 1], backend='python')
        a['weights']['W1'][0][0] = 999.0          # caller mutation must not poison the cache
        a['nodes'].clear()
        b = nv.model_graph([1, 1], backend='python')
        self.assertNotEqual(b['weights']['W1'][0][0], 999.0)
        self.assertEqual(len(b['nodes']), 11)
        self.assertIs(nv._trained('python'), nv._trained('python'))

    def test_concurrent_first_calls_train_once(self):
        nv.reset_cache()
        calls = []
        original = nv._train_python

        def counting(*args, **kwargs):
            calls.append(threading.get_ident())
            return original(*args, **kwargs)

        nv._train_python = counting
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(
                    lambda i: nv.model_graph([i % 2, (i // 2) % 2], backend='python'), range(32)))
        finally:
            nv._train_python = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({json.dumps(r['weights']) for r in results}), 1)
        self.assertTrue(all(r['trained'] for r in results))


class InvalidInputTests(unittest.TestCase):
    def test_model_graph_rejects_bad_inputs(self):
        bad = [[2, 0], [0, -1], [0.5, 1], [float('nan'), 0], [0, float('inf')], [float('-inf'), 1],
               ['1', '0'], ['a', 'b'], [None, 1], [1], [1, 0, 1], [], '10', 'ab', 5, {'a': 1}, [[1], 0],
               [1e-9, 0], [1, 1.0000001]]
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    nv.model_graph(value)

    def test_model_graph_accepts_exact_binary_values(self):
        for value in ([1, 0], (0, 1), [1.0, 0.0], [True, False]):
            d = nv.model_graph(value)
            self.assertEqual(d['inputs'], [float(value[0]), float(value[1])])
        self.assertEqual(nv.model_graph()['inputs'], [1.0, 0.0])
        self.assertEqual(nv.model_graph(None)['inputs'], [1.0, 0.0])

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            nv.model_graph([1, 0], backend='tensorflow')

    def test_parse_query(self):
        self.assertEqual(nv.parse_query({}), [1.0, 0.0])
        self.assertEqual(nv.parse_query({'a': ['0'], 'b': ['1']}), [0.0, 1.0])
        for q in ({'a': ['nan']}, {'a': ['inf']}, {'b': ['abc']}, {'a': ['2']}, {'a': ['1.0']},
                  {'a': ['1e0']}, {'b': ['-0']}, {'a': ['']}, {'a': ['0x1']}):
            with self.subTest(q=q):
                with self.assertRaises(ValueError):
                    nv.parse_query(q)

    def test_http_response_never_raises(self):
        status, body = nv.http_response({'a': ['1'], 'b': ['1']})
        self.assertEqual(status, 200)
        self.assertEqual(body['expected'], 0)
        for q in ({'a': ['nan']}, {'a': ['abc']}, {'b': ['7']}):
            status, body = nv.http_response(q)
            self.assertEqual(status, 400)
            self.assertIs(body['available'], False)
            self.assertTrue(body['error'])
            self.assertEqual(body['reason'], body['error'])
            json.dumps(body)


class SchemaTests(unittest.TestCase):
    def test_legacy_and_new_keys(self):
        d = nv.model_graph([1, 0], backend='python')
        self.assertTrue(LEGACY_KEYS <= set(d))
        self.assertTrue(NEW_KEYS <= set(d))
        self.assertIs(d['available'], True)
        self.assertEqual(d['architecture'], [2, 8, 1])
        self.assertEqual(d['parameter_count'], 2 * 8 + 8 + 8 * 1 + 1)
        self.assertEqual(d['backend'], 'python')
        self.assertEqual(d['framework'], 'pure-python')
        self.assertIsNone(d['backend_note'])
        self.assertIsInstance(d['description'], str)
        self.assertNotIn('PyTorch', d['description'])   # must not claim torch when torch was not used
        for n in d['nodes']:
            self.assertTrue({'id', 'label', 'kind', 'description', 'layer', 'index', 'activation'} <= set(n))
            self.assertEqual(n['kind'], 'neuron')
            self.assertEqual(n['id'], f"neuron:{n['layer']}:{n['index']}")
        ids = {n['id'] for n in d['nodes']}
        for e in d['edges']:
            self.assertEqual(set(e), {'source', 'target', 'relation', 'weight', 'signal'})
            self.assertIn(e['source'], ids)
            self.assertIn(e['target'], ids)
        w = d['weights']
        self.assertEqual(
            (len(w['W1']), len(w['W1'][0]), len(w['b1']), len(w['W2']), len(w['W2'][0]), len(w['b2'])),
            (8, 2, 8, 1, 8, 1))

    def test_response_is_strict_json(self):
        d = nv.model_graph([0, 0], backend='python')
        text = json.dumps(d, ensure_ascii=False, allow_nan=False)   # no NaN/Infinity anywhere
        self.assertEqual(json.loads(text)['prediction'], d['prediction'])

    def test_torch_backend_or_honest_fallback(self):
        try:
            import torch  # noqa: F401
            has_torch = True
        except ImportError:
            has_torch = False
        d = nv.model_graph([1, 0], backend='torch')
        ref = nv.model_graph([1, 0], backend='python')
        self.assertEqual(set(d), set(ref))                # same schema on both paths
        self.assertIs(d['trained'], True)
        if has_torch:
            self.assertEqual(d['backend'], 'torch')
            self.assertTrue(d['framework'].startswith('PyTorch'))
            for p, q in zip(nv._flat(d['weights']), nv._flat(ref['weights'])):
                self.assertAlmostEqual(p, q, places=3)    # same init + same optimiser
        else:
            self.assertEqual(d['backend'], 'python')
            self.assertEqual(d['framework'], 'pure-python')
            self.assertIn('PyTorch kurulu değil', d['backend_note'])
            self.assertEqual(d['weights'], ref['weights'])
        auto = nv.model_graph([1, 0], backend='auto')
        self.assertEqual(auto['backend'], 'torch' if has_torch else 'python')
        if not has_torch:
            self.assertIsNone(auto['backend_note'])


if __name__ == '__main__':
    unittest.main()
