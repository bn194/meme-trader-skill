import os
import unittest

from _load import FIX, GATO, MemeDir, load, run

W = load("meme-whales", "whales")
D = os.path.join(FIX, "meme-whales")
HOLDER = "8gHMH4VqW9Vwk5Z8NbJWa5nup4Wx4exxcR8f8ALCzsxo"
DEV = "5MVneCfDge5vtf4C7QZmczCJbBB8vfvDbMqvopvkBLJm"


def swap(wallet, mint, d_tokens, d_lamports):
    pre = [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmountString": "1000000"}}]
    post = [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmountString": str(1000000 + d_tokens)}}]
    return {"blockTime": 1793567000, "meta": {"fee": 5000, "preBalances": [10 ** 10], "postBalances": [10 ** 10 + d_lamports],
                                             "preTokenBalances": pre, "postTokenBalances": post},
            "transaction": {"message": {"accountKeys": [{"pubkey": wallet}]}}}


class Whales(unittest.TestCase):
    def test_the_reel_holder(self):
        with MemeDir() as md:
            md.write("plan.json", {"address": GATO, "symbol": "GATO"})
            run(W, ["add", HOLDER, "--label", "GATO #2 holder"])
            code, out = run(W, ["check", "--offline", D])
            self.assertEqual(code, 0)
            self.assertIn("4 new from 1 wallet", out)
            self.assertIn("2026-08-26 17:45  GATO #2 holder RECEIVED 25,000,000.00 GATO", out)
            self.assertIn("! on your watchlist", out)
            _, out = run(W, ["check", "--offline", D])
            self.assertIn("Nothing new from 1 wallet.", out)

    def test_buy_sell_and_the_dev_flag(self):
        toks, sol = W.deltas(swap(DEV, GATO, -500000, 39 * 10 ** 8), DEV)
        rows = W.classify(toks, sol, 0.000005)
        self.assertEqual(rows[0][0], "SELL")
        toks, sol = W.deltas(swap(DEV, GATO, 500000, -39 * 10 ** 8), DEV)
        self.assertEqual(W.classify(toks, sol, 0.000005)[0][0], "BUY")
        toks, sol = W.deltas(swap(DEV, GATO, -500000, -5000), DEV)
        self.assertEqual(W.classify(toks, sol, 0.000005)[0][0], "SENT")

    def test_dev_from_the_rugcheck_report(self):
        with MemeDir() as md:
            code, out = run(W, ["dev", GATO, "--offline-rugcheck", os.path.join(FIX, "meme-analyst", "rugcheck-GATO-2158.json")])
            self.assertEqual(code, 0)
            w = md.read("wallets.json")["wallets"][0]
            self.assertEqual((w["address"], w["role"], w["token"]), (DEV, "dev", GATO))

    def test_a_dev_sale_rings_first(self):
        with MemeDir() as md:
            md.write("wallets.json", {"wallets": [{"address": DEV, "label": "GATO dev", "role": "dev", "token": GATO}]})

            class Fake(object):
                def call(self, method, params):
                    if method == "getSignaturesForAddress":
                        return [{"signature": "S" * 88, "err": None, "blockTime": 1793567000}]
                    return swap(DEV, GATO, -500000, 39 * 10 ** 8)

            state = {"last_sig": {}, "seen": []}
            rows, clusters = W.check(Fake(), md.read("wallets.json")["wallets"], state, 10, "Europe/Berlin")
            self.assertEqual(clusters, [])
            self.assertEqual(rows[0]["action"], "SELL")
            self.assertTrue(rows[0]["flags"][0].startswith("DEV SOLD"))

    def test_clusters_and_import(self):
        state = {"recent_buys": []}
        alerts = [{"time": 1000, "wallet": "W1", "mint": "M", "action": "BUY", "symbol": "MEME", "label": "a"},
                  {"time": 1600, "wallet": "W2", "mint": "M", "action": "BUY", "symbol": "MEME", "label": "b"},
                  {"time": 1700, "wallet": "W3", "mint": "N", "action": "SELL", "symbol": "X", "label": "c"}]
        c = W.find_clusters(alerts, state)
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["mint"], c[0]["wallets"]), ("M", ["W1", "W2"]))
        self.assertEqual(W.find_clusters([{"time": 9000, "wallet": "W4", "mint": "Q", "action": "BUY"}], {"recent_buys": []}), [])
        txt = W.render([], "Europe/Berlin", 3, c)
        self.assertIn("CLUSTER: 2 of your wallets bought MEME within 10 minutes (a, b): M", txt)
        with MemeDir() as md:
            path = md.file("wallets.txt")
            with open(path, "w") as fh:
                fh.write("# public leaderboard\n%s, top trader\nnot-an-address\n%s\n" % (HOLDER, DEV))
            code, out = run(W, ["import", path])
            self.assertIn("Imported 2 wallets", out)
            self.assertEqual(sorted(w["address"] for w in md.read("wallets.json")["wallets"]), sorted([HOLDER, DEV]))


if __name__ == "__main__":
    unittest.main()
