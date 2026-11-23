"""Per-connection outgoing queue with ONE wake-up point (section 7.4).

Control messages are kept in order (bounded). One 'latest' item (a frame on the Host,
a mouse position on the Viewer) is overwritten instead of queued. get() returns control
messages first, then the latest item, and blocks without polling until something arrives."""
import collections
import threading
import time


class Outbox:
    def __init__(self, max_control=128):
        self._cond = threading.Condition()
        self._control = collections.deque()
        self._max = max_control
        self._latest = None
        self._closed = False
        self.replaced = 0  # latest items overwritten before they were sent (a statistic)

    def put_control(self, item):
        """Queue an ordered message. Returns False if the box is full or closed:
        the caller must then close the session (never drop a permission or key event)."""
        with self._cond:
            if self._closed or len(self._control) >= self._max:
                return False
            self._control.append(item)
            self._cond.notify()
            return True

    def put_latest(self, item):
        with self._cond:
            if self._closed:
                return
            if self._latest is not None:
                self.replaced += 1
            self._latest = item
            self._cond.notify()

    def get(self, timeout=None):
        """Return ("control", item), ("latest", item), or None (closed, or timeout expired)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while not self._control and self._latest is None and not self._closed:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._cond.wait(remaining)
            if self._control:
                return ("control", self._control.popleft())
            if self._latest is not None:
                item, self._latest = self._latest, None
                return ("latest", item)
            return None

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()
