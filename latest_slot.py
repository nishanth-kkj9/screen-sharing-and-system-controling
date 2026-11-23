# file: latest_slot.py
"""One-item 'latest value' slot with blocking wait. Used for host->viewer frames
(one per viewer) and for the viewer's decoded image / latest mouse position."""
import threading


class LatestSlot:
    def __init__(self):
        self._cond = threading.Condition()
        self._item = None
        self._closed = False
        self.replaced = 0  # how many unsent items were overwritten (a statistic)

    def put(self, item):
        with self._cond:
            if self._item is not None:
                self.replaced += 1
            self._item = item
            self._cond.notify()

    def take(self, timeout=None):
        """Return the newest item (and empty the slot), or None on timeout/close."""
        with self._cond:
            if self._item is None and not self._closed:
                self._cond.wait(timeout)
            item, self._item = self._item, None
            return item

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()
