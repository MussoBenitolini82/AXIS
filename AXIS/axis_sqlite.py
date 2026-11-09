"""SQLite transactions that release Windows file handles on context exit."""
import sqlite3

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def open_db(path, setup, timeout=15, row_factory=sqlite3.Row):
    """Open a ClosingConnection and run setup(db); close it if setup fails so no file lock leaks."""
    db = sqlite3.connect(path, factory=ClosingConnection, timeout=timeout)
    try:
        db.row_factory = row_factory
        setup(db)
    except BaseException:
        db.close()
        raise
    return db
