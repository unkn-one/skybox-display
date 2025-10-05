import logging
import threading

LOGGER = logging.getLogger(__name__)


class Threaded(threading.Thread):
    """Thread with stop support"""

    def __init__(self):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self._stop_ev = threading.Event()

    def stop(self, join_timeout: float | None = None) -> None:
        """Signal the thread to stop and optionally join.

        Args:
            join_timeout: If provided, block up to this many seconds
                          for the thread to finish. If None, do not join.
        """
        LOGGER.debug(f"Stopping {self.name} thread")
        self._stop_ev.set()
        # Avoid deadlock if called from within the same thread
        if join_timeout is not None and threading.current_thread() is not self:
            if self.is_alive():
                try:
                    self.join(timeout=join_timeout)
                except Exception:
                    pass

    def run(self) -> None:
        LOGGER.debug(f"Starting {self.name} thread")
        try:
            while not self._stop_ev.is_set():
                self._execute()
        finally:
            self._clean()

    def _execute(self) -> None:
        pass

    def _clean(self):
        pass
