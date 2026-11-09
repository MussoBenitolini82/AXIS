import unittest
from unittest.mock import patch
import axis_v13

class V13Tests(unittest.TestCase):
    def test_role_validation(self):
        with self.assertRaises(ValueError):
            axis_v13.log_stage('task','unknown','run','success')
    def test_repair_rejects_short_report(self):
        with self.assertRaises(ValueError):
            axis_v13.repair('oops')
    def test_repair_rejects_core_target(self):
        with self.assertRaises(ValueError):
            axis_v13.repair('An example failure report', 'server.py')
    @patch.object(axis_v13.vector_agents,'run',return_value={'status':'awaiting_tests_and_approval','id':'run'})
    @patch.object(axis_v13,'log_stage')
    def test_development_requires_approval(self, log, run):
        result=axis_v13.development('Add a simple pure function')
        self.assertTrue(result['requires_approval'])
        self.assertEqual(run.call_count,1)
        self.assertEqual(log.call_count,3)
    @patch.object(axis_v13.vector_discovery,'scan',return_value={'matched':[]})
    def test_catalog_no_install(self,scan):
        r=axis_v13.model_suggestions('semantic memory')
        self.assertFalse(r['downloads_performed'])
        self.assertTrue(r['approval_required'])
        self.assertEqual(len(r['suggestions']),2)
    @patch.object(axis_v13.axis_learning,'events',return_value=[{'id':'e','task_id':'t','agent':'coder','outcome':'success'}])
    @patch.object(axis_v13.axis_learning,'lessons',return_value=[{'id':'l','signature':'x','evidence':'["e"]'}])
    def test_graph_links(self, lessons, events):
        g=axis_v13.dashboard()
        self.assertEqual(len(g['nodes']),3)
        self.assertEqual(len(g['edges']),2)

if __name__=='__main__': unittest.main()