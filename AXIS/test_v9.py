import unittest, tempfile
from pathlib import Path
from unittest.mock import patch
import vector_discovery as d
class DiscoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(d,'DB',Path(self.tmp.name)/'test.sqlite3');self.patch.start()
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def test_missing_agent_requires_approval(self):
  x=d.scan('Fotoğraf görsel analizi yap');self.assertIn('vision',x['missing']);self.assertEqual(d.installed(),[])
  aid=x['proposals'][0]['id'];self.assertRaises(ValueError,d.decision,aid,'approve','')
  d.decision(aid,'approve','ONAYLIYORUM');self.assertEqual(len(d.installed()),1)
 def test_rejected_agent_not_reproposed(self):
  aid=d.scan('mikrofon ses işleme')['proposals'][0]['id'];d.decision(aid,'reject');self.assertEqual(d.scan('mikrofon ses işleme')['proposals'],[])
 def test_builtin(self):
  x=d.scan('literatür araştır ve test et');self.assertEqual(x['missing'],[]);self.assertGreaterEqual(len(x['available']),2)
 def test_invalid(self):
  self.assertRaises(ValueError,d.scan,'a');self.assertRaises(ValueError,d.decision,'invalid','approve','ONAYLIYORUM')
if __name__=='__main__':unittest.main()