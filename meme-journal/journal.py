#!/usr/bin/env python3
"""The Trade Journal (meme-journal). Standard library only.

Every real trade, what it cost and what it made, after fees. It reads the
broker log (meme/state/broker.json: each buy with its max loss, each sell
with its profit or loss) plus trades you add by hand, and answers the only
question that matters before you trade bigger: does this make money for
you, after costs, on real fills?

    python3 journal.py                      # the stats, live trades
    python3 journal.py --paper              # the paper trades instead
    python3 journal.py trades               # every trade, newest first
    python3 journal.py testphase            # where the test phase stands
    python3 journal.py add --symbol GATO --token MINT --buy-usd 22 --sell-usd 24.10 \
        --opened "2026-11-02 14:05" --closed "2026-11-02 14:40" --max-loss 1.70 --reason target
    python3 journal.py export trades.csv

The test phase: the first `testphase_trades` (20) real trades stay at
`testphase_max_order_usd` (22). It is PASSED when those trades made money in
total and on average per unit of risk (expectancy above 0R) with a profit
factor of at least 1.2. Otherwise it is FAILED, and meme-risk keeps the cap.
"""

import argparse
import calendar
import csv
import datetime
import json
import os
import re
import sys
import time

DEFAULTS = {"timezone": "Europe/Berlin", "testphase_trades": 20, "testphase_max_order_usd": 22,
            "testphase_min_profit_factor": 1.2, "paper": True}


class JournalError(Exception):
    pass


# ---------------------------------------------------------------- files and time

def mdir():
    return os.environ.get("MEME_DIR", "meme")


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


TZ = {"UTC": (0, None), "Europe/London": (0, "eu"), "Europe/Dublin": (0, "eu"), "Europe/Lisbon": (0, "eu"),
      "Europe/Berlin": (60, "eu"), "Europe/Vienna": (60, "eu"), "Europe/Zurich": (60, "eu"),
      "Europe/Paris": (60, "eu"), "Europe/Amsterdam": (60, "eu"), "Europe/Brussels": (60, "eu"),
      "Europe/Madrid": (60, "eu"), "Europe/Rome": (60, "eu"), "Europe/Warsaw": (60, "eu"),
      "Europe/Prague": (60, "eu"), "Europe/Stockholm": (60, "eu"), "Europe/Copenhagen": (60, "eu"),
      "Europe/Oslo": (60, "eu"), "Europe/Budapest": (60, "eu"), "Europe/Athens": (120, "eu"),
      "Europe/Helsinki": (120, "eu"), "Europe/Bucharest": (120, "eu"), "Europe/Istanbul": (180, None),
      "America/New_York": (-300, "us"), "America/Chicago": (-360, "us"), "America/Denver": (-420, "us"),
      "America/Los_Angeles": (-480, "us"), "Asia/Dubai": (240, None), "Asia/Singapore": (480, None),
      "Asia/Tokyo": (540, None)}


def _sunday(year, month, n):
    if n > 0:
        d = datetime.date(year, month, 1)
        d += datetime.timedelta(days=(6 - d.weekday()) % 7)
        return d + datetime.timedelta(weeks=n - 1)
    d = (datetime.date(year, month + 1, 1) if month < 12 else datetime.date(year + 1, 1, 1)) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() - 6) % 7)


def utc_offset(ts, tz):
    tz = tz or "UTC"
    m = re.match(r"^([+-])(\d{1,2}):?(\d{2})$", tz)
    if m:
        return (-1 if m.group(1) == "-" else 1) * (int(m.group(2)) * 60 + int(m.group(3)))
    base, rule = TZ.get(tz, (0, None))
    y = time.gmtime(ts).tm_year
    if rule == "eu":
        a = calendar.timegm(_sunday(y, 3, -1).timetuple()) + 3600
        b = calendar.timegm(_sunday(y, 10, -1).timetuple()) + 3600
        return base + (60 if a <= ts < b else 0)
    if rule == "us":
        a = calendar.timegm(_sunday(y, 3, 2).timetuple()) + 7200 - base * 60
        b = calendar.timegm(_sunday(y, 11, 1).timetuple()) + 7200 - (base + 60) * 60
        return base + (60 if a <= ts < b else 0)
    return base


def local_str(ts, tz, fmt="%Y-%m-%d %H:%M"):
    return time.strftime(fmt, time.gmtime(ts + utc_offset(ts, tz) * 60))


def parse_local(text, tz):
    dt = datetime.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    guess = calendar.timegm(dt.timetuple())
    return guess - utc_offset(guess - utc_offset(guess, tz) * 60, tz) * 60


def money(v):
    return ("-" if v < 0 else "") + "${:,.2f}".format(abs(v))


# ---------------------------------------------------------------- trades from the log

def trades_from_log(events):
    """Pair each buy with the sells that closed it. Open positions are left out (and counted)."""
    open_pos, done = {}, []
    for e in sorted(events or [], key=lambda x: x.get("at", 0)):
        tok = e.get("token")
        if e.get("type") == "placed" and e.get("side") == "buy":
            pos = open_pos.setdefault(tok, {"token": tok, "symbol": e.get("symbol"), "opened_at": e["at"],
                                            "cost_usd": 0.0, "tokens": 0.0, "sold": 0.0, "proceeds": 0.0,
                                            "pnl_usd": 0.0, "max_loss": 0.0, "paper": bool(e.get("paper")),
                                            "setup": e.get("setup"), "venue": e.get("venue"), "reason": None})
            pos["cost_usd"] += float(e.get("spent_usd") or e.get("amount_usd") or 0)
            pos["tokens"] += float(e.get("tokens") or 0)
            pos["max_loss"] += float(e.get("max_loss") or 0)
        elif e.get("type") == "fill" and e.get("side") == "sell" and tok in open_pos:
            pos = open_pos[tok]
            pos["sold"] += float(e.get("tokens") or 0)
            pos["proceeds"] += float(e.get("usd") or 0)
            pos["pnl_usd"] += float(e.get("pnl_usd") or 0)
            pos["reason"] = e.get("reason")
            if pos["sold"] >= pos["tokens"] - 1e-6:
                pos["closed_at"] = e["at"]
                pos["source"] = "broker"
                done.append(open_pos.pop(tok))
    return done, list(open_pos.values())


def enrich(t):
    t = dict(t)
    t["r"] = (t["pnl_usd"] / t["max_loss"]) if t.get("max_loss") else None
    t["hold_minutes"] = int((t["closed_at"] - t["opened_at"]) // 60) if t.get("closed_at") and t.get("opened_at") else None
    t["win"] = t["pnl_usd"] > 0
    return t


def all_trades(base, paper=False):
    done, still_open = trades_from_log((load(os.path.join(base, "state", "broker.json"), {}) or {}).get("events"))
    manual = (load(os.path.join(base, "journal.json"), {}) or {}).get("trades", [])
    rows = [enrich(t) for t in done + manual if bool(t.get("paper")) == paper]
    rows.sort(key=lambda t: t["closed_at"])
    return rows, [p for p in still_open if bool(p.get("paper")) == paper]


# ---------------------------------------------------------------- the numbers

def stats(trades):
    n = len(trades)
    out = {"trades": n}
    if not n:
        return out
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    gross_win = sum(t["pnl_usd"] for t in wins)
    gross_loss = -sum(t["pnl_usd"] for t in losses)
    rs = [t["r"] for t in trades if t.get("r") is not None]
    equity, peak, dd = 0.0, 0.0, 0.0
    for t in trades:
        equity += t["pnl_usd"]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    holds = [t["hold_minutes"] for t in trades if t.get("hold_minutes") is not None]
    out.update(wins=len(wins), losses=len(losses), win_rate=100.0 * len(wins) / n,
               total_usd=sum(t["pnl_usd"] for t in trades), avg_usd=sum(t["pnl_usd"] for t in trades) / n,
               avg_win=(gross_win / len(wins)) if wins else 0.0, avg_loss=(-gross_loss / len(losses)) if losses else 0.0,
               profit_factor=(gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
               expectancy_r=(sum(rs) / len(rs)) if rs else None, max_drawdown=dd,
               best=max(t["pnl_usd"] for t in trades), worst=min(t["pnl_usd"] for t in trades),
               avg_hold=(sum(holds) / float(len(holds))) if holds else None,
               fees_note="profit and loss are after the costs the broker log recorded")
    return out


def groups(trades, key):
    out = {}
    for t in trades:
        out.setdefault(key(t) or "?", []).append(t)
    return dict((k, stats(v)) for k, v in out.items())


def testphase(trades, cfg):
    """('off'|'active'|'passed'|'failed', text). Same rule as meme-risk's cap."""
    n = int(cfg.get("testphase_trades") or 0)
    if not n:
        return "off", "no test phase in the config (testphase_trades is 0)"
    if cfg.get("paper", True):
        return "off", ("paper mode: the test phase (%d real trades at %s or less) starts once paper is false"
                       % (n, money(float(cfg.get("testphase_max_order_usd") or 0))))
    first = trades[:n]
    st = stats(first)
    if len(first) < n:
        return "active", "test phase: %d of %d real trades closed; orders stay at %s or less" % (
            len(first), n, money(float(cfg.get("testphase_max_order_usd") or 0)))
    pf_min = float(cfg.get("testphase_min_profit_factor") or 1.2)
    ok = st["total_usd"] > 0 and (st.get("expectancy_r") or 0) > 0 and st["profit_factor"] >= pf_min
    text = ("%d real trades: %s in total, %.0f %% winners, expectancy %+.2fR, profit factor %s" % (
        n, money(st["total_usd"]), st["win_rate"], st.get("expectancy_r") or 0.0, _pf(st["profit_factor"])))
    if ok:
        return "passed", "test phase PASSED: " + text + ". Raising the size is your decision, and only as far as your limits allow."
    return "failed", ("test phase FAILED: " + text + ". After costs this did not pay. Stay small, change the setup, "
                      "or stop; meme-risk keeps the cap.")


def _pf(v):
    return "inf" if v == float("inf") else "%.2f" % v


def render_stats(st, label, tz, trades, still_open, cfg):
    out = ["%s trades, after costs:" % label]
    if not st["trades"]:
        out.append("  none closed yet%s." % ((" (%d still open)" % len(still_open)) if still_open else ""))
        return "\n".join(out)
    out.append("  %d closed (%d open): %d winners, %d losers, %.0f %% win rate" % (
        st["trades"], len(still_open), st["wins"], st["losses"], st["win_rate"]))
    out.append("  total %s, average %s a trade (winners %s, losers %s)" % (
        money(st["total_usd"]), money(st["avg_usd"]), money(st["avg_win"]), money(st["avg_loss"])))
    out.append("  expectancy %s, profit factor %s, worst run down %s" % (
        ("%+.2fR" % st["expectancy_r"]) if st.get("expectancy_r") is not None else "n/a", _pf(st["profit_factor"]),
        money(-st["max_drawdown"]) if st["max_drawdown"] else "$0.00"))
    out.append("  best %s, worst %s, average hold %s" % (money(st["best"]), money(st["worst"]),
                                                          ("%.0f minutes" % st["avg_hold"]) if st.get("avg_hold") is not None else "n/a"))
    for name, key in (("by exit", lambda t: t.get("reason")), ("by setup", lambda t: t.get("setup")),
                      ("by app", lambda t: t.get("venue")),
                      ("by hour", lambda t: local_str(t["opened_at"], tz, "%H:00") if t.get("opened_at") else None)):
        g = groups(trades, key)
        if len(g) > 1 or name == "by exit":
            out.append("  %s: %s" % (name, ", ".join("%s %d (%s)" % (k, v["trades"], money(v["total_usd"]))
                                                     for k, v in sorted(g.items(), key=lambda kv: -kv[1]["trades"]))))
    if st["trades"] < 20:
        out.append("  %d trades are too few to judge: luck dominates under about 20." % st["trades"])
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trade journal (meme-journal). Reads and counts, never trades.")
    ap.add_argument("cmd", nargs="?", default="stats", choices=("stats", "trades", "testphase", "add", "export"))
    ap.add_argument("file", nargs="?", help="export: the CSV file to write")
    ap.add_argument("--paper", action="store_true", help="the paper trades instead of the live ones")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--token")
    ap.add_argument("--symbol")
    ap.add_argument("--buy-usd", type=float)
    ap.add_argument("--sell-usd", type=float, help="what you got back, after the app's fees")
    ap.add_argument("--opened")
    ap.add_argument("--closed")
    ap.add_argument("--max-loss", type=float, help="the planned loss at the stop, for R")
    ap.add_argument("--reason", default="manual")
    ap.add_argument("--setup")
    ap.add_argument("--venue")
    a = ap.parse_args(argv)
    base = mdir()
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (load(os.path.join(base, "config.json"), {}) or {}).items() if v is not None})
    tz = cfg["timezone"]
    try:
        if a.cmd == "add":
            if not (a.symbol and a.buy_usd is not None and a.sell_usd is not None and a.opened and a.closed):
                raise JournalError("add needs --symbol, --buy-usd, --sell-usd, --opened and --closed")
            j = load(os.path.join(base, "journal.json"), {"trades": []}) or {"trades": []}
            t = {"token": a.token, "symbol": a.symbol, "opened_at": parse_local(a.opened, tz),
                 "closed_at": parse_local(a.closed, tz), "cost_usd": a.buy_usd, "proceeds": a.sell_usd,
                 "pnl_usd": round(a.sell_usd - a.buy_usd, 2), "max_loss": a.max_loss or 0.0, "paper": a.paper,
                 "reason": a.reason, "setup": a.setup, "venue": a.venue, "source": "manual"}
            if t["closed_at"] < t["opened_at"]:
                raise JournalError("--closed is before --opened")
            j["trades"].append(t)
            save(os.path.join(base, "journal.json"), j)
            print("Added %s: %s in, %s out, %s." % (a.symbol, money(a.buy_usd), money(a.sell_usd), money(t["pnl_usd"])))
            return 0
        trades, still_open = all_trades(base, a.paper)
        if a.cmd == "export":
            if not a.file:
                raise JournalError("export needs a file name")
            with open(a.file, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["opened", "closed", "symbol", "token", "cost_usd", "proceeds_usd", "pnl_usd", "r", "reason",
                            "setup", "app", "paper"])
                for t in trades:
                    w.writerow([local_str(t["opened_at"], tz), local_str(t["closed_at"], tz), t.get("symbol"), t.get("token"),
                                "%.2f" % t["cost_usd"], "%.2f" % t.get("proceeds", 0), "%.2f" % t["pnl_usd"],
                                "" if t.get("r") is None else "%.3f" % t["r"], t.get("reason"), t.get("setup"),
                                t.get("venue"), t.get("paper")])
            print("Wrote %d trades to %s." % (len(trades), a.file))
            return 0
        if a.cmd == "trades":
            if a.json:
                print(json.dumps(trades, indent=2))
                return 0
            if not trades:
                print("No closed %s trades yet." % ("paper" if a.paper else "live"))
            for t in reversed(trades):
                print("%s  %-10s %s in, %s  %s%s" % (local_str(t["closed_at"], tz), (t.get("symbol") or "?")[:10],
                                                     money(t["cost_usd"]), money(t["pnl_usd"]),
                                                     ("%+.2fR " % t["r"]) if t.get("r") is not None else "",
                                                     t.get("reason") or ""))
            return 0
        if a.cmd == "testphase":
            state, text = testphase(trades, cfg)
            print(json.dumps({"state": state, "text": text}) if a.json else text)
            return 0
        st = stats(trades)
        if a.json:
            print(json.dumps({"stats": st, "open": len(still_open), "testphase": testphase(trades, cfg)}, indent=2,
                             default=str))
            return 0
        print(render_stats(st, "Paper" if a.paper else "Live", tz, trades, still_open, cfg))
        if not a.paper:
            print(testphase(trades, cfg)[1])
        return 0
    except JournalError as e:
        print("Journal: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
