import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional
from db.generated.query import Querier # Imported from your sqlc output output folder

class DatabaseManager:
    def __init__(self):
        self._db_path: Optional[str] = None

    def init_db(self, db_path: str):
        self._db_path = db_path
        
        with self.get_client() as db:
            db._conn.execute("PRAGMA foreign_keys = ON;")

    @contextmanager
    def get_client(self) -> Generator[Querier, None, None]:
        if not self._db_path:
            raise RuntimeError("DatabaseManager has not been initialised. Call init_db() first.")

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row 
        
        try:
            querier = Querier(conn)
            yield querier
            conn.commit()  
        except Exception:
            conn.rollback()  
            raise
        finally:
            conn.close() 

db_manager = DatabaseManager()
