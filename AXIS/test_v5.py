import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import neural_view, vector_upgrade as up
class V5Tests(unittest.TestCase):
 def setUp(self):
  # Isolate DATA/DB/TESTS/ROOT so proposals never land in a real install.
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  data=Path(tmp.name);root=data/'root';root.mkdir();tests=data/'behavior_specs';tests.mkdir()
  for name,val in (('DATA',data),('DB',data/'upgrades.sqlite3'),('TESTS',tests),('ROOT',root)):
   p=patch.object(up,name,val);p.start();self.addCleanup(p.stop)
 def test_real_weights(self):
  g=neural_view.model_graph()
  self.assertTrue(g['available'])
  self.assertTrue(g['trained'])
  self.assertEqual(g['architecture'],[2,8,1])
  self.assertEqual(len(g['edges']),2*8+8*1)
  self.assertEqual(g['parameter_count'],2*8+8+8*1+1)
 def test_reject_protected(self):
  with self.assertRaises(ValueError):up.propose('server.py','x=1')
 def test_approval_without_docker_blocked(self):
  x=up.propose('research_extensions.py','def hello():\n    return 1','test')
  original=up.docker_available
  try:
   up.docker_available=lambda:False
   result=up.verify(x['id']);self.assertFalse(result['passed'])
   with self.assertRaises(ValueError):up.decide(x['id'],'approve','ONAYLIYORUM')
  finally:up.docker_available=original
  self.assertEqual(up.decide(x['id'],'reject')['status'],'rejected')
 def test_rollback_requires_approval(self):
  with self.assertRaises(ValueError):up.rollback('missing')
if __name__=='__main__':unittest.main()