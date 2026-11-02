import os
import unittest

from _load import FIX, MemeDir, load, run

D = load("meme-radar", "radar")
REC = os.path.join(FIX, "meme-radar", "radar-2026-11-01-2309.json.gz")


class Radar(unittest.TestCase):
    def test_the_recorded_six_minutes(self):
        with MemeDir() as md:
            code, out = run(D, ["--offline", REC])
            self.assertEqual(code, 0)
            self.assertIn("Radar, 6 minutes: 58 new coins, 26 flagged at birth, 27 checked after 90s, 0 HOT, 2 to watch, "
                          "1 graduated, 1 bundled launches.", out)
            self.assertIn("BUNDLED   23:10:04  HV4fcGzFKLBV5Q8fKsgvedKHu7K3XpEZc7pgpgxVpump  graduated 0.2 s after launch", out)
            self.assertIn("GRADUATED 23:11:53  Bv9xDKiQzZMwPw7rCzog2dEYuZp3wBGaoK4DacC7pump", out)
            self.assertIn("WATCH 23:13:08  COVERED (GeLShjLo8XV2iR1pvky4h9F2RzFKq4aDKVmKCNTZpump)  93s old: 166 buys vs 81 sells", out)
            st = md.read("radar.json")
            self.assertEqual(st["counts"]["new"], 58)
            self.assertTrue(any(r["status"] == "bundled" for r in st["coins"]))
            code, out = run(D, ["show"])
            self.assertIn("copy race: HYPERHOLD was already launched 9 times", out)

    def test_instant_checks(self):
        cfg = dict(D.DEFAULTS)
        ev = {"mint": "M" * 44, "symbol": "DOGE2", "name": "Doge Two", "traderPublicKey": "dev1",
              "initialBuy": 150000000.0, "solAmount": 3.0, "marketCapSol": 40}
        flags, facts = D.instant(ev, {"dev1": 1}, set(), cfg, {})
        self.assertEqual(facts["dev_buy_pct"], 15.0)
        self.assertTrue(any("dev bought 15.0%" in f for f in flags))
        ev.update(initialBuy=1000000.0, name="FREE AIRDROP")
        flags, _ = D.instant(ev, {"dev1": 3}, {"DOGE2"}, cfg, {"DOGE2": 1})
        text = " | ".join(flags)
        for bit in ("serial launcher", "junk name", "copycat", "copy race"):
            self.assertIn(bit, text)
        flags, _ = D.instant(dict(ev, name="Doge Two"), {"dev1": 1}, set(), cfg, {})
        self.assertEqual(flags, [])

    def test_follow_up_verdicts(self):
        cfg = dict(D.DEFAULTS)
        mint = "P" * 44

        class Net(object):
            def __init__(self, buys, sells, vol, chg, meta):
                self.d = {D.DS_TOKEN % mint: [{"baseToken": {"address": mint, "symbol": "P"}, "dexId": "pumpfun",
                                               "txns": {"m5": {"buys": buys, "sells": sells}}, "volume": {"m5": vol, "h24": vol},
                                               "priceChange": {"m5": chg}, "marketCap": 12000}],
                          "https://ipfs.io/ipfs/abc": meta}

            def get(self, url, timeout=10):
                return self.d.get(url)

        v, reasons, f = D.follow_up(mint, Net(60, 20, 9000, 40, {"twitter": "x.com/p"}), "ipfs://x/ipfs/abc", cfg)
        self.assertEqual(v, "hot")
        v, reasons, f = D.follow_up(mint, Net(60, 20, 9000, 40, {}), "ipfs://x/ipfs/abc", cfg)
        self.assertEqual(v, "watch")
        v, reasons, f = D.follow_up(mint, Net(5, 30, 500, -60, {}), "ipfs://x/ipfs/abc", cfg)
        self.assertEqual(v, "skip")
        self.assertTrue(any("dumped" in r for r in reasons))

    def test_a_frame_parser_answers_pings(self):
        s = D.Stream()
        sent = []

        class Sock(object):
            def __init__(self, data):
                self.data = data

            def recv(self, n):
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

            def sendall(self, b):
                sent.append(b)

            def close(self):
                pass

        msg = b'{"txType": "create", "mint": "abc"}'
        s.sock = Sock(bytes([0x89, 0x02]) + b"hi" + bytes([0x81, len(msg)]) + msg)
        s.buf = b""
        got = next(s.messages())
        self.assertEqual(got["mint"], "abc")
        self.assertEqual(sent[0][0], 0x8A)                                # a pong went back


if __name__ == "__main__":
    unittest.main()
