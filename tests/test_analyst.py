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

    def test_lookalikes(self):
        self.assertEqual(A.lookalikes([])[0], 0)
        self.assertEqual(A.lookalikes([3, 2, 1])[0], 1)            # real holders spread out
        n, lo, hi, tot = A.lookalikes([5, 1.0, 0.99, 0.97, 0.96, 0.5])
        self.assertEqual((n, lo, hi), (4, 0.96, 1.0))
        self.assertAlmostEqual(tot, 3.92)
        self.assertEqual(A.lookalikes([1.0, 0.952])[0], 2)          # inside 5 %
        self.assertEqual(A.lookalikes([1.0, 0.94])[0], 1)           # outside

    def test_lookalike_wallets_are_a_bundle(self):
        # ANAKIN, 2026-11-02 06:36: RugCheck saw no insiders and the top 10 holds 0.8 %, but 14 of the
        # top 19 wallets hold 0.076 to 0.079 % each: one buyer split across many wallets
        r = rep("ANAKIN", now=1793597760)
        m = r["metrics"]
        self.assertEqual(r["verdict"], "AVOID")
        self.assertEqual(codes(r, "avoid"), {"bundle"})
        self.assertEqual(m["lookalike_wallets"], 14)
        self.assertAlmostEqual(m["lookalike_pct"], 1.09, delta=0.005)
        self.assertEqual(m["insider_pct"], 0)
        self.assertLess(m["top10_pct"], 1)
        text = [f["text"] for f in r["flags"] if f["code"] == "bundle"][0]
        self.assertIn("14 of the top 19 wallets hold almost the same amount (0.076 to 0.079% each", text)
        r = rep("ANAKIN", now=1793597760, lookalike_avoid=15)
        self.assertEqual(r["verdict"], "CAUTION")
        self.assertIn("bundle", codes(r, "caution"))
        self.assertEqual(rep("ANAKIN", now=1793597760, lookalike_avoid=15, lookalike_caution=15)["verdict"], "PASS")
        # the organic coins of the reel do not trip it; MONEYBIZ's seven wallets at exactly 0.602 % do
        for name in ("GATO-2158", "Dacity", "PAWCAT", "VICE"):
            self.assertNotIn("bundle", codes(rep(name), "caution") | codes(rep(name), "avoid"), name)
        self.assertEqual(rep("GATO-2158")["verdict"], "PASS")
        self.assertIn("bundle", codes(rep("MONEYBIZ"), "caution"))

    def test_locked_supply(self):
        # uni, 2026-11-02 06:36: 98.4 % of the supply in five Streamflow vaults, left out of the holder math
        r = rep("uni", now=1793597760)
        m = r["metrics"]
        self.assertEqual(r["verdict"], "AVOID")
        self.assertEqual(codes(r, "avoid"), {"locked_supply"})
        self.assertAlmostEqual(m["locked_pct"], 98.4, delta=0.05)
        self.assertLess(m["largest_holder_pct"], 0.1)             # the vaults are not people
        text = [f["text"] for f in r["flags"] if f["code"] == "locked_supply"][0]
        self.assertIn("98.4% of the supply sits in lock contracts (Streamflow Vault)", text)
        r = rep("uni", now=1793597760, max_locked_pct=99)
        self.assertIn("locked_supply", codes(r, "caution"))
        self.assertNotEqual(r["verdict"], "AVOID")
        self.assertEqual(rep("GATO-2158")["metrics"]["locked_pct"], 0)

    def test_lookalikes_and_locks_on_goplus(self):
        with open(os.path.join(D, "goplus-ONECOIN-base.json")) as fh:
            gp = json.load(fh)
        with open(os.path.join(D, "dex-ONECOIN-base.json")) as fh:
            pairs = json.load(fh)
        addr = "0x456aC19C8a72Aed16376D57c367640D69ff9e6ea"
        r = A.analyze("base", addr, pairs, None, {}, 1793570000, gp)
        self.assertNotIn("bundle", codes(r, "avoid") | codes(r, "caution"))
        self.assertEqual(r["metrics"]["locked_pct"], 0)
        g = list(gp["result"].values())[0]
        g["holders"] = [{"address": "0x%040x" % (i + 1), "percent": "0.0%d" % (i % 2 + 20), "is_locked": 0}
                        for i in range(10)]
        g["holders"][0].update(percent="0.6", is_locked=1)
        r = A.analyze("base", addr, pairs, None, {}, 1793570000, gp)
        self.assertIn("bundle", codes(r, "caution"))                # 9 wallets at 2.0 and 2.1 %
        self.assertIn("locked_supply", codes(r, "avoid"))
        self.assertEqual(r["metrics"]["locked_pct"], 60)

    def test_the_report_shows_lookalikes_and_locks(self):
        with MemeDir():
            code, out = run(A, ["jM9r9PJFyPaMEbhGZPbDeZJiysn2pfyz5TzdDs5pump", "--offline-dex", os.path.join(D, "dex-uni.json"),
                                "--offline-rugcheck", os.path.join(D, "rugcheck-uni.json"), "--no-goplus",
                                "--now", "2026-11-02 06:36"])
        self.assertEqual(code, 2)
        self.assertIn("look-alikes      2 wallets with nearly the same amount   locked 98.4% in lock contracts", out)
        self.assertIn("Verdict: AVOID", out)


if __name__ == "__main__":
    unittest.main()
