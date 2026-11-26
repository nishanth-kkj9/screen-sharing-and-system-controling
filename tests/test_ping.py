"""Application-level PING/PONG round trip (extension). Real TCP on 127.0.0.1:5057 (HostCase)."""
import queue
import time
import unittest

from screenshare import client as client_mod
from screenshare import config, protocol
from screenshare.server import ViewerSession
from tests.test_audit_fixes import HostCase, wait_for



class SessionPing(unittest.TestCase):
    def make(self, features):
        s = ViewerSession("v", sock=None, addr=("127.0.0.1", 1))
        s.features = frozenset(features)
        return s

    def test_no_ping_without_the_feature(self):
        self.assertIsNone(self.make([]).make_ping(100.0))

    def test_interval_timeout_and_matching(self):
        s = self.make(["ping"])
        first = s.make_ping(100.0)
        self.assertEqual(first, {"type": "PING", "id": 1})
        self.assertIsNone(s.make_ping(100.5))                  # waiting for the PONG
        s.on_pong(99, 100.2)                                    # wrong id ignored
        self.assertIsNone(s.rtt_ms)
        s.on_pong(1, 100.25)
        self.assertAlmostEqual(s.rtt_ms, 250.0, places=3)
        self.assertIsNone(s.make_ping(100.6))                   # interval not over
        self.assertEqual(s.make_ping(101.1)["id"], 2)
        # unanswered PING is abandoned after PING_TIMEOUT
        self.assertIsNone(s.make_ping(101.1 + config.PING_TIMEOUT - 0.1))
        self.assertEqual(s.make_ping(101.1 + config.PING_TIMEOUT + 0.1)["id"], 3)


class WireProtocol(HostCase):
    def setUp(self):
        super().setUp()
        self._old_interval = config.PING_INTERVAL
        config.PING_INTERVAL = 0.1

    def tearDown(self):
        config.PING_INTERVAL = self._old_interval
        super().tearDown()

    def join_with(self, features):
        s = self.raw()
        msg = {"type": "JOIN", "protocol_version": 1, "client_name": "V",
               "session_code": self.srv.session_code}
        if features is not None:
            msg["features"] = features
        self.send(s, msg)
        self.assertEqual(self.next_json(s)["type"], "JOIN_ACCEPT")
        return s

    def test_host_pings_and_records_rtt(self):
        s = self.join_with(["ping"])
        ping = self.next_json(s, "PING")
        self.assertIsNotNone(ping, "no PING arrived")
        self.send(s, {"type": "PONG", "id": ping["id"]})
        self.assertTrue(wait_for(lambda: any(
            x.rtt_ms is not None for x in self.srv._sessions.values())))
        rows = self.srv.stats_snapshot()["viewers"]
        self.assertIsNotNone(rows[0]["rtt_ms"])
        self.assertIn("tcp", rows[0])

    def test_old_viewer_without_features_is_never_pinged(self):
        s = self.join_with(None)
        self.assertIsNone(self.next_json(s, "PING", timeout=1.0))
        self.assertEqual(self.thread_errors, [])

    def test_malformed_pong_closes_the_session_cleanly(self):
        s = self.join_with(["ping"])
        self.send(s, {"type": "PONG", "id": "x"})
        self.assertEqual(self.next_json(s, "ERROR")["reason"], "unsupported_message")


class EndToEnd(HostCase):
    def test_real_viewer_client_gets_an_rtt_on_the_host(self):
        import threading
        config_ping, config.PING_INTERVAL = config.PING_INTERVAL, 0.1
        viewer = client_mod.ViewerClient(queue.Queue(), "Laptop B")
        try:
            threading.Thread(target=viewer.connect,
                             args=("127.0.0.1", self.srv.session_code), daemon=True).start()
            def has_rtt():
                return any(s.rtt_ms is not None for s in list(self.srv._sessions.values()))
            self.assertTrue(wait_for(has_rtt, timeout=5.0), "Host never measured an RTT")
            row = self.srv.stats_snapshot()["viewers"][0]
            self.assertLess(row["rtt_ms"], 1000.0)
            self.assertEqual(row["name"], "Laptop B")
        finally:
            config.PING_INTERVAL = config_ping
            viewer.disconnect()


class ViewerSide(unittest.TestCase):
    def test_viewer_answers_ping_with_the_same_id(self):
        viewer = client_mod.ViewerClient(queue.Queue(), "B")
        from screenshare.outbox import Outbox
        viewer.outbox = Outbox()
        self.assertTrue(viewer._handle_message({"type": "PING", "id": 42}))
        _kind, data = viewer.outbox.get(0.1)
        self.assertEqual(protocol.decode_json_payload(data[protocol.HEADER.size:]),
                         {"type": "PONG", "id": 42})

    def test_bad_ping_id_is_ignored_not_fatal(self):
        viewer = client_mod.ViewerClient(queue.Queue(), "B")
        from screenshare.outbox import Outbox
        viewer.outbox = Outbox()
        for bad in ("x", None, True, 1.5):
            self.assertTrue(viewer._handle_message({"type": "PING", "id": bad}))
        self.assertIsNone(viewer.outbox.get(0.05))


if __name__ == "__main__":
    unittest.main()
