import ast,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import vector_agents,vector_upgrade
class AgentTests(unittest.TestCase):
 def setUp(self):
  # Isolate every path the agent/upgrade pipeline writes to, so a run inside a real install never touches it.
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  data=Path(tmp.name);root=data/'root';root.mkdir();tests=data/'behavior_specs';tests.mkdir()
  for mod,name,val in ((vector_upgrade,'DATA',data),(vector_upgrade,'DB',data/'upgrades.sqlite3'),(vector_upgrade,'TESTS',tests),(vector_upgrade,'ROOT',root),(vector_agents,'ROOT',root),(vector_agents,'DB',data/'agents.sqlite3')):
   p=patch.object(mod,name,val);p.start();self.addCleanup(p.stop)
 def test_extract_code(self):
  self.assertEqual(vector_agents.extract_code('```python\ndef run(x): return x\n```'),'def run(x): return x')
 def test_invalid_syntax(self):
  with self.assertRaises(SyntaxError):vector_agents.extract_code('def run(:')
 def test_target_whitelist(self):
  with self.assertRaises(ValueError):vector_upgrade.safe_target('server.py')
 def test_contract_valid(self):
  ast.parse(vector_upgrade.CONTRACT_TEST)
 def test_bad_request(self):
  with self.assertRaises(ValueError):vector_agents.run('kısa')
 def test_review_failure_does_not_propose(self):
  with patch.object(vector_agents,'llm',side_effect=['Plan','def run(x): return x','VERDICT: FAIL\nTest yok']):
   r=vector_agents.run('Yeni saf hesaplama becerisi oluştur','research_extensions.py')
  self.assertEqual(r['status'],'review_failed')
  self.assertFalse(r['proposal_id'])
 def test_review_pass_creates_pending_not_applied(self):
  with patch.object(vector_agents,'llm',side_effect=['Plan','def run(x): return x','VERDICT: PASS\nBasit']):
   r=vector_agents.run('Saf hesaplama becerisi oluştur ve öner','research_extensions.py')
  self.assertEqual(r['status'],'awaiting_tests_and_approval')
  self.assertEqual(r['proposal']['status'],'pending')
if __name__=='__main__':unittest.main()