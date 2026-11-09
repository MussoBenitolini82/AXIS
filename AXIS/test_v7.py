import ast,unittest
from unittest.mock import patch
import vector_agents,vector_upgrade
class AgentTests(unittest.TestCase):
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