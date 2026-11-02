import unittest

from _load import GATO, MemeDir, load, run

J = load("meme-journal", "journal")


def trade(i, pnl, paper=False, token=None, max_loss=2.0, reason="stop"):
    tok = token or ("T%043d" % i)
    t0 = 1793000000 + i * 1000
    return [{"type": "placed", "at": t0, "side": "buy", "token": tok, "symbol": "C%d" % i, "amount_usd": "22.00",
             "spent_usd": 22.0, "tokens": 100.0, "max_loss": max_loss, "paper": paper, "setup": "range", "venue": "phantom"},
            {"type": "fill", "at": t0 + 600, "side": "sell", "token": tok, "tokens": 100.0, "usd": 22.0 + pnl,
             "pnl_usd": pnl, "reason": reason}]


class Journal(unittest.TestCase):
    def test_trades_from_the_broker_log(self):
        ev = trade(1, -2.0) + trade(2, 3.0, reason="target") + [
            {"type": "placed", "at": 1793009000, "side": "buy", "token": GATO, "tokens": 50.0, "spent_usd": 22.0,
             "max_loss": 2.0, "paper": False}]
        done, still_open = J.trades_from_log(ev)
        self.assertEqual(len(done), 2)
        self.assertEqual(len(still_open), 1)
        st = J.stats([J.enrich(t) for t in done])
        self.assertEqual((st["trades"], st["wins"], st["losses"]), (2, 1, 1))
        self.assertAlmostEqual(st["total_usd"], 1.0)
        self.assertAlmostEqual(st["expectancy_r"], 0.25)
        self.assertAlmostEqual(st["profit_factor"], 1.5)
        self.assertAlmostEqual(st["max_drawdown"], 2.0)

    def test_partial_sells_close_a_trade_only_when_all_is_sold(self):
        ev = trade(1, 0)[:1] + [
            {"type": "fill", "at": 1793001300, "side": "sell", "token": "T%043d" % 1, "tokens": 50.0, "usd": 13.0, "pnl_usd": 2.0},
            {"type": "fill", "at": 1793001400, "side": "sell", "token": "T%043d" % 1, "tokens": 50.0, "usd": 10.0, "pnl_usd": -1.0,
             "reason": "time"}]
        done, still_open = J.trades_from_log(ev)
        self.assertEqual(len(done), 1)
        self.assertAlmostEqual(done[0]["pnl_usd"], 1.0)
        self.assertEqual(done[0]["reason"], "time")

    def test_the_test_phase(self):
        self.assertEqual(J.testphase([], dict(J.DEFAULTS, paper=True))[0], "off")   # paper never counts
        cfg = dict(J.DEFAULTS, paper=False)
        losers = [J.enrich(t) for i in range(20) for t in J.trades_from_log(trade(i, -1.0))[0]]
        state, text = J.testphase(losers[:7], cfg)
        self.assertEqual(state, "active")
        self.assertIn("7 of 20 real trades", text)
        state, text = J.testphase(losers, cfg)
        self.assertEqual(state, "failed")
        self.assertIn("test phase FAILED", text)
        mixed = [J.enrich(t) for i in range(20) for t in J.trades_from_log(trade(i, 3.0 if i % 2 else -1.0))[0]]
        state, text = J.testphase(mixed, cfg)
        self.assertEqual(state, "passed")
        self.assertIn("20 real trades: $20.00 in total, 50 % winners, expectancy +0.50R, profit factor 3.00", text)

    def test_cli_stats_paper_apart_and_manual_trades(self):
        with MemeDir(paper=False) as md:
            md.write("state/broker.json", {"events": trade(1, -2.0) + trade(2, 3.0, reason="target") + trade(3, 5.0, paper=True)})
            code, out = run(J, [])
            self.assertEqual(code, 0)
            self.assertIn("2 closed (0 open): 1 winners, 1 losers, 50 % win rate", out)
            self.assertIn("test phase: 2 of 20 real trades closed", out)
            code, out = run(J, ["--paper"])
            self.assertIn("1 closed (0 open): 1 winners", out)
            code, out = run(J, ["add", "--symbol", "WIF", "--buy-usd", "20", "--sell-usd", "23.5", "--opened", "2026-11-02 14:05",
                                "--closed", "2026-11-02 14:40", "--max-loss", "2", "--reason", "target"])
            self.assertIn("Added WIF: $20.00 in, $23.50 out, $3.50.", out)
            code, out = run(J, ["trades"])
            self.assertIn("WIF", out)
            self.assertIn("+1.75R", out)
            code, out = run(J, ["add", "--symbol", "X", "--buy-usd", "1", "--sell-usd", "1", "--opened", "2026-11-02 15:00",
                                "--closed", "2026-11-02 14:00"])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
