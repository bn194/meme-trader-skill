#!/usr/bin/env python3
"""Price Alerts (meme-alerts). Standard library only.

Rings when a meme coin hits your stop, your target, your time stop, or when
its pool's liquidity drops (the rug alarm). Each alert rings once. Prices and
liquidity come from DexScreener (free, no key, up to 30 coins a request),
and every check writes meme/prices.json for /meme-budget and /meme-risk.

    python3 alerts.py add --from-plan                  # stop, target, time stop, rug alarm (-30 % liquidity)
    python3 alerts.py add --token MINT --above 0.0081
    python3 alerts.py add --token MINT --below 0.0070
    python3 alerts.py add --token MINT --pct 15        # a 15 % move either way from now
    python3 alerts.py add --token MINT --at 23:30      # a reminder at a time (your time zone)
    python3 alerts.py add --token MINT --liq-drop 25   # liquidity down 25 % from now
    python3 alerts.py check                            # rings what hit, once
    python3 alerts.py watch --every 30                 # check until everything rang
    python3 alerts.py quote MINT --write               # price and liquidity now -> meme/prices.json
    python3 alerts.py list
    python3 alerts.py clear --token MINT
"""

import argparse
import calendar
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "meme-trader-skill/1.0 (+https://github.com/bn194/meme-trader-skill)"
DS_TOKENS = "https://api.dexscreener.com/tokens/v1/%s/%s"
JUP_PRICE = "https://lite-api.jup.ag/price/v3?ids=So11111111111111111111111111111111111111112"
SOL = "So11111111111111111111111111111111111111112"
DEFAULT_RUG_DROP = 30.0


class AlertError(Exception):
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


def local_str(ts, tz, fmt="%H:%M"):
    return time.strftime(fmt, time.gmtime(ts + utc_offset(ts, tz) * 60))


def parse_now(text, tz):
    if not text:
        return int(time.time())
    dt = datetime.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    guess = calendar.timegm(dt.timetuple())
    return guess - utc_offset(guess - utc_offset(guess, tz) * 60, tz) * 60


def parse_clock(text, now, tz):
    text = text.strip()
    if len(text) > 5:
        return parse_now(text, tz)
    h, m = [int(x) for x in text.split(":")]
    ts = parse_now("%s %02d:%02d" % (local_str(now, tz, "%Y-%m-%d"), h, m), tz)
    return ts + 86400 if ts <= now else ts


def get_json(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < 2:
                time.sleep(5 * (i + 1))
                continue
            raise AlertError("%s answered HTTP %d" % (url.split("/")[2], e.code))
        except (urllib.error.URLError, OSError, ValueError) as e:
            if i == 2:
                raise AlertError("could not read %s (%s)" % (url.split("/")[2], e))
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


# ---------------------------------------------------------------- quotes

def quotes_from_pairs(pairs, now):
    """DexScreener pairs -> {address: quote} using each token's most liquid pool."""
    best = {}
    for p in pairs or []:
        if not isinstance(p, dict) or "baseToken" not in p:
            continue
        a = p["baseToken"]["address"]
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if a not in best or liq > ((best[a].get("liquidity") or {}).get("usd") or 0):
            best[a] = p
    out = {}
    for a, p in best.items():
        created = p.get("pairCreatedAt")
        out[a] = {"symbol": p["baseToken"].get("symbol"), "chain": p.get("chainId"), "pair": p.get("pairAddress"),
                  "price": float(p["priceUsd"]) if p.get("priceUsd") else None,
                  "liquidity_usd": (p.get("liquidity") or {}).get("usd"), "market_cap": p.get("marketCap"),
                  "change": p.get("priceChange") or {}, "pool_created_at": int(created // 1000) if created else None,
                  "ts": now, "source": "DexScreener"}
    return out


def fetch_quotes(tokens, now, offline=None):
    """tokens: [(chain, address)] -> {address: quote}."""
    if offline:
        data = load(offline)
        pairs = []
        if isinstance(data, dict) and "responses" in data:
            for v in data["responses"].values():
                pairs.extend(v if isinstance(v, list) else (v or {}).get("pairs") or [])
        else:
            pairs = data if isinstance(data, list) else (data or {}).get("pairs") or []
        return quotes_from_pairs(pairs, now)
    out = {}
    by_chain = {}
    for chain, addr in tokens:
        by_chain.setdefault(chain, []).append(addr)
    for chain, addrs in by_chain.items():
        addrs = sorted(set(addrs))
        for i in range(0, len(addrs), 30):
            data = get_json(DS_TOKENS % (chain, ",".join(addrs[i:i + 30])))
            out.update(quotes_from_pairs(data if isinstance(data, list) else (data or {}).get("pairs"), now))
            time.sleep(0.25)
    return out


def write_prices(quotes, sol=None):
    path = os.path.join(mdir(), "prices.json")
    prices = load(path, {}) or {}
    prices.update(quotes)
    if sol:
        prices["SOL"] = sol
    save(path, prices)


# ---------------------------------------------------------------- the rules

def describe(al, tz):
    k = al["kind"]
    sym = al.get("symbol") or al["token"][:6]
    if k in ("above", "target"):
        return "%s %s at or above $%s" % (k, sym, fp(al["level"]))
    if k in ("below", "stop"):
        return "%s %s at or below $%s" % (k, sym, fp(al["level"]))
    if k == "pct":
        return "%s moves %g%% from $%s" % (sym, al["pct"], fp(al["base"]))
    if k == "time":
        return "time stop %s at %s" % (sym, local_str(al["at"], tz))
    if k == "liq_drop":
        return "rug alarm %s: pool liquidity down %g%% from %s" % (sym, al["pct"], money(al["base"]))
    return k


def evaluate(alerts, quotes, now, tz):
    """Pure: ring every alert that hit, once. Returns the messages and marks them rung."""
    msgs = []
    for al in alerts:
        if al.get("rang_at"):
            continue
        q = quotes.get(al["token"]) or {}
        price, liq = q.get("price"), q.get("liquidity_usd")
        sym = al.get("symbol") or q.get("symbol") or al["token"][:6]
        hit, text = False, None
        k = al["kind"]
        if k in ("above", "target") and price is not None and price >= al["level"]:
            hit = True
            text = "%s: %s $%s >= $%s at %s." % ("TARGET hit" if k == "target" else "ABOVE", sym, fp(price), fp(al["level"]), local_str(now, tz))
            if k == "target":
                text += " Take it: sell now in your app, or /meme-broker flatten."
        elif k in ("below", "stop") and price is not None and price <= al["level"]:
            hit = True
            text = "%s: %s $%s <= $%s at %s." % ("STOP hit" if k == "stop" else "BELOW", sym, fp(price), fp(al["level"]), local_str(now, tz))
            if k == "stop":
                text += " Get out now, no second thoughts: sell in your app, or /meme-broker flatten."
        elif k == "pct" and price is not None and al.get("base"):
            move = (price / al["base"] - 1) * 100
            if abs(move) >= al["pct"]:
                hit = True
                text = "MOVE: %s %+.1f%% from $%s to $%s at %s." % (sym, move, fp(al["base"]), fp(price), local_str(now, tz))
        elif k == "time" and now >= al["at"]:
            hit = True
            text = "TIME STOP %s: it is %s. If %s is still open, get out now, win or lose: /meme-broker flatten." % (
                local_str(al["at"], tz), local_str(now, tz), sym)
        elif k == "liq_drop" and liq is not None and al.get("base"):
            drop = (1 - liq / al["base"]) * 100
            if drop >= al["pct"]:
                hit = True
                text = ("RUG ALARM: %s pool liquidity %s, down %.0f%% from %s at %s. If you hold it, get out now; "
                        "if the pool is empty there may be no one to sell to." % (sym, money(liq), drop, money(al["base"]),
                                                                                   local_str(now, tz)))
        if hit:
            al["rang_at"] = now
            al["rang_price"] = price
            msgs.append(text)
    return msgs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price alerts (meme-alerts). Watches, never trades.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--from-plan", action="store_true")
    p.add_argument("--token")
    p.add_argument("--chain", default="solana")
    p.add_argument("--symbol")
    p.add_argument("--above", type=float)
    p.add_argument("--below", type=float)
    p.add_argument("--stop", type=float)
    p.add_argument("--target", type=float)
    p.add_argument("--pct", type=float)
    p.add_argument("--at")
    p.add_argument("--liq-drop", type=float)
    p.add_argument("--note")
    for name in ("check", "watch", "quote", "add"):
        q = p if name == "add" else sub.add_parser(name)
        if name == "quote":
            q.add_argument("token")
            q.add_argument("--chain", default="solana")
            q.add_argument("--write", action="store_true")
        if name == "watch":
            q.add_argument("--every", type=int, default=30)
            q.add_argument("--max-checks", type=int, default=600)
        q.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
        q.add_argument("--offline", help="saved DexScreener tokens/v1 JSON (or a bundle)")
        q.add_argument("--json", action="store_true")
    sub.add_parser("list")
    c = sub.add_parser("clear")
    c.add_argument("--token")
    c.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    cfg = load(os.path.join(mdir(), "config.json"), {}) or {}
    tz = cfg.get("timezone") or "Europe/Berlin"
    path = os.path.join(mdir(), "alerts.json")
    st = load(path, {"alerts": []}) or {"alerts": []}
    try:
        if a.cmd == "list":
            live = [x for x in st["alerts"] if not x.get("rang_at")]
            if not live:
                print("No open alerts.")
            for x in st["alerts"]:
                print("%s %s" % ("RANG " + local_str(x["rang_at"], tz) if x.get("rang_at") else "open      ", describe(x, tz)))
            return 0
        if a.cmd == "clear":
            before = len(st["alerts"])
            st["alerts"] = [] if a.all else [x for x in st["alerts"] if a.token and x["token"] != a.token and
                                             (x.get("symbol") or "").upper() != a.token.upper()]
            save(path, st)
            print("Cleared %d alert%s." % (before - len(st["alerts"]), "" if before - len(st["alerts"]) == 1 else "s"))
            return 0
        now = parse_now(a.now, tz)
        if a.cmd == "quote":
            q = fetch_quotes([(a.chain, a.token)], now, a.offline)
            if a.token not in q:
                raise AlertError("DexScreener has no pool for %s" % a.token)
            x = q[a.token]
            if a.write:
                write_prices({a.token: x})
            print(json.dumps(x, indent=2) if a.json else "%s $%s at %s, pool liquidity %s, market cap %s, 1h %s%%." % (
                x["symbol"], fp(x["price"]), local_str(now, tz), money(x["liquidity_usd"]), money(x["market_cap"]),
                (x["change"] or {}).get("h1")))
            return 0
        if a.cmd == "add":
            new = []
            if a.from_plan:
                plan = load(os.path.join(mdir(), "plan.json"))
                if not plan:
                    raise AlertError("no meme/plan.json; run /meme-exit plan --write first")
                tok, sym = plan["address"], plan.get("symbol")
                base = {"token": tok, "symbol": sym, "chain": plan.get("chain", "solana"), "added_at": now}
                new.append(dict(base, kind="stop", level=float(plan["stop"])))
                new.append(dict(base, kind="target", level=float(plan["target"])))
                new.append(dict(base, kind="time", at=int(plan["flat_by"])))
                q = fetch_quotes([(base["chain"], tok)], now, a.offline).get(tok) or {}
                if q.get("liquidity_usd"):
                    new.append(dict(base, kind="liq_drop", pct=DEFAULT_RUG_DROP, base=float(q["liquidity_usd"])))
                    write_prices({tok: q})
            else:
                if not a.token:
                    raise AlertError("give --token MINT, or --from-plan")
                base = {"token": a.token, "symbol": a.symbol, "chain": a.chain, "added_at": now, "note": a.note}
                q = None
                for kind, val in (("above", a.above), ("below", a.below), ("stop", a.stop), ("target", a.target)):
                    if val is not None:
                        new.append(dict(base, kind=kind, level=float(val)))
                if a.at:
                    new.append(dict(base, kind="time", at=parse_clock(a.at, now, tz)))
                if a.pct is not None or a.liq_drop is not None:
                    q = fetch_quotes([(a.chain, a.token)], now, a.offline).get(a.token) or {}
                    if a.pct is not None:
                        if not q.get("price"):
                            raise AlertError("no price for %s to measure the move from" % a.token)
                        new.append(dict(base, kind="pct", pct=float(a.pct), base=float(q["price"])))
                    if a.liq_drop is not None:
                        if not q.get("liquidity_usd"):
                            raise AlertError("no liquidity for %s to measure the drop from" % a.token)
                        new.append(dict(base, kind="liq_drop", pct=float(a.liq_drop), base=float(q["liquidity_usd"])))
                    if not base["symbol"]:
                        for x in new:
                            x["symbol"] = q.get("symbol")
                if not new:
                    raise AlertError("say what to watch: --above, --below, --stop, --target, --pct, --at or --liq-drop")
            st["alerts"].extend(new)
            save(path, st)
            for x in new:
                print("Added: %s" % describe(x, tz))
            print("Run alerts.py check (or watch --every 30) to ring them; each rings once.")
            return 0
        # check / watch
        checks = 1 if a.cmd == "check" else a.max_checks
        for n in range(checks):
            live = [x for x in st["alerts"] if not x.get("rang_at")]
            port = load(os.path.join(mdir(), "portfolio.json"), {}) or {}
            toks = {(x.get("chain", "solana"), x["token"]) for x in live}
            toks |= {("solana", t) for t in (port.get("positions") or {})}
            if not toks:
                print("No open alerts and nothing held. Add some: alerts.py add --from-plan")
                return 0
            quotes = fetch_quotes(sorted(toks), now, a.offline)
            sol = None
            if not a.offline:
                try:
                    sol = {"price": float(get_json(JUP_PRICE)[SOL]["usdPrice"]), "ts": now, "source": "Jupiter"}
                except (AlertError, KeyError, TypeError, ValueError):
                    sol = None
            write_prices(quotes, sol)
            msgs = evaluate(st["alerts"], quotes, now, tz)
            save(path, st)
            if a.json:
                print(json.dumps({"rang": msgs, "quotes": quotes}, indent=2))
            else:
                for m in msgs:
                    print(m)
                if a.cmd == "check":
                    if not msgs:
                        for tok, q in sorted(quotes.items(), key=lambda kv: kv[1].get("symbol") or ""):
                            print("  %-10s $%-11s liquidity %s at %s" % (q["symbol"], fp(q["price"]), money(q["liquidity_usd"]), local_str(now, tz)))
                        print("Nothing rang.")
            sys.stdout.flush()
            if a.cmd == "watch":
                if not [x for x in st["alerts"] if not x.get("rang_at")]:
                    print("Every alert has rung.")
                    return 0
                time.sleep(a.every)
                now = parse_now(None, tz)
        return 0
    except AlertError as e:
        print("Alerts: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
