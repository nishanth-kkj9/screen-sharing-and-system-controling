"""Regression tests: Host stat rates must never be negative (docs/test_results.md section 13).

`stats_snapshot()` subtracts a mark that still holds counters of Viewers that
have already left, so the tick racing a disconnect used to report negative
FPS/KB/s on the Host panel."""
import queue
import time
import types
import unittest

from screenshare.server import HostServer
from tests.test_permissions import FakeFrameSource, FakeInputBackend


def viewer(viewer_id, now, frames, byte_count):
    return types.SimpleNamespace(
        id=viewer_id, display=viewer_id, addr=("127.0.0.1", 40000),
        authenticated=True, connected_at=now - 2.0,
        frames_sent=frames, bytes_sent=byte_count, frames_skipped=0,
        sock=None, rtt_ms=None)


class StatsRatesNeverNegative(unittest.TestCase):
    def setUp(self):
        self.srv = HostServer(queue.Queue(), input_backend=FakeInputBackend(),
                              frame_factory=FakeFrameSource)

    def test_rates_stay_non_negative_when_the_last_viewer_leaves(self):
        now = time.monotonic()
        self.srv._sessions["v1"] = viewer("v1", now, 100, 50000)
        first = self.srv.stats_snapshot()
        self.assertGreaterEqual(first["fps"], 0.0)
        del self.srv._sessions["v1"]           # the Viewer leaves between two ticks
        second = self.srv.stats_snapshot()     # the tick that raced the disconnect
        self.assertEqual(second["viewers"], [])
        self.assertGreaterEqual(second["fps"], 0.0,
                                "negative fps after the last Viewer left")
        self.assertGreaterEqual(second["kbps"], 0.0,
                                "negative kbps after the last Viewer left")

    def test_rates_stay_non_negative_when_one_of_two_viewers_leaves(self):
        now = time.monotonic()
        self.srv._sessions["v1"] = viewer("v1", now, 100, 50000)
        self.srv._sessions["v2"] = viewer("v2", now, 80, 40000)
        self.srv.stats_snapshot()
        del self.srv._sessions["v1"]           # one of two leaves; the other keeps streaming
        second = self.srv.stats_snapshot()
        self.assertEqual(len(second["viewers"]), 1)
        self.assertGreaterEqual(second["fps"], 0.0,
                                "negative fps while a second Viewer still streams")
        self.assertGreaterEqual(second["kbps"], 0.0,
                                "negative kbps while a second Viewer still streams")


if __name__ == "__main__":
    unittest.main()
