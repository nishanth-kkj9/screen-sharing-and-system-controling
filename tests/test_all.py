# file: tests/test_all.py
import json, os, sys, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P
from latest_slot import LatestSlot
from keymap import tk_keysym_to_wire, ALLOWED_KEYS
from geometry import norm_to_pixel, avoid_points, widget_to_norm
from outbox import Outbox


class Dribble:
    """Fake socket returning at most `step` bytes per recv_into."""
    def __init__(self, data, step=1): self.d, self.i, self.s = data, 0, step
    def recv_into(self, view, n):
        k = min(self.s, n, len(self.d) - self.i)
        view[:k] = self.d[self.i:self.i + k]; self.i += k
        return k


class Framing(unittest.TestCase):
    def test_header_is_5_bytes(self):
        self.assertEqual(P.HEADER.size, 5)
        self.assertEqual(P.HEADER.pack(1, 2), b"\x01\x00\x00\x00\x02")

    def test_partial_reads_json_and_two_messages_back_to_back(self):
        a = P.encode_json_message({"type": "STATUS", "n": 1})
        b = P.encode_message(P.TYPE_JPEG, b"\xff\xd8abc")
        s = Dribble(a + b, step=1)
        t, p = P.recv_message(s, P.HOST_TO_VIEWER)
        self.assertEqual((t, P.decode_json_payload(p)["n"]), (1, 1))
        self.assertEqual(P.recv_message(s, P.HOST_TO_VIEWER), (2, b"\xff\xd8abc"))

    def test_early_eof(self):
        with self.assertRaises(P.ConnectionClosed):
            P.recv_exact(Dribble(b"abc"), 5)

    def test_unknown_type_and_oversize_rejected_before_payload(self):
        for hdr in (P.HEADER.pack(9, 3), P.HEADER.pack(1, P.MAX_JSON_BYTES + 1),
                    P.HEADER.pack(2, P.MAX_JPEG_BYTES + 1), P.HEADER.pack(1, 0)):
            s = Dribble(hdr)  # no payload bytes exist: proves we reject on the header alone
            with self.assertRaises(P.ProtocolError):
                P.recv_message(s, P.HOST_TO_VIEWER)

    def test_viewer_may_not_send_jpeg(self):
        with self.assertRaises(P.ProtocolError):
            P.recv_message(Dribble(P.encode_message(2, b"x")), P.VIEWER_TO_HOST)

    def test_bad_json(self):
        for raw in (b"\xff\xfe", b"{", b"[1]", b'{"type": 5}'):
            with self.assertRaises(P.ProtocolError):
                P.decode_json_payload(raw)

    def test_valid_norm(self):
        for v in (0, 0.0, 1, 0.5):
            self.assertTrue(P.valid_norm(v))
        for v in (-0.1, 1.01, float("nan"), float("inf"), True, "0.5", None):
            self.assertFalse(P.valid_norm(v))


class Slot(unittest.TestCase):
    def test_keeps_only_newest_and_counts_replacements(self):
        s = LatestSlot(); s.put(1); s.put(2); s.put(3)
        self.assertEqual(s.take(0.1), 3); self.assertEqual(s.replaced, 2)
        self.assertIsNone(s.take(0.05))

    def test_take_wakes_on_put_without_polling(self):
        s = LatestSlot(); out = []
        th = threading.Thread(target=lambda: out.append(s.take(2))); th.start()
        time.sleep(0.05); s.put("x"); th.join(1)
        self.assertEqual(out, ["x"])

    def test_close_unblocks(self):
        s = LatestSlot(); out = []
        th = threading.Thread(target=lambda: out.append(s.take(5))); th.start()
        time.sleep(0.05); s.close(); th.join(1)
        self.assertEqual(out, [None])


class Keys(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(tk_keysym_to_wire("Return"), "enter")
        self.assertEqual(tk_keysym_to_wire("Escape"), "esc")
        self.assertEqual(tk_keysym_to_wire("a"), "a")
        self.assertEqual(tk_keysym_to_wire("A"), "a")
        self.assertEqual(tk_keysym_to_wire("7"), "7")
        for bad in ("F4", "Alt_L", "Control_L", "Super_L", "Delete", "ß", ""):
            self.assertIsNone(tk_keysym_to_wire(bad))
        self.assertTrue(all(tk_keysym_to_wire(k) in ALLOWED_KEYS for k in ("Return", "Left", "q")))


class Geometry(unittest.TestCase):
    def test_norm_to_pixel_bounds(self):
        self.assertEqual(norm_to_pixel(0, 0, 1920, 1080), (0, 0))
        self.assertEqual(norm_to_pixel(1, 1, 1920, 1080), (1919, 1079))

    def test_avoid_failsafe_corners(self):
        pts = [(0, 0), (0, 1079), (1919, 0), (1919, 1079)]
        self.assertEqual(avoid_points(0, 0, pts, 1920, 1080), (1, 1))
        self.assertEqual(avoid_points(1919, 1079, pts, 1920, 1080), (1918, 1078))
        self.assertEqual(avoid_points(1919, 0, pts, 1920, 1080), (1918, 1))
        self.assertEqual(avoid_points(10, 10, pts, 1920, 1080), (10, 10))

    def test_widget_to_norm_letterbox(self):
        self.assertIsNone(widget_to_norm(5, 50, 10, 0, 100, 100))
        self.assertEqual(widget_to_norm(10, 0, 10, 0, 100, 100), (0.0, 0.0))
        self.assertEqual(widget_to_norm(109, 99, 10, 0, 100, 100), (1.0, 1.0))


class OutboxTests(unittest.TestCase):
    def test_control_first_then_latest_and_latest_is_replaced(self):
        o = Outbox(); o.put_latest("f1"); o.put_latest("f2"); o.put_control("c1"); o.put_control("c2")
        self.assertEqual([o.get(0.1), o.get(0.1), o.get(0.1)],
                         [("control", "c1"), ("control", "c2"), ("latest", "f2")])
        self.assertEqual(o.replaced, 1); self.assertIsNone(o.get(0.05))

    def test_control_queue_is_bounded_and_never_drops_silently(self):
        o = Outbox(max_control=2)
        self.assertTrue(o.put_control(1)); self.assertTrue(o.put_control(2))
        self.assertFalse(o.put_control(3))  # caller must close the session

    def test_wakes_on_either_source_without_polling(self):
        for put in (lambda o: o.put_control("c"), lambda o: o.put_latest("l")):
            o = Outbox(); out = []
            th = threading.Thread(target=lambda: out.append(o.get(2))); th.start()
            time.sleep(0.05); put(o); th.join(1)
            self.assertEqual(len(out), 1); self.assertIsNotNone(out[0])

    def test_close_unblocks_and_rejects_new_control(self):
        o = Outbox(); out = []
        th = threading.Thread(target=lambda: out.append(o.get(5))); th.start()
        time.sleep(0.05); o.close(); th.join(1)
        self.assertEqual(out, [None]); self.assertFalse(o.put_control("x"))


if __name__ == "__main__":
    unittest.main()
