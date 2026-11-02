#!/usr/bin/env python3
"""The News Monitor (meme-news). Standard library only.

What is moving the meme coins you watch, and the market around them:

  - crypto headlines from public RSS feeds (Cointelegraph, Decrypt, CoinDesk)
    that name your coin, plus the market headlines that move all of them
    (exchange hacks, listings, regulation, SOL and BTC);
  - DexScreener events for each coin: paid boosts, a new token profile, a
    community takeover;
  - each coin's move now (5 minutes, 1 hour, 6 hours, 24 hours) and its pool's
    liquidity, compared with your last check: a pool that is draining is the
    first sign of a rug.

Shows only what is new since the last check, newest first, in your time zone,
tags each item and never repeats one.

    python3 news.py                          # coins in plan, entry, watchlist and portfolio
    python3 news.py --tokens MINT1,MINT2 --hours 12
    python3 news.py --market                 # market headlines only
    python3 news.py --all                    # repeat what was already shown
"""

import argparse
import calendar
import datetime
import email.utils
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import html as htmllib
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (compatible; meme-trader-skill/1.0; +https://github.com/bn194/meme-trader-skill)"
FEEDS = (("Cointelegraph", "https://cointelegraph.com/rss", "cointelegraph.xml"),
         ("Decrypt", "https://decrypt.co/feed", "decrypt.xml"),
         ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "coindesk.xml"))
DS = "https://api.dexscreener.com"
DS_LISTS = (("boost", "/token-boosts/latest/v1", "boosts_latest.json"),
            ("boost", "/token-boosts/top/v1", "boosts_top.json"),
            ("profile", "/token-profiles/latest/v1", "profiles.json"),
            ("cto", "/community-takeovers/latest/v1", "cto.json"))
TAGS = (("hack", r"\b(hack|hacked|hacker|exploit|drain(ed)?|stolen|phishing|attacker)"),
        ("rug", r"\b(rug|rugpull|rug pull|scam|honeypot|exit scam)"),
        ("listing", r"\b(lists|listing|listed|delist\w*)\b"),
        ("exchange", r"\b(binance|coinbase|upbit|bybit|okx|kraken|robinhood|bithumb)\b"),
        ("whale", r"\b(whale|dump(ed|s)?|sell-off|selloff|liquidat\w*)"),
        ("launch", r"\b(launch\w*|airdrop|tge|unlock\w*)\b"),
        ("regulatory", r"\b(sec|cftc|regulat\w*|lawsuit|ban(s|ned)?|court|senate|bill|fbi|doj)\b"),
        ("macro", r"\b(fed|rates?|inflation|cpi|etf|tariff\w*|treasury|gold)\b"),
        ("memecoin", r"\b(meme ?coins?|pump\.?fun|bonk|wif|pepe|doge\w*|trump coin|letsbonk)\b"),
        ("solana", r"\b(solana|sol)\b"),
        ("bitcoin", r"\b(bitcoin|btc)\b"))
MARKET_TAGS = {"hack", "listing", "exchange", "regulatory", "macro", "memecoin", "solana", "whale"}
LIQ_DRAIN_PCT = 20.0


class NewsError(Exception):
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


def local_str(ts, tz, fmt="%a %H:%M"):
    return time.strftime(fmt, time.gmtime(ts + utc_offset(ts, tz) * 60))


def parse_now(text, tz):
    if not text:
        return int(time.time())
    dt = datetime.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    guess = calendar.timegm(dt.timetuple())
    return guess - utc_offset(guess - utc_offset(guess, tz) * 60, tz) * 60


def fetch(url, as_json=True):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, application/rss+xml, */*"})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8")) if as_json else raw
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < 2:
                time.sleep(4 * (i + 1))
                continue
            return None
        except (urllib.error.URLError, OSError, ValueError):
            if i == 2:
                return None
            time.sleep(2)


def fp(p):
    if p is None:
        return "n/a"
    p = float(p)
    if p <= 0:
        return "0"
    e = int(("%e" % p).split("e")[1])
    return "%.*f" % (max(0, 4 - e), p)


def money(v):
    return "${:,.0f}".format(v) if v is not None else "n/a"


# ---------------------------------------------------------------- parsing

def parse_rss(raw, source):
    """RSS 2.0 bytes -> [{id, time, source, title, link, summary}]."""
    out = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        when = it.findtext("pubDate")
        try:
            ts = int(email.utils.mktime_tz(email.utils.parsedate_tz(when))) if when else None
        except (TypeError, ValueError, OverflowError):
            ts = None
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        out.append({"id": hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:16], "time": ts,
                    "source": source, "title": title, "link": link, "summary": desc[:300]})
    return out


def parse_tg(raw, channel):
    """A public channel's web preview (t.me/s/NAME) -> (posts, subscribers). Posts: id, time, text, views."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else (raw or "")
    posts = []
    for block in re.split(r'<div class="tgme_widget_message_wrap', text)[1:]:
        pid = re.search(r'data-post="([^"]+)"', block)
        when = re.search(r'<time datetime="([^"]+)"', block)
        body = re.search(r'<div class="tgme_widget_message_text js-message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        views = re.search(r'tgme_widget_message_views">([^<]+)<', block)
        ts = None
        if when:
            try:
                ts = calendar.timegm(time.strptime(when.group(1)[:19], "%Y-%m-%dT%H:%M:%S"))
                off = re.search(r"([+-])(\d\d):(\d\d)$", when.group(1))
                if off:
                    ts -= (1 if off.group(1) == "+" else -1) * (int(off.group(2)) * 3600 + int(off.group(3)) * 60)
            except ValueError:
                ts = None
        msg = ""
        if body:
            msg = re.sub(r"<br\s*/?>", "\n", body.group(1))
            msg = htmllib.unescape(re.sub(r"<[^>]+>", "", msg)).strip()
        posts.append({"id": "tg:" + (pid.group(1) if pid else "%s/%s" % (channel, ts)), "channel": channel, "time": ts,
                      "text": msg, "views": views.group(1) if views else None})
    subs = re.search(r'counter_value">([^<]+)</span> <span class="counter_type">(subscribers|members)', text)
    return posts, (subs.group(1) if subs else None)


SOL_ADDR = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")


def tag(text):
    low = text.lower()
    return [name for name, rx in TAGS if re.search(rx, low)]


def mentions(item, tok):
    """Does a headline name this coin? Its ticker as a word ($GATO or GATO, 3+ letters) or its name (4+ letters)."""
    text = item["title"] + " " + item.get("summary", "")
    sym = (tok.get("symbol") or "").strip()
    name = (tok.get("name") or "").strip()
    if len(sym) >= 3 and re.search(r"(?<![A-Za-z0-9])\$?%s(?![A-Za-z0-9])" % re.escape(sym), text):
        return True
    if len(name) >= 4 and re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(name), text, re.I):
        return True
    return False


def best_pairs(pairs):
    best = {}
    for p in pairs or []:
        if not isinstance(p, dict) or "baseToken" not in p:
            continue
        a = p["baseToken"]["address"]
        if a not in best or ((p.get("liquidity") or {}).get("usd") or 0) > ((best[a].get("liquidity") or {}).get("usd") or 0):
            best[a] = p
    return best


# ---------------------------------------------------------------- gathering

def watched(base):
    """(chain, address, symbol) for the coins in the plan, entry, watchlist and portfolio."""
    out = {}
    for f in ("plan.json", "entry.json"):
        d = load(os.path.join(base, f))
        if d and d.get("address"):
            out[d["address"]] = (d.get("chain", "solana"), d.get("symbol"))
    for h in (load(os.path.join(base, "watchlist.json"), {}) or {}).get("hits", [])[:20]:
        out.setdefault(h["address"], (h.get("chain", "solana"), h.get("symbol")))
    for a, pos in ((load(os.path.join(base, "portfolio.json"), {}) or {}).get("positions") or {}).items():
        out.setdefault(a, ("solana", pos.get("symbol")))
    return [(c, a, s) for a, (c, s) in out.items()]


def gather_telegram(channels, now, hours, offline=None):
    """Recent posts of the public channels you follow -> (posts, failed, subscribers)."""
    since = now - int(hours * 3600)
    posts, failed, subs = [], [], {}
    for ch in channels or []:
        ch = ch.strip().lstrip("@").split("/")[-1]
        if not ch:
            continue
        if offline:
            path = os.path.join(offline, "tg-%s.html" % ch)
            raw = open(path, "rb").read() if os.path.exists(path) else None
        else:
            raw = fetch("https://t.me/s/%s" % ch, as_json=False)
        if not raw:
            failed.append("t.me/" + ch)
            continue
        got, n = parse_tg(raw, ch)
        if not got:
            failed.append("t.me/%s (no public preview)" % ch)
        subs[ch] = n
        posts.extend(p for p in got if p["time"] is None or since <= p["time"] <= now + 300)
    return posts, failed, subs


def gather(tokens, now, hours, offline=None, market=True):
    def get(url, fname, as_json=True):
        if offline:
            path = os.path.join(offline, fname)
            if not os.path.exists(path):
                return None
            if as_json:
                return load(path)
            with open(path, "rb") as fh:
                return fh.read()
        return fetch(url, as_json)

    since = now - int(hours * 3600)
    headlines, failed = [], []
    for source, url, fname in FEEDS:
        raw = get(url, fname, as_json=False)
        if not raw:
            failed.append(source)
            continue
        for it in parse_rss(raw, source):
            if it["time"] is None or since <= it["time"] <= now + 300:
                it["tags"] = tag(it["title"] + " " + it["summary"])
                headlines.append(it)
    pairs = []
    by_chain = {}
    for chain, addr, _ in tokens:
        by_chain.setdefault(chain, []).append(addr)
    for chain, addrs in by_chain.items():
        for i in range(0, len(addrs), 30):
            data = get("%s/tokens/v1/%s/%s" % (DS, chain, ",".join(addrs[i:i + 30])), "dex.json")
            pairs.extend(data if isinstance(data, list) else (data or {}).get("pairs") or [])
    best = best_pairs(pairs)
    lists = {}
    for kind, path, fname in DS_LISTS:
        rows = get(DS + path, fname) or []
        for r in rows if isinstance(rows, list) else []:
            if r.get("tokenAddress"):
                lists.setdefault(r["tokenAddress"], []).append((kind, r))
    coins = []
    for chain, addr, sym in tokens:
        p = best.get(addr)
        tok = {"chain": chain, "address": addr, "symbol": sym, "name": None}
        if p:
            tok.update(symbol=p["baseToken"].get("symbol") or sym, name=p["baseToken"].get("name"),
                       price=float(p["priceUsd"]) if p.get("priceUsd") else None,
                       liquidity_usd=(p.get("liquidity") or {}).get("usd"), change=p.get("priceChange") or {},
                       market_cap=p.get("marketCap"), boosts=(p.get("boosts") or {}).get("active") or 0)
        items = []
        for it in headlines:
            if mentions(it, tok):
                items.append(dict(it, token=addr))
        seen_kinds = set()
        for kind, r in lists.get(addr, []):
            if kind in seen_kinds:
                continue
            seen_kinds.add(kind)
            if kind == "boost":
                text = "paid DexScreener boost: %s active (promotion, not demand)" % (tok.get("boosts") or r.get("totalAmount") or r.get("amount"))
                tags = ["promo"]
            elif kind == "profile":
                text = "new DexScreener token profile%s" % ((": " + r["description"][:90]) if r.get("description") else "")
                tags = ["promo"]
            else:
                text = "community takeover (CTO) listed on DexScreener: the original team may be gone"
                tags = ["cto"]
            items.append({"id": hashlib.sha1(("%s-%s-%s" % (addr, kind, r.get("totalAmount") or r.get("description") or "")).encode("utf-8")).hexdigest()[:16],
                          "time": None, "source": "DexScreener", "title": text, "link": r.get("url"), "tags": tags,
                          "token": addr})
        tok["items"] = items
        coins.append(tok)
    market_items = [it for it in headlines if MARKET_TAGS & set(it["tags"])] if market else []
    return coins, market_items, failed


def telegram_section(coins, posts, subs, tz, hours, show_all, seen, fresh_ids):
    out = ["Telegram, %d channel%s, last %g hours (%d posts):" % (len(subs), "" if len(subs) == 1 else "s", hours, len(posts))]
    for c in coins:
        hits = [p for p in posts if c["address"] in p["text"] or mentions({"title": p["text"], "summary": ""}, c)]
        if hits:
            chans = sorted(set(p["channel"] for p in hits))
            out.append("  %s named in %d post%s in %s" % (c.get("symbol") or c["address"][:8], len(hits),
                                                         "" if len(hits) == 1 else "s", ", ".join(chans)))
            for p in sorted(hits, key=lambda x: -(x["time"] or 0))[:3]:
                if show_all or p["id"] not in seen:
                    fresh_ids.append(p["id"])
                    out.append("    %s t.me/%s: %s" % (local_str(p["time"], tz) if p["time"] else "?", p["channel"],
                                                       p["text"].replace("\n", " ")[:140]))
    counts = {}
    for p in posts:
        for a in set(SOL_ADDR.findall(p["text"])):
            counts.setdefault(a, set()).add(p["id"])
    top = sorted(counts.items(), key=lambda kv: -len(kv[1]))[:5]
    if top:
        out.append("  contract addresses posted most: " + ", ".join("%s (%d)" % (a, len(v)) for a, v in top))
    new = [p for p in sorted(posts, key=lambda x: -(x["time"] or 0)) if show_all or p["id"] not in seen][:5]
    for p in new:
        fresh_ids.append(p["id"])
        out.append("  %-9s t.me/%s%s: %s" % (local_str(p["time"], tz) if p["time"] else "?", p["channel"],
                                            (" (%s views)" % p["views"]) if p.get("views") else "", p["text"].replace("\n", " ")[:120]))
    out.append("  Calls in channels are often paid or the poster's own bags. A mention is a fact, not a reason to buy.")
    return out


def render(coins, market_items, failed, prev, now, tz, hours, show_all, seen, tg=None):
    out = []
    fresh_ids = []
    for c in coins:
        head = "%s (%s)" % (c.get("symbol") or "?", c["address"])
        out.append(head)
        if c.get("price") is not None:
            ch = c.get("change") or {}
            line = "  now $%s at %s: 5m %s, 1h %s, 6h %s, 24h %s; pool liquidity %s" % (
                fp(c["price"]), local_str(now, tz, "%H:%M"), _pc(ch.get("m5")), _pc(ch.get("h1")), _pc(ch.get("h6")),
                _pc(ch.get("h24")), money(c.get("liquidity_usd")))
            out.append(line)
            p = (prev or {}).get(c["address"])
            if p and p.get("liquidity_usd") and c.get("liquidity_usd") is not None:
                drop = (1 - c["liquidity_usd"] / p["liquidity_usd"]) * 100
                if drop >= LIQ_DRAIN_PCT:
                    out.append("  [rug] RUG WARNING: liquidity down %.0f%% since your last check at %s (%s -> %s)" % (
                        drop, local_str(p["ts"], tz, "%H:%M"), money(p["liquidity_usd"]), money(c["liquidity_usd"])))
                else:
                    out.append("  since your last check at %s: price %+.1f%%, liquidity %+.1f%%" % (
                        local_str(p["ts"], tz, "%H:%M"), (c["price"] / p["price"] - 1) * 100 if p.get("price") else 0.0,
                        (c["liquidity_usd"] / p["liquidity_usd"] - 1) * 100))
        else:
            out.append("  no DexScreener pool found")
        items = [it for it in c["items"] if show_all or it["id"] not in seen]
        items.sort(key=lambda it: -(it.get("time") or now))
        for it in items:
            fresh_ids.append(it["id"])
            when = local_str(it["time"], tz) if it.get("time") else "now"
            out.append("  %-9s [%s] %s (%s)" % (when, ", ".join(it["tags"]) or "news", it["title"], it["source"]))
        if not items:
            out.append("  no new headline names it in the last %g hours" % hours)
    if market_items:
        items = [it for it in market_items if show_all or it["id"] not in seen]
        items.sort(key=lambda it: -(it.get("time") or 0))
        out.append("Market, last %g hours (%d new):" % (hours, len(items)))
        for it in items[:8]:
            fresh_ids.append(it["id"])
            out.append("  %-9s [%s] %s (%s)" % (local_str(it["time"], tz) if it.get("time") else "?",
                                               ", ".join(t for t in it["tags"] if t in MARKET_TAGS), it["title"], it["source"]))
        if len(items) > 8:
            out.append("  ... %d more" % (len(items) - 8))
    if tg is not None:
        out.extend(telegram_section(coins, tg[0], tg[2], tz, hours, show_all, seen, fresh_ids))
        failed = list(failed) + list(tg[1])
    if failed:
        out.append("Could not read: %s (the other sources are complete)." % ", ".join(failed))
    out.append("Headlines are context, not signals. A coin that is in the news is often a coin that already moved.")
    return "\n".join(out), fresh_ids


def _pc(v):
    return "n/a" if v is None else "%+.1f%%" % float(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description="News monitor (meme-news). Reads, never trades.")
    ap.add_argument("--tokens", help="comma list of contract addresses (default: plan, entry, watchlist, portfolio)")
    ap.add_argument("--chain", default="solana")
    ap.add_argument("--hours", type=float, default=12)
    ap.add_argument("--market", action="store_true", help="market headlines only")
    ap.add_argument("--all", action="store_true", help="also show what was already shown")
    ap.add_argument("--telegram", help="comma list of public Telegram channels (default: telegram_channels in the config)")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
    ap.add_argument("--offline", help="a folder with saved feeds (cointelegraph.xml ...) and DexScreener files")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    base = mdir()
    cfg = load(os.path.join(base, "config.json"), {}) or {}
    tz = cfg.get("timezone") or "Europe/Berlin"
    now = parse_now(a.now, tz)
    if a.market:
        tokens = []
    elif a.tokens:
        tokens = [(a.chain, t.strip(), None) for t in a.tokens.split(",") if t.strip()]
    else:
        tokens = watched(base)
    if not tokens and not a.market:
        print("No coins to watch: give --tokens MINT, or run /meme-scanner first. Showing the market.")
    spath = os.path.join(base, "state", "news.json")
    state = load(spath, {"seen": [], "coins": {}}) or {"seen": [], "coins": {}}
    coins, market_items, failed = gather(tokens, now, a.hours, a.offline)
    channels = [] if a.no_telegram else (a.telegram.split(",") if a.telegram else list(cfg.get("telegram_channels") or []))
    tg = gather_telegram(channels, now, a.hours, a.offline) if channels else None
    if len(failed) == len(FEEDS) and not coins:
        print("No news source answered. Try again in a minute.")
        return 1
    text, fresh = render(coins, market_items, failed, state.get("coins"), now, tz, a.hours, a.all, set(state.get("seen", [])), tg)
    if a.json:
        print(json.dumps({"coins": coins, "market": market_items, "failed": failed}, indent=2))
    else:
        print(text)
    if not a.no_write:
        state["seen"] = (state.get("seen", []) + [i for i in fresh if i not in state.get("seen", [])])[-2000:]
        for c in coins:
            if c.get("price") is not None:
                state.setdefault("coins", {})[c["address"]] = {"ts": now, "price": c["price"], "liquidity_usd": c.get("liquidity_usd")}
        save(spath, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
