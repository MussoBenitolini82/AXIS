import unittest, tempfile, json
from pathlib import Path
from unittest.mock import patch
import vector_upgrade as u
class V8Tests(unittest.TestCase):
 def test_valid_cases(self):
  self.assertEqual(len(u.validate_behavior_cases([{'function':'add','args':[2,3],'expected':5}])),1)
 def test_bad_function(self):
  with self.assertRaises(ValueError):u.validate_behavior_cases([{'function':'__import__','args':[],'expected':None}])
 def test_extra_keys(self):
  with self.assertRaises(ValueError):u.validate_behavior_cases([{'function':'f','args':[],'expected':1,'command':'x'}])
 def test_empty(self):
  with self.assertRaises(ValueError):u.validate_behavior_cases([])
 def test_behavior_runner_syntax(self):
  compile(u.BEHAVIOR_RUNNER.replace('CANDIDATE','x.py'),'<runner>','exec')
 def test_attach_and_retrieve(self):
  p=u.propose('skills_helpers.py','def add(a,b): return a+b','test')
  c=[{'function':'add','args':[2,3],'expected':5}]
  self.assertEqual(u.attach_behavior_cases(p['id'],c)['case_count'],1)
  self.assertEqual(u.behavior_cases(p['id'])['cases'],c)
  self.assertEqual(u.detail(p['id'])['behavior_cases'],c)
 def test_docker_missing_fails_closed(self):
  p=u.propose('skills_helpers.py','def add(a,b): return a+b','test')
  with patch.object(u,'docker_available',return_value=False):
   self.assertFalse(u.verify(p['id'])['passed'])
if __name__=='__main__':unittest.main()