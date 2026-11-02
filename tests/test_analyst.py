import json
import os
import unittest

from _load import FIX, GATO, MemeDir, load, run

A = load("meme-analyst", "report")
D = os.path.join(FIX, "meme-analyst")


def rep(name, now=1793566680, **cfg):
    with open(os.path.join(D, "dex-%s.json" % name)) as fh:
        pairs = json.load(fh)
    with open(os.path.join(D, "rugcheck-%s.json" % name)) as fh:
        rc = json.load(fh)
    return A.analyze("solana", pairs[0]["baseToken"]["address"], pairs, rc, cfg, now)


def codes(r, level):
    return {f["code"] for f in r["flags"] if f["level"] == level}


class Analyst(unittest.TestCase):
    def test_gato_passes_with_the_reel_numbers(self):
        r = rep("GATO-2158")
        m = r["metrics"]
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["symbol"], "GATO")
        self.assertIsNone(m["mint_authority"])
        self.assertIsNone(m["freeze_authority"])
        self.assertEqual(m["lp_locked_pct"], 100)
        self.assertEqual(m["holders"], 13645)
        self.assertAlmostEqual(m["top10_pct"], 15.5, delta=0.05)
        self.assertAlmostEqual(m["largest_holder_pct"], 3.32, delta=0.01)
        self.assertAlmostEqual(m["creator_pct"], 3.32, delta=0.01)
        self.assertAlmostEqual(m["insider_pct"], 2.11, delta=0.01)
        self.assertEqual(m["pair"], "5E3dXLXGwmTDCokA51WYYaKttjFZBwqCoyUHBUi5gt2m")
        self.assertEqual(codes(r, "info"), {"boosted", "creator_bag"})

    def test_the_four_avoids_of_that_evening(self):
        self.assertIn("insiders", codes(rep("Dacity"), "avoid"))
        self.assertEqual(rep("Dacity")["verdict"], "AVOID")
        paw = rep("PAWCAT")
        self.assertIn("wash", codes(paw, "caution"))
        self.assertGreater(paw["metrics"]["turnover"], 1900)
        vice = rep("VICE")
        self.assertTrue({"whale", "top10", "liquidity"} <= codes(vice, "avoid"))
        biz = rep("MONEYBIZ")
        self.assertTrue({"lp_unlocked", "whale", "creator", "liquidity"} <= codes(biz, "avoid"))
        for name in ("PAWCAT", "VICE", "MONEYBIZ"):
            self.assertEqual(rep(name)["verdict"], "AVOID", name)

    def test_pools_are_not_counted_as_whales(self):
        # PAWCAT's pool holds 88 % of the supply; with it left out the top 10 is about 10 %
        self.assertLess(rep("PAWCAT")["metrics"]["top10_pct"], 11)

    def test_active_authorities_and_token2022_traps_are_avoid(self):
        with open(os.path.join(D, "rugcheck-GATO-2158.json")) as fh:
            rc = json.load(fh)
        with open(os.path.join(D, "dex-GATO-2158.json")) as fh:
            pairs = json.load(fh)
        rc["token"]["mintAuthority"] = "Mint1111111111111111111111111111111111111"
        rc["token"]["freezeAuthority"] = "Frz11111111111111111111111111111111111111"
        rc["transferFee"]["pct"] = 5
        rc["token_extensions"]["permanentDelegate"] = "Del11111111111111111111111111111111111111"
        r = A.analyze("solana", GATO, pairs, rc, {}, 1793566680)
        self.assertEqual(r["verdict"], "AVOID")
        self.assertTrue({"mint", "freeze", "transfer_fee", "delegate"} <= codes(r, "avoid"))

    def test_no_report_off_solana_is_unverified(self):
        with open(os.path.join(D, "dex-GATO-2158.json")) as fh:
            pairs = json.load(fh)
        self.assertEqual(A.analyze("base", GATO, pairs, None, {}, 1793566680)["verdict"], "UNVERIFIED")
        self.assertEqual(A.analyze("solana", GATO, pairs, None, {}, 1793566680)["verdict"], "AVOID")

    def test_write_updates_safety_json(self):
        with MemeDir() as md:
            code, out = run(A, [GATO, "--offline-dex", os.path.join(D, "dex-GATO-2158.json"),
                                "--offline-rugcheck", os.path.join(D, "rugcheck-GATO-2158.json"),
                                "--offline-goplus", os.path.join(D, "goplus-GATO.json"),
                                "--now", "2026-11-01 21:58", "--write"])
            self.assertEqual(code, 0)
            self.assertIn("Verdict: PASS (0 avoid, 0 caution)", out)
            s = md.read("safety.json")[GATO]
            self.assertEqual(s["verdict"], "PASS")
            self.assertEqual(s["checked_at"], 1793566680)
            self.assertAlmostEqual(s["liquidity_usd"], 278503.92)
            self.assertTrue(os.path.exists(md.file("analyst", GATO + ".json")))

    def test_an_avoid_exits_2(self):
        with MemeDir():
            code, out = run(A, ["D3YBbpwUAENRYkKW7H4crp67icXazkZFb2UajoW31yoi",
                                "--offline-dex", os.path.join(D, "dex-MONEYBIZ.json"),
                                "--offline-rugcheck", os.path.join(D, "rugcheck-MONEYBIZ.json"), "--no-goplus"])
            self.assertEqual(code, 2)
            self.assertIn("meme-risk blocks any buy", out)

    def test_a_ticker_alone_is_refused(self):
        with MemeDir():
            code, out = run(A, ["GATO"])
            self.assertEqual(code, 1)
            self.assertIn("symbols are not unique", out)

    def test_goplus_agrees_on_gato(self):
        with open(os.path.join(D, "goplus-GATO.json")) as fh:
            gp = json.load(fh)
        with open(os.path.join(D, "dex-GATO-2158.json")) as fh:
            pairs = json.load(fh)
        with open(os.path.join(D, "rugcheck-GATO-2158.json")) as fh:
            rc = json.load(fh)
        r = A.analyze("solana", GATO, pairs, rc, {}, 1793566680, gp)
        self.assertEqual(r["verdict"], "PASS")
        self.assertIn("GoPlus", r["sources"])
        r = A.analyze("solana", GATO, pairs, None, {}, 1793566680, gp)     # GoPlus alone: checked, but not everything
        self.assertEqual(r["verdict"], "CAUTION")
        self.assertIn("no_rugcheck", codes(r, "caution"))

    def test_goplus_on_base(self):
        with open(os.path.join(D, "goplus-ONECOIN-base.json")) as fh:
            gp = json.load(fh)
        with open(os.path.join(D, "dex-ONECOIN-base.json")) as fh:
            pairs = json.load(fh)
        addr = "0x456aC19C8a72Aed16376D57c367640D69ff9e6ea"
        r = A.analyze("base", addr, pairs, None, {}, 1793570000, gp)
        self.assertEqual(r["verdict"], "AVOID")
        self.assertTrue({"lp_unlocked", "liquidity"} <= codes(r, "avoid"))
        self.assertIn("owner", codes(r, "caution"))
        self.assertAlmostEqual(r["metrics"]["top10_pct"], 18.6, delta=0.05)  # the Uniswap v4 PoolManager is left out
        self.assertEqual(A.analyze("base", addr, pairs, None, {}, 1793570000)["verdict"], "AVOID")
        gp2 = json.loads(json.dumps(gp))
        g = list(gp2["result"].values())[0]
        g.update(is_honeypot="1", sell_tax="0.25")
        r = A.analyze("base", addr, pairs, None, {}, 1793570000, gp2)
        self.assertTrue({"honeypot", "tax"} <= codes(r, "avoid"))

    def test_holder_trend(self):
        with open(os.path.join(D, "dex-GATO-2158.json")) as fh:
            pairs = json.load(fh)
        with open(os.path.join(D, "rugcheck-GATO-2158.json")) as fh:
            rc = json.load(fh)
        hist = [[1793566680 - 7200, 14400]]
        r = A.analyze("solana", GATO, pairs, rc, {}, 1793566680, None, hist)
        self.assertEqual(r["metrics"]["holder_trend"]["change"], 13645 - 14400)
        self.assertIn("holders_falling", codes(r, "caution"))
        r = A.analyze("solana", GATO, pairs, rc, {}, 1793566680, None, [[1793566680 - 7200, 13500]])
        self.assertNotIn("holders_falling", codes(r, "caution"))
        with MemeDir() as md:
            for now in ("2026-11-01 20:00", "2026-11-01 21:58"):
                run(A, [GATO, "--offline-dex", os.path.join(D, "dex-GATO-2158.json"), "--offline-rugcheck",
                        os.path.join(D, "rugcheck-GATO-2158.json"), "--no-goplus", "--now", now, "--write"])
            self.assertEqual(len(md.read("state/holders.json")[GATO]), 2)


if __name__ == "__main__":
    unittest.main()
