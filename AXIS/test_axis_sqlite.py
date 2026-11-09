import sqlite3
import tempfile
import unittest
from pathlib import Path
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
