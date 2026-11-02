#!/usr/bin/env python3
"""The Coin Scanner (meme-scanner). Standard library only.

Scans the meme coins people are trading right now and lists the ones that
match a rule. Three steps:

  universe  collects the tokens in play from DexScreener (top and latest paid
            boosts, new token profiles, community takeovers, ads) and, when it
            answers, GeckoTerminal (trending and new pools), then reads each
            token's main pool from DexScreener -> meme/universe.json
  pairs     refreshes every pool's stats (price change m5/h1/h6/h24, buys and
            sells, volume, liquidity), drops what is too thin, too young or
            washed, and tags setups: momentum, volume surge, dip in an
            uptrend, new pool -> meme/watchlist.json
  range     reads 1-minute bars for the liquid candidates (the tokens that pass
            the pairs filters, setup or not) and finds the ones whose
            last few completed bars CLOSED above the high of the 15 minutes
            before, on rising volume -> meme/watchlist.json

    python3 scan.py universe
    python3 scan.py pairs
    python3 scan.py range                       # candidates: the pairs hits
    python3 scan.py range --tokens MINT1,MINT2  # or your own list
    python3 scan.py pairs --json

A hit matched a rule. It is not a buy, and most meme coins go to zero.
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
DS = "https://api.dexscreener.com"
GT = "https://api.geckoterminal.com/api/v2"
JUP_CHART = "https://datapi.jup.ag/v2/charts/%s?interval=1_MINUTE&to=%d&candles=%d&type=price"
GECKO_NET = {"solana": "solana", "ethereum": "eth", "base": "base", "bsc": "bsc", "arbitrum": "arbitrum",
             "polygon": "polygon_pos", "avalanche": "avax", "sui": "sui-network", "ton": "ton", "tron": "tron"}
LISTS = (("boosts_top", "/token-boosts/top/v1"), ("boosts_latest", "/token-boosts/latest/v1"),
         ("profiles", "/token-profiles/latest/v1"), ("cto", "/community-takeovers/latest/v1"),
         ("ads", "/ads/latest/v1"))
CURVES = ("pumpfun", "moonshot", "launchlab", "bonk", "believe")
DEFAULTS = {"timezone": "Europe/Berlin", "chains": ["solana"], "min_liquidity_usd": 50000,
            "min_pool_age_hours": 6, "max_turnover": 50}


class ScanError(Exception):
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
    opener = gzip.open if path.endswith(".gz") else open
    with opener(tmp, "wt", encoding="utf-8") as fh:
        json.dump(data, fh, indent=None if path.endswith(".gz") else 2)
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


class Net:
    """HTTP GET with a polite pause; --offline replays a saved bundle, --save records one."""

    def __init__(self, offline=None, record=False, pause=0.25):
        self.bundle = None
        if offline:
            self.bundle = load(offline)
            if not isinstance(self.bundle, dict) or "responses" not in self.bundle:
                raise ScanError("%s is not a saved bundle (no 'responses')" % offline)
        self.recorded = {} if record else None
        self.pause = pause
        self.calls = 0

    def get(self, url, required=True):
        if self.bundle is not None:
            if url in self.bundle["responses"]:
                return self.bundle["responses"][url]
            if required:
                raise ScanError("the offline bundle has no %s" % url)
            return None
        if self.calls:
            time.sleep(self.pause)
        self.calls += 1
        for i in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = json.load(r)
                if self.recorded is not None:
                    self.recorded[url] = data
                return data
            except urllib.error.HTTPError as e:
                if e.code in (429, 502, 503) and i < 2:
                    time.sleep(5 * (i + 1))
                    continue
                if required:
                    raise ScanError("%s answered HTTP %d" % (url.split("/")[2], e.code))
                return None
            except (urllib.error.URLError, OSError, ValueError) as e:
                if i < 2:
                    time.sleep(2)
                    continue
                if required:
                    raise ScanError("could not read %s (%s)" % (url.split("/")[2], e))
                return None


# ---------------------------------------------------------------- the universe

def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def summarize(pair, now):
    """A DexScreener pair -> the flat row the scanner and the other skills use."""
    created = pair.get("pairCreatedAt")
    tx = pair.get("txns") or {}
    vol = pair.get("volume") or {}
    info = pair.get("info") or {}
    return {"chain": pair.get("chainId"), "address": pair["baseToken"]["address"],
            "symbol": pair["baseToken"].get("symbol"), "name": pair["baseToken"].get("name"),
            "pair": pair.get("pairAddress"), "dex": pair.get("dexId"),
            "quote": (pair.get("quoteToken") or {}).get("symbol"),
            "price_usd": _f(pair.get("priceUsd")), "liquidity_usd": _f((pair.get("liquidity") or {}).get("usd")),
            "market_cap": _f(pair.get("marketCap")), "fdv": _f(pair.get("fdv")),
            "pool_created_at": int(created // 1000) if created else None,
            "age_hours": round((now - created / 1000.0) / 3600.0, 1) if created else None,
            "txns": {k: [(tx.get(k) or {}).get("buys", 0), (tx.get(k) or {}).get("sells", 0)] for k in ("m5", "h1", "h6", "h24")},
            "volume": {k: _f(vol.get(k), 0.0) for k in ("m5", "h1", "h6", "h24")},
            "change": {k: _f((pair.get("priceChange") or {}).get(k)) for k in ("m5", "h1", "h6", "h24")},
            "boosts": (pair.get("boosts") or {}).get("active") or 0,
            "socials": len(info.get("socials") or []) + len(info.get("websites") or []),
            "url": pair.get("url")}


def best_pairs(pairs):
    best = {}
    for p in pairs or []:
        if not isinstance(p, dict) or "baseToken" not in p:
            continue
        key = (p.get("chainId"), p["baseToken"]["address"])
        cur = best.get(key)
        rank = ((p.get("liquidity") or {}).get("usd") or 0, (p.get("volume") or {}).get("h24") or 0)
        if cur is None or rank > ((cur.get("liquidity") or {}).get("usd") or 0, (cur.get("volume") or {}).get("h24") or 0):
            best[key] = p
    return best


def fetch_pairs(net, chain, addresses):
    out = []
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i + 30]
        data = net.get("%s/tokens/v1/%s/%s" % (DS, chain, ",".join(chunk)), required=False)
        if isinstance(data, dict):
            data = data.get("pairs")
        out.extend(data or [])
    return out


def build_universe(net, chains, now, gecko=True):
    seen = {}
    counts = {}
    for name, path in LISTS:
        rows = net.get(DS + path, required=False) or []
        if isinstance(rows, dict):
            rows = rows.get("data") or []
        n = 0
        for r in rows:
            chain, addr = r.get("chainId"), r.get("tokenAddress")
            if chain in chains and addr:
                seen.setdefault((chain, addr), set()).add(name)
                n += 1
        counts[name] = n
    if gecko:
        for chain in chains:
            netid = GECKO_NET.get(chain)
            if not netid:
                continue
            for name, path in (("gecko_trending", "/networks/%s/trending_pools" % netid),
                               ("gecko_new", "/networks/%s/new_pools" % netid)):
                data = net.get(GT + path, required=False)
                n = 0
                for pool in (data or {}).get("data") or []:
                    rel = ((pool.get("relationships") or {}).get("base_token") or {}).get("data") or {}
                    tid = rel.get("id") or ""
                    addr = tid.split("_", 1)[1] if "_" in tid else None
                    if addr:
                        seen.setdefault((chain, addr), set()).add(name)
                        n += 1
                counts[name] = n if data is not None else "skipped (no answer, rate limit?)"
    rows = []
    for chain in chains:
        addrs = sorted(a for (c, a) in seen if c == chain)
        best = best_pairs(fetch_pairs(net, chain, addrs))
        for a in addrs:
            p = best.get((chain, a))
            if p is None:
                continue
            row = summarize(p, now)
            row["sources"] = sorted(seen[(chain, a)])
            rows.append(row)
    return {"as_of": now, "chains": list(chains), "lists": counts, "tokens_seen": len(seen),
            "tokens": sorted(rows, key=lambda r: -(r["volume"]["h1"] or 0))}


# ---------------------------------------------------------------- pairs scan

def tag_setups(r):
    ch, vol, tx = r["change"], r["volume"], r["txns"]
    h6_hour = (vol["h6"] or 0) / 6.0
    tags = []
    if (ch["h1"] or 0) >= 5 and (ch["m5"] or 0) >= 0 and tx["h1"][0] > tx["h1"][1] and vol["h1"] >= h6_hour > 0:
        tags.append("momentum")
    if h6_hour > 0 and vol["h1"] >= 2 * h6_hour:
        tags.append("volume_surge")
    if (ch["h24"] or 0) >= 20 and ch["h1"] is not None and -15 <= ch["h1"] <= -3 and (ch["m5"] or 0) >= 0:
        tags.append("dip")
    if r["age_hours"] is not None and r["age_hours"] <= 24:
        tags.append("new_pool")
    return tags


def scan_pairs(universe, cfg, a, now):
    rows = universe["tokens"]
    stats = {"universe": len(rows), "with_pool": 0, "liquid": 0, "washed": 0, "curve": 0, "hits": 0}
    hits, liquid = [], []
    for r in rows:
        if r["dex"] in CURVES and not r["liquidity_usd"]:
            stats["curve"] += 1
            if not a.include_curve:
                continue
        else:
            stats["with_pool"] += 1
        if (r["liquidity_usd"] or 0) < a.min_liquidity and not (a.include_curve and r["dex"] in CURVES):
            continue
        if r["age_hours"] is None or r["age_hours"] < a.min_age_hours:
            continue
        if (r["market_cap"] or 0) < a.min_mcap or (a.max_mcap and (r["market_cap"] or 0) > a.max_mcap):
            continue
        if sum(r["txns"]["h1"]) < a.min_txns:
            continue
        if r["liquidity_usd"] and r["volume"]["h24"] / r["liquidity_usd"] > a.max_turnover:
            stats["washed"] += 1
            continue
        stats["liquid"] += 1
        liquid.append(r)
        tags = tag_setups(r)
        if a.setup:
            tags = [t for t in tags if t in a.setup.split(",")]
        if tags:
            hit = dict(r)
            hit["setups"] = tags
            hits.append(hit)
    stats["hits"] = len(hits)
    hits.sort(key=lambda h: -(h["volume"]["h1"] or 0))
    return stats, hits, liquid


# ---------------------------------------------------------------- range scan (1-minute bars)

def parse_bars(obj):
    """Jupiter {"candles": [...]} or GeckoTerminal {"data": {"attributes": {"ohlcv_list": [...]}}} -> ascending bars."""
    out = {}
    if isinstance(obj, dict) and "candles" in obj:
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


def bars_url(row, now, n):
    if row["chain"] == "solana":
        return JUP_CHART % (row["address"], now * 1000, n)
    netid = GECKO_NET.get(row["chain"], row["chain"])
    return "%s/networks/%s/pools/%s/ohlcv/minute?aggregate=1&limit=%d&currency=usd&before_timestamp=%d" % (
        GT, netid, row["pair"], n, now)


def find_breakout(bars, now, range_minutes=15, fresh=10, vol_x=1.5):
    """The first of the last `fresh` completed 1-minute bars that closed above the high of the
    `range_minutes` bars before it, with volume >= vol_x times their average. None if none."""
    done = [b for b in bars if b["t"] + 60 <= now]
    if len(done) < range_minutes + 1:
        return None
    start = max(range_minutes, len(done) - fresh)
    for k in range(start, len(done)):
        rng = done[k - range_minutes:k]
        if rng[-1]["t"] != done[k]["t"] - 60 or rng[0]["t"] != done[k]["t"] - 60 * range_minutes:
            continue  # a gap in the minutes: no clean range
        hi = max(b["h"] for b in rng)
        lo = min(b["l"] for b in rng)
        avg = sum(b["v"] for b in rng) / float(range_minutes)
        b = done[k]
        if b["c"] > hi and (vol_x <= 0 or (avg > 0 and b["v"] >= vol_x * avg)):
            return {"range_start": rng[0]["t"], "range_end": b["t"], "range_high": hi, "range_low": lo,
                    "bar_time": b["t"], "close_time": b["t"] + 60, "close": b["c"],
                    "over_pct": round((b["c"] / hi - 1) * 100, 2), "vol_x": round(b["v"] / avg, 1) if avg else None,
                    "last_close": done[-1]["c"], "last_time": done[-1]["t"] + 60}
    return None


def scan_range(net, cands, a, now):
    hits, failed = [], 0
    for row in cands:
        data = net.get(bars_url(row, now, a.range_minutes + a.fresh + 5), required=False)
        bars = parse_bars(data) if data else []
        if not bars:
            failed += 1
            continue
        hit = find_breakout(bars, now, a.range_minutes, a.fresh, a.vol_x)
        if hit:
            h = dict(row)
            h.update(hit)
            h["setups"] = ["range_breakout"]
            hits.append(h)
    hits.sort(key=lambda h: h["bar_time"])
    return hits, failed


# ---------------------------------------------------------------- edge: the rule's own history on each coin

def sibling(folder, name):
    """Load a tool from a sibling skill folder, or None if it is not installed next to this one."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", folder, name + ".py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("meme_sibling_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def round_trip_pct(cfg):
    v = (cfg.get("venues") or {}).get(str(cfg.get("venue", "")).lower()) or {}
    fee = float(v.get("fee_pct", cfg.get("fee_pct", 0.85)))
    return 2 * (fee + float(cfg.get("slippage_pct", 0.3)) + float(cfg.get("pool_fee_pct", 0.5)))


def add_edge(hits, cfg, now, days=3.0, limit=10, bundle=None):
    """The default range-breakout rule (15 minutes, range-low stop, 3R, 60-minute time stop) replayed on each hit's
    own last days, after your app's costs. Sorts the hits by it. Returns a note when it cannot run."""
    tm = sibling("meme-timemachine", "timemachine")
    if tm is None:
        return "edge skipped: meme-timemachine is not installed next to the scanner"
    rule = {"range_minutes": 15, "vol_x": 1.5, "max_wait": 60, "target_r": 3.0, "stop_rule": "range-low",
            "risk_pct": 4.0, "round_trip_pct": round_trip_pct(cfg), "setup": "range"}
    for h in hits[:limit]:
        try:
            if bundle is not None:
                bars = tm.parse_bars(bundle.get(h["address"]) or {})
            else:
                bars = tm.fetch_history({"address": h["address"], "chain": h.get("chain", "solana"), "pair": h.get("pair"),
                                         "entry_time": now}, days)
        except tm.TMError:
            bars = []
        rows = [b for b in bars if b["t"] + 60 <= now]
        if len(rows) < 600:
            h["edge"] = {"trades": 0, "avg_r_net": None, "note": "too few bars"}
            continue
        res = tm.history({}, rows, 60, {}, rule)
        h["edge"] = {"trades": res["fired"], "avg_r_net": res.get("avg_r_net"),
                     "days": round((rows[-1]["t"] - rows[0]["t"] + 60) / 86400.0, 1)}
    hits.sort(key=lambda x: -((x.get("edge") or {}).get("avg_r_net") if (x.get("edge") or {}).get("avg_r_net") is not None else -99))
    return None


def edge_text(h):
    e = h.get("edge")
    if not e:
        return ""
    if e.get("avg_r_net") is None:
        return "edge: n/a (%s)" % (e.get("note") or "%d past trades" % e.get("trades", 0))
    return "edge: %+.2fR after costs over %d past breakouts (%.1f days)%s" % (
        e["avg_r_net"], e["trades"], e.get("days") or 0, "" if e["avg_r_net"] > 0 else "  LOST MONEY")


# ---------------------------------------------------------------- output

def _k(v):
    if v is None:
        return "n/a"
    v = float(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if v >= div:
            return "%.1f%s" % (v / div, suf)
    return "%.0f" % v


def fp(p):
    if p is None:
        return "n/a"
    p = float(p)
    if p <= 0:
        return "0"
    e = int(("%e" % p).split("e")[1])
    return "%.*f" % (max(0, 4 - e), p)


def _c(v):
    return "  n/a" if v is None else "%+5.1f%%" % v


def main(argv=None):
    ap = argparse.ArgumentParser(description="Meme coin scanner (meme-scanner). Lists rule matches, never trades.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("universe", "pairs", "range"):
        p = sub.add_parser(name)
        p.add_argument("--chains", help="comma list, default from meme/config.json (solana)")
        p.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
        p.add_argument("--offline", help="replay a saved bundle (.json or .json.gz)")
        p.add_argument("--save", help="also save every response to this bundle file")
        p.add_argument("--no-write", action="store_true")
        p.add_argument("--json", action="store_true")
        p.add_argument("--show", type=int, default=15)
        p.add_argument("--no-gecko", action="store_true", help="skip GeckoTerminal's trending and new pools")
        p.add_argument("--min-liquidity", type=float)
        p.add_argument("--min-age-hours", type=float)
        p.add_argument("--min-mcap", type=float, default=100000)
        p.add_argument("--max-mcap", type=float)
        p.add_argument("--min-txns", type=int, default=100, help="buys + sells in the last hour")
        p.add_argument("--max-turnover", type=float)
        p.add_argument("--include-curve", action="store_true", help="keep tokens still on a bonding curve")
        p.add_argument("--setup", help="only these setups: momentum,volume_surge,dip,new_pool")
        p.add_argument("--tokens", help="range: comma list of addresses to check instead of the watchlist")
        p.add_argument("--watchlist", help="range: candidates from this watchlist (default meme/watchlist.json)")
        p.add_argument("--max-confirm", type=int, default=25)
        p.add_argument("--range-minutes", type=int, default=15)
        p.add_argument("--fresh", type=int, default=10, help="range: look at the last N completed bars")
        p.add_argument("--vol-x", type=float, default=1.5, help="range: breakout bar volume vs the range average")
        p.add_argument("--edge", action="store_true", help="replay the breakout rule on each hit's last 3 days, sort by it")
        p.add_argument("--edge-max", type=int, default=10)
        p.add_argument("--edge-offline", help="saved bars for --edge, {mint: {candles: [...]}}")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    cfg.update(load(os.path.join(mdir(), "config.json"), {}) or {})
    tz = cfg.get("timezone") or "UTC"
    chains = a.chains.split(",") if a.chains else list(cfg.get("chains") or ["solana"])
    a.min_liquidity = a.min_liquidity if a.min_liquidity is not None else float(cfg["min_liquidity_usd"])
    a.min_age_hours = a.min_age_hours if a.min_age_hours is not None else float(cfg["min_pool_age_hours"])
    a.max_turnover = a.max_turnover if a.max_turnover is not None else float(cfg["max_turnover"])
    try:
        net = Net(a.offline, record=bool(a.save))
        now = parse_now(a.now, tz)
        if a.offline and not a.now:
            now = int(net.bundle.get("now") or now)
        code = run(a, net, cfg, chains, tz, now)
    except ScanError as e:
        print("Scan did not run: %s" % e)
        return 1
    if a.save:
        save(a.save, {"now": now, "tz": tz, "responses": net.recorded})
    return code


def run(a, net, cfg, chains, tz, now):
    upath = os.path.join(mdir(), "universe.json")
    stamp = local_str(now, tz, "%a %Y-%m-%d %H:%M")
    if a.cmd == "universe":
        uni = build_universe(net, chains, now, gecko=not a.no_gecko)
        if not a.no_write:
            save(upath, uni)
        if a.json:
            print(json.dumps(uni, indent=2))
            return 0 if uni["tokens"] else 1
        print("Universe at %s (%s): %d tokens seen on %s, %d with a DexScreener pool." % (
            stamp, tz, uni["tokens_seen"], ", ".join(chains), len(uni["tokens"])))
        print("  lists: " + ", ".join("%s %s" % (k, v) for k, v in uni["lists"].items()))
        return 0 if uni["tokens"] else 1

    if a.cmd == "pairs":
        old = load(upath)
        if old and old.get("tokens") and now - int(old.get("as_of", 0)) < 6 * 3600 and not a.offline:
            uni = {"as_of": now, "chains": chains, "lists": old.get("lists", {}), "tokens_seen": old.get("tokens_seen")}
            rows = []
            for chain in chains:
                addrs = [t["address"] for t in old["tokens"] if t["chain"] == chain]
                best = best_pairs(fetch_pairs(net, chain, addrs))
                for t in old["tokens"]:
                    p = best.get((chain, t["address"]))
                    if p is not None:
                        r = summarize(p, now)
                        r["sources"] = t.get("sources", [])
                        rows.append(r)
            uni["tokens"] = rows
        else:
            uni = build_universe(net, chains, now, gecko=not a.no_gecko)
        if not a.no_write:
            save(upath, uni)
        stats, hits, _ = scan_pairs(uni, cfg, a, now)
        note = add_edge(hits, cfg, now, limit=a.edge_max, bundle=load(a.edge_offline) if a.edge_offline else None) if a.edge else None
        wl = {"mode": "pairs", "as_of": now, "chains": chains, "stats": stats,
              "filters": {"min_liquidity_usd": a.min_liquidity, "min_age_hours": a.min_age_hours,
                          "min_mcap": a.min_mcap, "min_txns_h1": a.min_txns, "max_turnover": a.max_turnover},
              "hits": hits}
        if not a.no_write:
            save(os.path.join(mdir(), "watchlist.json"), wl)
        if a.json:
            print(json.dumps(wl, indent=2))
            return 0 if hits else 1
        print("Pairs scan at %s (%s), DexScreener stats:" % (stamp, tz))
        print("  %d tokens in the universe, %d with a pool, %d still on a bonding curve (left out)." % (
            stats["universe"], stats["with_pool"], stats["curve"]))
        print("  %d passed the filters (liquidity >= $%s, pool >= %sh old, market cap >= $%s, >= %d trades in the "
              "last hour); %d left out as washed (24h volume over %sx liquidity)." % (
                  stats["liquid"], _k(a.min_liquidity), ("%g" % a.min_age_hours), _k(a.min_mcap), a.min_txns,
                  stats["washed"], ("%g" % a.max_turnover)))
        print("%d matched a setup, most traded in the last hour first:" % len(hits))
        for h in hits[:a.show]:
            print("  %-10s $%-11s liq $%-6s mcap $%-6s 5m %s 1h %s 24h %s  %s" % (
                (h["symbol"] or "?")[:10], fp(h["price_usd"]), _k(h["liquidity_usd"]), _k(h["market_cap"]),
                _c(h["change"]["m5"]), _c(h["change"]["h1"]), _c(h["change"]["h24"]), ",".join(h["setups"])))
            print("             %s  %s" % (h["address"], edge_text(h)))
        if note:
            print(note)
        elif a.edge:
            print("Sorted by edge: the range-breakout rule replayed on each coin's own last days, after your costs.")
        if len(hits) > a.show:
            print("  ... %d more in meme/watchlist.json" % (len(hits) - a.show))
        return 0 if hits else 1

    # range
    if a.tokens:
        cands = []
        for chain in chains:
            best = best_pairs(fetch_pairs(net, chain, a.tokens.split(",")))
            cands.extend(summarize(p, now) for p in best.values())
    elif a.watchlist:
        wl = load(a.watchlist)
        if not wl or not wl.get("hits"):
            raise ScanError("%s has no hits" % a.watchlist)
        cands = wl["hits"]
    else:
        uni = load(upath)
        if a.offline or not uni or now - int(uni.get("as_of", 0)) > 900:
            uni = build_universe(net, chains, now, gecko=not a.no_gecko)
            if not a.no_write:
                save(upath, uni)
        _, _, cands = scan_pairs(uni, cfg, a, now)
        if not cands:
            raise ScanError("no token in the universe passed the liquidity filters; nothing to chart")
    cands = sorted(cands, key=lambda r: -((r.get("volume") or {}).get("h1") or 0))
    skipped = max(0, len(cands) - a.max_confirm) if a.max_confirm else 0
    if a.max_confirm:
        cands = cands[:a.max_confirm]
    hits, failed = scan_range(net, cands, a, now)
    note = add_edge(hits, cfg, now, limit=a.edge_max, bundle=load(a.edge_offline) if a.edge_offline else None) if a.edge else None
    wl = {"mode": "range", "as_of": now, "chains": chains, "range_minutes": a.range_minutes, "fresh": a.fresh,
          "vol_x": a.vol_x, "checked": len(cands), "failed": failed, "skipped": skipped, "hits": hits}
    if not a.no_write:
        save(os.path.join(mdir(), "watchlist.json"), wl)
    if a.json:
        print(json.dumps(wl, indent=2))
        return 0 if hits else 1
    print("Range scan at %s (%s), 1-minute bars:" % (stamp, tz))
    print("  checked %d charts (%d had no bars)%s." % (len(cands), failed,
                                                       ("; PARTIAL: %d more candidates not checked (--max-confirm)" % skipped) if skipped else ""))
    print("%d closed above the high of the %d minutes before, on volume >= %gx, in the last %d bars:" % (
        len(hits), a.range_minutes, a.vol_x, a.fresh))
    for h in hits[:a.show]:
        print("  %s  %-10s $%-11s range %s to %s (%s to %s)  +%.2f%% over, volume %sx" % (
            local_str(h["close_time"], tz), (h["symbol"] or "?")[:10], fp(h["close"]), fp(h["range_low"]),
            fp(h["range_high"]), local_str(h["range_start"], tz), local_str(h["range_end"], tz),
            h["over_pct"], h["vol_x"]))
        print("         %s  now $%s  %s" % (h["address"], fp(h["last_close"]), edge_text(h)))
    if note:
        print(note)
    elif a.edge and hits:
        print("Sorted by edge: the same breakout rule replayed on each coin's own last days, after your costs.")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
