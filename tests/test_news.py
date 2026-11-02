import os
import unittest

from _load import FIX, GATO, MemeDir, load, run

N = load("meme-news", "news")
D = os.path.join(FIX, "meme-news")


class News(unittest.TestCase):
    def test_the_reel_briefing(self):
        with MemeDir() as md:
            code, out = run(N, ["--tokens", GATO, "--offline", D, "--now", "2026-11-01 21:58", "--hours", "24"])
            self.assertEqual(code, 0)
            self.assertIn("now $0.0077880 at 21:58: 5m +2.6%, 1h +12.1%, 6h +2.3%, 24h +20.4%; pool liquidity $278,504", out)
            self.assertIn("[promo] paid DexScreener boost: 100 active", out)
            self.assertIn("Market, last 24 hours (8 new):", out)
            self.assertIn("FBI confirms North Korea's role in $6 billion Binance hack", out)

    def test_never_repeats_and_compares_liquidity(self):
        with MemeDir() as md:
            run(N, ["--tokens", GATO, "--offline", D, "--now", "2026-11-01 21:58", "--hours", "24"])
            _, out = run(N, ["--tokens", GATO, "--offline", D, "--now", "2026-11-01 22:05", "--hours", "24"])
            self.assertIn("Market, last 24 hours (0 new):", out)
            self.assertIn("since your last check at 21:58: price +0.0%, liquidity +0.0%", out)
            st = md.read("state/news.json")
            st["coins"][GATO]["liquidity_usd"] = 500000.0
            md.write("state/news.json", st)
            _, out = run(N, ["--tokens", GATO, "--offline", D, "--now", "2026-11-01 22:10", "--hours", "24"])
            self.assertIn("RUG WARNING: liquidity down 44%", out)

    def test_tags_and_matching(self):
        self.assertIn("hack", N.tag("Binance hacked, $6B stolen"))
        self.assertEqual(N.tag("Coinbase lists a new token")[:2], ["listing", "exchange"])
        self.assertIn("memecoin", N.tag("Memecoins rally as pump.fun volume jumps"))
        tok = {"symbol": "GATO", "name": "GTA6CAT"}
        self.assertTrue(N.mentions({"title": "$GATO is up", "summary": ""}, tok))
        self.assertTrue(N.mentions({"title": "Why GTA6CAT doubled", "summary": ""}, tok))
        self.assertFalse(N.mentions({"title": "Gatorade sales", "summary": ""}, tok))

    def test_rss_parsing(self):
        with open(os.path.join(D, "decrypt.xml"), "rb") as fh:
            items = N.parse_rss(fh.read(), "Decrypt")
        self.assertGreater(len(items), 30)
        self.assertTrue(all(i["title"] and i["id"] for i in items))

    def test_telegram_preview(self):
        with open(os.path.join(D, "tg-pumpfun.html"), "rb") as fh:
            posts, subs = N.parse_tg(fh.read(), "pumpfun")
        self.assertEqual(len(posts), 19)
        self.assertEqual(subs, "40.8K")
        last = posts[-1]
        self.assertEqual(last["id"], "tg:pumpfun/255")
        self.assertEqual(last["time"], 1792255918)                     # 2026-10-17T16:51:58+00:00
        self.assertEqual(last["text"], "my favorite trader just posted a callout")
        self.assertEqual(last["views"], "2.17K")
        with MemeDir():
            code, out = run(N, ["--tokens", GATO, "--offline", D, "--now", "2026-11-01 21:58", "--hours", "400",
                                "--telegram", "pumpfun,nosuchchannel"])
            self.assertIn("Telegram, 1 channel, last 400 hours (3 posts):", out)
            self.assertIn("Sat 18:51 t.me/pumpfun (2.17K views): my favorite trader just posted a callout", out)
            self.assertIn("Could not read: t.me/nosuchchannel", out)


if __name__ == "__main__":
    unittest.main()
