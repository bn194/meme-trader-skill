import unittest

import _reel
from _load import MemeDir, run

T = _reel.T


class TimeMachine(unittest.TestCase):
    def test_the_reel_replay(self):
        with MemeDir() as md:
            _reel.plan()
            code, out = _reel.timemachine()
            self.assertEqual(code, 0)
            r = md.read("timemachine.json")
            mc, h = r["mc"], r["history"]
            self.assertEqual((mc["target"], mc["stop"], mc["neither"]), (1212, 4415, 4373))
            self.assertAlmostEqual(mc["avg_r"], 0.221, places=3)
            self.assertAlmostEqual(mc["avg_r_net"], -0.387, places=3)
            self.assertEqual(r["pool"]["bars"], 4312)
            self.assertEqual((h["ranges"], h["fired"], h["target"], h["stop"], h["neither"]), (120, 35, 3, 11, 21))
            self.assertAlmostEqual(h["avg_r_net"], -0.446, places=3)
            self.assertTrue(r["verdict"].startswith("Strongly toward the stop"))
            self.assertIn("break-even after costs is 40.2 %", r["verdict"])
            self.assertIn("Costs take 0.61R a trade (2.60 % round trip on a 4.28 % risk).", out)
            self.assertIn("seed 19", out)

    def test_same_seed_same_numbers(self):
        with MemeDir() as md:
            _reel.plan()
            plan = md.read("plan.json")
            bars = T.parse_bars(T.load(_reel.HISTORY))
            _, ratios = T.pool_of(bars, plan, 3)
            a = T.replay(plan, ratios, 60, 500, seed=7)
            b = T.replay(plan, ratios, 60, 500, seed=7)
            c = T.replay(plan, ratios, 60, 500, seed=8)
            self.assertEqual((a["target"], a["stop"]), (b["target"], b["stop"]))
            self.assertNotEqual((a["target"], a["stop"], a["avg_r"]), (c["target"], c["stop"], c["avg_r"]))

    def test_no_bar_after_the_entry_is_in_the_pool(self):
        with MemeDir() as md:
            _reel.plan()
            plan = md.read("plan.json")
            rows, _ = T.pool_of(T.parse_bars(T.load(_reel.HISTORY)), plan, 3)
            self.assertLessEqual(rows[-1]["t"] + 60, plan["entry_time"])

    def test_the_break_even_counts_the_costs(self):
        plan = {"target_r": 3.0, "risk_pct": 4.0, "costs": {"round_trip_pct": 0.0}}
        mc = {"target": 25, "stop": 75, "neither": 0, "neither_pct": 0.0, "avg_r_net": 0.0, "costs_in_r": 0.0}
        head, _ = T.verdict(plan, mc)
        self.assertTrue(head.startswith("Close to break-even"))              # 25 % at 3R with no costs
        mc["costs_in_r"] = 0.5
        head, below = T.verdict(plan, mc)
        self.assertTrue(head.startswith("Leans toward the stop"))             # with 0.5R of costs it needs 37.5 %
        self.assertIn("Costs take 0.50R", below[-1])

    def test_too_few_bars_is_refused(self):
        with MemeDir() as md:
            _reel.plan()
            code, out = run(T, ["run", "--offline", _reel.HISTORY, "--days", "0.5"])
            self.assertEqual(code, 1)
            self.assertIn("too new or too thin", out)

    def test_chart(self):
        with MemeDir():
            _reel.plan()
            _reel.timemachine("500")
            code, out = run(T, ["chart"])
            self.assertEqual(code, 0)
            self.assertIn("T target", out)


if __name__ == "__main__":
    unittest.main()
