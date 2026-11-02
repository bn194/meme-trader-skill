import unittest

import _reel
from _load import GATO, MemeDir, load, run

R = load("meme-risk", "check")
K = load("meme-broker", "ticket")


def reel(md, replays="10000"):
    _reel.all_steps(replays)
    return md.read("orders.json")[0]


class Risk(unittest.TestCase):
    def test_the_reel_is_blocked_by_the_edge(self):
        with MemeDir() as md:
            reel(md)
            code, out = run(R, ["--now", _reel.NOW])
            self.assertEqual(code, 1)
            self.assertIn("max loss $2.49 incl. $1.08 costs (limit $3.30), reward:risk 1.26 after costs", out)
            self.assertIn("time machine: -0.55R after costs, history -0.42R over 32 trades", out)
            self.assertIn("- edge: the time machine's average R after costs is -0.55", out)
            v = md.read("state/risk.json")["verdicts"][-1]
            self.assertEqual(v["verdict"], "BLOCK")
            self.assertEqual(len(v["reasons"]), 1)

    def test_without_require_edge_it_passes(self):
        with MemeDir(require_edge=False) as md:
            o = reel(md, "500")
            code, out = run(R, ["--now", _reel.NOW])
            self.assertEqual(code, 0)
            self.assertIn("1 passed, 0 blocked", out)
            self.assertIn("Cash after the passed orders: $78.00 (paper)", out)
            self.assertEqual(md.read("state/risk.json")["verdicts"][-1]["fp"], K.fingerprint(o))

    def test_one_dollar_more_risk_blocks_the_loss(self):
        with MemeDir(require_edge=False) as md:
            reel(md, "500")
            md.write("config.json", dict(md.read("config.json"), max_loss_per_trade_usd=2.4))
            code, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("loss: $2.49 at the stop", out)

    def test_coin_checks(self):
        with MemeDir(require_edge=False) as md:
            o = reel(md, "500")
            s = md.read("safety.json")
            s[GATO]["verdict"] = "AVOID"
            s[GATO]["reasons"] = ["mint authority is still active"]
            md.write("safety.json", s)
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("safety: the analyst says AVOID", out)
            _, out = run(R, ["--now", "2026-11-01 23:30", "--no-write"])
            self.assertIn("the report is 92 minutes old", out)
            self.assertIn("stale: the plan is 92 minutes old", out)
            md.write("safety.json", {})
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("no /meme-analyst report", out)
            o["plan"]["liquidity_usd"] = 30000
            md.write("orders.json", [o])
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("liquidity: the pool holds $30,000.00", out)

    def test_the_day(self):
        with MemeDir(require_edge=False) as md:
            reel(md, "500")
            t0 = 1793566000
            md.write("state/broker.json", {"events": [
                {"type": "placed", "at": t0 - 3000, "side": "buy", "token": "A" * 44, "max_loss": 3.2, "paper": True},
                {"type": "fill", "at": t0 - 2000, "side": "sell", "token": "A" * 44, "pnl_usd": -3.1},
                {"type": "placed", "at": t0 - 1500, "side": "buy", "token": "B" * 44, "max_loss": 3.2, "paper": True},
                {"type": "fill", "at": t0 - 600, "side": "sell", "token": "B" * 44, "pnl_usd": -3.0}]})
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("pause: 2 losing trades in a row; no new entries until 23:36", out)
            self.assertIn("today before this: 2 of 4 trades, $6.40 of $11.00 daily loss", out)
            md.write("config.json", dict(md.read("config.json"), max_daily_loss_usd=8))
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("daily loss: $6.40 already at risk today + $2.49 here is over your $8.00 daily limit", out)

    def test_the_test_phase_holds_until_the_journal_passes_it(self):
        with MemeDir(require_edge=False, paper=False) as md:
            reel(md, "500")
            o = md.read("orders.json")[0]
            self.assertEqual(o["amount_usd"], "22.00")                    # meme-budget sized it into the cap
            o["amount_usd"] = "33.00"
            md.write("orders.json", [o])
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("test phase: $33.00 is over the $22.00 cap", out)
            ev = []
            for i in range(20):                                          # 20 real trades that lost: FAILED
                ev.append({"type": "placed", "at": 1793000000 + i * 100, "side": "buy", "token": "C" * 44, "max_loss": 2,
                           "tokens": 10, "amount_usd": "22", "paper": False})
                ev.append({"type": "fill", "at": 1793000000 + i * 100 + 50, "side": "sell", "token": "C" * 44, "tokens": 10,
                           "usd": 21, "pnl_usd": -1.0})
            md.write("state/broker.json", {"events": ev})
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertIn("test phase FAILED", out)
            self.assertIn("test phase: $33.00 is over the $22.00 cap", out)
            for e in ev:                                                 # the same 20 trades as winners: PASSED
                if e["type"] == "fill":
                    e.update(usd=25, pnl_usd=3.0)
            md.write("state/broker.json", {"events": ev})
            _, out = run(R, ["--now", _reel.NOW, "--no-write"])
            self.assertNotIn("test phase", out)

    def test_exits_are_never_blocked_by_day_limits(self):
        with MemeDir(require_edge=False, max_trades_per_day=0) as md:
            md.write("portfolio.json", {"cash_usd": 78, "positions": {GATO: {"symbol": "GATO", "tokens": 31679.7, "cost_usd": 33}}})
            md.write("orders.json", [{"chain": "solana", "side": "sell", "token": GATO, "symbol": "GATO",
                                      "tokens": "31679.7", "receive": "SOL", "slippage_bps": 300}])
            code, out = run(R, ["--now", _reel.NOW])
            self.assertEqual(code, 0)
            self.assertIn("PASS  #1 sell 31679.7 GATO, exit", out)

    def test_format_and_asset(self):
        orders = [{"chain": "solana", "side": "buy", "token": "GATO", "amount_usd": 250, "slippage_bps": 9999},
                  {"chain": "ethereum", "side": "buy", "token": GATO, "amount_usd": "50", "slippage_bps": 100},
                  {"chain": "solana", "side": "buy", "token": GATO, "amount_usd": "50", "slippage_bps": 100,
                   "type": "perp", "leverage": 10},
                  {"chain": "solana", "side": "sell", "token": GATO, "tokens": "5", "slippage_bps": 100}]
        res, _, _ = R.check_all(orders, {"require_edge": False}, None, {}, {}, {}, None, 1793566680)
        self.assertTrue(any("contract address" in r for r in res[0]["reasons"]))
        self.assertTrue(any("amount_usd as a positive string" in r for r in res[0]["reasons"]))
        self.assertTrue(any("slippage_bps" in r for r in res[0]["reasons"]))
        self.assertTrue(any(r.startswith("chain:") for r in res[1]["reasons"]))
        self.assertTrue(any(r.startswith("asset:") for r in res[2]["reasons"]))
        self.assertTrue(any(r.startswith("short:") for r in res[3]["reasons"]))

    def test_same_fingerprint_as_the_broker(self):
        o = {"chain": "solana", "side": "buy", "token": GATO, "amount_usd": "250.00", "why": "notes are not part of it"}
        self.assertEqual(R.fingerprint(o), K.fingerprint(o))
        self.assertEqual(R.fingerprint(o), R.fingerprint(dict(o, why="other", plan={"x": 1})))
        self.assertNotEqual(R.fingerprint(o), R.fingerprint(dict(o, amount_usd="251.00")))


if __name__ == "__main__":
    unittest.main()
