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
            self.assertEqual(o["amount_usd"], "33.00")
            self.assertEqual(o["amount_in"], "0.3503")
            self.assertEqual(o["pay_with"], "SOL")
            self.assertEqual(o["slippage_bps"], 150)
            self.assertEqual(o["jupiter_quote"], {"inputMint": B.SOL, "outputMint": GATO, "amount": "350309918",
                                                  "slippageBps": 150})
            self.assertEqual(o["plan"]["max_loss"], 2.49)
            self.assertEqual(o["plan"]["gain_at_target"], 3.15)
            self.assertEqual(o["plan"]["reward_risk_net"], 1.26)
            self.assertEqual(o["plan"]["costs_usd"], 1.08)
            self.assertEqual(o["plan"]["venues"], [["jupiter", 0.6, 1.81], ["phantom", 1.08, 3.28], ["fomo", 2.43, 7.37]])
            self.assertIn("position cap  $33.00     30% of $111.00   <- decides it", out)
            self.assertIn("max loss      $43.00", out)
            self.assertIn("Phantom fees $0.55, slippage $0.19, pool $0.34 (measured round trip 1.03%)", out)
            self.assertIn("Same trade at each app: Jupiter $0.60 (1.81%), Phantom $1.08 (3.28%), Fomo $2.43 (7.37%). "
                          "Cheapest: Jupiter.", out)

    def test_the_fee_minimum_bites_on_small_buys(self):
        cfg = dict(B.DEFAULTS, fee_pct=0.5, fee_min_usd=0.95)
        small = B.trade_costs(20, 4.0, cfg, 278503.92)
        big = B.trade_costs(250, 4.0, cfg, 278503.92)
        self.assertAlmostEqual(small["fees"], 1.90)                          # $0.95 each way
        self.assertGreater(small["total_pct"], big["total_pct"] + 5)

    def test_euros(self):
        with MemeDir() as md:
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget(["--eur-usd", "1.1132"])
            self.assertIn("In euros (1 EUR = 1.1132 USD): buy 29.64 EUR, -2.24 EUR at the stop, +2.83 EUR at the target.", out)

    def test_the_test_phase_caps_live_orders(self):
        with MemeDir(paper=False) as md:
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertIn("test phase    $22.00     real trade 1 of 20 in the test phase   <- decides it", out)
            self.assertEqual(md.read("orders.json")[0]["amount_usd"], "22.00")
        with MemeDir(paper=True) as md:
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertNotIn("test phase", out)
        with MemeDir(paper=False) as md:                                  # 20 real trades that lost: the cap stays
            ev = []
            for i in range(20):
                ev.append({"type": "placed", "at": 1793000000 + i * 100, "side": "buy", "token": "C" * 44, "max_loss": 2,
                           "tokens": 10, "amount_usd": "22", "paper": False})
                ev.append({"type": "fill", "at": 1793000000 + i * 100 + 50, "side": "sell", "token": "C" * 44,
                           "tokens": 10, "usd": 21, "pnl_usd": -1.0})
            md.write("state/broker.json", {"events": ev})
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertIn("test phase    $22.00     test phase FAILED: the cap stays   <- decides it", out)
            for e in ev:
                if e["type"] == "fill":
                    e.update(usd=25, pnl_usd=3.0)
            md.write("state/broker.json", {"events": ev})
            code, out = _reel.budget()
            self.assertNotIn("test phase", out)
            self.assertEqual(md.read("orders.json")[0]["amount_usd"], "33.00")

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
        with MemeDir(max_loss_per_trade_usd=0.05) as md:
            _reel.analyst()
            _reel.plan()
            code, out = _reel.budget()
            self.assertEqual(code, 1)
            self.assertIn("No order", out)
        with MemeDir() as md:
            _reel.analyst()
            _reel.plan()
            code, out = run(B, ["--now", "2026-11-01 22:20", "--sol-price", "94.2", "--eur-usd", "1.1"])
            self.assertIn("minutes old", out)
            code, out = run(B, ["--now", _reel.NOW, "--sol-price", "94.2", "--eur-usd", "1.1", "--price", "0.0088"])
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
            run(B, ["--now", _reel.NOW, "--sol-price", "94.2", "--eur-usd", "1.1", "--price", "0.00785", "--write"])
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
