import json
import os
import unittest

import _reel
from _load import FIX, GATO, MemeDir, load, run

B = _reel.B


class Budget(unittest.TestCase):
    def test_the_reel_size(self):
        with MemeDir() as md:
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertEqual(code, 0)
            o = md.read("orders.json")[0]
            self.assertEqual(o["amount_usd"], "250.00")
            self.assertEqual(o["amount_in"], "2.6539")
            self.assertEqual(o["pay_with"], "SOL")
            self.assertEqual(o["slippage_bps"], 150)
            self.assertEqual(o["jupiter_quote"], {"inputMint": B.SOL, "outputMint": GATO, "amount": "2653863016",
                                                  "slippageBps": 150})
            self.assertEqual(o["plan"]["max_loss"], 17.62)
            self.assertEqual(o["plan"]["gain_at_target"], 25.12)
            self.assertEqual(o["plan"]["reward_risk_net"], 1.43)
            self.assertEqual(o["plan"]["costs_usd"], 6.94)
            self.assertIn("position cap  $250.00    25% of $1,000.00   <- decides it", out)
            self.assertIn("max loss      $282.00", out)
            self.assertIn("Fomo fees $2.45, slippage $1.47, pool $3.02 (measured round trip 1.21%)", out)

    def test_the_fee_minimum_bites_on_small_buys(self):
        cfg = dict(B.DEFAULTS)
        small = B.trade_costs(20, 4.0, cfg, 278503.92)
        big = B.trade_costs(250, 4.0, cfg, 278503.92)
        self.assertAlmostEqual(small["fees"], 1.90)                          # $0.95 each way
        self.assertGreater(small["total_pct"], big["total_pct"] + 5)

    def test_the_max_loss_decides_on_a_big_account(self):
        with MemeDir(budget_usd=10000, max_order_usd=5000, max_position_pct=50) as md:
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertEqual(code, 0)
            self.assertIn("<- decides it", [l for l in out.splitlines() if l.strip().startswith("max loss")][0])
            o = md.read("orders.json")[0]
            self.assertLessEqual(o["plan"]["max_loss"], 20.0)

    def test_refusals(self):
        with MemeDir(max_loss_per_trade_usd=0.5) as md:
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertEqual(code, 1)
            self.assertIn("No order", out)
        with MemeDir() as md:
            _reel.analyst()
            _reel.plan()
            code, out = run(B, ["--now", "2026-11-01 22:20", "--sol-price", "94.2"])
            self.assertIn("minutes old", out)
            code, out = run(B, ["--now", _reel.NOW, "--sol-price", "94.2", "--price", "0.0088"])
            self.assertIn("already at or over the target", out)
        with MemeDir(blocked=["GATO"]):
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertIn("blocked", out)

    def test_a_fresh_higher_price_shrinks_nothing_but_raises_the_risk(self):
        with MemeDir() as md:
            _reel.analyst()
            _reel.plan()
            run(B, ["--now", _reel.NOW, "--sol-price", "94.2", "--price", "0.00785", "--write"])
            o = md.read("orders.json")[0]
            self.assertEqual(o["plan"]["entry"], 0.00785)
            self.assertGreater(o["plan"]["risk_pct"], 4.275)

    def test_the_jupiter_round_trip_from_the_saved_quotes(self):
        d = os.path.join(FIX, "meme-broker")
        with open(os.path.join(d, "quote-buy-2700000000.json")) as fh:
            buy = json.load(fh)
        with open(os.path.join(d, "quote-sell-2700000000.json")) as fh:
            sell = json.load(fh)
        self.assertEqual(sell["inAmount"], buy["outAmount"])
        rt = (1 - int(sell["outAmount"]) / 2700000000.0) * 100
        self.assertAlmostEqual(rt, 1.213, places=3)


if __name__ == "__main__":
    unittest.main()
