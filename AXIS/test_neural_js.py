"""static/neural.js pure math (window.AxisNeural._math) must match neural_view's Python forward pass.

Runs neural.js under Node in a vm sandbox with a minimal fake window (no DOM, no libraries).
Node is required: when it is missing the tests FAIL with a clear message (they never skip).
"""
import json
import os
import shutil
import subprocess
import unittest

import neural_view as nv

HERE = os.path.dirname(os.path.abspath(__file__))
NEURAL_JS = os.path.join(HERE, 'static', 'neural.js')
INPUTS = [(0, 0), (0, 1), (1, 0), (1, 1)]

RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const [file] = process.argv.slice(1);
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const sandbox = { console: console, Math: Math, JSON: JSON, Float32Array: Float32Array };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(file, 'utf8'), sandbox, { filename: 'neural.js' });
const api = sandbox.window.AxisNeural;
const M = api && api._math;
const out = {
  api: api ? Object.keys(api).sort() : null,
  math: M ? Object.keys(M).sort() : null,
  forward: [], selfCheck: [], truth: null, heat: null, badWeights: null, column: null, tamperedOk: null,
};
const w = payload.graphs[0].weights;
for (const g of payload.graphs) {
  const fns = M.fnsFrom(g);
  const f = M.forward(g.weights, g.inputs, fns);
  out.forward.push({ inputs: g.inputs, pre: f.pre, act: f.act });
  out.selfCheck.push(M.selfCheck(g, M.normalizeWeights(g.weights)));
}
out.truth = M.truthRows(w).map(r => ({ a: r.a, b: r.b, expected: r.expected, prediction: r.prediction, ok: r.ok }));
const n = 48, grid = Array.from(M.heatGrid(w, n));
out.heat = { n: n, length: grid.length, corners: [grid[0], grid[n - 1], grid[(n - 1) * n], grid[n * n - 1]] };
out.badWeights = M.normalizeWeights({ W1: [[1, 2]], b1: [0], W2: [[1]], b2: [0] });
const col = { W1: w.W1, b1: w.b1, W2: w.W2[0].map(v => [v]), b2: w.b2 };
out.column = M.forward(col, [1, 0]).act[2][0];
const bad = JSON.parse(JSON.stringify(payload.graphs[0]));
bad.prediction = bad.prediction + 0.01;
out.tamperedOk = M.selfCheck(bad, M.normalizeWeights(bad.weights)).ok;
process.stdout.write(JSON.stringify(out));
"""


def _node():
    exe = shutil.which('node')
    if not exe:
        raise AssertionError('Node.js bulunamadı: test_neural_js için "node" PATH üzerinde olmalı '
                             '(Node.js is required for these tests; install it or add it to PATH).')
    return exe


class NeuralJsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graphs = [nv.model_graph(list(p)) for p in INPUTS]
        cls.params = nv._trained()['params']   # unrounded weights (same object model_graph used)

    def run_js(self):
        node = _node()
        proc = subprocess.run([node, '-e', RUNNER, NEURAL_JS], input=json.dumps({'graphs': self.graphs}),
                              capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(proc.returncode, 0, 'node failed:\n' + proc.stderr)
        return json.loads(proc.stdout)

    def test_node_check_syntax(self):
        proc = subprocess.run([_node(), '--check', NEURAL_JS], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_contract_and_forward_matches_python(self):
        out = self.run_js()
        self.assertEqual(out['api'], ['_math', 'destroy', 'mount', 'update'])
        for name in ('forward', 'heatGrid', 'truthRows', 'selfCheck', 'normalizeWeights', 'fnsFrom'):
            self.assertIn(name, out['math'])
        self.assertEqual(len(out['forward']), 4)
        for (a, b), js in zip(INPUTS, out['forward']):
            py = nv.forward(self.params, (a, b))
            self.assertEqual(js['inputs'], [a, b])
            for layer in (1, 2):
                for x, y in zip(js['pre'][layer], py['pre'][layer]):
                    self.assertAlmostEqual(x, y, delta=1e-9)
                for x, y in zip(js['act'][layer], py['act'][layer]):
                    self.assertAlmostEqual(x, y, delta=1e-9)

    def test_weights_in_response_are_unrounded(self):
        """The 1e-9 comparison above is only meaningful if data.weights are the real weights."""
        for g in self.graphs:
            self.assertEqual(g['weights']['W1'], self.params['W1'])
            self.assertEqual(g['weights']['W2'], self.params['W2'])

    def test_self_check_tolerances(self):
        out = self.run_js()
        for chk in out['selfCheck']:
            self.assertTrue(chk['ok'], chk)
            self.assertEqual((chk['checked'], chk['passed'], chk['failed']), (5, 5, 0))
            self.assertLessEqual(chk['diff'], 1e-5)
        self.assertFalse(out['tamperedOk'], 'a prediction off by 0.01 must fail the self-check')

    def test_truth_table(self):
        out = self.run_js()
        rows = out['truth']
        self.assertEqual([(r['a'], r['b'], r['expected']) for r in rows],
                         [(0, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 0)])
        for r in rows:
            py = nv.forward(self.params, (r['a'], r['b']))['act'][2][0]
            self.assertAlmostEqual(r['prediction'], py, delta=1e-9)
            self.assertEqual(r['ok'], (py >= 0.5) == bool(r['expected']))
        self.assertTrue(all(r['ok'] for r in rows))   # the trained net solves XOR

    def test_heatmap_corners(self):
        out = self.run_js()
        heat = out['heat']
        self.assertEqual(heat['length'], 48 * 48)
        # grid spans [-0.2, 1.2]^2; row index is b, column index is a; Float32 precision
        corners = [(-0.2, -0.2), (1.2, -0.2), (-0.2, 1.2), (1.2, 1.2)]
        for got, (a, b) in zip(heat['corners'], corners):
            self.assertAlmostEqual(got, nv.forward(self.params, (a, b))['act'][2][0], delta=1e-6)
        lo, _, _, hi = heat['corners']
        self.assertLess(lo, 0.5)    # near (0,0) -> class 0
        self.assertLess(hi, 0.5)    # near (1,1) -> class 0

    def test_weight_shapes(self):
        out = self.run_js()
        self.assertIsNone(out['badWeights'])
        self.assertAlmostEqual(out['column'], nv.forward(self.params, (1, 0))['act'][2][0], delta=1e-9)

    def test_no_unsafe_dom_apis(self):
        with open(NEURAL_JS, encoding='utf-8') as fh:
            src = fh.read()
        for bad in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'eval(', 'new Function', 'alert('):
            self.assertNotIn(bad, src)


if __name__ == '__main__':
    unittest.main()
