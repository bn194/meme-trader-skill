import json
import os
import unittest

from _load import FIX, GATO, MemeDir, load, run

S = load("meme-scanner", "scan")
PAIRS = os.path.join(FIX, "meme-scanner", "pairs-2026-11-01-2155.json.gz")
RANGE = os.path.join(FIX, "meme-scanner", "range-2026-11-01-2158.json.gz")


def bar(t, o, h, l, c, v):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


class Pairs(unittest.TestCase):
    def test_the_reel_pairs_scan(self):
        with MemeDir() as md:
            code, out = run(S, ["pairs", "--offline", PAIRS])
            self.assertEqual(code, 0)
            wl = md.read("watchlist.json")
            st = wl["stats"]
            self.assertEqual((st["universe"], st["with_pool"], st["curve"], st["liquid"], st["washed"], st["hits"]),
                             (104, 62, 42, 19, 1, 4))
            self.assertEqual([h["symbol"] for h in wl["hits"]], ["Anakin", "ANSEM", "ANSEM", "HELL"])
            self.assertEqual(wl["hits"][0]["setups"], ["volume_surge"])
            self.assertEqual(wl["hits"][1]["setups"], ["dip"])
            self.assertIn("4 matched a setup", out)
            self.assertIn("Sun 2026-11-01 21:55 (Europe/Berlin)", out)

    def test_setups_on_pool_stats(self):
        r = {"change": {"m5": 1.0, "h1": 8.0, "h6": 3.0, "h24": 30.0}, "volume": {"m5": 0, "h1": 60000, "h6": 120000, "h24": 0},
             "txns": {"h1": [300, 200]}, "age_hours": 10}
        self.assertEqual(S.tag_setups(r), ["momentum", "volume_surge", "new_pool"])
        r["txns"]["h1"] = [200, 300]
        self.assertNotIn("momentum", S.tag_setups(r))
        dip = {"change": {"m5": 0.5, "h1": -6.0, "h6": 1.0, "h24": 40.0}, "volume": {"m5": 0, "h1": 1, "h6": 600, "h24": 0},
               "txns": {"h1": [1, 1]}, "age_hours": 100}
        self.assertEqual(S.tag_setups(dip), ["dip"])

    def test_the_bundle_replays_without_the_network(self):
        net = S.Net(PAIRS)
        self.assertIsNotNone(net.get("https://api.dexscreener.com/token-boosts/top/v1"))
        with self.assertRaises(S.ScanError):
            net.get("https://api.dexscreener.com/not-in-the-bundle")


class Range(unittest.TestCase):
    def test_the_reel_range_scan_finds_gato(self):
        with MemeDir() as md:
            code, out = run(S, ["range", "--offline", RANGE, "--no-gecko"])
            self.assertEqual(code, 0)
            wl = md.read("watchlist.json")
            self.assertEqual(wl["checked"], 7)
            self.assertEqual(len(wl["hits"]), 1)
            h = wl["hits"][0]
            self.assertEqual(h["address"], GATO)
            self.assertEqual(h["range_start"], 1793565720)   # 21:42 Berlin
            self.assertEqual(h["bar_time"], 1793566620)      # the 21:57 bar
            self.assertEqual(S.fp(h["close"]), "0.0077889")
            self.assertEqual(S.fp(h["range_high"]), "0.0077195")
            self.assertEqual(S.fp(h["range_low"]), "0.0074560")
            self.assertEqual(h["over_pct"], 0.9)
            self.assertEqual(h["vol_x"], 2.7)
            self.assertIn("21:58  GATO", out)

    def test_breakout_rules(self):
        t0 = 1793565720
        bars = [bar(t0 + 60 * i, 1.0, 1.01, 0.99, 1.0, 100) for i in range(15)]
        bars.append(bar(t0 + 900, 1.0, 1.03, 1.0, 1.02, 200))            # closes over 1.01 on 2x
        self.assertIsNotNone(S.find_breakout(bars, t0 + 960))
        self.assertIsNone(S.find_breakout(bars, t0 + 959))                 # the bar is not complete yet
        bars[-1]["v"] = 120                                                # 1.2x: not enough volume
        self.assertIsNone(S.find_breakout(bars, t0 + 960))
        self.assertIsNotNone(S.find_breakout(bars, t0 + 960, vol_x=0))
        bars[-1].update(v=200, c=1.009, h=1.05)                            # a wick over the high does not count
        self.assertIsNone(S.find_breakout(bars, t0 + 960))
        gap = [b for b in bars if b["t"] != t0 + 300]                      # a minute with no trades
        gap[-1].update(c=1.02)
        self.assertIsNone(S.find_breakout(gap, t0 + 960))

    def test_both_bar_formats(self):
        with open(os.path.join(FIX, "meme-entry", "gecko-AAPLCAT-1m.json")) as fh:
            gecko = S.parse_bars(json.load(fh))
        self.assertGreater(len(gecko), 900)
        self.assertLess(gecko[0]["t"], gecko[-1]["t"])                    # sorted oldest first
        jup = S.parse_bars({"candles": [{"time": 60, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 9}]})
        self.assertEqual(jup[0]["c"], 1.5)

class Edge(unittest.TestCase):
    def test_edge_sorts_and_marks_losers(self):
        with MemeDir():
            code, out = run(S, ["range", "--offline", RANGE, "--no-gecko", "--edge", "--edge-offline",
                                os.path.join(FIX, "meme-timemachine", "eleven-coins-1m-2026-11-01.json.gz")])
            self.assertIn("edge: -0.89R after costs over 8 past breakouts (0.7 days)  LOST MONEY", out)
            self.assertIn("Sorted by edge", out)

    def test_round_trip_follows_the_venue(self):
        self.assertAlmostEqual(S.round_trip_pct({"venue": "fomo", "venues": {"fomo": {"fee_pct": 0.5}}}), 2.6)
        self.assertAlmostEqual(S.round_trip_pct({"venue": "phantom", "venues": {"phantom": {"fee_pct": 0.85}}}), 3.3)


if __name__ == "__main__":
    unittest.main()
