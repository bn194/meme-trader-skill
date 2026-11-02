import unittest

import _reel
from _load import GATO, MemeDir, load, run

R = load("meme-risk", "check")
K = load("meme-broker", "ticket")


def ready(md):
    _reel.all_steps("500")
    run(R, ["--now", _reel.NOW])
    return md.read("orders.json")[0]


class Yes(unittest.TestCase):
    def setUp(self):
        self.o = {"side": "buy", "symbol": "GATO", "token": GATO, "amount_usd": "33.00", "amount_in": "0.3503",
                  "plan": {"max_loss": 2.49, "stop": 0.007456, "target": 0.0087878}}

    def ok(self, reply, others=("GATO", "HELL")):
        return K.parse_yes(reply, self.o, others)[0]

    def test_explicit_yes_only(self):
        for good in ("yes", "Yes", "y", "ja", "Ja!", "yes, buy 33 of GATO", "ja, kauf GATO für 33", "yes 0.3503 SOL"):
            self.assertTrue(self.ok(good), good)
        for bad in ("ok", "sure", "mach", "go", "do it", "yes to all", "ja, alle", "ja, aber nur 100",
                    "yes if it dips", "yes?", "yes buy 100", "yes, buy HELL", "nein", "", "ja vielleicht", "ja 250"):
            self.assertFalse(self.ok(bad), bad)


class Broker(unittest.TestCase):
    def test_blocked_orders_are_not_shown_for_a_yes(self):
        with MemeDir() as md:
            ready(md)
            code, out = run(K, ["show", "--now", _reel.NOW])
            self.assertIn("BLOCKED by meme-risk: edge:", out)
            self.assertNotIn("Reply \"yes\"", out)
            code, out = run(K, ["approve", "--index", "1", "--reply", "yes", "--now", _reel.NOW])
            self.assertEqual(code, 1)
            self.assertIn("not READY", out)

    def test_the_paper_trade(self):
        with MemeDir(require_edge=False) as md:
            ready(md)
            _, out = run(K, ["show", "--now", _reel.NOW])
            self.assertIn("ORDER 1 of 1, PAPER (simulated fills, no money), Phantom", out)
            self.assertIn("BUY $33.00 of GATO on Solana, paid with 0.3503 SOL, max slippage 1.5%", out)
            self.assertIn("contract  " + GATO, out)
            self.assertIn("READY: meme-risk PASS, waiting for your yes", out)
            code, out = run(K, ["approve", "--index", "1", "--reply", "ok", "--now", _reel.NOW])
            self.assertIn("Not recorded", out)
            code, out = run(K, ["paper", "--index", "1", "--price", "0.0077889", "--now", _reel.NOW])
            self.assertEqual(code, 1)                                    # no yes, no fill
            code, out = run(K, ["approve", "--index", "1", "--reply", "ja", "--now", _reel.NOW])
            self.assertIn("Recorded your yes for order 1: buy $33.00 of GATO.", out)
            code, out = run(K, ["paper", "--index", "1", "--price", "0.0077889", "--now", _reel.NOW])
            self.assertEqual(code, 0)
            self.assertIn("PAPER fill: bought 4,166.9 GATO at $0.0077889 for $33.00. Cash left $78.00.", out)
            port = md.read("portfolio.json")
            self.assertAlmostEqual(port["positions"][GATO]["tokens"], 4166.9, delta=0.1)
            code, out = run(K, ["approve", "--index", "1", "--reply", "yes", "--now", _reel.NOW])
            self.assertEqual(code, 1)                                    # one yes, one trade
            code, out = run(K, ["fill", "--token", GATO, "--price", "0.007456", "--reason", "stop", "--now", "2026-11-01 22:20"])
            self.assertIn("(stop): loss $2.44", out)
            ev = md.read("state/broker.json")["events"]
            self.assertEqual([e["type"] for e in ev], ["yes", "placed", "fill"])
            self.assertEqual(ev[1]["max_loss"], 2.49)
            self.assertEqual((ev[1]["setup"], ev[1]["venue"], ev[1]["paper"]), ("range", "phantom", True))

    def test_live_tells_the_user_what_to_do(self):
        with MemeDir(require_edge=False, paper=False) as md:
            ready(md)
            _, out = run(K, ["approve", "--index", "1", "--reply", "yes", "--now", _reel.NOW])
            self.assertIn("LIVE: do it yourself in Phantom", out)
            self.assertIn("Search by the contract address, pasted: " + GATO, out)
            code, out = run(K, ["paper", "--index", "1", "--price", "0.0077889", "--now", _reel.NOW])
            self.assertEqual(code, 1)
            code, out = run(K, ["result", "--index", "1", "--status", "placed", "--tokens", "2800",
                                "--price", "0.0078102", "--tx", "5sig", "--now", _reel.NOW])
            self.assertIn("Recorded: bought 2,800.0 GATO", out)

    def test_flatten_goes_back_through_risk(self):
        with MemeDir() as md:
            md.write("portfolio.json", {"cash_usd": 750, "positions": {GATO: {"symbol": "GATO", "tokens": 31679.7, "cost_usd": 250}}})
            code, out = run(K, ["flatten", "--token", GATO, "--now", _reel.NOW])
            o = md.read("orders.json")[0]
            self.assertEqual((o["side"], o["tokens"], o["slippage_bps"]), ("sell", "31679.7", 300))
            _, out = run(K, ["show", "--now", _reel.NOW])
            self.assertIn("NOT READY", out)


if __name__ == "__main__":
    unittest.main()
