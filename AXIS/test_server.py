import tempfile, unittest
from pathlib import Path
import server

class Tests(unittest.TestCase):
    def test_graph_and_sources(self):
        with tempfile.TemporaryDirectory() as d:
            old=server.DB
            server.DB=Path(d)/'test.db'
            try:
                with server.connect() as db:
                    a=server.add_node(db,'Sinir ağları','topic')
                    b=server.add_node(db,'Makale','paper')
                    server.link(db,a,b,'literatür')
                    db.commit()
                g=server.graph()
                self.assertEqual(len(g['nodes']),2)
                self.assertEqual(len(g['edges']),1)
                self.assertEqual(server.sources(b),[])
            finally: server.DB=old
    def test_abstract(self):
        self.assertEqual(server.clean_abstract({'world':[1],'hello':[0]}),'hello world')
    def test_validation(self):
        with self.assertRaises(ValueError):server.start_research('x')
if __name__=='__main__':unittest.main()