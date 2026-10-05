import logging
import queue
import threading
from collections.abc import Callable

from db.connection import db_manager
from db.generated.query import Querier

Write = Callable[[Querier], object]

logger = logging.getLogger(__name__)


class ExecutionLog:
    """Writes tool-execution rows on one background thread so a tool call never waits on the database. Writes run
    in order, batched into one transaction; readers call flush() first to see every row written so far."""

    def __init__(self):
        self.queue: queue.Queue[Write] = queue.Queue()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def write(self, fn: Write):
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.run, name="execution-log", daemon=True)
                self.thread.start()
        self.queue.put(fn)

    def flush(self):
        self.queue.join()

    def run(self):
        while True:
            batch = [self.queue.get()]
            while not self.queue.empty():
                batch.append(self.queue.get_nowait())
            try:
                with db_manager.session() as db:
                    for fn in batch:
                        try:
                            fn(db)
                        except Exception:
                            logger.exception("tool execution write failed")
            except Exception:
                logger.exception("tool execution batch failed")
            finally:
                for _ in batch:
                    self.queue.task_done()
