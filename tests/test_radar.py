import json
import os
import socket
import unittest

from _load import FIX, MemeDir, load, run

D = load("meme-radar", "radar")
T0 = 1793599200.0  # Mon 2026-11-02 07:00 Europe/Berlin
MINT = "Fr35hCo1n111111111111111111111111111111pump"


def asset(price=1.0e-5, traders=30, holders=30, buys=30, sells=10, bought=2500.0, dev_mints=1, dev_pct=2.0, top10=25.0,
          sniper=3.0, mayhem=False, grad=None, chg=10.0, liq_chg=0.0, mint=MINT):
    return {"id": mint, "symbol": "FRESH", "usdPrice": price, "holderCount": holders, "mcap": price * 1e9 if price else None,
            "isMayhem": mayhem, "graduatedPool": grad,
            "audit": {"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "devMints": dev_mints,
                      "devMigrations": 0, "devBalancePercentage": dev_pct, "topHoldersPercentage": top10,
                      "sniperPct": sniper},
            "stats5m": {"numTraders": traders, "numBuys": buys, "numSells": sells, "buyVolume": bought,
                        "priceChange": chg, "liquidityChange": liq_chg}}


def price(p, mint=MINT):
    return {"id": mint, "usdPrice": p}


def create(mint=MINT, symbol="FRESH", dev="dev1", dev_tokens=20000000.0, t=T0):
    return {"txType": "create", "mint": mint, "symbol": symbol, "name": "Fresh Coin", "traderPublicKey": dev,
            "initialBuy": dev_tokens, "solAmount": 0.6, "marketCapSol": 31, "_t": t}


def radar(snaps, **cfg):
    c = dict(D.DEFAULTS)
    c.update(cfg)
    lines = []

    class Out(object):
        def write(self, s):
            lines.append(s)

        def flush(self):
            pass

    r = D.Radar(c, D.Jup(recording=snaps), "Europe/Berlin", out=Out(), eur_usd=1.11)
    return r, lines


def drive(r, events, until):
    """Feed events and tick every second, like the live loop."""
    evs = sorted(events, key=lambda e: e["_t"])
    clock = T0
    while clock <= until:
        for ev in [e for e in evs if clock - 1 < e["_t"] <= clock]:
            r.on_event(ev, ev["_t"])
        r.tick(clock)
        clock += 1.0


class Checks(unittest.TestCase):
    cfg = dict(D.DEFAULTS)

    def row(self, dev_buy=2.0, created=T0):
        return {"mint": MINT, "created": created, "facts": {"dev_buy_pct": dev_buy}}

    def test_hard_nos(self):
        self.assertEqual(D.hard_nos(asset(), self.row(), self.cfg, T0 + 10), [])
        text = " | ".join(D.hard_nos(asset(dev_mints=161, mayhem=True, sniper=22.5), self.row(), self.cfg, T0 + 10))
        self.assertIn("the dev has launched 161 coins (0 graduated): a serial launcher", text)
        self.assertIn("Mayhem mode", text)
        self.assertIn("snipers hold 22.5% (limit 15%)", text)
        a = asset()
        a["audit"]["freezeAuthorityDisabled"] = False
        self.assertIn("freeze authority", D.hard_nos(a, self.row(), self.cfg, T0 + 10)[0])
        self.assertIn("bundled", D.hard_nos(asset(grad="Pool111"), self.row(), self.cfg, T0 + 10)[0])
        self.assertIn("the dev already sold: bought 5.0%, holds 0.10% now",
                      D.hard_nos(asset(dev_pct=0.1), self.row(dev_buy=5.0), self.cfg, T0 + 30)[0])
        a = asset()
        a["audit"]["bundlerStats"] = {"holdingPct": 12.0}
        self.assertIn("bundlers hold 12.0%", D.hard_nos(a, self.row(), self.cfg, T0 + 10)[0])

    def test_decide(self):
        v, good, bad = D.decide(asset(), self.row(), self.cfg, T0 + 30)
        self.assertEqual((v, bad), ("buy", []))
        self.assertEqual(good, ["30 traders", "30 holders", "$2.5k bought", "30 buys vs 10 sells", "the dev's first coin"])
        v, good, bad = D.decide(asset(traders=4, holders=5, bought=300, buys=8, sells=20, chg=-45, top10=60),
                                self.row(), self.cfg, T0 + 30)
        self.assertEqual(v, "skip")
        text = " | ".join(bad)
        for bit in ("only 4 traders (min 15)", "only 5 holders (min 15)", "$300 bought (min $1.0k)",
                    "more selling than buying: 20 sells vs 8 buys", "down 45% already: dumped",
                    "the top 10 wallets hold 60% (limit 40%)"):
            self.assertIn(bit, text)
        self.assertIn("no price yet", D.decide(asset(price=None), self.row(), self.cfg, T0 + 30)[2])
        self.assertIn("only 1 holder (min 15)", D.decide(asset(holders=1), self.row(), self.cfg, T0 + 30)[2])

    def test_costs(self):
        cfg = dict(self.cfg, venues={"phantom": {"fee_pct": 0.85, "fee_min_usd": 0},
                                     "fomo": {"fee_pct": 0.5, "fee_min_usd": 0.95}})
        self.assertAlmostEqual(D.side_costs(cfg, 5.55), 0.024)                 # 0.85 + 1.25 + 0.3 %
        self.assertAlmostEqual(D.side_costs(dict(cfg, venue="fomo"), 5.55), 0.95 / 5.55 + 0.0155)
        self.assertAlmostEqual(D.net_result(1.0, 1.0, 0.024), 0.976 / 1.024 - 1)
        self.assertAlmostEqual(D.net_result(1.0, 1.5, 0.0), 0.5)

    def test_price_str(self):
        self.assertEqual(D.price_str(2.6833907e-06), "$0.000002683")
        self.assertEqual(D.price_str(0.0030331), "$0.003033")
        self.assertEqual(D.price_str(1.5), "$1.50")
        self.assertEqual(D.price_str(None), "n/a")


class PaperTest(unittest.TestCase):
    def test_a_buy_followed_to_the_target_with_the_delays(self):
        snaps = {MINT: [[T0 + 10, asset()], [T0 + 30, asset(price=1.0e-5)], [T0 + 40, price(1.0e-5)],
                        [T0 + 80, price(1.1e-5)], [T0 + 90, price(1.2e-5)], [T0 + 100, price(1.7e-5)],
                        [T0 + 120, price(1.8e-5)], [T0 + 140, price(1.65e-5)], [T0 + 150, price(1.6e-5)]]}
        r, lines = radar(snaps)
        drive(r, [create()], T0 + 160)
        out = "".join(lines)
        self.assertIn("BUY   07:00:30  FRESH (%s)  30s: 30 traders; 30 holders; $2.5k bought; 30 buys vs 10 sells; "
                      "the dev's first coin; price $0.00001000, mcap $10.0k" % MINT, out)
        self.assertIn("paper test, signal 1 of 50: 5 EUR ($5.55) as if bought 45 s from now; stop -25 %, target +50 %, "
                      "out after 10 minutes; costs about 4.8 % a round trip", out)
        t = r.trades[0]
        self.assertEqual(t["status"], "closed")
        self.assertEqual(t["eur_usd"], 1.11)
        self.assertEqual((t["entry_t"], t["entry"]), (T0 + 80, 1.1e-5))     # filled 45 s later, at that price
        self.assertEqual((t["trigger_t"], t["exit_reason"]), (T0 + 100, "target"))
        self.assertEqual((t["exit_t"], t["exit"]), (T0 + 150, 1.6e-5))       # sold 45 s after the alarm
        self.assertAlmostEqual(t["net_pct"], (1.6 / 1.1) * 0.976 / 1.024 - 1, places=4)
        self.assertIn("PAPER 07:02:30  FRESH (%s)  target: in $0.00001100, out $0.00001600 (+45.5 %%), after costs +38.6 %%"
                      % MINT, out)
        self.assertIn("test: 1 of 50 closed, total +1.93 EUR", out)

    def test_a_stop_fills_where_the_price_is_45_s_later(self):
        snaps = {MINT: [[T0 + 10, asset()], [T0 + 30, asset(price=1.0e-5)], [T0 + 80, price(1.0e-5)],
                        [T0 + 90, price(0.7e-5)], [T0 + 130, price(0.4e-5)], [T0 + 140, price(0.45e-5)]]}
        r, lines = radar(snaps)
        drive(r, [create()], T0 + 150)
        t = r.trades[0]
        self.assertEqual((t["exit_reason"], t["trigger_t"], t["trigger_price"]), ("stop", T0 + 90, 0.7e-5))
        self.assertEqual((t["exit_t"], t["exit"]), (T0 + 140, 0.45e-5))       # the first poll after 45 s
        self.assertLess(t["net_pct"], -0.55)                                  # far worse than the -25 % stop

    def test_no_price_counts_as_a_total_loss(self):
        snaps = {MINT: [[T0 + 10, asset()], [T0 + 30, asset()], [T0 + 80, price(1.0e-5)]]}
        r, lines = radar(snaps, fresh_hold_minutes=1)
        drive(r, [create()], T0 + 400)
        t = r.trades[0]
        self.assertEqual((t["status"], t["exit_reason"], t["net_pct"]), ("closed", "no price", -1.0))
        self.assertIn("out nothing (counted as -100 %)", "".join(lines))

    def test_the_time_stop(self):
        snaps = {MINT: [[T0 + 10, asset()], [T0 + 30, asset()]] + [[T0 + 80 + 10 * i, price(1.05e-5)] for i in range(12)]}
        r, _ = radar(snaps, fresh_hold_minutes=1)
        drive(r, [create()], T0 + 200)
        t = r.trades[0]
        self.assertEqual((t["exit_reason"], t["trigger_t"], t["exit_t"]), ("time", T0 + 140, T0 + 190))

    def test_skips_at_each_stage(self):
        a, b, c, d = ("A" * 40 + "pump", "B" * 40 + "pump", "C" * 40 + "pump", "D" * 40 + "pump")
        snaps = {b: [[T0 + 10, asset(dev_mints=161, mint=b)]],
                 c: [[T0 + 10, asset(mint=c)], [T0 + 30, asset(traders=3, mint=c)]]}
        r, lines = radar(snaps)
        drive(r, [create(mint=a, dev_tokens=150000000.0), create(mint=b, symbol="BBB", dev="d2"),
                  create(mint=c, symbol="CCC", dev="d3"), create(mint=d, symbol="DDD", dev="d4")], T0 + 60)
        out = "".join(lines)
        self.assertIn("SKIP  07:00:00  FRESH (%s)  0s: dev bought 15.0%% of the supply at launch (limit 10%%)" % a, out)
        self.assertIn("SKIP  07:00:10  BBB (%s)  10s: the dev has launched 161 coins (0 graduated): a serial launcher" % b, out)
        self.assertIn("SKIP  07:00:30  CCC (%s)  30s: only 3 traders (min 15)" % c, out)
        self.assertIn("SKIP  07:00:18  DDD (%s)  18s: Jupiter had no data for it yet" % d, out)
        self.assertEqual(r.trades, [])
        self.assertEqual((r.counts["skip_birth"], r.counts["skip_first"], r.counts["skip_decide"], r.counts["skip_nodata"]),
                         (1, 1, 1, 1))
        self.assertIn("Radar, 1 minute: 4 new coins: 0 BUY, 4 SKIP (1 at birth, 1 at 10s, 1 at 30s, 1 without data), 0 graduated, 0 bundled launches.",
                      r.summary(1))

    def test_quiet_hides_the_skips(self):
        r, lines = radar({})
        r.quiet = True
        drive(r, [create(dev_tokens=150000000.0)], T0 + 2)
        self.assertEqual(lines, [])

    def test_a_bundled_launch(self):
        r, lines = radar({})
        drive(r, [create(), {"txType": "migrate", "mint": MINT, "pool": "pump-amm", "_t": T0 + 0.4}], T0 + 20)
        self.assertIn("BUNDLED   07:00:00  %s  graduated 0.4 s after launch" % MINT, "".join(lines))
        self.assertEqual(r.looks, [])

    def test_stats_and_the_verdict(self):
        cfg = dict(D.DEFAULTS, fresh_test_signals=4)

        def tr(i, usd):
            return {"n": i, "signal_t": T0 + i, "status": "closed", "net_usd": usd, "net_pct": usd / 5.55,
                    "exit_reason": "target" if usd > 0 else "stop"}

        st = D.test_stats([tr(1, 2.0), tr(2, -1.0), tr(3, 3.0)], cfg)
        self.assertEqual((st["closed"], st["wins"], st["verdict"]), (3, 2, None))
        st = D.test_stats([tr(1, 2.0), tr(2, -1.0), tr(3, 3.0), tr(4, -1.5), tr(5, -50)], cfg)
        self.assertEqual(st["closed"], 4)                                     # only the first 4 count
        self.assertAlmostEqual(st["profit_factor"], 2.0)
        self.assertEqual(st["verdict"], "PASSED")
        st = D.test_stats([tr(1, 1.0), tr(2, -1.0), tr(3, 0.1), tr(4, -0.2)], cfg)
        self.assertEqual(st["verdict"], "FAILED")
        lines = D.test_lines(st, 1.11)
        self.assertIn("FAILED: after costs this rule lost money on paper over 4 signals", lines[-1])
        self.assertIn("no BUY signal yet", D.test_lines(D.test_stats([], cfg), 1.11)[0])

    def test_resume_drops_what_ran_while_the_radar_was_off(self):
        trades = [{"status": "open", "path": [[T0, 1.0]]}, {"status": "closed", "path": [[T0, 1.0]]}]
        self.assertEqual(D.resume(trades, T0 + 3600), 1)
        self.assertEqual([t["status"] for t in trades], ["untracked", "closed"])

    def test_a_price_poll_wants_a_fresh_price(self):
        j = D.Jup(recording={MINT: [[T0, asset()], [T0 + 5, price(2e-5)]]})
        self.assertEqual(j.assets([MINT], T0 + 10, full=False)[MINT]["usdPrice"], 2e-5)
        self.assertEqual(j.assets([MINT], T0 + 10, full=True)[MINT]["audit"]["devMints"], 1)   # a full record
        self.assertEqual(j.assets([MINT], T0 + 100, full=False), {})


class Stream(unittest.TestCase):
    def sock(self, data, sent, quiet=False):
        class Sock(object):
            def __init__(self):
                self.data = data

            def recv(self, n):
                if quiet and not self.data:
                    raise socket.timeout("quiet")
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

            def sendall(self, b):
                sent.append(b)

            def close(self):
                pass
        return Sock()

    def test_a_frame_parser_answers_pings(self):
        s = D.Stream()
        sent = []
        msg = b'{"txType": "create", "mint": "abc"}'
        s.sock = self.sock(bytes([0x89, 0x02]) + b"hi" + bytes([0x81, len(msg)]) + msg, sent)
        s.buf = b""
        got = next(s.messages())
        self.assertEqual(got["mint"], "abc")
        self.assertEqual(sent[0][0], 0x8A)                                # a pong went back

    def test_a_quiet_stream_still_ticks(self):
        s = D.Stream()
        msg = b'{"txType": "create", "mint": "abc"}'
        s.sock = self.sock(bytes([0x81, len(msg)]) + msg, [], quiet=True)
        s.buf = b""
        it = s.messages()
        self.assertEqual(next(it)["mint"], "abc")
        self.assertIsNone(next(it))                                       # a tick, not a reconnect
        self.assertIsNone(next(it))


LIVE = os.path.join(FIX, "meme-radar", "radar-2026-11-02-0719.json.gz")


class Recording(unittest.TestCase):
    def test_four_live_minutes_replay_to_the_same_verdicts(self):
        # radar.py --minutes 4 --save, Monday 2026-11-02 07:19 to 07:23 Europe/Berlin
        with MemeDir() as md:
            code, out = run(D, ["--offline", LIVE])
            self.assertEqual(code, 0)
            self.assertIn("Radar, 4 minutes: 20 new coins: 3 BUY, 16 SKIP (6 at birth, 6 at 10s, 4 at 30s, 0 without data), "
                          "0 graduated, 1 bundled launch.", out)
            self.assertIn("BUY   07:20:12  OKCAT (gZRR9VtuyZDdQkUDKCEoheEHUxzps4Zg2Z7RB3Jpump)  30s: 19 traders; 15 holders; "
                          "$1.3k bought; 19 buys vs 6 sells; the dev's coin no. 3; price $0.000005025, mcap $5.0k", out)
            self.assertIn("paper test, signal 1 of 50: 5 EUR ($5.59 = 0.0592 SOL) as if bought 45 s from now", out)
            self.assertIn("SKIP  07:20:30  CI (Gg29Wfhq2nRNziL32wCLEXDdWQ5amuJQC2yH1Qm218iY)  10s: the dev has launched 171 "
                          "coins (0 graduated): a serial launcher", out)
            self.assertIn("Mayhem mode: pump.fun's AI agent trades it", out)
            self.assertIn("snipers hold 15.1% (limit 15%)", out)
            self.assertIn("BUNDLED   07:23:03  EpwR7NhYigWiGQ7PWKscrAbf9pENT9dvbBKaiy7tpump  graduated 0.5 s after launch", out)
            self.assertIn("3 paper trades were still running when the recording ended.", out)
            self.assertFalse(os.path.exists(md.file("fresh.json")))       # a replay never touches the paper test
            st = md.read("radar.json")
            self.assertEqual(sum(1 for r in st["coins"] if r["status"] == "buy"), 3)
            _, out = run(D, ["show"])
            self.assertIn("buy       OKCAT      gZRR9VtuyZDdQkUDKCEoheEHUxzps4Zg2Z7RB3Jpump  19 traders", out)
            _, quiet = run(D, ["--offline", LIVE, "--quiet", "--no-write"])
            self.assertNotIn("SKIP  ", quiet)
            self.assertEqual(quiet.count("BUY   "), 3)


    def test_twelve_minutes_without_a_buy(self):
        # 07:07 to 07:19 Europe/Berlin, every coin followed for 15 minutes: of the 58 with a price 75 s and 11 minutes
        # after launch, 8 were up. The rules bought none of the 74
        with MemeDir():
            code, out = run(D, ["--offline", os.path.join(FIX, "meme-radar", "radar-2026-11-02-0707.json.gz"), "--no-write"])
        self.assertEqual(code, 0)
        self.assertIn("Radar, 12 minutes: 74 new coins: 0 BUY, 72 SKIP (37 at birth, 22 at 10s, 12 at 30s, 1 without data), "
                      "6 graduated, 3 bundled launches.", out)
        self.assertEqual(out.count("a serial launcher"), 20)
        self.assertEqual(out.count("Mayhem mode"), 7)


class Cli(unittest.TestCase):
    def test_test_command(self):
        with MemeDir() as md:
            code, out = run(D, ["test"])
            self.assertEqual(code, 0)
            self.assertIn("Paper test: no BUY signal yet", out)
            md.write("fresh.json", {"trades": [{"n": 1, "signal_t": T0, "status": "closed", "net_usd": 1.0, "net_pct": 0.18,
                                                "exit_reason": "target", "mint": MINT, "symbol": "FRESH"}]})
            code, out = run(D, ["test"])
            self.assertIn("Paper test: 1 of 50 signals closed (0 still running): 1 won, 0 lost, 100 % win rate", out)
            self.assertIn("total +0.90 EUR", out)                           # at the fallback rate, 1.11
            md.write("fresh.json", {"trades": [{"n": 1, "signal_t": T0, "status": "closed", "net_usd": 1.0, "net_pct": 0.18,
                                                "exit_reason": "target", "mint": MINT, "symbol": "FRESH", "eur_usd": 1.25}]})
            _, out = run(D, ["test"])
            self.assertIn("total +0.80 EUR", out)                           # at the rate the radar used
            self.assertIn("#1   11-02 07:00  FRESH      %s  +18.0 %% after costs (target)" % MINT, out)

    def test_an_old_recording_is_refused(self):
        with MemeDir() as md:
            path = os.path.join(md.path, "old.json")
            with open(path, "w") as fh:
                json.dump({"events": [], "responses": {}}, fh)
            code, out = run(D, ["--offline", path])
            self.assertEqual(code, 1)
            self.assertIn("is not a recording of this radar", out)


if __name__ == "__main__":
    unittest.main()
