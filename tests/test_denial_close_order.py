"""Regression: denying a JOIN must close the connection cleanly (FIN after the denial).

A denial is decided inside the reader thread. close() used to join the writer thread
before _accept_loop had started it, raising RuntimeError and leaving the socket open.
Real TCP on 127.0.0.1:5058, fake backend and frames."""
import socket
import threading
import time
import unittest

from screenshare import protocol
from tests.test_audit_fixes import HostCase
import tests.test_audit_fixes as taf

TRIALS = 12


class DenialClosesCleanly(HostCase):
    def _eof_within(self, s, seconds=3.0):
        s.settimeout(0.3)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if not s.recv(65536):
                    return True
            except socket.timeout:
                continue
            except OSError:
                return True
        return False

    def test_third_viewer_denial_ends_with_eof(self):
        v1, v2 = self.join("V1"), self.join("V2")
        self.assertEqual(self.next_json(v1)["type"], "JOIN_ACCEPT")
        self.assertEqual(self.next_json(v2)["type"], "JOIN_ACCEPT")
        bad = 0
        for _ in range(TRIALS):
            v3 = self.join("V3")
            msg = self.next_json(v3)
            self.assertEqual(msg["reason"], "viewer_limit_reached")
            if not self._eof_within(v3):
                bad += 1
        time.sleep(0.3)
        self.assertEqual(bad, 0, "%d/%d denied connections were not closed" % (bad, TRIALS))
        self.assertEqual(self.thread_errors, [])

    def test_bad_version_join_ends_with_eof(self):
        bad = 0
        for _ in range(TRIALS):
            s = self.raw()
            s.sendall(protocol.encode_json_message({
                "type": "JOIN", "protocol_version": 99, "client_name": "X",
                "session_code": self.srv.session_code}))
            msg = self.next_json(s)
            self.assertEqual(msg["type"], "JOIN_DENIED")
            if not self._eof_within(s):
                bad += 1
        time.sleep(0.3)
        self.assertEqual(bad, 0, "%d/%d bad-version JOINs were not closed" % (bad, TRIALS))
        self.assertEqual(self.thread_errors, [])


if __name__ == "__main__":
    unittest.main()
