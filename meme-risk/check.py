#!/usr/bin/env python3
"""The Risk Manager (meme-risk). Standard library only.

The gate between a proposal and your yes. Every order in meme/orders.json is
checked against your limits and gets PASS or BLOCK with the reason. A BLOCK
is final for that order: meme-broker will not show it for a yes.

For a meme coin buy it checks the coin first (the analyst's verdict, fresh;
pool liquidity and age; price impact and your share of the pool), then the
trade (a stop, the loss at the stop INCLUDING costs, reward:risk after costs,
the time machine's edge after costs), then the day (daily loss limit, trades
per day, a pause after a losing streak, open positions, your entry hours) and
the basics (format, chain, leverage, blocked tokens, size, position cap, cash,
duplicates, orders per day). Getting out is never blocked by a day limit.

    python3 check.py                  # meme/orders.json; writes meme/state/risk.json
    python3 check.py --json
    python3 check.py --no-write
    python3 check.py --now "2026-11-01 21:59"
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

FP_FIELDS = ("chain", "side", "token", "amount_usd", "pay_with", "amount_in", "tokens", "receive", "slippage_bps")
FRESH_PRICE_SECONDS = 180
DEFAULTS = {"budget_usd": 1000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 250,
            "min_order_usd": 20, "max_loss_per_trade_usd": 20, "max_daily_loss_usd": 60, "max_trades_per_day": 3,
            "max_orders_per_day": 10, "max_open_positions": 2, "min_reward_risk": 1.0, "require_stop": True,
            "require_edge": True, "max_plan_age_minutes": 10, "losing_streak_pause": 2, "pause_minutes": 120,
            "no_entries_before": None, "no_entries_after": None, "timezone": "Europe/Berlin",
            "chains": ["solana"], "fee_pct": 0.5, "fee_min_usd": 0.95, "slippage_pct": 0.3, "pool_fee_pct": 0.5,
            "max_price_impact_pct": 1.0, "max_pct_of_liquidity": 0.5, "min_liquidity_usd": 50000,
            "min_pool_age_hours": 6, "require_safety": True, "safety_max_age_minutes": 60, "paper": True,
            "blocked": [], "allow_leverage": False, "allow_perps": False, "allow_short": False}
ADDRESS = re.compile(r"^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$")


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


def fingerprint(order):
    """Same function as meme-broker/ticket.py: identifies the exact order."""
    core = {k: order[k] for k in FP_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


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


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the cost model (same as meme-budget)

def impact_pct(usd, liquidity):
    if not liquidity or liquidity <= 0:
        return 100.0
    return 100.0 * usd / (liquidity / 2.0 + usd)


def trade_costs(usd, risk_pct, cfg, liquidity, measured=None):
    fee_pct, fee_min = float(cfg["fee_pct"]), float(cfg.get("fee_min_usd") or 0)
    exit_usd = usd * (1 - risk_pct / 100.0)
    fees = max(fee_min, usd * fee_pct / 100.0) + max(fee_min, exit_usd * fee_pct / 100.0)
    slip = (usd + exit_usd) * float(cfg["slippage_pct"]) / 100.0
    if measured is not None:
        base = measured["pool_round_trip_pct"]
        fixed = min(base, 2 * float(cfg["pool_fee_pct"]))
        var = max(0.0, base - fixed) * (usd / measured["usd"]) if measured.get("usd") else 0.0
        pool_rt = fixed + var
    else:
        pool_rt = 2 * float(cfg["pool_fee_pct"]) + 2 * impact_pct(usd, liquidity)
    return fees + slip + usd * pool_rt / 100.0


# ---------------------------------------------------------------- the day so far

def day_of(ts, tz):
    return local_str(ts, tz, "%Y-%m-%d")


def the_day(broker, today, tz):
    ev = (broker or {}).get("events", [])
    placed = [e for e in ev if e.get("type") == "placed" and day_of(int(e["at"]), tz) == today]
    entries = [e for e in placed if e.get("side") == "buy"]
    closes = [e for e in ev if e.get("type") == "fill" and e.get("side") == "sell" and e.get("pnl_usd") is not None]
    streak, last_loss_at = 0, None
    for e in reversed(closes):
        if float(e["pnl_usd"]) < 0:
            streak += 1
            last_loss_at = last_loss_at or int(e["at"])
        else:
            break
    return {"orders": len(placed), "entries": len(entries),
            "risked": sum(float(e.get("max_loss") or 0) for e in entries),
            "tokens_today": {(e.get("token"), e.get("side")) for e in placed},
            "streak": streak, "last_loss_at": last_loss_at}


# ---------------------------------------------------------------- the checks

def check_all(orders, cfg, portfolio, prices, safety, broker, tm, now):
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    tz = c["timezone"]
    today = day_of(now, tz)
    day = the_day(broker, today, tz)
    budget = float(c["budget_usd"])
    port = portfolio if portfolio else {"cash_usd": budget, "positions": {}}
    cash = float(port.get("cash_usd", budget))
    positions = dict(port.get("positions") or {})
    buffer = budget * float(c["cash_buffer_pct"]) / 100.0
    results = []
    seen = set()
    run_entries, run_risk, run_orders = 0, 0.0, 0
    for i, o in enumerate(orders, 1):
        reasons, warns = [], []
        side = str(o.get("side", "")).lower()
        token = o.get("token")
        sym = o.get("symbol") or token
        held = float((positions.get(token) or {}).get("tokens") or 0)
        sell_tokens = _f(o.get("tokens"))
        is_exit = side == "sell" and sell_tokens is not None and sell_tokens <= held + 1e-9
        info = {}
        # format and asset: always
        if side not in ("buy", "sell"):
            reasons.append("format: side must be buy or sell")
        if not token or not ADDRESS.match(str(token)):
            reasons.append("format: the token must be a contract address (symbols are not unique for meme coins)")
        if o.get("chain", "solana") not in c["chains"]:
            reasons.append("chain: %s is not in your chains %s" % (o.get("chain"), c["chains"]))
        if o.get("leverage") or str(o.get("type", "")).lower() in ("perp", "perpetual", "futures", "margin"):
            if not (c["allow_leverage"] and c["allow_perps"]):
                reasons.append("asset: leverage, perps and margin are off (allow_leverage / allow_perps)")
        bps = o.get("slippage_bps")
        if bps is None or not (1 <= int(bps) <= 5000):
            reasons.append("format: slippage_bps must be between 1 and 5000")
        elif int(bps) > 300:
            warns.append("slippage tolerance %d bps (%.1f%%) is wide: a sandwich bot can take all of it" % (int(bps), int(bps) / 100.0))
        if side == "buy":
            usd = _f(o.get("amount_usd"))
            if usd is None or usd <= 0 or not isinstance(o.get("amount_usd"), str):
                reasons.append("format: a buy needs amount_usd as a positive string, like \"250.00\"")
                usd = usd or 0.0
        else:
            usd = 0.0
            if sell_tokens is None or sell_tokens <= 0:
                reasons.append("format: a sell needs tokens (how many to sell) as a positive string")
            elif sell_tokens > held + 1e-9 and not c["allow_short"]:
                reasons.append("short: selling %s but you hold %s; short selling is off" % (o.get("tokens"), held))

        entry_rules = []  # (code, text) that BLOCK an entry and only warn on an exit
        p = o.get("plan") or {}
        if side == "buy":
            if token in c["blocked"] or str(o.get("symbol", "")).upper() in [str(b).upper() for b in c["blocked"]]:
                entry_rules.append("blocked: %s is on your blocked list" % sym)
            # the coin
            s = (safety or {}).get(token)
            if s is None:
                if c["require_safety"]:
                    entry_rules.append("safety: no /meme-analyst report for this token; run it first")
            else:
                age_min = (now - int(s.get("checked_at") or 0)) / 60.0
                info["safety"] = "%s, checked %d minutes ago" % (s.get("verdict"), age_min)
                if s.get("verdict") == "AVOID":
                    entry_rules.append("safety: the analyst says AVOID (%s)" % "; ".join((s.get("reasons") or [])[:2]))
                elif s.get("verdict") == "UNVERIFIED" and c["require_safety"]:
                    entry_rules.append("safety: UNVERIFIED (no on-chain report on this chain)")
                elif s.get("verdict") == "CAUTION":
                    warns.append("the analyst says CAUTION: %s" % "; ".join((s.get("reasons") or [])[:2]))
                if age_min > float(c["safety_max_age_minutes"]):
                    entry_rules.append("safety: the report is %d minutes old (limit %s); run /meme-analyst again"
                                       % (age_min, c["safety_max_age_minutes"]))
            liq = _f(p.get("liquidity_usd")) or _f((s or {}).get("liquidity_usd"))
            if liq is None:
                entry_rules.append("liquidity: unknown; run /meme-analyst or /meme-alerts quote")
            else:
                if liq < float(c["min_liquidity_usd"]):
                    entry_rules.append("liquidity: the pool holds %s, under your %s minimum" % (money(liq), money(float(c["min_liquidity_usd"]))))
                if usd > liq * float(c["max_pct_of_liquidity"]) / 100.0:
                    entry_rules.append("liquidity: %s is more than %g%% of the pool's %s" % (money(usd), float(c["max_pct_of_liquidity"]), money(liq)))
                imp = impact_pct(usd, liq)
                if imp > float(c["max_price_impact_pct"]):
                    entry_rules.append("impact: about %.2f%% price impact a side, over your %g%%" % (imp, float(c["max_price_impact_pct"])))
            created = p.get("pool_created_at") or (s or {}).get("pool_created_at")
            if created:
                hours = (now - int(created)) / 3600.0
                if hours < float(c["min_pool_age_hours"]):
                    entry_rules.append("age: the pool is %.1f hours old, under your %g" % (hours, float(c["min_pool_age_hours"])))
            else:
                warns.append("the pool's age is unknown")
            # the trade
            created_plan = p.get("plan_created_at") or p.get("entry_time")
            if created_plan and (now - int(created_plan)) / 60.0 > float(c["max_plan_age_minutes"]):
                entry_rules.append("stale: the plan is %d minutes old (limit %s); make a new one" % (
                    (now - int(created_plan)) // 60, c["max_plan_age_minutes"]))
            stop, target, entry = _f(p.get("stop")), _f(p.get("target")), _f(p.get("entry"))
            pr = (prices or {}).get(token) or {}
            fresh = pr.get("price") if pr.get("ts") and now - int(pr["ts"]) <= FRESH_PRICE_SECONDS else None
            if pr.get("price") and fresh is None:
                warns.append("the last price in meme/prices.json is too old to use (over %d minutes)" % (FRESH_PRICE_SECONDS // 60))
            used = "the plan's entry"
            if entry is not None and fresh is not None and fresh > entry:
                entry, used = float(fresh), "a fresh price"
            if stop is None:
                if c["require_stop"]:
                    entry_rules.append("stop: no stop in the plan; every meme trade needs one (/meme-exit)")
            elif entry is not None and stop >= entry:
                entry_rules.append("stop: the stop %s is not under the entry %s" % (fp(stop), fp(entry)))
            if stop is not None and entry is not None and target is not None and stop < entry:
                risk_pct = (entry - stop) / entry * 100.0
                cost = trade_costs(usd, risk_pct, c, liq or 0, p.get("measured"))
                loss = usd * risk_pct / 100.0 + cost
                gain = usd * (target - entry) / entry - cost
                rr = gain / loss if loss > 0 else 0.0
                info.update(entry=entry, used=used, stop=stop, target=target, risk_pct=risk_pct, loss=loss, gain=gain,
                            rr=rr, cost=cost)
                if loss > float(c["max_loss_per_trade_usd"]) + 1e-9:
                    entry_rules.append("loss: %s at the stop (%.2f%% x %s + %s costs), over your %s max loss per trade" % (
                        money(loss), risk_pct, money(usd), money(cost), money(float(c["max_loss_per_trade_usd"]))))
                if target <= entry:
                    entry_rules.append("target: the price %s is already at the target %s" % (fp(entry), fp(target)))
                elif rr < float(c["min_reward_risk"]) - 1e-9:
                    entry_rules.append("reward:risk: %.2f after costs (+%s vs -%s), under your %g minimum" % (
                        rr, money(gain), money(loss), float(c["min_reward_risk"])))
                if c["require_edge"]:
                    run = tm or {}
                    tp = run.get("plan") or {}
                    same = (tp.get("address") == token and abs(float(tp.get("stop", -1)) - stop) < 1e-12
                            and abs(float(tp.get("target", -1)) - target) < 1e-12)
                    if not same:
                        entry_rules.append("edge: no /meme-timemachine run for this exact plan (require_edge is on)")
                    else:
                        mc = run.get("mc") or {}
                        hist = run.get("history") or {}
                        info["edge"] = (mc.get("avg_r_net"), hist.get("fired"), hist.get("avg_r_net"))
                        if mc.get("avg_r_net") is not None and mc["avg_r_net"] < 0:
                            entry_rules.append("edge: the time machine's average R after costs is %+.2f%s: this setup "
                                               "has lost money after costs on this coin's recent bars" % (
                                                   mc["avg_r_net"], (" (history %+.2f over %d real trades)" % (
                                                       hist["avg_r_net"], hist["fired"])) if hist.get("fired") else ""))
                        elif hist.get("fired") and hist.get("avg_r_net") is not None and hist["avg_r_net"] < 0:
                            warns.append("the real history of this rule is %+.2fR after costs over %d trades" % (
                                hist["avg_r_net"], hist["fired"]))
            # the day
            if day["risked"] + run_risk + info.get("loss", 0.0) > float(c["max_daily_loss_usd"]) + 1e-9:
                entry_rules.append("daily loss: %s already at risk today + %s here is over your %s daily limit" % (
                    money(day["risked"] + run_risk), money(info.get("loss", 0.0)), money(float(c["max_daily_loss_usd"]))))
            if day["entries"] + run_entries >= int(c["max_trades_per_day"]):
                entry_rules.append("trades: %d of %d trades already today" % (day["entries"] + run_entries, int(c["max_trades_per_day"])))
            if int(c["losing_streak_pause"] or 0) and day["streak"] >= int(c["losing_streak_pause"]) and day["last_loss_at"]:
                until = day["last_loss_at"] + int(c["pause_minutes"]) * 60
                if now < until:
                    entry_rules.append("pause: %d losing trades in a row; no new entries until %s (a break beats a "
                                       "revenge trade)" % (day["streak"], local_str(until, tz)))
            open_n = len([t for t, v in positions.items() if float((v or {}).get("tokens") or 0) > 0 and t != token])
            if open_n >= int(c["max_open_positions"]):
                entry_rules.append("positions: %d open already (limit %d)" % (open_n, int(c["max_open_positions"])))
            hhmm = local_str(now, tz)
            if c["no_entries_before"] and hhmm < c["no_entries_before"]:
                entry_rules.append("window: no new entries before %s (it is %s)" % (c["no_entries_before"], hhmm))
            if c["no_entries_after"] and hhmm >= c["no_entries_after"]:
                entry_rules.append("window: no new entries after %s (it is %s)" % (c["no_entries_after"], hhmm))
            # the basics
            if usd and usd < float(c["min_order_usd"]):
                entry_rules.append("size: %s is under your %s minimum order" % (money(usd), money(float(c["min_order_usd"]))))
            if usd > float(c["max_order_usd"]) + 1e-9:
                entry_rules.append("size: %s is over your %s max order" % (money(usd), money(float(c["max_order_usd"]))))
            pos_val = float((positions.get(token) or {}).get("cost_usd") or 0) + usd
            if pos_val > budget * float(c["max_position_pct"]) / 100.0 + 1e-9:
                entry_rules.append("position: %s in one coin is over %g%% of your %s" % (money(pos_val), float(c["max_position_pct"]), money(budget)))
            if cash - usd < buffer - 1e-9:
                entry_rules.append("cash: %s would leave %s, under your %s buffer" % (money(usd), money(cash - usd), money(buffer)))
            if (token, side) in seen or (token, side) in day["tokens_today"]:
                entry_rules.append("duplicate: you already bought %s today; a second buy after a stop is a revenge trade" % sym)
        if day["orders"] + run_orders >= int(c["max_orders_per_day"]):
            entry_rules.append("daily limit: %d of %d orders already today" % (day["orders"] + run_orders, int(c["max_orders_per_day"])))
        if is_exit:
            warns.extend("(exit, not blocked) " + r for r in entry_rules)
        else:
            reasons.extend(entry_rules)
        verdict = "BLOCK" if reasons else "PASS"
        if verdict == "PASS":
            seen.add((token, side))
            run_orders += 1
            if side == "buy":
                run_entries += 1
                run_risk += info.get("loss", 0.0)
                cash -= usd
                positions[token] = dict(positions.get(token) or {}, tokens=1, cost_usd=float((positions.get(token) or {}).get("cost_usd") or 0) + usd)
            elif sell_tokens:
                pos = dict(positions.get(token) or {})
                pos["tokens"] = max(0.0, float(pos.get("tokens") or 0) - sell_tokens)
                positions[token] = pos
        if not c["paper"]:
            warns.append("LIVE: this is real money in your own wallet")
        results.append({"index": i, "fp": fingerprint(o), "verdict": verdict, "side": side, "token": token,
                        "symbol": o.get("symbol"), "amount_usd": o.get("amount_usd"), "tokens": o.get("tokens"),
                        "kind": "exit" if is_exit else "entry", "reasons": reasons, "warnings": warns,
                        "info": info, "day": {"entries": day["entries"], "risked": day["risked"]}})
    return results, cash, c


def render(results, cash, c, now, tz):
    out = []
    for r in results:
        i = r["info"]
        if r["side"] == "buy":
            head = "%-5s #%d buy %s of %s, %s" % (r["verdict"], r["index"], money(float(r["amount_usd"] or 0)),
                                                  r["symbol"] or r["token"], r["kind"])
        else:
            head = "%-5s #%d sell %s %s, %s" % (r["verdict"], r["index"], r.get("tokens"), r["symbol"] or r["token"], r["kind"])
        out.append(head)
        if "loss" in i:
            out.append("          entry %s (%s), stop %s, target %s: risk %.2f%%" % (fp(i["entry"]), i["used"], fp(i["stop"]),
                                                                                    fp(i["target"]), round(i["risk_pct"], 3)))
            out.append("          max loss %s incl. %s costs (limit %s), reward:risk %.2f after costs (min %g)" % (
                money(i["loss"]), money(i["cost"]), money(float(c["max_loss_per_trade_usd"])), i["rr"], float(c["min_reward_risk"])))
        if i.get("safety"):
            out.append("          analyst: %s" % i["safety"])
        if i.get("edge") and i["edge"][0] is not None:
            out.append("          time machine: %+.2fR after costs%s" % (i["edge"][0], (", history %+.2fR over %d trades" % (
                i["edge"][2], i["edge"][1])) if i["edge"][1] else ""))
        if r["side"] == "buy":
            out.append("          today before this: %d of %d trades, %s of %s daily loss" % (
                r["day"]["entries"], int(c["max_trades_per_day"]), money(r["day"]["risked"]), money(float(c["max_daily_loss_usd"]))))
        for x in r["reasons"]:
            out.append("        - %s" % x)
        for w in r["warnings"]:
            out.append("        ! %s" % w)
        out.append("")
    n_pass = sum(1 for r in results if r["verdict"] == "PASS")
    out.append("%d passed, %d blocked at %s %s. Cash after the passed orders: %s (%s)." % (
        n_pass, len(results) - n_pass, local_str(now, tz, "%Y-%m-%d %H:%M"), tz, money(cash),
        "paper" if c["paper"] else "LIVE"))
    out.append("A PASS means the order may be shown to you for a yes. It is not a recommendation.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Risk gate (meme-risk). Checks, never trades.")
    ap.add_argument("orders", nargs="?", help="default meme/orders.json")
    ap.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    base = mdir()
    cfg = load(os.path.join(base, "config.json"), {}) or {}
    tz = cfg.get("timezone") or DEFAULTS["timezone"]
    now = parse_now(a.now, tz)
    orders = load(a.orders or os.path.join(base, "orders.json"))
    if not orders:
        print("No orders to check (meme/orders.json is missing or empty). Run /meme-budget first.")
        return 1
    if isinstance(orders, dict):
        orders = [orders]
    results, cash, c = check_all(orders, cfg, load(os.path.join(base, "portfolio.json")),
                                 load(os.path.join(base, "prices.json"), {}), load(os.path.join(base, "safety.json"), {}),
                                 load(os.path.join(base, "state", "broker.json"), {}),
                                 load(os.path.join(base, "timemachine.json")), now)
    if not a.no_write:
        path = os.path.join(base, "state", "risk.json")
        st = load(path, {"verdicts": []}) or {"verdicts": []}
        for r in results:
            st["verdicts"].append({"fp": r["fp"], "at": now, "date": local_str(now, tz, "%Y-%m-%d"), "index": r["index"],
                                   "verdict": r["verdict"], "kind": r["kind"], "symbol": r["symbol"], "side": r["side"],
                                   "reasons": r["reasons"], "max_loss": round(r["info"].get("loss", 0.0), 2)})
        st["verdicts"] = st["verdicts"][-500:]
        save(path, st)
    if a.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(render(results, cash, c, now, tz))
    return 0 if all(r["verdict"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
