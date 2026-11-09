import unittest, tempfile
from pathlib import Path
from unittest.mock import patch
import axis_learning as al
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(al,'DB',Path(self.tmp.name)/'events.db');self.p.start()
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_events(self):
  al.record('t1','research','lookup','search_memory','success',{'source':'paper'})
  self.assertEqual(len(al.events('t1')),1)
 def test_learning(self):
  for _ in range(2):al.record('t','research','lookup','search_memory','failure')
  self.assertEqual(len(al.learn()),1);self.assertEqual(len(al.learn()),0)
  self.assertEqual(len(al.lessons()),1)
 def test_validation(self):
  with self.assertRaises(ValueError):al.record('','a','k','t','success')
  with self.assertRaises(ValueError):al.run_with_recovery('x',{},3)
 def test_recovery(self):
  with patch.object(al.executor,'execute',side_effect=[{'status':'failure','run_id':'a'},{'status':'success','run_id':'b'}]):
   result=al.run_with_recovery('approved',{},2)
  self.assertEqual(result['status'],'success');self.assertEqual(len(result['attempts']),2)
 def test_composition_requires_two(self):
  with self.assertRaises(ValueError):al.compose('test',['only-one'])
if __name__=='__main__':unittest.main()