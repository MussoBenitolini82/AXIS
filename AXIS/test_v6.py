import unittest
import neural_view

class NeuralTests(unittest.TestCase):
    def test_xor(self):
        d=neural_view.model_graph([1,0])
        self.assertTrue(d['available'])
        self.assertIn(d['backend'],('python','torch'))
        self.assertTrue(d['trained'])
        self.assertEqual(d['architecture'],[2,8,1])
        self.assertEqual(len(d['edges']),24)
        self.assertTrue(all(abs(e['prediction']-e['expected'])<.1 for e in d['examples']))
    def test_activations_change(self):
        a=neural_view.model_graph([0,0]);b=neural_view.model_graph([1,1])
        self.assertTrue(a['available'] and b['available'])
        self.assertNotEqual([n['activation'] for n in a['nodes']],[n['activation'] for n in b['nodes']])
    def test_invalid(self):
        self.assertTrue(neural_view.model_graph()['available'])
        for bad in ([2,0],[float('nan'),0],[0,float('inf')],['1','0'],[1]):
            with self.assertRaises(ValueError):neural_view.model_graph(bad)
if __name__=='__main__':unittest.main()