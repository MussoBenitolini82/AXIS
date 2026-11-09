import tempfile,unittest
from pathlib import Path
import central_brain as b
class BrainTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=b.DB;b.DB=Path(self.tmp.name)/'brain.sqlite3'
 def tearDown(self):b.DB=self.old;self.tmp.cleanup()
 def test_learning_requires_evidence_and_approval(self):
  a=b.log('research','find','research','success','Found sources',task_id='t')
  c=b.log('research','find_again','research','success','Found more sources',task_id='t')
  self.assertTrue(b.discover())
  x=b.propose('research_reuse',['research','research'],[a['id'],c['id']]);self.assertEqual(x['status'],'pending')
  with self.assertRaises(ValueError):b.decide(x['id'],'approve','')
  self.assertEqual(b.decide(x['id'],'approve','ONAYLIYORUM')['status'],'approved')
  self.assertEqual(len(b.graph()['edges']),2)
 def test_failure_is_not_learning_evidence(self):
  a=b.log('tester','check','research','failure','Bad result')
  c=b.log('research','find','research','success','Good result')
  with self.assertRaises(ValueError):b.propose('invalid',['research','research'],[a['id'],c['id']])
 def test_invalid_tools_rejected(self):
  with self.assertRaises(ValueError):b.log('research','test','shell','success','x')
  with self.assertRaises(ValueError):b.propose('bad',['shell','research'],['a','b'])
 def test_isolated_storage(self):
  b.log('planner','scan','agent_scan','success','Scan complete')
  self.assertEqual(len(b.experiences()),1)
  self.assertEqual(len(b.skills()),0)
if __name__=='__main__':unittest.main()