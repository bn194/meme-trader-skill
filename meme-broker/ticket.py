#!/usr/bin/env python3
"""Trade tickets and your yes (meme-broker). Standard library only.

This tool never touches a wallet, never signs anything and never asks for a
key. It does its work around the one moment that matters, your yes:

  show      renders each proposed order as a plain ticket: the coin, its
            contract address (paste it, never search by name), the amount,
            the slippage, the stop, the target, the time stop and the max
            loss at the stop. READY only if meme-risk passed THIS exact order
            today (matched by fingerprint) and nobody has decided on it yet.
  approve   records your explicit yes ("yes" or "ja") for ONE order, word for
            word. It refuses "yes to all", "sure", "ok", a yes with a doubt in
            it, and a yes that names another coin or amount.
  decline   records a no.
  paper     (paper mode, the default) fills an approved order at the live
            price, minus the costs, in meme/portfolio.json. No app, no money.
  result    (live mode) records what happened after YOU traded in your app
            (Fomo, Phantom, Jupiter): placed with the tokens and the price you
            got, or failed, or denied.
  fill      records a sell (stop, target, time stop, or you got out), with the
            profit or loss, for meme-risk's losing-streak pause.
  flatten   writes a sell-everything order for one coin. It still goes through
            meme-risk and your yes.
  quote     asks Jupiter (read only) what this order would get right now.
  log       prints today's decisions and closed trades.

    python3 ticket.py show
    python3 ticket.py approve --index 1 --reply "yes"
    python3 ticket.py paper --index 1 --price 0.0077889
    python3 ticket.py result --index 1 --status placed --tokens 32010.4 --price 0.0078102 --tx SIG
    python3 ticket.py fill --token MINT --tokens 32010.4 --price 0.0074560 --reason stop
    python3 ticket.py flatten --token MINT
    python3 ticket.py log
"""

import argparse
import calendar
import datetime
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "meme-trader-skill/1.0 (+https://github.com/bn194/meme-trader-skill)"
FP_FIELDS = ("chain", "side", "token", "amount_usd", "pay_with", "amount_in", "tokens", "receive", "slippage_bps")
SOL = "So11111111111111111111111111111111111111112"
DS_TOKENS = "https://api.dexscreener.com/tokens/v1/%s/%s"
JUP_QUOTE = "https://lite-api.jup.ag/swap/v1/quote?inputMint=%s&outputMint=%s&amount=%s&slippageBps=%d"
JUP_PRICE = "https://lite-api.jup.ag/price/v3?ids=%s"
YES_WORDS = ("yes", "y", "ja", "j")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each",
               "alle", "alles", "beide", "jeden", "jede", "restlichen"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later", "hold", "unless",
               "if", "nein", "nicht", "warte", "warten", "abbrechen", "aber", "vielleicht", "später", "spaeter",
               "falls", "wenn", "doch", "kein", "keine"}
VENUES = {"fomo": "Fomo", "phantom": "Phantom", "jupiter": "Jupiter", "axiom": "Axiom", "photon": "Photon",
          "bullx": "BullX", "pumpfun": "pump.fun", "solflare": "Solflare", "trojan": "Trojan"}
DEFAULTS = {"timezone": "Europe/Berlin", "paper": True, "venue": "phantom", "budget_usd": 111, "fee_pct": 0.85,
            "fee_min_usd": 0, "slippage_pct": 0.3, "pool_fee_pct": 0.5, "slippage_bps": 150}


class TicketError(Exception):
    pass

def apply_venue(cfg):
    """The venue's fee profile (config "venues") wins over the plain fee_pct and fee_min_usd."""
    v = (cfg.get("venues") or {}).get(str(cfg.get("venue", "")).lower())
    if v:
        cfg = dict(cfg)
        cfg["fee_pct"] = float(v.get("fee_pct", cfg.get("fee_pct", 0.85)))
        cfg["fee_min_usd"] = float(v.get("fee_min_usd") or 0)
    return cfg



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


def get_json(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except (urllib.error.URLError, OSError, ValueError) as e:
            if i == 2:
                raise TicketError("could not read %s (%s)" % (url.split("/")[2], e))
            time.sleep(3)


def fp(p):
    if p is None:
        return "n/a"
    p = float(p)
    if p <= 0:
        return "0"
    e = int(("%e" % p).split("e")[1])
    return "%.*f" % (max(0, 4 - e), p)


def money(v):
    return "${:,.2f}".format(v)


def fingerprint(order):
    """Same function as meme-risk/check.py: identifies the exact order."""
    core = {k: order[k] for k in FP_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the order in words

def plain(order):
    sym = order.get("symbol") or order.get("token")
    if order.get("side") == "buy":
        return "buy %s of %s" % (money(float(order.get("amount_usd") or 0)), sym)
    return "sell %s %s" % (order.get("tokens"), sym)


def amount_numbers(order):
    nums = []
    for k in ("amount_usd", "amount_in", "tokens"):
        v = _f(order.get(k))
        if v is not None:
            nums.append(v)
    p = order.get("plan") or {}
    for k in ("max_loss", "stop", "target"):
        v = _f(p.get(k))
        if v is not None:
            nums.append(v)
    return nums


def parse_yes(reply, order, batch_symbols=()):
    """Is this reply an explicit yes for THIS one order? Returns (ok, why)."""
    raw = (reply or "").strip()
    if not raw:
        return False, "the reply is empty"
    if "?" in raw:
        return False, "the reply is a question, not a yes"
    words = re.findall(r"[a-zäöüß']+", raw.lower())
    if not words or words[0] not in YES_WORDS:
        return False, "only a reply that starts with \"yes\" or \"ja\" counts (not ok, sure, go, mach)"
    if BATCH_WORDS & set(words):
        return False, "a yes covers one order at a time, not a batch"
    if DOUBT_WORDS & set(words[1:]):
        return False, "the reply has a condition or a doubt in it; ask again"
    sym = str(order.get("symbol") or "").upper()
    named = set(re.findall(r"\$?([A-Z][A-Z0-9]{1,9})\b", raw.upper())) & ({str(s).upper() for s in batch_symbols} - {sym})
    if named:
        return False, "the reply names %s, but this order is for %s" % (", ".join(sorted(named)), sym)
    nums = [float(n.replace(",", ".")) if n.count(",") == 1 and "." not in n else float(n.replace(",", ""))
            for n in re.findall(r"\d[\d,]*(?:\.\d+)?", raw)]
    if nums:
        want = amount_numbers(order)
        if not any(abs(n - w) <= max(0.005, 1e-9 * w) for n in nums for w in want):
            return False, "the reply says %s, but this order is %s" % (", ".join("%g" % n for n in nums), plain(order))
    return True, "explicit yes for %s" % plain(order)


# ---------------------------------------------------------------- state

def state_path():
    return os.path.join(mdir(), "state", "broker.json")


def events():
    return (load(state_path(), {"events": []}) or {"events": []}).get("events", [])


def add_event(ev):
    st = load(state_path(), {"events": []}) or {"events": []}
    st.setdefault("events", []).append(ev)
    save(state_path(), st)


def risk_verdict(fpr, today, tz):
    st = load(os.path.join(mdir(), "state", "risk.json"), {"verdicts": []}) or {"verdicts": []}
    mine = [v for v in st.get("verdicts", []) if v.get("fp") == fpr and v.get("date") == today]
    return mine[-1] if mine else None


def decided(fpr, today, tz):
    mine = [e for e in events() if e.get("fp") == fpr and local_str(int(e["at"]), tz, "%Y-%m-%d") == today
            and e.get("type") in ("yes", "no", "placed", "failed", "denied")]
    return mine[-1] if mine else None


def status_of(order, today, tz):
    fpr = fingerprint(order)
    rv = risk_verdict(fpr, today, tz)
    d = decided(fpr, today, tz)
    if rv is None:
        return "NOT READY", "NOT READY: meme-risk has not passed this exact order today; run /meme-risk", rv, d
    if rv["verdict"] != "PASS":
        return "BLOCKED", "BLOCKED by meme-risk: %s" % "; ".join(rv.get("reasons", [])[:2]), rv, d
    if d is not None and d["type"] == "yes":
        return "APPROVED", "APPROVED: your yes is recorded (%s)" % local_str(int(d["at"]), tz), rv, d
    if d is not None:
        return "DECIDED", "DECIDED: %s at %s" % (d["type"], local_str(int(d["at"]), tz)), rv, d
    return "READY", "READY: meme-risk PASS, waiting for your yes", rv, d


def render(order, idx, total, cfg, today, tz):
    venue = VENUES.get(str(order.get("venue") or cfg.get("venue")).lower(), order.get("venue"))
    paper = bool(cfg.get("paper", True))
    _, text, rv, d = status_of(order, today, tz)
    p = order.get("plan") or {}
    lines = ["ORDER %d of %d, %s, %s" % (idx, total, "PAPER (simulated fills, no money)" if paper else "LIVE (your own wallet)", venue)]
    if order.get("side") == "buy":
        lines.append("  BUY %s of %s on %s%s, max slippage %.1f%%" % (
            money(float(order["amount_usd"])), order.get("symbol") or "?", (order.get("chain") or "solana").capitalize(),
            (", paid with %s %s" % (order["amount_in"], order.get("pay_with"))) if order.get("amount_in") else "",
            int(order.get("slippage_bps") or 0) / 100.0))
    else:
        lines.append("  SELL %s %s for %s, max slippage %.1f%%" % (order.get("tokens"), order.get("symbol") or "?",
                                                                   order.get("receive", "SOL"), int(order.get("slippage_bps") or 0) / 100.0))
    lines.append("  contract  %s   <- paste this address, never search by name" % order.get("token"))
    if p.get("stop") is not None:
        lines.append("  plan: stop $%s, target $%s, flat by %s" % (fp(p["stop"]), fp(p.get("target")),
                                                                 local_str(int(p["flat_by"]), tz) if p.get("flat_by") else "n/a"))
        lines.append("  max loss about %s at the stop incl. costs (a meme coin can gap through a stop: it can be worse)" % money(float(p.get("max_loss") or 0)))
    if order.get("why"):
        lines.append("  why: %s" % order["why"])
    lines.append("  " + text)
    if text.startswith("READY"):
        lines.append("  Reply \"yes\" (or \"ja\") to take this one trade, or \"no\" to skip it.")
    return "\n".join(lines)


def portfolio(cfg):
    path = os.path.join(mdir(), "portfolio.json")
    port = load(path)
    if not port:
        port = {"cash_usd": float(cfg.get("budget_usd", 1000)), "positions": {}, "paper": bool(cfg.get("paper", True))}
    return path, port


def fee(usd, cfg):
    return max(float(cfg.get("fee_min_usd") or 0), usd * float(cfg["fee_pct"]) / 100.0)


# ---------------------------------------------------------------- commands

def main(argv=None):
    ap = argparse.ArgumentParser(description="Trade tickets and your yes (meme-broker). Never trades by itself.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
        p.add_argument("--json", action="store_true")
        return p

    p = common(sub.add_parser("show"))
    p.add_argument("--index", type=int)
    p = common(sub.add_parser("approve"))
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply", required=True, help="the user's reply, word for word")
    p = common(sub.add_parser("decline"))
    p.add_argument("--index", type=int, required=True)
    p = common(sub.add_parser("paper"))
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--price", type=float, help="fill price (default: DexScreener now)")
    p = common(sub.add_parser("result"))
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--status", choices=("placed", "failed", "denied"), required=True)
    p.add_argument("--tokens", type=float, help="how many tokens you got")
    p.add_argument("--price", type=float, help="the price you got (USD a token)")
    p.add_argument("--usd", type=float, help="what it cost you in USD, all in (default: the order's amount)")
    p.add_argument("--tx", help="the transaction signature")
    p.add_argument("--note")
    p = common(sub.add_parser("fill"))
    p.add_argument("--token", required=True)
    p.add_argument("--tokens", type=float, help="how many you sold (default: all you hold)")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--usd", type=float, help="what you received in USD after fees (default: estimated)")
    p.add_argument("--reason", default="manual", help="stop, target, time, rug, manual")
    p = common(sub.add_parser("flatten"))
    p.add_argument("--token", required=True)
    p.add_argument("--tokens", type=float, help="default: everything meme/portfolio.json says you hold")
    p.add_argument("--slippage-bps", type=int, default=300)
    p = common(sub.add_parser("quote"))
    p.add_argument("--index", type=int, required=True)
    common(sub.add_parser("log"))
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (load(os.path.join(mdir(), "config.json"), {}) or {}).items() if v is not None})
    cfg = apply_venue(cfg)
    tz = cfg["timezone"]
    now = parse_now(a.now, tz)
    today = local_str(now, tz, "%Y-%m-%d")
    try:
        return run(a, cfg, tz, now, today)
    except TicketError as e:
        print("Not done: %s" % e)
        return 1


def pick(index):
    orders = load(os.path.join(mdir(), "orders.json")) or []
    if isinstance(orders, dict):
        orders = [orders]
    if not orders:
        raise TicketError("meme/orders.json is empty; run /meme-budget first")
    if not 1 <= index <= len(orders):
        raise TicketError("there is no order %d (there are %d)" % (index, len(orders)))
    return orders, orders[index - 1]


def run(a, cfg, tz, now, today):
    if a.cmd == "show":
        orders = load(os.path.join(mdir(), "orders.json")) or []
        if isinstance(orders, dict):
            orders = [orders]
        if not orders:
            print("No orders in meme/orders.json.")
            return 1
        rows = list(enumerate(orders, 1))
        if a.index:
            rows = [r for r in rows if r[0] == a.index]
        out = []
        for i, o in rows:
            if a.json:
                st, text, rv, d = status_of(o, today, tz)
                out.append({"index": i, "status": st, "text": text, "fp": fingerprint(o), "order": o})
            else:
                print(render(o, i, len(orders), cfg, today, tz))
                print("")
        if a.json:
            print(json.dumps(out, indent=2))
        else:
            print("One order at a time: a yes covers one ticket, never the batch. Education and tooling, not "
                  "financial advice.")
        return 0

    if a.cmd in ("approve", "decline"):
        orders, o = pick(a.index)
        st, text, rv, d = status_of(o, today, tz)
        if st != "READY":
            raise TicketError("order %d is not READY (%s)" % (a.index, text))
        if a.cmd == "decline":
            add_event({"type": "no", "at": now, "fp": fingerprint(o), "index": a.index, "token": o.get("token"),
                       "symbol": o.get("symbol"), "side": o.get("side")})
            print("Recorded your no for order %d: %s. Nothing happens." % (a.index, plain(o)))
            return 0
        ok, why = parse_yes(a.reply, o, [x.get("symbol") for x in orders if x.get("symbol")])
        if not ok:
            print("Not recorded: %s. Ask again: \"%s? Reply yes or no.\"" % (why, plain(o)))
            return 1
        add_event({"type": "yes", "at": now, "fp": fingerprint(o), "index": a.index, "reply": a.reply,
                   "token": o.get("token"), "symbol": o.get("symbol"), "side": o.get("side"),
                   "amount_usd": o.get("amount_usd")})
        print("Recorded your yes for order %d: %s." % (a.index, plain(o)))
        venue = VENUES.get(str(o.get("venue") or cfg["venue"]).lower(), o.get("venue"))
        if cfg.get("paper", True):
            print("PAPER: nothing to do in %s. Next: ticket.py paper --index %d fills it at the live price, minus "
                  "the costs." % (venue, a.index))
        elif o.get("side") == "buy":
            print("LIVE: do it yourself in %s, now, before the price moves:" % venue)
            print("  1. Search by the contract address, pasted: %s" % o["token"])
            print("  2. Check the ticker (%s) and that it is the pool DexScreener shows; fake copies use the same name." % o.get("symbol"))
            print("  3. Buy %s%s. Max slippage %.1f%% if the app lets you set it." % (
                money(float(o["amount_usd"])), (" (%s %s)" % (o["amount_in"], o.get("pay_with"))) if o.get("amount_in") else "",
                int(o.get("slippage_bps") or 0) / 100.0))
            print("  4. Then tell Claude the tokens you got and the price: ticket.py result --index %d --status "
                  "placed --tokens Q --price P" % a.index)
            print("  If the price ran more than a little past the plan's entry, do not chase it: skip it and say so.")
        else:
            print("LIVE: sell %s %s yourself in %s now, then: ticket.py fill --token %s --price P" % (
                o.get("tokens"), o.get("symbol"), venue, o["token"]))
        return 0

    if a.cmd in ("paper", "result"):
        orders, o = pick(a.index)
        st, text, rv, d = status_of(o, today, tz)
        if st != "APPROVED":
            raise TicketError("order %d has no yes recorded today (%s); a fill can only follow your yes" % (a.index, text))
        if a.cmd == "paper" and not cfg.get("paper", True):
            raise TicketError("paper fills are for paper mode; your config is LIVE. Use result after you trade in your app")
        if a.cmd == "result" and a.status != "placed":
            add_event({"type": a.status, "at": now, "fp": fingerprint(o), "index": a.index, "token": o.get("token"),
                       "side": o.get("side"), "note": a.note})
            print("Recorded: order %d %s. A failed or denied order is not retried without a new check and a new yes." % (
                a.index, a.status))
            return 0
        if o.get("side") != "buy":
            if a.cmd == "paper":
                price = a.price or live_price(o)
                return do_fill(cfg, tz, now, o["token"], float(o["tokens"]), price, None, "flatten", o, a.index)
            raise TicketError("record a sell with: ticket.py fill --token %s --price P" % o["token"])
        usd = float(o["amount_usd"])
        p = o.get("plan") or {}
        if a.cmd == "paper":
            price = a.price or live_price(o)
            cost_in = fee(usd, cfg) + usd * float(cfg["slippage_pct"]) / 100.0 + usd * float(cfg["pool_fee_pct"]) / 100.0
            tokens = (usd - cost_in) / price
            spent = usd
        else:
            if not a.tokens or not a.price:
                raise TicketError("a placed result needs --tokens and --price (what your app shows)")
            tokens, price, spent = a.tokens, a.price, a.usd or usd
        path, port = portfolio(cfg)
        pos = port["positions"].get(o["token"]) or {"symbol": o.get("symbol"), "tokens": 0.0, "cost_usd": 0.0}
        pos["tokens"] = float(pos["tokens"]) + tokens
        pos["cost_usd"] = float(pos["cost_usd"]) + spent
        pos.update(entry_price=price, opened_at=now, stop=p.get("stop"), target=p.get("target"), flat_by=p.get("flat_by"))
        port["positions"][o["token"]] = pos
        port["cash_usd"] = float(port["cash_usd"]) - spent
        save(path, port)
        add_event({"type": "placed", "at": now, "fp": fingerprint(o), "index": a.index, "token": o["token"],
                   "symbol": o.get("symbol"), "side": "buy", "amount_usd": o["amount_usd"], "tokens": tokens,
                   "price": price, "max_loss": p.get("max_loss"), "tx": getattr(a, "tx", None),
                   "paper": a.cmd == "paper", "spent_usd": round(spent, 2), "setup": p.get("setup"),
                   "venue": o.get("venue"), "stop": p.get("stop"), "target": p.get("target")})
        print("%s: bought %s %s at $%s for %s. Cash left %s." % (
            "PAPER fill" if a.cmd == "paper" else "Recorded", "{:,.1f}".format(tokens), o.get("symbol"), fp(price),
            money(spent), money(port["cash_usd"])))
        print("Next: /meme-alerts add --from-plan watches the stop, the target, the time stop and the pool's liquidity.")
        return 0

    if a.cmd == "fill":
        return do_fill(cfg, tz, now, a.token, a.tokens, a.price, a.usd, a.reason, None, None)

    if a.cmd == "flatten":
        path, port = portfolio(cfg)
        pos = port["positions"].get(a.token)
        qty = a.tokens if a.tokens is not None else (float(pos["tokens"]) if pos else 0)
        if not qty:
            raise TicketError("meme/portfolio.json shows no %s to sell; give --tokens from your app" % a.token)
        order = {"chain": "solana", "venue": cfg["venue"], "side": "sell", "token": a.token,
                 "symbol": (pos or {}).get("symbol"), "tokens": ("%.6f" % qty).rstrip("0").rstrip("."),
                 "receive": "SOL", "slippage_bps": int(a.slippage_bps),
                 "why": "get out: sell everything you hold of %s" % ((pos or {}).get("symbol") or a.token),
                 "note": "Flatten ticket. Nothing happens until meme-risk passes it and you say yes."}
        save(os.path.join(mdir(), "orders.json"), [order])
        print("Wrote a sell of %s %s to meme/orders.json. Check the amount in your app before you say yes." % (
            order["tokens"], order["symbol"] or a.token))
        print("  1. /meme-risk (a sell that only gets you out is never blocked by a day limit)")
        print("  2. ticket.py show, then your yes for this one order.")
        return 0

    if a.cmd == "quote":
        orders, o = pick(a.index)
        if o.get("chain", "solana") != "solana" or not o.get("jupiter_quote"):
            raise TicketError("a Jupiter quote works for Solana buys with a jupiter_quote block")
        q = o["jupiter_quote"]
        buy = get_json(JUP_QUOTE % (q["inputMint"], q["outputMint"], q["amount"], int(q["slippageBps"])))
        sell = get_json(JUP_QUOTE % (q["outputMint"], q["inputMint"], buy["outAmount"], int(q["slippageBps"])))
        rt = (1 - int(sell["outAmount"]) / float(q["amount"])) * 100.0
        try:
            dec = int(get_json(JUP_PRICE % q["outputMint"])[q["outputMint"]]["decimals"])
            got = "%s %s" % ("{:,.1f}".format(int(buy["outAmount"]) / 10.0 ** dec), o.get("symbol") or "tokens")
        except (TicketError, KeyError, TypeError, ValueError):
            got = "%s raw token units" % buy["outAmount"]
        print("Jupiter right now (read only, nothing signed): %s %s -> %s; selling them straight back returns "
              "%.4f %s. Pool round trip %.2f%% (before the app's fee)." % (
                  o.get("amount_in"), o.get("pay_with"), got, int(sell["outAmount"]) / 1e9 if o.get("pay_with") == "SOL"
                  else int(sell["outAmount"]) / 1e6, o.get("pay_with"), rt))
        print("Route: %s. If the round trip is far above what /meme-budget assumed, re-run it with --quote." % (
            ", ".join(r["swapInfo"].get("label", "?") for r in buy.get("routePlan", []))))
        return 0

    if a.cmd == "log":
        ev = [e for e in events() if local_str(int(e["at"]), tz, "%Y-%m-%d") == today]
        if not ev:
            print("Nothing logged today (%s)." % today)
            return 0
        for e in ev:
            extra = ""
            if e.get("pnl_usd") is not None:
                extra = "  P&L %s (%s)" % (("+" if e["pnl_usd"] >= 0 else "-") + money(abs(e["pnl_usd"])), e.get("reason"))
            print("%s  %-6s %-4s %s%s%s" % (local_str(int(e["at"]), tz), e["type"], e.get("side", ""), e.get("symbol") or e.get("token"),
                                            ("  " + money(float(e["amount_usd"]))) if e.get("amount_usd") else "", extra))
        return 0
    return 1


def live_price(o):
    pairs = get_json(DS_TOKENS % (o.get("chain", "solana"), o["token"]))
    pairs = pairs if isinstance(pairs, list) else (pairs or {}).get("pairs") or []
    mine = [p for p in pairs if (p.get("baseToken") or {}).get("address") == o["token"]]
    if not mine:
        raise TicketError("no live price for %s; pass --price" % o["token"])
    best = max(mine, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    return float(best["priceUsd"])


def do_fill(cfg, tz, now, token, tokens, price, usd, reason, order, index):
    path, port = portfolio(cfg)
    pos = port["positions"].get(token)
    if not pos or not float(pos.get("tokens") or 0):
        raise TicketError("meme/portfolio.json holds no %s" % token)
    held = float(pos["tokens"])
    qty = held if tokens is None else min(float(tokens), held)
    gross = qty * price
    if usd is None:
        usd = gross - fee(gross, cfg) - gross * (float(cfg["slippage_pct"]) + float(cfg["pool_fee_pct"])) / 100.0
    basis = float(pos["cost_usd"]) * qty / held
    pnl = usd - basis
    pos["tokens"] = held - qty
    pos["cost_usd"] = float(pos["cost_usd"]) - basis
    if pos["tokens"] <= 1e-9:
        port["positions"].pop(token, None)
    else:
        port["positions"][token] = pos
    port["cash_usd"] = float(port["cash_usd"]) + usd
    save(path, port)
    ev = {"type": "fill", "at": now, "token": token, "symbol": pos.get("symbol"), "side": "sell", "tokens": qty,
          "price": price, "usd": round(usd, 2), "pnl_usd": round(pnl, 2), "reason": reason}
    if order is not None:
        ev.update(fp=fingerprint(order), index=index)
    add_event(ev)
    print("Sold %s %s at $%s for %s (%s): %s %s. Cash %s." % (
        "{:,.1f}".format(qty), pos.get("symbol") or token, fp(price), money(usd), reason,
        "profit" if pnl >= 0 else "loss", money(abs(pnl)), money(port["cash_usd"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
