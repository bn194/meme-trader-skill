#!/usr/bin/env python3
"""The Exit Planner (meme-exit). Standard library only.

Sets the stop, the target and the time stop BEFORE the entry, and counts the
costs a meme coin trade really pays: the app's fee, slippage and the pool's
fee, both ways. On a meme coin those costs are often 2 % or more a round
trip, so a tight stop or a small target loses money even when it "works".

    python3 exit.py plan                          # meme/entry.json: range-low stop, 3R target
    python3 exit.py plan --stop range-mid --target 2R --write
    python3 exit.py plan --stop pct:8 --target pct:20
    python3 exit.py plan --stop atr:2              # 2 x the 14-bar ATR (needs the bars)
    python3 exit.py plan --entry 0.0075741 --address MINT --symbol GATO --stop price:0.0072
    python3 exit.py show

Rounding: the stop rounds DOWN to 5 significant digits (away from the entry),
the target half up. Refused, with the reason: a stop at or above the entry,
a target at or below it, or a stop closer than the round-trip costs. Writes
meme/plan.json for /meme-timemachine, /meme-budget and /meme-alerts.
Long side only.
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
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

UA = "meme-trader-skill/1.0 (+https://github.com/bn194/meme-trader-skill)"
JUP_CHART = "https://datapi.jup.ag/v2/charts/%s?interval=1_MINUTE&to=%d&candles=%d&type=price"
DEFAULTS = {"timezone": "Europe/Berlin", "fee_pct": 0.85, "fee_min_usd": 0, "slippage_pct": 0.3,
            "pool_fee_pct": 0.5, "max_hold_minutes": 60, "min_reward_risk": 1.0, "venue": "phantom"}
VENUES = {"fomo": "Fomo", "phantom": "Phantom", "jupiter": "Jupiter", "axiom": "Axiom", "photon": "Photon",
          "bullx": "BullX", "pumpfun": "pump.fun", "solflare": "Solflare", "trojan": "Trojan"}


class PlanError(Exception):
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


# ---------------------------------------------------------------- prices

def sig(p, n=5, rounding=ROUND_HALF_UP):
    """p rounded to n significant digits (ROUND_FLOOR for a long's stop)."""
    d = Decimal(repr(float(p)))
    if d <= 0:
        return 0.0
    q = Decimal(1).scaleb(d.adjusted() - n + 1)
    return float(d.quantize(q, rounding=rounding))


def fp(p):
    if p is None:
        return "n/a"
    p = float(p)
    if p <= 0:
        return "0"
    e = int(("%e" % p).split("e")[1])
    return "%.*f" % (max(0, 4 - e), p)


def costs(cfg):
    """Per side and round trip, in percent of the position, before your size is known."""
    side = float(cfg["fee_pct"]) + float(cfg["slippage_pct"]) + float(cfg["pool_fee_pct"])
    return {"fee_pct": float(cfg["fee_pct"]), "fee_min_usd": float(cfg.get("fee_min_usd") or 0),
            "slippage_pct": float(cfg["slippage_pct"]), "pool_fee_pct": float(cfg["pool_fee_pct"]),
            "per_side_pct": round(side, 4), "round_trip_pct": round(2 * side, 4)}


def atr(bars, upto, n=14):
    rows = [b for b in bars if b["t"] <= upto]
    if len(rows) < 2:
        raise PlanError("an ATR stop needs the bars up to the entry; none came back")
    trs = []
    for i in range(1, len(rows)):
        pc = rows[i - 1]["c"]
        trs.append(max(rows[i]["h"] - rows[i]["l"], abs(rows[i]["h"] - pc), abs(rows[i]["l"] - pc)))
    use = trs[-n:]
    return sum(use) / len(use), len(use)


def parse_bars(obj):
    out = {}
    if isinstance(obj, dict) and "candles" in obj:
        for c in obj["candles"] or []:
            out[int(c["time"])] = {"t": int(c["time"]), "o": float(c["open"]), "h": float(c["high"]),
                                   "l": float(c["low"]), "c": float(c["close"]), "v": float(c.get("volume") or 0)}
    elif isinstance(obj, dict) and "data" in obj:
        for row in ((obj.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []:
            t, o, h, l, c, v = row[:6]
            out[int(t)] = {"t": int(t), "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v or 0)}
    return [out[k] for k in sorted(out)]


def get_json(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except (urllib.error.URLError, OSError, ValueError) as e:
            if i == 2:
                raise PlanError("could not read the bars (%s)" % e)
            time.sleep(3)


# ---------------------------------------------------------------- the plan

def make_plan(entry, cfg, stop_rule="range-low", target_rule="3R", max_hold=None, bars=None, exits=None):
    """Pure: entry (meme/entry.json shape, triggered) + the rules -> the plan dict. Raises PlanError."""
    price = float(entry["trigger"]["price"])
    t_entry = int(entry["trigger"]["time"])
    rng = entry.get("range") or {}
    rule = stop_rule.lower()
    if rule in ("range-low", "range-mid") and rng.get("high") is None:
        raise PlanError("a %s stop needs a range; a level setup needs a stop you name (price:X, pct:X or atr:K)" % rule)
    if rule == "range-low":
        raw, why = rng["low"], "range low"
    elif rule == "range-mid":
        raw, why = (rng["high"] + rng["low"]) / 2.0, "range midpoint ($%s + $%s) / 2" % (fp(rng["high"]), fp(rng["low"]))
    elif rule.startswith("price:"):
        raw, why = float(rule.split(":", 1)[1]), "your price"
    elif rule.startswith("pct:"):
        pct = float(rule.split(":", 1)[1])
        raw, why = price * (1 - pct / 100.0), "%g%% under the entry" % pct
    elif rule.startswith("atr:"):
        k = float(rule.split(":", 1)[1])
        if not bars:
            raise PlanError("an ATR stop needs the 1-minute bars (online, or --offline FILE)")
        val, used = atr(bars, int(entry["trigger"]["bar_time"]))
        raw, why = price - k * val, "%g x the %d-bar ATR (%s)" % (k, used, fp(val))
    else:
        raise PlanError("unknown stop rule '%s' (range-low, range-mid, price:X, pct:X, atr:K)" % stop_rule)
    stop = sig(raw, 5, ROUND_FLOOR)
    if stop >= price:
        raise PlanError("the stop $%s is not under the entry $%s: a long's stop must be below it" % (fp(stop), fp(price)))
    if stop <= 0:
        raise PlanError("the stop is at or below zero")
    risk = price - stop
    risk_pct = risk / price * 100.0
    c = costs(cfg)
    if risk_pct < c["round_trip_pct"]:
        raise PlanError("the stop is %.2f%% under the entry, less than the %.2f%% a round trip costs: fees and "
                        "slippage alone would be more than the risk. Use a wider stop (range-low, pct:X) or skip it"
                        % (risk_pct, c["round_trip_pct"]))
    trule = target_rule.strip()
    m = re.match(r"^(\d+(?:\.\d+)?)R$", trule, re.I)
    if m:
        r_mult = float(m.group(1))
        target = sig(price + r_mult * risk, 5, ROUND_HALF_UP)
        twhy = "%sR (%s times the risk)" % (("%g" % r_mult), ("%g" % r_mult))
    elif trule.lower().startswith("price:"):
        target = float(trule.split(":", 1)[1])
        twhy = "your price"
    elif trule.lower().startswith("pct:"):
        pct = float(trule.split(":", 1)[1])
        target = sig(price * (1 + pct / 100.0), 5, ROUND_HALF_UP)
        twhy = "%g%% over the entry" % pct
    else:
        raise PlanError("unknown target '%s' (3R, 2R, price:X, pct:X)" % target_rule)
    if target <= price:
        raise PlanError("the target $%s is not above the entry $%s" % (fp(target), fp(price)))
    reward_pct = (target - price) / price * 100.0
    loss_net = risk_pct + c["round_trip_pct"]
    gain_net = reward_pct - c["round_trip_pct"]
    hold = int(max_hold if max_hold is not None else cfg["max_hold_minutes"])
    return {"symbol": entry.get("symbol"), "chain": entry.get("chain", "solana"), "address": entry["address"],
            "pair": entry.get("pair"), "setup": entry.get("setup", "range"), "interval": entry.get("interval", "1m"),
            "entry": price, "entry_time": t_entry, "entry_bar": int(entry["trigger"].get("bar_time", t_entry - 60)),
            "stop": stop, "stop_rule": stop_rule, "stop_why": why, "target": target, "target_rule": target_rule,
            "target_why": twhy, "target_r": round((target - price) / risk, 2), "risk": risk,
            "risk_pct": round(risk_pct, 3), "reward_pct": round(reward_pct, 3), "costs": c,
            "net": {"loss_pct_at_stop": round(loss_net, 3), "gain_pct_at_target": round(gain_net, 3),
                    "reward_risk": round(gain_net / loss_net, 2) if loss_net > 0 else None,
                    "costs_in_r": round(c["round_trip_pct"] / risk_pct, 2)},
            "max_hold_minutes": hold, "flat_by": t_entry + hold * 60, "range": rng or None,
            "level": entry.get("level"), "range_minutes": rng.get("minutes"),
            "vol_x": entry.get("vol_x_min"), "max_wait": entry.get("max_wait"), "exits": exits or {}}


def render(p, cfg, tz):
    c = p["costs"]
    n = p["net"]
    day = local_str(p["entry_time"], tz, "%a %Y-%m-%d")
    setup = ("%s-minute range breakout" % p.get("range_minutes")) if p["setup"] == "range" else "level breakout"
    lines = ["Exit plan: %s long, %s, %s on 1-minute bars" % (p.get("symbol") or p["address"], day, setup),
             "  Entry         $%s at %s (the %s bar)" % (fp(p["entry"]), local_str(p["entry_time"], tz),
                                                        local_str(p["entry_bar"], tz)),
             "  Stop          $%s  %s, rounded down" % (fp(p["stop"]), p["stop_why"]),
             "  Target        $%s  %s" % (fp(p["target"]), p["target_why"]),
             "  Risk          $%s a token, %.2f%% of the entry" % (fp(p["risk"]), p["risk_pct"]),
             "  Reward:risk   %.2f before costs" % p["target_r"],
             "  Costs         about %.2f%% a round trip: %s fee %.2f%% + slippage %.2f%% + pool %.2f%%, each way" % (
                 c["round_trip_pct"], VENUES.get(str(cfg.get("venue")).lower(), cfg.get("venue", "app")), c["fee_pct"],
                 c["slippage_pct"], c["pool_fee_pct"]),
             "  After costs   -%.2f%% at the stop, +%.2f%% at the target: reward:risk %.2f (costs eat %.2fR)" % (
                 n["loss_pct_at_stop"], n["gain_pct_at_target"], n["reward_risk"], n["costs_in_r"]),
             "  Flat by       %s %s (%d minutes), win or lose" % (local_str(p["flat_by"], tz), tz, p["max_hold_minutes"])]
    ex = p.get("exits") or {}
    if ex.get("scale_r"):
        lines.append("  Partial       sell %g%% at %gR ($%s), then move the stop to the entry" % (
            float(ex["scale_pct"]), float(ex["scale_r"]), fp(p["entry"] + float(ex["scale_r"]) * p["risk"])))
    if ex.get("trail_r"):
        lines.append("  Trailing      keep the stop %gR ($%s) under the highest price since the entry" % (
            float(ex["trail_r"]), fp(float(ex["trail_r"]) * p["risk"])))
    if n["reward_risk"] < float(cfg.get("min_reward_risk", 1.0)):
        lines.append("  WARNING: after costs the reward:risk is %.2f, under your %g minimum: /meme-risk will block "
                     "it. A farther target, or skip the trade." % (n["reward_risk"], float(cfg.get("min_reward_risk", 1.0))))
    if c["fee_min_usd"]:
        lines.append("  The %s fee has a $%.2f minimum each way: on a small buy that is more than %.2f%%; "
                     "/meme-budget counts it." % (VENUES.get(str(cfg.get("venue")).lower(), cfg.get("venue", "app")),
                                                   c["fee_min_usd"], c["fee_pct"]))
    lines.append("A stop is a plan, not a guarantee: a meme coin can gap through it, or have no buyers there.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Exit planner (meme-exit). Plans, never trades.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--stop", default="range-low", help="range-low (default), range-mid, price:X, pct:X, atr:K")
    p.add_argument("--target", default="3R", help="3R (default), 2R, price:X, pct:X")
    p.add_argument("--max-hold", type=int, help="minutes until the time stop (default max_hold_minutes, 60)")
    p.add_argument("--scale", help="partial take, like 1.5R:50 (sell 50 %% at 1.5R, then the stop to the entry)")
    p.add_argument("--trail", help="trailing stop, like 1R under the highest price")
    p.add_argument("--entry", type=float, help="plan at this price (an entry that has not triggered yet)")
    p.add_argument("--address")
    p.add_argument("--symbol")
    p.add_argument("--chain", default="solana")
    p.add_argument("--range-high", type=float)
    p.add_argument("--range-low", type=float)
    p.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
    p.add_argument("--offline", help="saved 1-minute bars, for an atr stop")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    sub.add_parser("show")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (load(os.path.join(mdir(), "config.json"), {}) or {}).items() if v is not None})
    cfg = apply_venue(cfg)
    tz = cfg["timezone"]
    if a.cmd == "show":
        plan = load(os.path.join(mdir(), "plan.json"))
        if not plan:
            print("No meme/plan.json yet. Run: exit.py plan --write")
            return 1
        print(render(plan, cfg, tz))
        return 0
    try:
        now = parse_now(a.now, tz)
        entry = load(os.path.join(mdir(), "entry.json")) or {}
        if a.address and entry.get("address") != a.address:
            entry = {"address": a.address, "chain": a.chain, "symbol": a.symbol, "setup": "range"}
        if a.entry is not None:
            entry = dict(entry)
            entry["trigger"] = {"price": a.entry, "time": now, "bar_time": (now // 60) * 60 - 60}
            if a.symbol:
                entry["symbol"] = a.symbol
        if not entry.get("address"):
            raise PlanError("no meme/entry.json; run /meme-entry first, or give --entry and --address")
        if a.range_high is not None and a.range_low is not None:
            entry["range"] = dict(entry.get("range") or {}, high=a.range_high, low=a.range_low,
                                  minutes=(entry.get("range") or {}).get("minutes", 15))
        if entry.get("status") not in (None, "triggered") and a.entry is None:
            raise PlanError("the entry has not triggered (it is %s); plan ahead with --entry PRICE" % entry.get("status"))
        if not entry.get("trigger"):
            raise PlanError("the entry has no trigger price; give --entry PRICE")
        bars = None
        if a.stop.lower().startswith("atr:"):
            if a.offline:
                bars = parse_bars(load(a.offline))
            else:
                bars = parse_bars(get_json(JUP_CHART % (entry["address"], int(entry["trigger"]["time"]) * 1000, 60)))
        exits = {}
        if a.scale:
            m = re.match(r"^\s*(\d+(?:\.\d+)?)R?\s*:\s*(\d+(?:\.\d+)?)\s*$", a.scale, re.I)
            if not m or not 0 < float(m.group(2)) < 100:
                raise PlanError("--scale wants R:PERCENT, like 1.5R:50")
            exits.update(scale_r=float(m.group(1)), scale_pct=float(m.group(2)))
        if a.trail:
            m = re.match(r"^\s*(\d+(?:\.\d+)?)R?\s*$", a.trail, re.I)
            if not m:
                raise PlanError("--trail wants a distance in R, like 1R")
            exits["trail_r"] = float(m.group(1))
        plan = make_plan(entry, cfg, a.stop, a.target, a.max_hold, bars, exits)
        plan["created_at"] = now
    except PlanError as e:
        print("No plan: %s" % e)
        return 1
    if a.write:
        save(os.path.join(mdir(), "plan.json"), plan)
    print(json.dumps(plan, indent=2) if a.json else render(plan, cfg, tz))
    if a.write and not a.json:
        print("Wrote meme/plan.json. Next: /meme-timemachine replays it, then /meme-budget sizes it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
