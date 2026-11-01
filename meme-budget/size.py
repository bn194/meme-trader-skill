#!/usr/bin/env python3
"""The Budget Manager (meme-budget). Standard library only.

Turns a plan ("buy GATO at 0.0077889, stop 0.0074560") into one exact buy
("$250 of GATO, paid with 2.6539 SOL"), inside rules you set once. The stop
and the costs decide the size: the loss at the stop INCLUDES the app's fee
(with its minimum), slippage and the pool's fee and price impact, both ways.
Six limits, the smallest wins: max loss per trade, position cap, max order,
cash after your buffer, a share of the pool's liquidity, and price impact.

    python3 size.py                     # meme/plan.json + meme/config.json
    python3 size.py --write             # write meme/orders.json (one buy)
    python3 size.py --quote --write     # measure the pool's real round trip with two Jupiter quotes first
    python3 size.py --json

It writes a proposal only. /meme-risk checks it, /meme-broker asks for your
yes. Nothing is bought here.
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
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DECIMALS = {SOL: 9, USDC: 6}
JUP_QUOTE = "https://lite-api.jup.ag/swap/v1/quote?inputMint=%s&outputMint=%s&amount=%d&slippageBps=%d"
JUP_PRICE = "https://lite-api.jup.ag/price/v3?ids=%s"
DS_TOKENS = "https://api.dexscreener.com/tokens/v1/%s/%s"
FRESH_PRICE_SECONDS = 180
DEFAULTS = {"budget_usd": 1000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 250,
            "min_order_usd": 20, "max_loss_per_trade_usd": 20, "min_reward_risk": 1.0, "max_plan_age_minutes": 10,
            "fee_pct": 0.5, "fee_min_usd": 0.95, "slippage_pct": 0.3, "pool_fee_pct": 0.5, "slippage_bps": 150,
            "max_price_impact_pct": 1.0, "max_pct_of_liquidity": 0.5, "venue": "fomo", "pay_with": "SOL",
            "chains": ["solana"], "blocked": [], "timezone": "Europe/Berlin", "paper": True}
VENUES = {"fomo": "Fomo", "phantom": "Phantom", "jupiter": "Jupiter", "axiom": "Axiom", "photon": "Photon",
          "bullx": "BullX", "pumpfun": "pump.fun", "solflare": "Solflare", "trojan": "Trojan"}


class SizeError(Exception):
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


def get_json(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < 2:
                time.sleep(4 * (i + 1))
                continue
            raise SizeError("%s answered HTTP %d" % (url.split("/")[2], e.code))
        except (urllib.error.URLError, OSError, ValueError) as e:
            if i == 2:
                raise SizeError("could not read %s (%s)" % (url.split("/")[2], e))
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
    return "${:,.2f}".format(v)


# ---------------------------------------------------------------- the cost model

def impact_pct(usd, liquidity):
    """Estimated price impact of one swap of `usd` into a constant-product pool holding `liquidity` (both sides)."""
    if not liquidity or liquidity <= 0:
        return 100.0
    side = liquidity / 2.0
    return 100.0 * usd / (side + usd)


def trade_costs(usd, risk_pct, cfg, liquidity, measured=None):
    """Dollars a round trip costs at this size: the app fee (with its minimum) both ways, slippage both ways,
    and the pool (its fee plus price impact, both ways; or a measured Jupiter round trip)."""
    fee_pct, fee_min = float(cfg["fee_pct"]), float(cfg.get("fee_min_usd") or 0)
    exit_usd = usd * (1 - risk_pct / 100.0)
    fees = max(fee_min, usd * fee_pct / 100.0) + max(fee_min, exit_usd * fee_pct / 100.0)
    slip = (usd + exit_usd) * float(cfg["slippage_pct"]) / 100.0
    if measured is not None:
        # scale the measured round trip: its fixed part (pool fees) stays, the impact part grows with size
        base = measured["pool_round_trip_pct"]
        fixed = min(base, 2 * float(cfg["pool_fee_pct"]))
        var = max(0.0, base - fixed) * (usd / measured["usd"]) if measured["usd"] else 0.0
        pool_rt = fixed + var
        source = "measured"
    else:
        pool_rt = 2 * float(cfg["pool_fee_pct"]) + 2 * impact_pct(usd, liquidity)
        source = "estimated"
    pool = usd * pool_rt / 100.0
    return {"fees": fees, "slippage": slip, "pool": pool, "total": fees + slip + pool,
            "pool_round_trip_pct": pool_rt, "pool_source": source,
            "total_pct": (fees + slip + pool) / usd * 100.0 if usd else 0.0}


def loss_at_stop(usd, risk_pct, cfg, liquidity, measured=None):
    return usd * risk_pct / 100.0 + trade_costs(usd, risk_pct, cfg, liquidity, measured)["total"]


def gain_at_target(usd, risk_pct, reward_pct, cfg, liquidity, measured=None):
    return usd * reward_pct / 100.0 - trade_costs(usd, risk_pct, cfg, liquidity, measured)["total"]


def largest(limit_fn, hi):
    """The largest whole-dollar size <= hi with limit_fn(size) true (limit_fn is monotone)."""
    lo, hi = 0, int(hi)
    if hi <= 0:
        return 0
    if limit_fn(hi):
        return hi
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if limit_fn(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------------------------------------------------------------- sizing

def size(plan, cfg, now, price=None, cash=None, liquidity=None, measured=None, sol_price=None):
    """Pure: the plan, the rules and the market -> (order dict, table). Raises SizeError with the reason."""
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    addr = plan["address"]
    if plan.get("chain", "solana") not in c["chains"]:
        raise SizeError("%s is not in your chains %s" % (plan.get("chain"), c["chains"]))
    if addr in c["blocked"] or str(plan.get("symbol", "")).upper() in [str(b).upper() for b in c["blocked"]]:
        raise SizeError("%s is on your blocked list" % (plan.get("symbol") or addr))
    age = (now - int(plan.get("created_at") or plan["entry_time"])) / 60.0
    if age > float(c["max_plan_age_minutes"]):
        raise SizeError("the plan is %.0f minutes old (your limit %s): meme coins move too fast; make a new one with "
                        "/meme-entry and /meme-exit" % (age, c["max_plan_age_minutes"]))
    entry = float(plan["entry"])
    used = "the plan's entry"
    if price is not None and price > entry:
        entry, used = float(price), "the fresh price (higher than the plan's entry)"
    stop, target = float(plan["stop"]), float(plan["target"])
    if stop >= entry:
        raise SizeError("the price $%s is already at or under the stop $%s" % (fp(entry), fp(stop)))
    if target <= entry:
        raise SizeError("the price $%s is already at or over the target $%s: the move happened" % (fp(entry), fp(target)))
    risk_pct = (entry - stop) / entry * 100.0
    reward_pct = (target - entry) / entry * 100.0
    liq = liquidity
    if not liq:
        raise SizeError("no pool liquidity known for %s; run /meme-analyst or /meme-alerts quote first" % addr)
    budget = float(c["budget_usd"])
    buffer = budget * float(c["cash_buffer_pct"]) / 100.0
    cash_room = budget - buffer if cash is None else max(0.0, float(cash) - buffer)
    max_loss = float(c["max_loss_per_trade_usd"])
    cap_usd = budget * float(c["max_position_pct"]) / 100.0
    hi = max(cash_room, cap_usd, float(c["max_order_usd"]), 1.0) + 1
    table = [
        ("max loss", largest(lambda u: loss_at_stop(u, risk_pct, c, liq, measured) <= max_loss, hi),
         "loss at the stop incl. costs <= %s" % money(max_loss)),
        ("position cap", int(cap_usd), "%g%% of %s" % (float(c["max_position_pct"]), money(budget))),
        ("max order", int(float(c["max_order_usd"])), "your max order"),
        ("cash", int(cash_room), "%s cash after the %g%% buffer" % (money(cash_room), float(c["cash_buffer_pct"]))),
        ("liquidity", int(liq * float(c["max_pct_of_liquidity"]) / 100.0),
         "%g%% of the pool's %s" % (float(c["max_pct_of_liquidity"]), money(liq))),
        ("price impact", largest(lambda u: impact_pct(u, liq) <= float(c["max_price_impact_pct"]), hi),
         "impact <= %g%% a side" % float(c["max_price_impact_pct"])),
    ]
    usd = min(v for _, v, _ in table)
    decided = [n for n, v, _ in table if v == usd][0]
    if usd <= 0:
        raise SizeError("the size is $0: even $1 would lose more than %s at the stop; the stop is too far away "
                        "(%.2f%%) for your max loss" % (money(max_loss), risk_pct))
    if usd < float(c["min_order_usd"]):
        raise SizeError("the size is %s, under your %s minimum order (bound by %s); at this size the fee minimum "
                        "alone is %.1f%% a side" % (money(usd), money(float(c["min_order_usd"])), decided,
                                                    float(c["fee_min_usd"]) / usd * 100))
    cost = trade_costs(usd, risk_pct, c, liq, measured)
    loss = loss_at_stop(usd, risk_pct, c, liq, measured)
    gain = gain_at_target(usd, risk_pct, reward_pct, c, liq, measured)
    rr = gain / loss if loss > 0 else 0.0
    if rr < float(c["min_reward_risk"]):
        raise SizeError("after costs the reward:risk is %.2f (+%s at the target vs -%s at the stop), under your %g "
                        "minimum. A farther target, or skip it" % (rr, money(gain), money(loss), float(c["min_reward_risk"])))
    pay = str(c["pay_with"]).upper()
    order = {"chain": plan.get("chain", "solana"), "venue": c["venue"], "side": "buy", "token": addr,
             "symbol": plan.get("symbol"), "amount_usd": "%.2f" % usd, "pay_with": pay,
             "slippage_bps": int(c["slippage_bps"])}
    if pay == "SOL":
        if sol_price:
            sol_amt = usd / float(sol_price)
            order["amount_in"] = "%.4f" % sol_amt
            order["jupiter_quote"] = {"inputMint": SOL, "outputMint": addr, "amount": str(int(round(sol_amt * 1e9))),
                                      "slippageBps": int(c["slippage_bps"])}
    elif pay == "USDC":
        order["amount_in"] = "%.2f" % usd
        order["jupiter_quote"] = {"inputMint": USDC, "outputMint": addr, "amount": str(int(round(usd * 1e6))),
                                  "slippageBps": int(c["slippage_bps"])}
    order["why"] = ("%s on %s: %s, bound by your %s (%s at the stop incl. %s of costs)" % (
        "range breakout" if plan.get("setup") == "range" else "level breakout", plan.get("symbol") or addr,
        money(usd), {"max loss": "%s max loss per trade" % money(max_loss)}.get(decided, decided),
        money(loss), money(cost["total"])))
    order["plan"] = {"entry": entry, "entry_used": used, "stop": stop, "target": target,
                     "risk_pct": round(risk_pct, 3), "reward_pct": round(reward_pct, 3),
                     "max_loss": round(loss, 2), "gain_at_target": round(gain, 2), "reward_risk_net": round(rr, 2),
                     "costs_usd": round(cost["total"], 2), "costs_pct": round(cost["total_pct"], 3),
                     "pool_source": cost["pool_source"], "liquidity_usd": liq,
                     "pool_created_at": plan.get("pool_created_at"), "pair": plan.get("pair"),
                     "setup": plan.get("setup"), "entry_time": plan["entry_time"], "flat_by": plan.get("flat_by"),
                     "plan_created_at": plan.get("created_at"), "sol_price": sol_price}
    return order, table, decided, cost


def render(order, table, decided, cost, cfg, tz):
    p = order["plan"]
    venue = VENUES.get(str(cfg.get("venue", "")).lower(), cfg.get("venue"))
    lines = ["%s: entry $%s (%s), stop $%s, target $%s; risk %.2f%% a token, reward %.2f%%." % (
        order.get("symbol") or order["token"], fp(p["entry"]), p["entry_used"], fp(p["stop"]), fp(p["target"]),
        p["risk_pct"], p["reward_pct"]),
        "  %-13s %-10s %s" % ("limit", "size", "the math")]
    for name, v, why in table:
        lines.append("  %-13s %-10s %s%s" % (name, money(v), why, "   <- decides it" if name == decided else ""))
    usd = float(order["amount_usd"])
    lines.append("Buy %s of %s%s. Costs about %s (%.2f%%): %s fees %s, slippage %s, pool %s (%s round trip %.2f%%)." % (
        money(usd), order.get("symbol") or order["token"],
        (" with %s SOL" % order["amount_in"]) if order.get("pay_with") == "SOL" and order.get("amount_in") else "",
        money(cost["total"]), cost["total_pct"], venue, money(cost["fees"]), money(cost["slippage"]),
        money(cost["pool"]), cost["pool_source"], cost["pool_round_trip_pct"]))
    lines.append("At the stop: -%s. At the target: +%s. Reward:risk after costs %.2f. Flat by %s." % (
        money(p["max_loss"]), money(p["gain_at_target"]), p["reward_risk_net"],
        local_str(p["flat_by"], tz) if p.get("flat_by") else "n/a"))
    lines.append("A stop is a plan, not a guarantee: a meme coin can gap through it, and a thin pool can fill worse.")
    return "\n".join(lines)


def measure(addr, usd, sol_price, slippage_bps):
    """Two Jupiter quotes, SOL -> token -> SOL, for this size: the pool's real round trip right now."""
    lamports = int(round(usd / sol_price * 1e9))
    buy = get_json(JUP_QUOTE % (SOL, addr, lamports, slippage_bps))
    out = int(buy["outAmount"])
    sell = get_json(JUP_QUOTE % (addr, SOL, out, slippage_bps))
    back = int(sell["outAmount"])
    return {"usd": usd, "pool_round_trip_pct": (1 - back / float(lamports)) * 100.0, "lamports_in": lamports,
            "tokens_out": out, "lamports_back": back, "route": [r["swapInfo"].get("label") for r in buy.get("routePlan", [])]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Position sizing (meme-budget). Writes a proposal, never buys.")
    ap.add_argument("--plan", help="default meme/plan.json")
    ap.add_argument("--config", help="default meme/config.json")
    ap.add_argument("--price", type=float, help="a fresh price to size at (if higher than the plan's entry)")
    ap.add_argument("--liquidity", type=float, help="pool liquidity in USD (default: safety.json / prices.json / DexScreener)")
    ap.add_argument("--sol-price", type=float, help="SOL in USD (default: prices.json or Jupiter)")
    ap.add_argument("--quote", action="store_true", help="measure the round trip with two Jupiter quotes (Solana)")
    ap.add_argument("--roundtrip", type=float, help="a measured pool round trip in %% at --roundtrip-usd")
    ap.add_argument("--roundtrip-usd", type=float, default=250.0)
    ap.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    base = mdir()
    cfg = dict(DEFAULTS)
    user_cfg = load(a.config or os.path.join(base, "config.json"))
    if user_cfg is None:
        print("No meme/config.json yet: copy config.example.json from this skill into meme/config.json and set "
              "your budget and max loss first. Using the example defaults for now.")
    cfg.update({k: v for k, v in (user_cfg or {}).items() if v is not None})
    tz = cfg["timezone"]
    try:
        now = parse_now(a.now, tz)
        plan = load(a.plan or os.path.join(base, "plan.json"))
        if not plan or "entry" not in plan:
            raise SizeError("no meme/plan.json; run /meme-exit plan --write first")
        prices = load(os.path.join(base, "prices.json"), {}) or {}
        safety = load(os.path.join(base, "safety.json"), {}) or {}
        portfolio = load(os.path.join(base, "portfolio.json"))
        pr = prices.get(plan["address"]) or {}
        fresh = pr if pr.get("ts") and now - int(pr["ts"]) <= FRESH_PRICE_SECONDS else {}
        liq = a.liquidity or fresh.get("liquidity_usd") or pr.get("liquidity_usd") or (safety.get(plan["address"]) or {}).get("liquidity_usd")
        plan = dict(plan)
        plan.setdefault("pool_created_at", (safety.get(plan["address"]) or {}).get("pool_created_at") or pr.get("pool_created_at"))
        if not liq:
            pairs = get_json(DS_TOKENS % (plan.get("chain", "solana"), plan["address"]))
            pairs = pairs if isinstance(pairs, list) else (pairs or {}).get("pairs") or []
            if pairs:
                best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
                liq = (best.get("liquidity") or {}).get("usd")
                plan["pool_created_at"] = plan.get("pool_created_at") or int((best.get("pairCreatedAt") or 0) // 1000) or None
        sol_price = a.sol_price or ((prices.get("SOL") or {}).get("price") if prices.get("SOL") else None)
        if not sol_price and str(cfg["pay_with"]).upper() == "SOL":
            try:
                sol_price = float(get_json(JUP_PRICE % SOL)[SOL]["usdPrice"])
            except (SizeError, KeyError, TypeError, ValueError):
                sol_price = None
        measured = None
        if a.roundtrip is not None:
            measured = {"usd": a.roundtrip_usd, "pool_round_trip_pct": a.roundtrip}
        cash = (portfolio or {}).get("cash_usd")
        price = a.price or fresh.get("price")
        order, table, decided, cost = size(plan, cfg, now, price, cash, liq, measured, sol_price)
        if a.quote and plan.get("chain", "solana") == "solana" and sol_price:
            measured = measure(plan["address"], float(order["amount_usd"]), sol_price, int(cfg["slippage_bps"]))
            order, table, decided, cost = size(plan, cfg, now, price, cash, liq, measured, sol_price)
        if measured is not None:
            order["plan"]["measured"] = measured  # meme-risk recomputes the costs from the same measurement
    except SizeError as e:
        print("No order: %s." % e)
        return 1
    if a.write:
        save(os.path.join(base, "orders.json"), [order])
    if a.json:
        print(json.dumps({"order": order, "limits": table, "decided_by": decided, "costs": cost}, indent=2))
    else:
        print(render(order, table, decided, cost, cfg, tz))
        if a.write:
            print("Wrote meme/orders.json (1 buy, nothing placed). Next: /meme-risk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
