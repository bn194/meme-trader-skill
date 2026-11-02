#!/usr/bin/env python3
"""The Time Machine (meme-timemachine). Standard library only.

Before you risk a dollar on a meme coin, it replays the next hour 10,000
times from the coin's own recent 1-minute bars, and re-runs the same rule on
every past time the setup fired. It counts the costs (fees, slippage, pool)
in every trade, because on a meme coin they decide whether a setup that
"works" actually pays.

    python3 timemachine.py run                    # meme/plan.json, 10,000 replays, seed 19
    python3 timemachine.py run --write            # + meme/timemachine.json
    python3 timemachine.py run --days 2 --block 15 --replays 20000
    python3 timemachine.py run --json
    python3 timemachine.py chart                  # text fan chart of the saved run

One replay starts at the entry and draws the next minutes in blocks of 10
consecutive real minutes (block bootstrap, so streaks and bursts survive),
each block from a random place in the coin's last 3 days, scaled to the
current price. Bar by bar it checks the stop first, then the target; a bar
that touches both counts as the stop. "Neither" means still open at the time
stop. A simulation built from the last few days, not a prediction: a rug, a
dev sell or a listing can do what those days never did.
"""

import argparse
import calendar
import datetime
import gzip
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

UA = "meme-trader-skill/1.0 (+https://github.com/bn194/meme-trader-skill)"
JUP_CHART = "https://datapi.jup.ag/v2/charts/%s?interval=1_MINUTE&to=%d&candles=1000&type=price"
GT = "https://api.geckoterminal.com/api/v2"
GECKO_NET = {"solana": "solana", "ethereum": "eth", "base": "base", "bsc": "bsc", "arbitrum": "arbitrum"}
MIN_POOL_BARS = 1440  # one day of minutes


class TMError(Exception):
    pass


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
        json.dump(data, fh)
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


def fp(p):
    if p is None:
        return "n/a"
    p = float(p)
    if p <= 0:
        return "0"
    e = int(("%e" % p).split("e")[1])
    return "%.*f" % (max(0, 4 - e), p)


# ---------------------------------------------------------------- bars

def parse_bars(obj, key=None):
    out = {}
    if isinstance(obj, dict) and "responses" in obj:
        for url, v in obj["responses"].items():
            if (key is None or key in url) and isinstance(v, dict):
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


def get_json(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < 2:
                time.sleep(6 * (i + 1))
                continue
            raise TMError("%s answered HTTP %d" % (url.split("/")[2], e.code))
        except (urllib.error.URLError, OSError, ValueError) as e:
            if i == 2:
                raise TMError("could not read %s (%s)" % (url.split("/")[2], e))
            time.sleep(3)


def fetch_history(plan, days):
    """Up to `days` of 1-minute bars before the entry: Jupiter pages of 1,000 (Solana), else GeckoTerminal."""
    want_from = plan["entry_time"] - int(days * 86400)
    bars = {}
    to = plan["entry_time"]
    for _ in range(int(days * 1440 // 1000) + 2):
        if plan.get("chain", "solana") == "solana":
            page = parse_bars(get_json(JUP_CHART % (plan["address"], to * 1000)))
        else:
            url = "%s/networks/%s/pools/%s/ohlcv/minute?aggregate=1&limit=1000&currency=usd&before_timestamp=%d" % (
                GT, GECKO_NET.get(plan["chain"], plan["chain"]), plan["pair"], to)
            page = parse_bars(get_json(url))
        if not page:
            break
        for b in page:
            bars[b["t"]] = b
        first = page[0]["t"]
        if first <= want_from or first >= to:
            break
        to = first
        time.sleep(0.5)
    return [bars[k] for k in sorted(bars)]


# ---------------------------------------------------------------- the engine

def pool_of(bars, plan, days):
    """Completed bars before the entry, within `days` -> (bars, ratios)."""
    lo = plan["entry_time"] - int(days * 86400)
    rows = [b for b in bars if lo <= b["t"] and b["t"] + 60 <= plan["entry_time"]]
    ratios = []
    for i in range(1, len(rows)):
        pc = rows[i - 1]["c"]
        if pc > 0:
            b = rows[i]
            ratios.append((b["o"] / pc, b["h"] / pc, b["l"] / pc, b["c"] / pc))
    return rows, ratios


class Exit:
    """How a trade ends, bar by bar: the stop first, then a partial take, then the target, then the trailing stop.

    exits: {"scale_r": 1.5, "scale_pct": 50} sells that share at 1.5R and moves the stop to the entry;
           {"trail_r": 1.0} keeps the stop 1R under the highest high once that is above the old stop.
    Outcomes: "target" (the rest hit the target), "stop" (the original stop, full size), "managed" (a stop
    after a partial take or a trailing move), "neither" (still open at the time stop)."""

    def __init__(self, entry, stop, target, exits=None):
        self.entry, self.stop0, self.target = entry, stop, target
        self.risk = entry - stop
        ex = exits or {}
        self.scale_r = ex.get("scale_r")
        self.scale_pct = float(ex.get("scale_pct") or 0) / 100.0
        self.trail_r = ex.get("trail_r")
        self.cur_stop, self.remaining, self.banked, self.high = stop, 1.0, 0.0, entry
        self.outcome, self.r, self.gap = None, None, False

    def bar(self, o, h, l, c):
        """Feed one bar; returns True once the trade is over."""
        if self.outcome is not None:
            return True
        if l <= self.cur_stop:
            self.gap = o <= self.cur_stop
            self.banked += self.remaining * (self.cur_stop - self.entry) / self.risk
            self.outcome = "stop" if (self.remaining == 1.0 and self.cur_stop == self.stop0) else "managed"
            self.r = self.banked
            return True
        if self.scale_r and self.remaining == 1.0 and self.scale_pct > 0 and h >= self.entry + self.scale_r * self.risk:
            self.banked += self.scale_pct * self.scale_r
            self.remaining -= self.scale_pct
            self.cur_stop = max(self.cur_stop, self.entry)
        if h >= self.target:
            self.banked += self.remaining * (self.target - self.entry) / self.risk
            self.outcome, self.r = "target", self.banked
            return True
        if self.trail_r:
            self.high = max(self.high, h)
            self.cur_stop = max(self.cur_stop, self.high - float(self.trail_r) * self.risk)
        return False

    def close(self, last):
        if self.outcome is None:
            self.banked += self.remaining * (last - self.entry) / self.risk
            self.outcome, self.r = "neither", self.banked
        return self.outcome, self.r


def replay(plan, ratios, steps, replays=10000, seed=19, block=10, keep_paths=160, exits=None):
    rng = random.Random(seed)
    entry, stop, target = float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    n = len(ratios)
    if n < block + 1:
        raise TMError("too few bars to draw from")
    counts = {"target": 0, "stop": 0, "managed": 0, "neither": 0}
    gap_s = 0
    rs, closes, paths = [], [], []
    band_cols = [[] for _ in range(steps)]
    for k in range(replays):
        p = entry
        ex = Exit(entry, stop, target, exits)
        path = [] if k < keep_paths else None
        j = 0
        idx = 0
        for s in range(steps):
            if j == 0:
                idx = rng.randrange(0, n - block)
            ro, rh, rl, rc = ratios[idx + j]
            j = (j + 1) % block
            o, h, l, c = p * ro, p * rh, p * rl, p * rc
            if ex.outcome is None and ex.bar(o, h, l, c) and ex.outcome == "stop" and ex.gap:
                gap_s += 1
            p = c
            band_cols[s].append(p)
            if path is not None:
                path.append(round(p, 12))
        outcome, r_val = ex.close(p)
        counts[outcome] += 1
        rs.append(r_val)
        closes.append(p)
        if path is not None:
            paths.append({"outcome": outcome, "path": path})
    closes_sorted = sorted(closes)

    def pct(arr, q):
        return arr[min(len(arr) - 1, max(0, int(round(q * (len(arr) - 1)))))]

    bands = []
    for col in band_cols:
        col.sort()
        bands.append([pct(col, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)])
    c_r = plan["costs"]["round_trip_pct"] / plan["risk_pct"]
    green_net = sum(1 for r in rs if r - c_r > 0)
    return {"replays": replays, "seed": seed, "block": block, "steps": steps, "exits": exits or {},
            "target": counts["target"], "stop": counts["stop"], "managed": counts["managed"],
            "neither": counts["neither"], "gap_stops": gap_s,
            "target_pct": 100.0 * counts["target"] / replays, "stop_pct": 100.0 * counts["stop"] / replays,
            "managed_pct": 100.0 * counts["managed"] / replays, "neither_pct": 100.0 * counts["neither"] / replays,
            "green_pct": 100.0 * sum(1 for r in rs if r > 0) / replays,
            "green_after_costs_pct": 100.0 * green_net / replays,
            "close_median": pct(closes_sorted, 0.5), "close_p05": pct(closes_sorted, 0.05),
            "close_p95": pct(closes_sorted, 0.95), "avg_r": sum(rs) / replays,
            "avg_r_net": sum(rs) / replays - c_r, "costs_in_r": c_r, "bands": bands, "paths": paths}


def rule_of(plan):
    """The setup's rule as plain parameters (meme-exit writes them into the plan)."""
    return {"range_minutes": int(plan.get("range_minutes") or 15),
            "vol_x": float(plan.get("vol_x") if plan.get("vol_x") is not None else 1.5),
            "max_wait": int(plan.get("max_wait") or 60), "target_r": float(plan["target_r"]),
            "stop_rule": str(plan.get("stop_rule", "range-low")).lower(), "risk_pct": float(plan["risk_pct"]),
            "round_trip_pct": float(plan["costs"]["round_trip_pct"]), "setup": plan.get("setup", "range")}


def history(plan, rows, steps, exits=None, rule=None):
    """The plan's own rule on every past range in the pool: what really happened."""
    ru = rule or rule_of(plan)
    rmin, vol_x, max_wait, target_r = ru["range_minutes"], ru["vol_x"], ru["max_wait"], ru["target_r"]
    srule = ru["stop_rule"]
    by_t = {b["t"]: b for b in rows}
    res = {"ranges": 0, "fired": 0, "refused": 0, "target": 0, "stop": 0, "managed": 0, "neither": 0, "r": [], "trades": []}
    if ru.get("setup", "range") != "range":
        res["note"] = "history runs for range setups only"
        return res
    t = rows[0]["t"] if rows else 0
    end_t = rows[-1]["t"] if rows else 0
    while t + (rmin + 1) * 60 <= end_t:
        rng = [by_t[t + 60 * i] for i in range(rmin) if (t + 60 * i) in by_t]
        if len(rng) < 0.8 * rmin:
            t += rmin * 60
            continue
        res["ranges"] += 1
        hi = max(b["h"] for b in rng)
        lo = min(b["l"] for b in rng)
        avg = sum(b["v"] for b in rng) / float(rmin)
        trig = None
        u = t + rmin * 60
        while u < t + (rmin + max_wait) * 60 and u <= end_t:
            b = by_t.get(u)
            if b is not None:
                if b["c"] < lo:
                    break
                if b["c"] > hi and (vol_x <= 0 or (avg > 0 and b["v"] >= vol_x * avg)):
                    trig = b
                    break
            u += 60
        if trig is None:
            t += rmin * 60
            continue
        entry = trig["c"]
        if srule == "range-mid":
            stop = (hi + lo) / 2.0
        elif srule == "range-low":
            stop = lo
        elif srule.startswith("pct:"):
            stop = entry * (1 - float(srule.split(":", 1)[1]) / 100.0)
        else:  # price, atr: keep the plan's distance in percent
            stop = entry * (1 - ru["risk_pct"] / 100.0)
        if stop >= entry:
            t += rmin * 60
            continue
        if (entry - stop) / entry * 100.0 < ru["round_trip_pct"]:
            res["refused"] += 1  # meme-exit refuses a stop inside the round-trip costs, so no trade
            t += rmin * 60
            continue
        risk = entry - stop
        ex = Exit(entry, stop, entry + target_r * risk, exits)
        last = entry
        v = trig["t"] + 60
        for _ in range(steps):
            b = by_t.get(v)
            v += 60
            if b is None:
                continue
            last = b["c"]
            if ex.bar(b["o"], b["h"], b["l"], b["c"]):
                break
        out, r_val = ex.close(last)
        res["fired"] += 1
        res[out] += 1
        res["r"].append(r_val)
        res["trades"].append({"time": trig["t"] + 60, "entry": entry, "risk_pct": round(risk / entry * 100, 3),
                              "outcome": out, "r": round(r_val, 3)})
        step = rmin * 60
        t += max(1, -(-(v - t) // step)) * step  # the first range start after the trade ended
    if res["fired"]:
        c = [ru["round_trip_pct"] / tr["risk_pct"] for tr in res["trades"]]
        for tr, ci in zip(res["trades"], c):
            tr["r_net"] = round(tr["r"] - ci, 3)
        res["avg_r"] = sum(res["r"]) / res["fired"]
        res["avg_r_net"] = sum(r - ci for r, ci in zip(res["r"], c)) / res["fired"]
    return res


def exits_text(exits):
    ex = exits or {}
    parts = []
    if ex.get("scale_r"):
        parts.append("sell %g%% at %gR, then the stop to the entry" % (float(ex.get("scale_pct") or 0), float(ex["scale_r"])))
    if ex.get("trail_r"):
        parts.append("trail the stop %gR under the high" % float(ex["trail_r"]))
    return "; ".join(parts) or "all at the stop, the target or the time stop"


def verdict(plan, mc):
    if (mc.get("exits") or {}).get("scale_r") or (mc.get("exits") or {}).get("trail_r"):
        r = mc["avg_r_net"]
        if r > 0.1:
            head = "Positive after costs: %+.3fR a trade on average with %s." % (r, exits_text(mc["exits"]))
        elif r < -0.1:
            head = "Negative after costs: %+.3fR a trade on average with %s." % (r, exits_text(mc["exits"]))
        else:
            head = "Close to break-even after costs: %+.3fR a trade on average with %s." % (r, exits_text(mc["exits"]))
        lines = ["Target first %.1f %%, full stop %.1f %%, managed exits %.1f %%, still open %.1f %%." % (
            mc["target_pct"], mc["stop_pct"], mc["managed_pct"], mc["neither_pct"]),
            "Costs take %.2fR a trade (%.2f %% round trip on a %.2f %% risk)." % (
                mc["costs_in_r"], plan["costs"]["round_trip_pct"], plan["risk_pct"])]
        return head, lines
    decided = mc["target"] + mc["stop"]
    R = float(plan["target_r"])
    c = mc["costs_in_r"]
    need = (1 + c) / (R + 1) * 100.0
    lines = []
    if decided == 0:
        head = "Undecided: no replay reached the stop or the target before the time stop."
    else:
        got = 100.0 * mc["target"] / decided
        d = got - need
        if need >= 100:
            head = ("No edge possible: after costs of %.2fR this target cannot pay for the losses, whatever the odds."
                    % c)
        elif abs(d) < 5:
            head = ("Close to break-even after costs: the target came first in %.1f %% of the replays that hit a side; "
                    "a %gR plan with %.2fR of costs needs %.1f %%." % (got, R, c, need))
        elif abs(d) < 15:
            head = "Leans toward the %s: target first in %.1f %% of the decided replays, break-even after costs is %.1f %%." % (
                "target" if d > 0 else "stop", got, need)
        else:
            head = "Strongly toward the %s: target first in %.1f %% of the decided replays, break-even after costs is %.1f %%." % (
                "target" if d > 0 else "stop", got, need)
        if mc["neither_pct"] > 40:
            lines.append("%.1f %% of the replays hit neither by the time stop; the price then decides those." % mc["neither_pct"])
        if decided and ((d > 0 and mc["avg_r_net"] < 0) or (d < 0 and mc["avg_r_net"] > 0)):
            lines.append("The average R after costs is %+.3f, against that lean: the replays that hit neither decide it."
                         % mc["avg_r_net"])
    lines.append("Costs take %.2fR a trade (%.2f %% round trip on a %.2f %% risk)." % (
        c, plan["costs"]["round_trip_pct"], plan["risk_pct"]))
    return head, lines


# ---------------------------------------------------------------- output

def render(plan, mc, hist, head, below, tz, pool_info):
    end = plan["entry_time"] + mc["steps"] * 60
    out = ["%s replays of the next %d minutes (%s to %s %s), drawn in %d-minute blocks from %s's own 1-minute bars" % (
        "{:,}".format(mc["replays"]), mc["steps"], local_str(plan["entry_time"], tz), local_str(end, tz), tz,
        mc["block"], plan.get("symbol") or "the coin"),
        "of the last %.1f days (%s bars), seed %d." % (pool_info["days"], "{:,}".format(pool_info["bars"]), mc["seed"]),
        "  plan: entry $%s, stop $%s (-%.2f %%), target $%s (%gR); exits: %s" % (
            fp(plan["entry"]), fp(plan["stop"]), plan["risk_pct"], fp(plan["target"]), plan["target_r"],
            exits_text(mc.get("exits"))),
        "  target first   %5.1f %%" % mc["target_pct"],
        "  stop first     %5.1f %%" % mc["stop_pct"],
        "  neither        %5.1f %%   still open at %s (the time stop)" % (mc["neither_pct"], local_str(end, tz))] + (
        ["  managed        %5.1f %%   stopped after a partial take or a trailing move" % mc["managed_pct"]]
        if (mc.get("exits") or {}) else []) + [
        "  green          %5.1f %%   target first, or above the entry at %s" % (mc["green_pct"], local_str(end, tz)),
        "  green after costs %5.1f %%" % mc["green_after_costs_pct"],
        "  Price at %s: median $%s, 90 %% of replays between $%s and $%s." % (
            local_str(end, tz), fp(mc["close_median"]), fp(mc["close_p05"]), fp(mc["close_p95"])),
        "  Average R: %+.3f before costs, %+.3f after costs." % (mc["avg_r"], mc["avg_r_net"])]
    if mc["gap_stops"]:
        out.append("  %d replays opened a minute below the stop (a gap): counted as -1R, a real fill would be worse." % mc["gap_stops"])
    if hist.get("fired"):
        out.append("History: the same rule on the last %.1f days of real bars (%d ranges) fired %d times: %d target, "
                   "%d stop, %s%d neither. Average R %+.3f before costs, %+.3f after.%s" % (
                       pool_info["days"], hist["ranges"], hist["fired"], hist["target"], hist["stop"],
                       ("%d managed, " % hist["managed"]) if hist.get("managed") else "",
                       hist["neither"], hist["avg_r"], hist["avg_r_net"],
                       (" %d more breakouts had a stop inside the costs (meme-exit refuses those)." % hist["refused"])
                       if hist.get("refused") else ""))
    elif hist.get("note"):
        out.append("History: %s." % hist["note"])
    else:
        out.append("History: the rule never fired in the last %.1f days (%d ranges)." % (pool_info["days"], hist["ranges"]))
    out.append(head)
    out.extend(below)
    out.append("Built from the last few days of this coin, not a prediction. A rug, a dev sell or a listing can do "
               "what those days never did.")
    return "\n".join(out)


def chart(saved, tz, width=60, height=16):
    plan, mc = saved["plan"], saved["mc"]
    bands = mc["bands"]
    lo = min(min(b) for b in bands + [[plan["stop"]]])
    hi = max(max(b) for b in bands + [[plan["target"]]])
    span = (hi - lo) or 1.0
    cols = [bands[int(i * (len(bands) - 1) / max(1, width - 1))] for i in range(width)]
    grid = [[" "] * width for _ in range(height)]

    def row(v):
        return max(0, min(height - 1, int(round((hi - v) / span * (height - 1)))))

    for x, b in enumerate(cols):
        for y in range(row(b[4]), row(b[0]) + 1):
            grid[y][x] = "."
        for y in range(row(b[3]), row(b[1]) + 1):
            grid[y][x] = ":"
        grid[row(b[2])][x] = "*"
    for v, ch in ((plan["target"], "T"), (plan["entry"], "-"), (plan["stop"], "S")):
        y = row(v)
        for x in range(width):
            if grid[y][x] == " ":
                grid[y][x] = ch
    lines = []
    for y in range(height):
        v = hi - span * y / (height - 1)
        lines.append("%12s |%s" % (fp(v), "".join(grid[y])))
    lines.append("%12s  %s%s" % ("", local_str(plan["entry_time"], tz), local_str(plan["entry_time"] + mc["steps"] * 60, tz).rjust(width - 5)))
    lines.append("  * median   : 25-75 %   . 5-95 %   T target   S stop   - entry")
    return "\n".join(lines)


def parse_exits(scale, trail, plan_exits=None, none=False):
    """--scale 1.5R:50 and --trail 1R (or the plan's exits) -> the exits dict."""
    if none:
        return {}
    ex = dict(plan_exits or {})
    if scale:
        m = re.match(r"^\s*(\d+(?:\.\d+)?)R?\s*:\s*(\d+(?:\.\d+)?)\s*$", scale, re.I)
        if not m or not 0 < float(m.group(2)) < 100:
            raise TMError("--scale wants R:PERCENT, like 1.5R:50")
        ex.update(scale_r=float(m.group(1)), scale_pct=float(m.group(2)))
    if trail:
        m = re.match(r"^\s*(\d+(?:\.\d+)?)R?\s*$", trail, re.I)
        if not m:
            raise TMError("--trail wants a distance in R, like 1R")
        ex["trail_r"] = float(m.group(1))
    return ex


GRID = {"stops": ["range-low", "range-mid", "pct:4", "pct:6", "pct:8"], "targets": [1.5, 2.0, 3.0, 4.0],
        "holds": [30, 60, 120], "exits": [("none", {}), ("scale 1.5R:50", {"scale_r": 1.5, "scale_pct": 50}),
                                           ("trail 1R", {"trail_r": 1.0})]}


def split(rows, frac=2.0 / 3):
    cut = rows[0]["t"] + (rows[-1]["t"] - rows[0]["t"]) * frac
    return [b for b in rows if b["t"] < cut], [b for b in rows if b["t"] >= cut]


def compare(plan, rows, min_trades=8, grid=None):
    """Every combination of stop, target, hold and exits on the first two thirds of the days (in-sample), ranked,
    and the same combination on the last third it never saw (out-of-sample)."""
    g = grid or GRID
    ins, oos = split(rows)
    base = rule_of(plan)
    res = []
    for st in g["stops"]:
        for tr in g["targets"]:
            for hold in g["holds"]:
                for exname, ex in g["exits"]:
                    ru = dict(base, stop_rule=st, target_r=tr)
                    hi, ho = history(plan, ins, hold, ex, ru), history(plan, oos, hold, ex, ru)
                    res.append({"stop": st, "target_r": tr, "hold": hold, "exits": exname,
                                "in_trades": hi["fired"], "in_r": hi.get("avg_r_net"),
                                "out_trades": ho["fired"], "out_r": ho.get("avg_r_net")})
    ranked = sorted([r for r in res if r["in_trades"] >= min_trades and r["in_r"] is not None],
                    key=lambda r: -r["in_r"])
    return res, ranked, (len(ins), len(oos))


def ruin(r_nets, start_usd, risk_usd, trades=50, runs=10000, seed=19, floor_pct=50.0):
    """Bootstrap the real per-trade results (R after costs) into many sequences for this account."""
    if not r_nets:
        raise TMError("no trades to draw from")
    rng = random.Random(seed)
    floor = start_usd * floor_pct / 100.0
    ends, broke = [], 0
    for _ in range(runs):
        bal, hit = start_usd, False
        for _ in range(trades):
            bal += r_nets[rng.randrange(len(r_nets))] * risk_usd
            if bal <= floor:
                hit = True
            if bal <= 0:
                bal = 0.0
                break
        broke += hit
        ends.append(bal)
    ends.sort()

    def q(x):
        return ends[min(len(ends) - 1, int(round(x * (len(ends) - 1))))]

    return {"runs": runs, "trades": trades, "seed": seed, "start": start_usd, "risk_usd": risk_usd,
            "floor_pct": floor_pct, "p_floor": 100.0 * broke / runs,
            "p_up": 100.0 * sum(1 for e in ends if e > start_usd) / runs,
            "median": q(0.5), "p05": q(0.05), "p95": q(0.95), "mean": sum(ends) / runs,
            "avg_r_net": sum(r_nets) / len(r_nets), "sample": len(r_nets)}


def multi_coins(args_tokens, base):
    """Which coins to test: --tokens, else the watchlist hits, else the liquid universe."""
    if args_tokens:
        coins = [{"chain": "solana", "address": t.strip(), "symbol": None} for t in args_tokens.split(",") if t.strip()]
        known = {}
        for f in ("safety.json", "prices.json"):
            for a, row in (load(os.path.join(base, f), {}) or {}).items():
                if isinstance(row, dict) and row.get("symbol"):
                    known.setdefault(a, row["symbol"])
        missing = [c["address"] for c in coins if c["address"] not in known]
        if missing:
            try:  # one DexScreener request names up to 30 coins
                pairs = get_json("https://api.dexscreener.com/tokens/v1/solana/%s" % ",".join(missing[:30]))
                for p in pairs if isinstance(pairs, list) else []:
                    known.setdefault((p.get("baseToken") or {}).get("address"), (p.get("baseToken") or {}).get("symbol"))
            except TMError:
                pass
        for c in coins:
            c["symbol"] = known.get(c["address"])
        return coins
    wl = load(os.path.join(base, "watchlist.json"), {}) or {}
    rows = wl.get("hits") or []
    if not rows:
        uni = load(os.path.join(base, "universe.json"), {}) or {}
        rows = [t for t in uni.get("tokens", []) if (t.get("liquidity_usd") or 0) >= 50000]
    return [{"chain": r.get("chain", "solana"), "address": r["address"], "symbol": r.get("symbol"), "pair": r.get("pair")}
            for r in rows]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Time machine (meme-timemachine). Simulates and tests, never trades.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--replays", type=int, default=10000)
    p.add_argument("--seed", type=int, default=19)
    p.add_argument("--block", type=int, default=10, help="minutes per drawn block")
    p.add_argument("--minutes", type=int, help="how long each replay runs (default: the plan's time stop)")
    p.add_argument("--write", action="store_true")
    for q in (p, sub.add_parser("compare"), sub.add_parser("multi"), sub.add_parser("ruin")):
        q.add_argument("--plan", default=None, help="path to plan.json (default meme/plan.json)")
        q.add_argument("--days", type=float, default=3.0, help="days of history")
        q.add_argument("--offline", help="saved 1-minute bars (.json/.json.gz), or for multi a {mint: bars} bundle")
        q.add_argument("--json", action="store_true")
        q.add_argument("--scale", help="partial take, like 1.5R:50 (sell 50 %% at 1.5R, stop to the entry)")
        q.add_argument("--trail", help="trailing stop distance, like 1R")
        q.add_argument("--no-exits", action="store_true", help="ignore the plan's partial and trailing exits")
        if q is not p:
            q.add_argument("--min-trades", type=int, default=8)
            q.add_argument("--tokens", help="multi: comma list of mints (default: the watchlist)")
            q.add_argument("--trades", type=int, default=50, help="ruin: trades in one sequence")
            q.add_argument("--runs", type=int, default=10000)
            q.add_argument("--seed", type=int, default=19)
            q.add_argument("--from-multi", action="store_true", help="ruin: draw from the last multi run's trades")
    c = sub.add_parser("chart")
    c.add_argument("--from", dest="src", default=None, help="a saved meme/timemachine.json")
    a = ap.parse_args(argv)
    base = mdir()
    cfg = load(os.path.join(base, "config.json"), {}) or {}
    tz = cfg.get("timezone") or "Europe/Berlin"
    if a.cmd == "chart":
        saved = load(a.src or os.path.join(base, "timemachine.json"))
        if not saved:
            print("No saved run. Run: timemachine.py run --write")
            return 1
        print(chart(saved, tz))
        return 0
    try:
        plan = load(a.plan or os.path.join(base, "plan.json"))
        if not plan or "entry" not in plan:
            raise TMError("no plan: run /meme-exit plan --write first")
        if plan["stop"] >= plan["entry"] or plan["target"] <= plan["entry"]:
            raise TMError("the plan does not make sense for a long (stop under the entry, target over it)")
        exits = parse_exits(a.scale, a.trail, plan.get("exits"), a.no_exits)
        if a.cmd == "multi":
            return run_multi(a, plan, exits, base, tz, cfg)
        if a.cmd == "ruin" and a.from_multi:
            return run_ruin(a, plan, None, base, tz, cfg)
        if a.offline:
            raw = load(a.offline)
            bars = parse_bars(raw, plan["address"] if "responses" in (raw or {}) else None)
        else:
            bars = fetch_history(plan, a.days)
        rows, ratios = pool_of(bars, plan, a.days)
        if len(rows) < MIN_POOL_BARS:
            raise TMError("only %d one-minute bars before the entry (need %d, one day): the coin is too new or too "
                          "thin to replay fairly" % (len(rows), MIN_POOL_BARS))
        steps = int(plan.get("max_hold_minutes") or 60)
        if a.cmd == "compare":
            return run_compare(a, plan, rows, tz)
        if a.cmd == "ruin":
            return run_ruin(a, plan, history(plan, rows, steps, exits), base, tz, cfg)
        steps = a.minutes or steps
        mc = replay(plan, ratios, steps, a.replays, a.seed, a.block, exits=exits)
        hist = history(plan, rows, steps, exits)
        head, below = verdict(plan, mc)
        pool_info = {"bars": len(rows), "days": round((rows[-1]["t"] - rows[0]["t"] + 60) / 86400.0, 1),
                     "from": rows[0]["t"], "to": rows[-1]["t"] + 60}
    except TMError as e:
        print("No replay: %s" % e)
        return 1
    result = {"plan": plan, "mc": mc, "history": {k: v for k, v in hist.items() if k != "r"},
              "verdict": head, "notes": below, "pool": pool_info}
    if a.write:
        slim = dict(result)
        slim["mc"] = dict(mc)
        save(os.path.join(base, "timemachine.json"), slim)
    if a.json:
        out = dict(result)
        out["mc"] = {k: v for k, v in mc.items() if k not in ("paths", "bands")}
        out["history"] = {k: v for k, v in hist.items() if k not in ("r", "trades")}
        print(json.dumps(out, indent=2))
    else:
        print(render(plan, mc, hist, head, below, tz, pool_info))
        if a.write:
            print("Saved meme/timemachine.json. Next, if you still want it: /meme-budget sizes it.")
    return 0


def _r(v):
    return "   n/a" if v is None else "%+.3f" % v


def run_compare(a, plan, rows, tz):
    res, ranked, (n_in, n_out) = compare(plan, rows, a.min_trades)
    own = rule_of(plan)
    mine = [r for r in res if r["stop"] == own["stop_rule"] and r["target_r"] == own["target_r"]
            and r["hold"] == int(plan.get("max_hold_minutes") or 60) and r["exits"] == "none"]
    if a.json:
        print(json.dumps({"ranked": ranked[:20], "plan": mine, "bars": [n_in, n_out]}, indent=2))
        return 0
    print("%d combinations of stop, target, hold and exits on %s's 1-minute bars: the first two thirds (%d bars) to "
          "pick, the last third (%d bars, never seen) to check. R is after costs." % (
              len(res), plan.get("symbol") or "the coin", n_in, n_out))
    print("  %-10s %-6s %-5s %-14s %14s %15s" % ("stop", "target", "hold", "exits", "picked on (R)", "unseen third (R)"))
    for r in ranked[:8]:
        print("  %-10s %-6s %-5s %-14s %6s (%3d tr) %7s (%3d tr)" % (r["stop"], "%gR" % r["target_r"], r["hold"], r["exits"],
                                                                     _r(r["in_r"]), r["in_trades"], _r(r["out_r"]), r["out_trades"]))
    for r in mine:
        print("  your plan: %s, %gR, %d min: %s (%d trades) picked on, %s (%d trades) unseen." % (
            r["stop"], r["target_r"], r["hold"], _r(r["in_r"]), r["in_trades"], _r(r["out_r"]), r["out_trades"]))
    if not ranked:
        print("No combination fired %d times in the first two thirds: too few trades to compare." % a.min_trades)
        return 0
    best = ranked[0]
    pos_out = sum(1 for r in ranked[:8] if (r["out_r"] or 0) > 0 and r["out_trades"] >= 3)
    if best["out_r"] is None or best["out_trades"] < 3:
        print("The best pick fired %d times in the unseen third: too few to confirm anything." % best["out_trades"])
    elif best["out_r"] > 0:
        print("The best pick held up on the unseen third (%s over %d trades). Still a small sample: check it again "
              "on other coins (timemachine.py multi)." % (_r(best["out_r"]), best["out_trades"]))
    else:
        print("The best pick LOST on the unseen third (%s over %d trades): what looked best was likely luck "
              "(curve fitting). Do not trade it on the strength of this table." % (_r(best["out_r"]), best["out_trades"]))
    print("%d of the top 8 were positive on the unseen third." % pos_out)
    return 0


def run_multi(a, plan, exits, base, tz, cfg):
    coins = multi_coins(a.tokens, base)
    if not coins and not a.offline:
        raise TMError("no coins: run /meme-scanner pairs first, or give --tokens")
    bundle = load(a.offline) if a.offline else None
    if bundle is not None:
        coins = [{"chain": "solana", "address": k, "symbol": (v or {}).get("symbol")} for k, v in sorted(bundle.items())]
    steps = int(plan.get("max_hold_minutes") or 60)
    rule = rule_of(plan)
    now = int(time.time()) if bundle is None else max(int(c["time"]) for v in bundle.values() for c in v["candles"]) + 60
    per, all_in, all_out, failed = [], [], [], 0
    for coin in coins:
        try:
            if bundle is not None:
                bars = parse_bars(bundle[coin["address"]])
            else:
                bars = fetch_history({"address": coin["address"], "chain": coin["chain"], "pair": coin.get("pair"),
                                      "entry_time": now}, a.days)
        except TMError:
            failed += 1
            continue
        rows = [b for b in bars if b["t"] + 60 <= now]
        if len(rows) < 600:
            failed += 1
            continue
        ins, oos = split(rows)
        hi, ho = history(plan, ins, steps, exits, rule), history(plan, oos, steps, exits, rule)
        r_in = [t["r_net"] for t in hi["trades"]]
        r_out = [t["r_net"] for t in ho["trades"]]
        all_in.extend(r_in)
        all_out.extend(r_out)
        per.append({"address": coin["address"], "symbol": coin.get("symbol"), "bars": len(rows),
                    "days": round((rows[-1]["t"] - rows[0]["t"] + 60) / 86400.0, 2),
                    "trades": len(r_in) + len(r_out), "avg_r_net": (sum(r_in + r_out) / len(r_in + r_out)) if (r_in or r_out) else None,
                    "r_nets": r_in + r_out})
    if not per:
        raise TMError("no coin had enough 1-minute bars")
    allr = all_in + all_out
    summary = {"coins": len(per), "failed": failed, "trades": len(allr),
               "avg_r_net": (sum(allr) / len(allr)) if allr else None,
               "in_r": (sum(all_in) / len(all_in)) if all_in else None, "out_r": (sum(all_out) / len(all_out)) if all_out else None,
               "coins_positive": sum(1 for c in per if (c["avg_r_net"] or 0) > 0 and c["trades"]),
               "rule": rule, "exits": exits}
    save(os.path.join(base, "multi.json"), {"summary": summary, "coins": per})
    if a.json:
        print(json.dumps({"summary": summary, "coins": [{k: v for k, v in c.items() if k != "r_nets"} for c in per]}, indent=2))
        return 0
    print("The rule (%d-minute range, %s stop, %gR target, %d-minute time stop; %s) on %d coins, %.1f days of 1-minute "
          "bars each on average%s:" % (rule["range_minutes"], rule["stop_rule"], rule["target_r"], steps, exits_text(exits),
                                        len(per), sum(c["days"] for c in per) / len(per),
                                        (", %d without enough bars" % failed) if failed else ""))
    for c in sorted(per, key=lambda c: -(c["avg_r_net"] if c["avg_r_net"] is not None else -9)):
        print("  %-10s %3d trades  %s after costs   %s" % ((c["symbol"] or "?")[:10], c["trades"], _r(c["avg_r_net"]), c["address"]))
    print("All together: %d trades, %s a trade after costs (first two thirds %s, last third %s); %d of %d coins positive." % (
        summary["trades"], _r(summary["avg_r_net"]), _r(summary["in_r"]), _r(summary["out_r"]),
        summary["coins_positive"], len(per)))
    if summary["avg_r_net"] is not None and summary["avg_r_net"] <= 0:
        print("Across these coins the rule lost money after costs. A coin where it 'worked' is most likely luck.")
    print("Saved meme/multi.json. timemachine.py ruin --from-multi shows what that means for your account.")
    return 0


def run_ruin(a, plan, hist, base, tz, cfg):
    if hist is None:
        m = load(os.path.join(base, "multi.json"))
        if not m:
            raise TMError("no meme/multi.json: run timemachine.py multi first")
        r_nets = [r for c in m["coins"] for r in c["r_nets"]]
        src = "%d trades on %d coins (multi)" % (len(r_nets), len(m["coins"]))
    else:
        r_nets = [t["r_net"] for t in hist.get("trades", [])]
        src = "%d real trades of the rule on %s" % (len(r_nets), plan.get("symbol") or "this coin")
    start = float(cfg.get("budget_usd") or 111)
    risk = float(cfg.get("max_loss_per_trade_usd") or 3.3)
    res = ruin(r_nets, start, risk, a.trades, a.runs, a.seed)
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print("Your account: $%.2f, losing up to $%.2f a trade at the stop. %s sequences of %d trades, each trade drawn "
          "from %s (seed %d):" % (start, risk, "{:,}".format(res["runs"]), res["trades"], src, res["seed"]))
    print("  average result of those trades: %+.3fR after costs" % res["avg_r_net"])
    print("  chance the account falls to half or less on the way: %.1f %%" % res["p_floor"])
    print("  chance it ends above $%.2f: %.1f %%" % (start, res["p_up"]))
    print("  where it ends: median $%.2f, 90 %% between $%.2f and $%.2f" % (res["median"], res["p05"], res["p95"]))
    if res["sample"] < 30:
        print("Only %d trades to draw from: a small sample, so these odds are rough." % res["sample"])
    print("Past trades, reshuffled. Not a forecast: a rug or a new market can do worse than any of them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
