#!/usr/bin/env python3
"""The Entry Timer (meme-entry). Standard library only.

Watches one meme coin bar by bar and says the moment to get in. It reads free
1-minute bars (Jupiter's chart data for Solana, GeckoTerminal for any other
chain), builds a range from the first 15 minutes after the time you start
watching (or the range the scanner found), and calls the entry on the first
completed bar that CLOSES above the range high on volume of at least 1.5x the
range's average. Or above a level you give it.

    python3 entry.py check MINT                     # range starts now, or reuses meme/entry.json
    python3 entry.py check MINT --from 19:31        # the range from 19:31 (your time zone)
    python3 entry.py check MINT --setup level --level 0.0081
    python3 entry.py watch MINT --every 30          # check every 30 s until it triggers or ends
    python3 entry.py show

States: building (the range is not done), waiting (and how far), triggered
(time and price), failed (a bar closed under the range low first), expired
(nothing within --max-wait minutes). Long side only. It never places an
order; it writes meme/entry.json for /meme-exit.
"""

import argparse
import calendar
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "meme-trader-skill/1.0 (+https://github.com/bn194/meme-trader-skill)"
JUP_CHART = "https://datapi.jup.ag/v2/charts/%s?interval=1_MINUTE&to=%d&candles=%d&type=price"
GT = "https://api.geckoterminal.com/api/v2"
DS_TOKENS = "https://api.dexscreener.com/tokens/v1/%s/%s"
GECKO_NET = {"solana": "solana", "ethereum": "eth", "base": "base", "bsc": "bsc", "arbitrum": "arbitrum",
             "polygon": "polygon_pos", "avalanche": "avax", "sui": "sui-network", "ton": "ton", "tron": "tron"}
STALE_MINUTES = 5


class EntryError(Exception):
    pass


# ---------------------------------------------------------------- files, time, network

def mdir():
    return os.environ.get("MEME_DIR", "meme")


def load(path, default=None):
    try:
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
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


def local_str(ts, tz, fmt="%H:%M"):
    return time.strftime(fmt, time.gmtime(ts + utc_offset(ts, tz) * 60))


def parse_now(text, tz):
    if not text:
        return int(time.time())
    dt = datetime.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    guess = calendar.timegm(dt.timetuple())
    return guess - utc_offset(guess - utc_offset(guess, tz) * 60, tz) * 60


def parse_clock(text, now, tz):
    """'19:31' today in the user's zone (yesterday if that is still ahead), or 'YYYY-MM-DD HH:MM'."""
    text = text.strip()
    if len(text) > 5:
        return parse_now(text, tz)
    h, m = [int(x) for x in text.split(":")]
    day = local_str(now, tz, "%Y-%m-%d")
    ts = parse_now("%s %02d:%02d" % (day, h, m), tz)
    return ts - 86400 if ts > now else ts


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < tries - 1:
                time.sleep(5 * (i + 1))
                continue
            raise EntryError("%s answered HTTP %d" % (url.split("/")[2], e.code))
        except (urllib.error.URLError, OSError, ValueError) as e:
            if i < tries - 1:
                time.sleep(2)
                continue
            raise EntryError("could not read %s (%s)" % (url.split("/")[2], e))


def parse_bars(obj, key=None):
    """Jupiter or GeckoTerminal bars -> ascending dicts. A scanner bundle (--save) holds many charts:
    only the ones whose URL names `key` (the token or pool address) are read."""
    out = {}
    if isinstance(obj, dict) and "responses" in obj:
        for url, v in obj["responses"].items():
            if key and key in url and isinstance(v, dict) and ("candles" in v or "ohlcv" in url):
                for b in parse_bars(v):
                    out[b["t"]] = b
    elif isinstance(obj, dict) and "candles" in obj:
        for c in obj["candles"] or []:
            out[int(c["time"])] = {"t": int(c["time"]), "o": float(c["open"]), "h": float(c["high"]),
                                   "l": float(c["low"]), "c": float(c["close"]), "v": float(c.get("volume") or 0)}
    elif isinstance(obj, dict) and "data" in obj:
        for row in ((obj.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []:
            t, o, h, l, c, v = row[:6]
            out[int(t)] = {"t": int(t), "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v or 0)}
    elif isinstance(obj, list):
        for c in obj:
            out[int(c["t"])] = c
    return [out[k] for k in sorted(out)]


def fetch_bars(tok, now, n):
    n = max(30, min(1000, n))
    if tok["chain"] == "solana":
        return parse_bars(get_json(JUP_CHART % (tok["address"], now * 1000, n)))
    if not tok.get("pair"):
        raise EntryError("no pool address for %s; GeckoTerminal needs the pool" % tok["address"])
    url = "%s/networks/%s/pools/%s/ohlcv/minute?aggregate=1&limit=%d&currency=usd&before_timestamp=%d" % (
        GT, GECKO_NET.get(tok["chain"], tok["chain"]), tok["pair"], n, now)
    return parse_bars(get_json(url))


# ---------------------------------------------------------------- prices

def fp(p):
    """A price to 5 significant digits, never in e-notation."""
    if p is None:
        return "n/a"
    p = float(p)
    if p <= 0:
        return "0"
    e = int(("%e" % p).split("e")[1])
    return "%.*f" % (max(0, 4 - e), p)


# ---------------------------------------------------------------- which token

def resolve(token, chain, offline):
    t = token.strip()
    m = re.search(r"dexscreener\.com/([a-z0-9]+)/([A-Za-z0-9]+)", t)
    if m:
        chain, t = m.group(1), m.group(2)
    base = mdir()
    known = []
    for src in ("entry.json", "plan.json"):
        d = load(os.path.join(base, src))
        if d and d.get("address"):
            known.append(d)
    wl = load(os.path.join(base, "watchlist.json"), {}) or {}
    known.extend(wl.get("hits", []))
    for k in known:
        if k.get("address") == t or str(k.get("symbol", "")).upper() == t.lstrip("$").upper():
            return {"chain": k.get("chain", chain), "address": k["address"], "symbol": k.get("symbol"),
                    "pair": k.get("pair"), "hit": k if "range_start" in k else None}
    if not re.match(r"^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$", t):
        raise EntryError("'%s' is not an address and not in meme/watchlist.json; give the contract address" % token)
    tok = {"chain": chain, "address": t, "symbol": None, "pair": None, "hit": None}
    if not offline:
        pairs = get_json(DS_TOKENS % (chain, t))
        pairs = pairs if isinstance(pairs, list) else (pairs or {}).get("pairs") or []
        mine = [p for p in pairs if (p.get("baseToken") or {}).get("address") == t]
        if mine:
            best = max(mine, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
            tok.update(symbol=best["baseToken"].get("symbol"), pair=best.get("pairAddress"))
    return tok


# ---------------------------------------------------------------- the rules

def evaluate(bars, now, start, setup="range", range_minutes=15, level=None, vol_x=1.5, max_wait=60):
    """Pure: the bars and the rule -> the state dict. Only completed bars count."""
    done = [b for b in bars if b["t"] + 60 <= now and b["t"] >= start]
    st = {"setup": setup, "start": start, "vol_x_min": vol_x, "max_wait": max_wait, "now": now}
    if now < start + 60:
        st.update(status="not_started", text="the watch starts at the first bar after %d" % start)
        return st
    if done:
        st["last"] = {"time": done[-1]["t"] + 60, "close": done[-1]["c"]}
    if setup == "level":
        if level is None:
            raise EntryError("a level setup needs --level PRICE")
        before = [b for b in bars if b["t"] < start][-15:]
        avg = (sum(b["v"] for b in before) / len(before)) if before else 0.0
        st["level"] = level
        st["avg_volume"] = avg
        watch_from = start
        end = start + max_wait * 60
    else:
        rng = [b for b in done if b["t"] < start + range_minutes * 60]
        st["range"] = {"start": start, "end": start + range_minutes * 60, "minutes": range_minutes,
                       "bars": len(rng)}
        if rng:
            st["range"].update(high=max(b["h"] for b in rng), low=min(b["l"] for b in rng),
                               avg_volume=sum(b["v"] for b in rng) / float(range_minutes))
        if now < start + range_minutes * 60:
            st.update(status="building")
            return st
        if len(rng) < 0.8 * range_minutes:
            st.update(status="thin", text="only %d of the %d range minutes traded: too thin for a range" % (
                len(rng), range_minutes))
            return st
        level = st["range"]["high"]
        avg = st["range"]["avg_volume"]
        watch_from = start + range_minutes * 60
        end = watch_from + max_wait * 60
    for b in done:
        if b["t"] < watch_from or b["t"] >= end:
            continue
        if setup != "level" and b["c"] < st["range"]["low"]:
            st.update(status="failed", failed={"time": b["t"] + 60, "close": b["c"]})
            return st
        vx = (b["v"] / avg) if avg > 0 else None
        if b["c"] > level and (vol_x <= 0 or (vx is not None and vx >= vol_x)):
            st.update(status="triggered", trigger={"bar_time": b["t"], "time": b["t"] + 60, "price": b["c"],
                                                   "volume": b["v"], "vol_x": round(vx, 2) if vx else None,
                                                   "over_pct": round((b["c"] / level - 1) * 100, 2)})
            st["stale"] = now - (b["t"] + 60) > STALE_MINUTES * 60
            return st
    if now >= end:
        st.update(status="expired")
    else:
        st.update(status="waiting")
    return st


def render(tok, st, tz):
    name = "%s (%s)" % (tok.get("symbol") or "?", tok["address"])
    when = local_str(st["now"], tz)
    rng = st.get("range") or {}
    lines = []
    if st["setup"] == "level":
        head = "%s, level breakout above $%s on 1-minute bars, checked %s %s" % (name, fp(st["level"]), when, tz)
    else:
        head = "%s, %d-minute range breakout on 1-minute bars, checked %s %s" % (name, rng.get("minutes", 15), when, tz)
    lines.append(head)
    if rng.get("high") is not None:
        lines.append("  range %s to %s: high $%s, low $%s (%d bars)" % (
            local_str(rng["start"], tz), local_str(rng["end"], tz), fp(rng["high"]), fp(rng["low"]), rng["bars"]))
    s = st["status"]
    last = st.get("last") or {}
    if s == "not_started":
        lines.append("NOT STARTED: the watch begins at %s." % local_str(st["start"], tz))
    elif s == "building":
        lines.append("BUILDING: %d of %d range bars done; the range closes at %s." % (
            rng.get("bars", 0), rng["minutes"], local_str(rng["end"], tz)))
    elif s == "thin":
        lines.append("NO SETUP: %s." % st["text"])
    elif s == "waiting":
        lvl = st.get("level") if st["setup"] == "level" else rng.get("high")
        gap = (lvl / last["close"] - 1) * 100 if last.get("close") else None
        lines.append("WAITING: last close $%s at %s, %s under $%s. It needs a 1-minute close above it on volume "
                     ">= %gx. Expires %s." % (fp(last.get("close")), local_str(last.get("time", st["now"]), tz),
                                              "%.2f%%" % gap if gap is not None else "n/a", fp(lvl), st["vol_x_min"],
                                              local_str((rng.get("end") or st["start"]) + st["max_wait"] * 60, tz)))
    elif s == "failed":
        f = st["failed"]
        lines.append("FAILED: the %s bar closed at $%s, under the range low $%s, before any breakout. The setup is off."
                     % (local_str(f["time"] - 60, tz), fp(f["close"]), fp(rng["low"])))
    elif s == "expired":
        lines.append("EXPIRED: no breakout within %d minutes of the range. Nothing to do." % st["max_wait"])
    elif s == "triggered":
        t = st["trigger"]
        lines.append("TRIGGERED at %s: the %s bar closed at $%s, %.2f%% over $%s, volume %sx the range average." % (
            local_str(t["time"], tz), local_str(t["bar_time"], tz), fp(t["price"]), t["over_pct"],
            fp(st.get("level") if st["setup"] == "level" else rng["high"]), t["vol_x"]))
        if st.get("stale"):
            move = (last["close"] / t["price"] - 1) * 100 if last.get("close") else 0.0
            lines.append("  STALE: that was %d minutes ago; the last close is $%s (%+.2f%%). A late entry carries more "
                         "risk: plan from the current price, or skip it." % ((st["now"] - t["time"]) // 60,
                                                                                fp(last.get("close")), move))
        lines.append("Next: /meme-exit plans the stop and the target before anything is bought.")
    return "\n".join(lines)


def check(a, cfg, tz, now, quiet=False):
    tok = resolve(a.token, a.chain, a.offline)
    if a.symbol:
        tok["symbol"] = a.symbol
    prev = load(os.path.join(mdir(), "entry.json")) or {}
    same = prev.get("address") == tok["address"] and prev.get("setup", "range") == a.setup
    if a.start:
        start = parse_clock(a.start, now, tz)
    elif same and prev.get("start") and prev.get("status") in ("building", "waiting", "not_started", "triggered"):
        start = int(prev["start"])
    elif tok.get("hit") and a.setup == "range":
        start = int(tok["hit"]["range_start"])
    else:
        start = (now // 60) * 60
    need = (now - start) // 60 + a.range_minutes + 20
    if a.setup == "level":
        need += 15
    if a.offline:
        raw = load(a.offline)
        bars = parse_bars(raw, tok.get("pair") if tok["chain"] != "solana" else tok["address"])
    else:
        bars = fetch_bars(tok, now, need)
    if not bars:
        raise EntryError("no 1-minute bars came back for %s" % tok["address"])
    st = evaluate(bars, now, start, a.setup, a.range_minutes, a.level, a.vol_x, a.max_wait)
    out = {"symbol": tok.get("symbol"), "chain": tok["chain"], "address": tok["address"], "pair": tok.get("pair"),
           "interval": "1m", "source": "jupiter" if tok["chain"] == "solana" else "geckoterminal",
           "checked_at": now}
    out.update(st)
    if not a.no_write:
        save(os.path.join(mdir(), "entry.json"), out)
    if not quiet:
        print(json.dumps(out, indent=2) if a.json else render(tok, st, tz))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Entry timer (meme-entry). Says when, never buys.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "watch"):
        p = sub.add_parser(name)
        p.add_argument("token", help="contract address, DexScreener URL, or a symbol in meme/watchlist.json")
        p.add_argument("--chain", default="solana")
        p.add_argument("--symbol", help="the ticker to show (looked up on DexScreener when online)")
        p.add_argument("--setup", choices=("range", "level"), default="range")
        p.add_argument("--from", dest="start", help="range or watch start, HH:MM in your time zone")
        p.add_argument("--range-minutes", type=int, default=15)
        p.add_argument("--level", type=float)
        p.add_argument("--vol-x", type=float, default=1.5, help="breakout bar volume vs the range average (0 = off)")
        p.add_argument("--max-wait", type=int, default=60, help="minutes after the range before it expires")
        p.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
        p.add_argument("--offline", help="saved 1-minute bars (Jupiter or GeckoTerminal JSON, or a scanner bundle)")
        p.add_argument("--no-write", action="store_true")
        p.add_argument("--json", action="store_true")
        if name == "watch":
            p.add_argument("--every", type=int, default=30, help="seconds between checks")
            p.add_argument("--max-checks", type=int, default=240)
    sub.add_parser("show")
    a = ap.parse_args(argv)
    cfg = load(os.path.join(mdir(), "config.json"), {}) or {}
    tz = cfg.get("timezone") or "Europe/Berlin"
    if a.cmd == "show":
        e = load(os.path.join(mdir(), "entry.json"))
        if not e:
            print("No meme/entry.json yet. Run: entry.py check MINT")
            return 1
        print(render(e, e, tz))
        return 0
    try:
        if a.cmd == "check":
            st = check(a, cfg, tz, parse_now(a.now, tz))
            return 0 if st["status"] == "triggered" else 1
        last = None
        for i in range(a.max_checks):
            st = check(a, cfg, tz, parse_now(a.now, tz), quiet=True)
            if st["status"] != last or st["status"] in ("triggered", "failed", "expired", "thin"):
                print(render(st, st, tz))
                sys.stdout.flush()
            last = st["status"]
            if st["status"] in ("triggered", "failed", "expired", "thin"):
                return 0 if st["status"] == "triggered" else 1
            time.sleep(a.every)
        return 1
    except EntryError as e:
        print("No entry check: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
