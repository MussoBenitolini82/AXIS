import unittest
import neural_view

class NeuralTests(unittest.TestCase):
    def test_xor(self):
        d=neural_view.model_graph([1,0])
        if not d['available']:self.skipTest('torch not installed')
        self.assertTrue(d['trained'])
        self.assertEqual(d['architecture'],[2,8,1])
        self.assertEqual(len(d['edges']),24)
        self.assertTrue(all(abs(e['prediction']-e['expected'])<.1 for e in d['examples']))
    def test_activations_change(self):
        a=neural_view.model_graph([0,0]);b=neural_view.model_graph([1,1])
        if not a['available']:self.skipTest('torch not installed')
        self.assertNotEqual([n['activation'] for n in a['nodes']],[n['activation'] for n in b['nodes']])
    def test_invalid(self):
        if not neural_view.model_graph()['available']:self.skipTest('torch not installed')
        with self.assertRaises(ValueError):neural_view.model_graph([2,0])
if __name__=='__main__':unittest.main()