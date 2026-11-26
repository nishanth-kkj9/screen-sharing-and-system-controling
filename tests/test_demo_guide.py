"""demo_guide: pure checks over Host statistics rows (no Tk)."""
import unittest
from screenshare import demo_guide as dg


def row(name="PC", skipped=0, retrans=0, snd=65536, tcp=True):
    t = {"rtt_ms": 0.2, "retrans": retrans, "retrans_unit": "segments", "dup_acks": 0,
         "cwnd": 10000, "snd_wnd": snd, "in_flight": 0} if tcp else None
    return {"id": 1, "name": name, "peer": "10.0.0.2:5555", "seconds": 3, "frames": 5,
            "bytes": 100, "skipped": skipped, "rtt_ms": 1.0, "tcp": t}


class DemoGuideTests(unittest.TestCase):
    def test_every_step_runs_on_empty_and_full_rows(self):
        for rows in ([], [row()], [row(tcp=False)]):
            for i in range(len(dg.STEPS)):
                status, text = dg.evaluate(i, rows)
                self.assertIn(status, dg.ICON)
                self.assertTrue(text)

    def test_waiting_until_the_action_happens(self):
        self.assertEqual(dg.evaluate(0, [])[0], "waiting")
        self.assertEqual(dg.evaluate(3, [row()])[0], "waiting")      # nothing skipped
        self.assertEqual(dg.evaluate(4, [row()])[0], "waiting")      # zero loss

    def test_ok_when_evidence_exists(self):
        self.assertEqual(dg.evaluate(0, [row()])[0], "ok")
        self.assertEqual(dg.evaluate(3, [row(skipped=9, snd=0)])[0], "ok")
        self.assertIn("0 B", dg.evaluate(3, [row(skipped=9, snd=0)])[1])
        self.assertEqual(dg.evaluate(4, [row(retrans=3)])[0], "ok")

    def test_snapshot_has_every_step_and_the_table(self):
        text = dg.snapshot_text([row(skipped=2)], when=0)
        for step in dg.STEPS:
            self.assertIn(step["title"], text)
        self.assertIn("App RTT", text)
        self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
