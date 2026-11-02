import os
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
            self.assertAlmostEqual(mc["avg_r_net"], -0.551, places=3)
            self.assertEqual(r["pool"]["bars"], 4312)
            self.assertEqual((h["ranges"], h["fired"], h["target"], h["stop"], h["neither"], h["refused"]), (126, 32, 3, 8, 21, 5))
            self.assertAlmostEqual(h["avg_r_net"], -0.419, places=3)
            self.assertTrue(r["verdict"].startswith("Strongly toward the stop"))
            self.assertIn("break-even after costs is 44.3 %", r["verdict"])
            self.assertIn("Costs take 0.77R a trade (3.30 % round trip on a 4.28 % risk).", out)
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

class TimeMachine2(unittest.TestCase):
    ELEVEN = os.path.join(_reel.FIX, "meme-timemachine", "eleven-coins-1m-2026-11-01.json.gz")

    def test_version_one_numbers_with_the_old_costs(self):
        with MemeDir(venue="fomo") as md:
            _reel.plan()
            _reel.timemachine()
            r = md.read("timemachine.json")
            mc, h = r["mc"], r["history"]
            self.assertEqual((mc["target"], mc["stop"], mc["neither"]), (1212, 4415, 4373))
            self.assertAlmostEqual(mc["avg_r_net"], -0.387, places=3)
            self.assertEqual((h["ranges"], h["fired"], h["target"], h["stop"], h["neither"]), (120, 35, 3, 11, 21))

    def test_the_exit_model(self):
        ex = T.Exit(1.0, 0.9, 1.3, {"scale_r": 1.5, "scale_pct": 50})
        self.assertFalse(ex.bar(1.0, 1.16, 1.0, 1.15))                   # half sold at 1.5R, stop to the entry
        self.assertEqual((ex.remaining, ex.cur_stop), (0.5, 1.0))
        self.assertTrue(ex.bar(1.1, 1.1, 0.99, 1.0))                      # the rest stops out at the entry
        self.assertEqual(ex.outcome, "managed")
        self.assertAlmostEqual(ex.r, 0.75)
        ex = T.Exit(1.0, 0.9, 1.3, {"trail_r": 1.0})
        ex.bar(1.0, 1.25, 1.0, 1.2)
        self.assertAlmostEqual(ex.cur_stop, 1.15)
        ex.bar(1.2, 1.2, 1.1, 1.12)
        self.assertEqual(ex.outcome, "managed")
        self.assertAlmostEqual(ex.r, 1.5)
        ex = T.Exit(1.0, 0.9, 1.3, {})
        ex.bar(1.0, 1.31, 0.95, 1.2)
        self.assertEqual((ex.outcome, round(ex.r, 6)), ("target", 3.0))
        ex = T.Exit(1.0, 0.9, 1.3, {})
        ex.bar(1.0, 1.31, 0.89, 1.2)                                       # both in one bar: the stop
        self.assertEqual((ex.outcome, ex.r), ("stop", -1.0))

    def test_compare_checks_the_unseen_third(self):
        with MemeDir():
            _reel.plan()
            code, out = run(T, ["compare", "--offline", _reel.HISTORY])
            self.assertEqual(code, 0)
            self.assertIn("180 combinations", out)
            self.assertIn("pct:8      3R     60    trail 1R       -0.144 ( 24 tr)  -0.531 ( 12 tr)", out)
            self.assertIn("The best pick LOST on the unseen third", out)
            self.assertIn("0 of the top 8 were positive on the unseen third.", out)

    def test_multi_and_ruin(self):
        with MemeDir() as md:
            _reel.plan()
            code, out = run(T, ["multi", "--offline", self.ELEVEN])
            self.assertEqual(code, 0)
            self.assertIn("All together: 52 trades, -0.599 a trade after costs (first two thirds -0.655, last third -0.500); "
                          "3 of 11 coins positive.", out)
            self.assertEqual(md.read("multi.json")["summary"]["coins"], 11)
            code, out = run(T, ["ruin", "--from-multi"])
            self.assertIn("Your account: $111.00, losing up to $3.30 a trade at the stop.", out)
            self.assertIn("chance the account falls to half or less on the way: 96.1 %", out)
            self.assertIn("where it ends: median $11.38", out)

    def test_ruin_math(self):
        r = T.ruin([1.0, -1.0], 100.0, 10.0, trades=4, runs=2000, seed=1)
        self.assertGreater(r["p_up"], 20)
        self.assertEqual(r["p_floor"], 0.0)                              # 4 trades of $10 cannot halve $100
        r = T.ruin([-1.0], 100.0, 10.0, trades=6, runs=10)
        self.assertEqual((r["p_floor"], r["median"]), (100.0, 40.0))

    def test_partial_exits_in_the_replay(self):
        with MemeDir():
            _reel.plan()
            code, out = run(T, ["run", "--offline", _reel.HISTORY, "--replays", "2000", "--scale", "1.5R:50"])
            self.assertIn("exits: sell 50% at 1.5R, then the stop to the entry", out)
            self.assertIn("managed", out)
            self.assertIn("after costs", out)


if __name__ == "__main__":
    unittest.main()
