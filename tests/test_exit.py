import unittest

from _load import GATO, HISTORY, MemeDir, load, run

E = load("meme-entry", "entry")
X = load("meme-exit", "exit")


def reel_entry(md):
    run(E, ["check", GATO, "--symbol", "GATO", "--from", "21:42", "--now", "2026-11-01 21:58", "--offline", HISTORY])
    return md.read("entry.json")


class Exit(unittest.TestCase):
    def test_the_reel_plan(self):
        with MemeDir() as md:
            reel_entry(md)
            code, out = run(X, ["plan", "--write", "--now", "2026-11-01 21:58"])
            self.assertEqual(code, 0)
            p = md.read("plan.json")
            self.assertEqual(p["stop"], 0.007456)
            self.assertEqual(p["target"], 0.0087878)
            self.assertEqual(p["target_r"], 3.0)
            self.assertEqual(p["risk_pct"], 4.275)
            self.assertEqual(p["costs"]["round_trip_pct"], 3.3)
            self.assertEqual(p["net"]["reward_risk"], 1.26)
            self.assertEqual(p["net"]["costs_in_r"], 0.77)
            self.assertEqual(p["exits"], {})
            self.assertEqual(p["flat_by"], 1793566680 + 3600)
            self.assertIn("Phantom fee 0.85% + slippage 0.30% + pool 0.50%", out)
            self.assertIn("-7.58% at the stop, +9.52% at the target: reward:risk 1.26", out)
            self.assertIn("Flat by       22:58 Europe/Berlin", out)

    def test_a_2r_target_warns_after_costs(self):
        with MemeDir() as md:
            reel_entry(md)
            code, out = run(X, ["plan", "--target", "2R", "--now", "2026-11-01 21:58"])
            self.assertEqual(code, 0)
            self.assertIn("reward:risk 0.69", out)
            self.assertIn("WARNING", out)

    def test_a_stop_inside_the_costs_is_refused(self):
        with MemeDir() as md:
            reel_entry(md)
            code, out = run(X, ["plan", "--stop", "range-mid", "--now", "2026-11-01 21:58"])
            self.assertEqual(code, 1)
            self.assertIn("2.58% under the entry, less than the 3.30% a round trip costs", out)

    def test_refusals(self):
        entry = {"address": GATO, "trigger": {"price": 1.0, "time": 1000, "bar_time": 940},
                 "range": {"high": 0.99, "low": 0.9, "minutes": 15}}
        cfg = dict(X.DEFAULTS)
        with self.assertRaises(X.PlanError):
            X.make_plan(entry, cfg, "price:1.01")
        with self.assertRaises(X.PlanError):
            X.make_plan(entry, cfg, "pct:10", "price:0.99")
        with self.assertRaises(X.PlanError):
            X.make_plan(dict(entry, range=None), cfg, "range-low")
        p = X.make_plan(entry, cfg, "pct:10", "pct:30")
        self.assertEqual(p["stop"], 0.9)
        self.assertEqual(p["target"], 1.3)

    def test_rounding_is_away_from_the_entry(self):
        self.assertEqual(X.sig(0.0074560041, 5, X.ROUND_FLOOR), 0.007456)
        self.assertEqual(X.sig(0.00737835, 5, X.ROUND_FLOOR), 0.0073783)
        self.assertEqual(X.sig(0.00878775, 5), 0.0087878)
        self.assertEqual(X.fp(0.00033295), "0.00033295")

    def test_fomo_costs_less_on_a_big_order_but_has_a_minimum(self):
        with MemeDir(venue="fomo") as md:
            reel_entry(md)
            run(X, ["plan", "--write", "--now", "2026-11-01 21:58"])
            p = md.read("plan.json")
            self.assertEqual(p["costs"]["round_trip_pct"], 2.6)
            self.assertEqual(p["costs"]["fee_min_usd"], 0.95)

    def test_partial_and_trailing_exits_go_into_the_plan(self):
        with MemeDir() as md:
            reel_entry(md)
            code, out = run(X, ["plan", "--write", "--now", "2026-11-01 21:58", "--scale", "1.5R:50", "--trail", "1R"])
            self.assertEqual(code, 0)
            self.assertEqual(md.read("plan.json")["exits"], {"scale_r": 1.5, "scale_pct": 50.0, "trail_r": 1.0})
            self.assertIn("Partial       sell 50% at 1.5R ($0.0082884), then move the stop to the entry", out)
            code, out = run(X, ["plan", "--now", "2026-11-01 21:58", "--scale", "1.5R:150"])
            self.assertEqual(code, 1)

    def test_atr_stop(self):
        with MemeDir() as md:
            reel_entry(md)
            code, out = run(X, ["plan", "--stop", "atr:3", "--now", "2026-11-01 21:58", "--offline", HISTORY])
            self.assertEqual(code, 0)
            self.assertIn("3 x the 14-bar ATR", out)


if __name__ == "__main__":
    unittest.main()
