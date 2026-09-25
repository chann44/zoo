import sqlite3
from typing import Generator, Optional
from db.generated.query import Querier # Imported from your sqlc output output folder


class _Result:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def first(self):
        return self._cursor.fetchone()

    def __iter__(self):
        return iter(self._cursor)


class SqliteConn:
    """Adapts a sqlite3 connection to the sqlalchemy-style calls sqlc-gen-python emits.

    The generated code calls `conn.execute(sqlalchemy.text(SQL), {"p1": .., "p2": ..})`
    but the sqlite queries keep `?` placeholders, so bind the params positionally.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, clause, params: dict | None = None) -> _Result:
        sql = getattr(clause, "text", clause)
        args = [params[k] for k in sorted(params or {}, key=lambda k: int(k[1:]))]
        return _Result(self._conn.execute(sql, args))

class DatabaseManager:
    def __init__(self):
        self._db_path: Optional[str] = None

    def init_db(self, db_path: str):
        self._db_path = db_path

    def get_client(self) -> Generator[Querier, None, None]:
        """FastAPI dependency: `db: Querier = Depends(db_manager.get_client)`"""
        if not self._db_path:
            raise RuntimeError("DatabaseManager has not been initialised. Call init_db() first.")

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row 
        # foreign keys are off by default and the setting is per connection
        conn.execute("PRAGMA foreign_keys = ON;")
        
        try:
            querier = Querier(SqliteConn(conn))
            yield querier
            conn.commit()  
        except Exception:
            conn.rollback()  
            raise
        finally:
            conn.close() 

db_manager = DatabaseManager()
