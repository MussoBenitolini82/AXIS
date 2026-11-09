import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import central_brain as brain
import axis_executor as ex

class AxisTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.p1=patch.object(brain,'DB',Path(self.tmp.name)/'brain.db');self.p1.start()
  self.p2=patch.object(ex,'DB',Path(self.tmp.name)/'runs.db');self.p2.start()
 def tearDown(self):self.p2.stop();self.p1.stop();self.tmp.cleanup()
 def test_approval_and_run(self):
  a=brain.log('system','count','count_nodes','success','ilk')
  b=brain.log('system','count','count_nodes','success','ikinci')
  skill=brain.propose('Düğüm sayacı',['count_nodes','count_nodes'],[a['id'],b['id']])
  with self.assertRaises(ValueError):ex.execute(skill['id'],{})
  brain.decide(skill['id'],'approve','ONAYLIYORUM')
  with patch('vector_intelligence.TOOLS',{'count_nodes':lambda a:{'nodes':3}}):
   result=ex.execute(skill['id'],{})
  self.assertEqual(result['status'],'success');self.assertEqual(len(result['steps']),2)
  self.assertEqual(len(ex.history()),1)
 def test_disallow_unsafe_steps(self):
  a=brain.log('research','search','research','success','ilk')
  b=brain.log('research','search','research','success','ikinci')
  skill=brain.propose('Ağ isteği',['research','research'],[a['id'],b['id']])
  brain.decide(skill['id'],'approve','ONAYLIYORUM')
  with self.assertRaises(ValueError):ex.execute(skill['id'],{})
 def test_args_validation(self):
  with self.assertRaises(ValueError):ex.execute('x',[])
  with self.assertRaises(ValueError):ex.execute('x',{'x':'a'*6000})

if __name__=='__main__':unittest.main()