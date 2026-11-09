import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from axis_sqlite import ClosingConnection

class ConnectionTests(unittest.TestCase):
    def test_commit_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'
            with sqlite3.connect(path, factory=ClosingConnection) as db:
                db.execute('CREATE TABLE entries(value)')
                db.execute('INSERT INTO entries VALUES (1)')
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            with sqlite3.connect(path, factory=ClosingConnection) as check:
                self.assertEqual(check.execute('SELECT value FROM entries').fetchall(), [(1,)])

    def test_rollback_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'
            with sqlite3.connect(path, factory=ClosingConnection) as db:
                db.execute('CREATE TABLE entries(value)')
            with self.assertRaises(ValueError):
                with sqlite3.connect(path, factory=ClosingConnection) as db:
                    db.execute('INSERT INTO entries VALUES (1)')
                    raise ValueError('rollback')
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            with sqlite3.connect(path, factory=ClosingConnection) as check:
                self.assertEqual(check.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 0)

class SetupFailureTests(unittest.TestCase):
    def test_open_db_closes_when_setup_fails(self):
        from axis_sqlite import open_db
        seen = []
        def setup(db):
            seen.append(db)
            db.execute('CREATE TABLE entries(value)')
            raise sqlite3.OperationalError('database is locked')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'
            with self.assertRaises(sqlite3.OperationalError):
                open_db(path, setup)
            with self.assertRaises(sqlite3.ProgrammingError):
                seen[0].execute('SELECT 1')
            os.remove(path)

    def test_open_db_returns_configured_connection(self):
        from axis_sqlite import open_db
        with tempfile.TemporaryDirectory() as directory:
            with open_db(Path(directory) / 'db.sqlite', lambda db: db.execute('CREATE TABLE t(v)')) as db:
                self.assertIs(db.row_factory, sqlite3.Row)
                self.assertIsInstance(db, ClosingConnection)

    def test_factories_release_file_when_setup_fails(self):
        import axis_executor, axis_learning, central_brain, self_evolution, server, vector_agents, vector_discovery
        factories = [(axis_executor, '_conn'), (axis_learning, 'connect'), (central_brain, 'conn'),
                     (self_evolution, 'db'), (server, 'connect'), (vector_agents, 'dbconn'), (vector_discovery, 'conn')]
        for module, name in factories:
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'broken.sqlite3'
                path.write_bytes(b'not a database ' * 100)
                error = None
                with patch.object(module, 'DB', path):
                    try:
                        getattr(module, name)()
                    except sqlite3.DatabaseError as exc:
                        error = exc  # keeps the failing frame (and any leaked connection) alive
                self.assertIsNotNone(error)
                os.remove(path)  # PermissionError on Windows if the connection leaked
                del error

    def test_factory_timeouts(self):
        import self_evolution, server, central_brain
        real = sqlite3.connect
        seen = {}
        def spy(*args, **kwargs):
            seen['timeout'] = kwargs.get('timeout')
            return real(*args, **kwargs)
        for module, name, expected in ((self_evolution, 'db', 15), (central_brain, 'conn', 15), (server, 'connect', 20)):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                seen.clear()
                with patch.object(module, 'DB', Path(directory) / 'x.sqlite3'), patch('sqlite3.connect', spy):
                    getattr(module, name)().close()
                self.assertEqual(seen['timeout'], expected)
