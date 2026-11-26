"""Kernel TCP statistics parsing and the pure dashboard text."""
import ctypes
import socket
import struct
import sys
import unittest

from screenshare import tcpstats, transport_view as tv


class WindowsLayout(unittest.TestCase):
    def test_struct_matches_tcp_info_v0_in_mstcpip_h(self):
        T = tcpstats.TcpInfoV0
        expected = {"State": 0, "Mss": 4, "ConnectionTimeMs": 8, "TimestampsEnabled": 16,
                    "RttUs": 20, "MinRttUs": 24, "BytesInFlight": 28, "Cwnd": 32, "SndWnd": 36,
                    "RcvWnd": 40, "RcvBuf": 44, "BytesOut": 48, "BytesIn": 56,
                    "BytesReordered": 64, "BytesRetrans": 68, "FastRetrans": 72,
                    "DupAcksIn": 76, "TimeoutEpisodes": 80, "SynRetrans": 84}
        self.assertEqual({n: getattr(T, n).offset for n, _ in T._fields_}, expected)
        self.assertEqual(ctypes.sizeof(T), 88)

    def test_parse_windows(self):
        info = tcpstats.TcpInfoV0(RttUs=2500, Cwnd=14600, SndWnd=65535, BytesInFlight=2920,
                                  BytesRetrans=1460, FastRetrans=1, DupAcksIn=3, TimeoutEpisodes=2)
        got = tcpstats.parse_windows(bytes(info))
        self.assertEqual((got["rtt_ms"], got["cwnd"], got["snd_wnd"], got["in_flight"],
                          got["retrans"], got["retrans_unit"], got["dup_acks"], got["timeouts"]),
                         (2.5, 14600, 65535, 2920, 1460, "bytes", 3, 2))

    def test_short_buffers_give_none(self):
        self.assertIsNone(tcpstats.parse_windows(b"\0" * 10))
        self.assertIsNone(tcpstats.parse_linux(b"\0" * 10))


class LinuxParse(unittest.TestCase):
    def test_parse_linux_offsets(self):
        raw = bytearray(104)
        struct.pack_into("I", raw, 16, 1000)     # mss
        struct.pack_into("I", raw, 24, 3)        # unacked segments
        struct.pack_into("I", raw, 68, 4200)     # rtt us
        struct.pack_into("I", raw, 80, 10)       # cwnd segments
        struct.pack_into("I", raw, 100, 7)       # total_retrans
        got = tcpstats.parse_linux(bytes(raw))
        self.assertEqual((got["rtt_ms"], got["cwnd"], got["in_flight"], got["retrans"],
                          got["retrans_unit"]), (4.2, 10000, 3000, 7, "segments"))

    @unittest.skipUnless(sys.platform.startswith("linux"), "uses the Linux TCP_INFO option")
    def test_read_on_a_real_connection(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname())
        peer, _ = server.accept()
        try:
            client.sendall(b"x" * 100000)
            got = tcpstats.read(client)
            self.assertIsNotNone(got)
            self.assertEqual(got["source"], "linux")
            mss = client.getsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG)
            self.assertEqual(got["cwnd"] % mss, 0)       # offsets right: cwnd is whole segments
            self.assertGreaterEqual(got["cwnd"], mss)
            self.assertEqual(got["retrans"], 0)
        finally:
            for s in (client, peer, server):
                s.close()


class ReadNeverRaises(unittest.TestCase):
    def test_none_and_closed_sockets_give_none(self):
        self.assertIsNone(tcpstats.read(None))
        s = socket.socket()
        s.close()
        self.assertIsNone(tcpstats.read(s))


class ViewText(unittest.TestCase):
    ROW = {"name": "Laptop B", "peer": "10.0.0.2:50000", "skipped": 4, "rtt_ms": 3.5,
           "tcp": {"rtt_ms": 1.25, "cwnd": 14600, "snd_wnd": 65535, "in_flight": 2048,
                   "retrans": 2920, "retrans_unit": "bytes", "dup_acks": 3}}

    def test_row_text(self):
        row = tv.viewer_rows([self.ROW])[0]
        self.assertEqual(len(row), len(tv.VIEWER_COLUMNS))
        self.assertEqual(row, ("Laptop B", "3.50 ms", "1.25 ms", "2920 B", "3",
                               "14.3 KB", "64.0 KB", "2.0 KB", "4"))

    def test_missing_numbers_are_dashes_not_zeros(self):
        row = tv.viewer_rows([{"name": "V", "skipped": 0, "rtt_ms": None, "tcp": None}])[0]
        self.assertEqual(row[1:8], (tv.DASH,) * 7)

    def test_linux_style_missing_fields(self):
        tcp = dict(self.ROW["tcp"], snd_wnd=None, dup_acks=None, retrans=5, retrans_unit="segments")
        row = tv.viewer_rows([dict(self.ROW, tcp=tcp)])[0]
        self.assertEqual((row[3], row[4], row[6]), ("5 seg", tv.DASH, tv.DASH))

    def test_explainer_uses_only_real_numbers(self):
        rows = tv.explainer([self.ROW])
        names = [r[0] for r in rows]
        self.assertEqual(names, ["Connection management", "Multiplexing by port", "Acknowledgement",
                                 "Error control", "Error detection", "Flow control",
                                 "Congestion control"])
        by_name = {r[0]: r[2] for r in rows}
        self.assertIn("2920 bytes retransmitted", by_name["Error control"])
        self.assertIn("4 frames skipped", by_name["Flow control"])
        self.assertIn("64.0 KB", by_name["Flow control"])

    def test_explainer_with_no_viewers_or_no_stats(self):
        for rows in ([], [{"name": "V", "peer": "p", "skipped": 0, "rtt_ms": None, "tcp": None}]):
            by_name = {r[0]: r[2] for r in tv.explainer(rows)}
            self.assertEqual(by_name["Error control"], tv.DASH)


if __name__ == "__main__":
    unittest.main()
