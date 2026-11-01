import os
import unittest

from _load import GATO, HISTORY, MemeDir, load, run

E = load("meme-entry", "entry")


class Entry(unittest.TestCase):
    def check(self, md, now, start=None, extra=()):
        argv = ["check", GATO, "--symbol", "GATO", "--now", now, "--offline", HISTORY] + list(extra)
        if start:
            argv += ["--from", start]
        code, out = run(E, argv)
        return code, out, md.read("entry.json")

    def test_the_reel_trigger(self):
        with MemeDir() as md:
            code, out, e = self.check(md, "2026-11-01 21:58", "21:42")
            self.assertEqual(code, 0)
            self.assertEqual(e["status"], "triggered")
            self.assertEqual(E.fp(e["range"]["high"]), "0.0077195")
            self.assertEqual(E.fp(e["range"]["low"]), "0.0074560")
            self.assertEqual(e["trigger"]["bar_time"], 1793566620)
            self.assertEqual(e["trigger"]["time"], 1793566680)
            self.assertEqual(E.fp(e["trigger"]["price"]), "0.0077889")
            self.assertEqual(e["trigger"]["vol_x"], 2.73)
            self.assertIn("TRIGGERED at 21:58: the 21:57 bar closed at $0.0077889, 0.90% over $0.0077195", out)

    def test_building_waiting_triggered_stale(self):
        with MemeDir() as md:
            _, out, e = self.check(md, "2026-11-01 19:40", "19:30")
            self.assertEqual(e["status"], "building")
            self.assertIn("10 of 15 range bars", out)
            _, out, e = self.check(md, "2026-11-01 19:46")       # reuses the 19:30 range from entry.json
            self.assertEqual(e["status"], "waiting")
            self.assertIn("0.66% under $0.0074900", out)
            _, out, e = self.check(md, "2026-11-01 19:47")
            self.assertEqual(e["status"], "triggered")
            self.assertEqual(E.fp(e["trigger"]["price"]), "0.0075741")
            self.assertEqual(e["trigger"]["vol_x"], 2.89)
            _, out, e = self.check(md, "2026-11-01 19:55")
            self.assertTrue(e["stale"])
            self.assertIn("STALE", out)

    def test_failed_and_expired(self):
        with MemeDir() as md:
            code, out, e = self.check(md, "2026-11-01 20:30", "20:00")
            self.assertEqual(e["status"], "failed")
            self.assertIn("the 20:15 bar closed at $0.0072442, under the range low $0.0072509", out)
            self.assertEqual(code, 1)
            _, out, e = self.check(md, "2026-11-01 20:00", "18:00", ["--vol-x", "50"])
            self.assertIn(e["status"], ("expired", "failed"))

    def test_level_setup(self):
        with MemeDir() as md:
            _, out, e = self.check(md, "2026-11-01 19:50", "19:40", ["--setup", "level", "--level", "0.0076"])
            self.assertEqual(e["status"], "waiting")
            self.assertIn("0.88% under $0.0076000", out)

    def test_only_completed_bars_count(self):
        bars = [{"t": 600 + 60 * i, "o": 1, "h": 1.01, "l": 0.99, "c": 1, "v": 10} for i in range(15)]
        bars.append({"t": 1500, "o": 1, "h": 1.2, "l": 1, "c": 1.1, "v": 100})
        self.assertEqual(E.evaluate(bars, 1559, 600)["status"], "waiting")
        self.assertEqual(E.evaluate(bars, 1560, 600)["status"], "triggered")

    def test_a_ticker_that_is_not_known_is_refused(self):
        with MemeDir():
            code, out = run(E, ["check", "GATO", "--offline", HISTORY])
            self.assertEqual(code, 1)
            self.assertIn("give the contract address", out)


if __name__ == "__main__":
    unittest.main()
