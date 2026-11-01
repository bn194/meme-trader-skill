import json
import os
import unittest

import _reel
from _load import FIX, GATO, MemeDir, load, run

L = load("meme-alerts", "alerts")
DEX = os.path.join(FIX, "meme-analyst", "dex-GATO-2158.json")
FOLLOW = os.path.join(FIX, "meme-alerts", "GATO-follow-2026-11-01.json")


def q(price, liq=278503.92):
    return {GATO: {"price": price, "liquidity_usd": liq, "symbol": "GATO"}}


class Alerts(unittest.TestCase):
    def test_from_plan_adds_four(self):
        with MemeDir() as md:
            _reel.plan()
            code, out = run(L, ["add", "--from-plan", "--offline", DEX, "--now", _reel.NOW])
            self.assertEqual(code, 0)
            self.assertIn("Added: stop GATO at or below $0.0074560", out)
            self.assertIn("Added: target GATO at or above $0.0087878", out)
            self.assertIn("Added: time stop GATO at 22:58", out)
            self.assertIn("Added: rug alarm GATO: pool liquidity down 30% from $278,504", out)
            kinds = [a["kind"] for a in md.read("alerts.json")["alerts"]]
            self.assertEqual(kinds, ["stop", "target", "time", "liq_drop"])
            self.assertAlmostEqual(md.read("prices.json")[GATO]["liquidity_usd"], 278503.92)

    def test_each_rings_once(self):
        al = [{"token": GATO, "symbol": "GATO", "kind": "stop", "level": 0.007456},
              {"token": GATO, "symbol": "GATO", "kind": "target", "level": 0.0087878},
              {"token": GATO, "symbol": "GATO", "kind": "time", "at": 1793570280},
              {"token": GATO, "symbol": "GATO", "kind": "liq_drop", "pct": 30, "base": 278503.92},
              {"token": GATO, "symbol": "GATO", "kind": "pct", "pct": 10, "base": 0.0077889}]
        tz = "Europe/Berlin"
        self.assertEqual(L.evaluate(al, q(0.0078), 1793567000, tz), [])
        msgs = L.evaluate(al, q(0.00745), 1793567000, tz)
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("STOP hit: GATO $0.0074500 <= $0.0074560"))
        self.assertEqual(L.evaluate(al, q(0.0074), 1793567060, tz), [])          # never twice
        msgs = L.evaluate(al, q(0.0086, 150000), 1793567120, tz)
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any(m.startswith("RUG ALARM: GATO pool liquidity $150,000, down 46%") for m in msgs))
        self.assertTrue(any(m.startswith("MOVE: GATO +10.4%") for m in msgs))
        msgs = L.evaluate(al, q(0.0089), 1793570280, tz)
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any(m.startswith("TARGET hit") for m in msgs))
        self.assertTrue(any(m.startswith("TIME STOP 22:58") for m in msgs))

    def test_the_reel_hour(self):
        """Replay the alerts over the real DexScreener snapshots taken every two minutes after the entry."""
        with open(FOLLOW) as fh:
            snaps = json.load(fh)
        al = [{"token": GATO, "symbol": "GATO", "kind": "stop", "level": 0.007456},
              {"token": GATO, "symbol": "GATO", "kind": "target", "level": 0.0087878},
              {"token": GATO, "symbol": "GATO", "kind": "time", "at": 1793570280},
              {"token": GATO, "symbol": "GATO", "kind": "liq_drop", "pct": 30, "base": 278503.92}]
        rang = []
        for s in snaps:
            for m in L.evaluate(al, L.quotes_from_pairs(s["pairs"], s["ts"]), s["ts"], "Europe/Berlin"):
                rang.append((s["ts"], m))
        self.assertEqual(len(rang), 1)                                   # neither stop nor target, only the clock
        self.assertTrue(rang[0][1].startswith("TIME STOP 22:58"))
        self.assertGreaterEqual(rang[0][0], 1793570280)

    def test_quote_writes_prices(self):
        with MemeDir() as md:
            code, out = run(L, ["quote", GATO, "--offline", DEX, "--write", "--now", _reel.NOW])
            self.assertIn("GATO $0.0077880 at 21:58, pool liquidity $278,504", out)
            p = md.read("prices.json")[GATO]
            self.assertEqual(p["ts"], 1793566680)
            self.assertEqual(p["pool_created_at"], 1787660841)

    def test_clear(self):
        with MemeDir() as md:
            run(L, ["add", "--token", GATO, "--symbol", "GATO", "--above", "0.009", "--at", "23:30", "--now", _reel.NOW])
            self.assertEqual(len(md.read("alerts.json")["alerts"]), 2)
            run(L, ["clear", "--token", "GATO"])
            self.assertEqual(md.read("alerts.json")["alerts"], [])


if __name__ == "__main__":
    unittest.main()
