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


def replay(plan, ratios, steps, replays=10000, seed=19, block=10, keep_paths=160):
    rng = random.Random(seed)
    entry, stop, target = float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    risk = entry - stop
    n = len(ratios)
    if n < block + 1:
        raise TMError("too few bars to draw from")
    hit_t = hit_s = 0
    gap_s = 0
    rs, closes, paths = [], [], []
    band_cols = [[] for _ in range(steps)]
    for k in range(replays):
        p = entry
        outcome = None
        r_val = None
        path = [] if k < keep_paths else None
        j = 0
        idx = 0
        for s in range(steps):
            if j == 0:
                idx = rng.randrange(0, n - block)
            ro, rh, rl, rc = ratios[idx + j]
            j = (j + 1) % block
            o, h, l, c = p * ro, p * rh, p * rl, p * rc
            if outcome is None:
                if l <= stop:
                    outcome, r_val = "stop", -1.0
                    if o <= stop:
                        gap_s += 1
                elif h >= target:
                    outcome, r_val = "target", (target - entry) / risk
            p = c
            band_cols[s].append(p)
            if path is not None:
                path.append(round(p, 12))
        if outcome is None:
            outcome, r_val = "neither", (p - entry) / risk
        if outcome == "target":
            hit_t += 1
        elif outcome == "stop":
            hit_s += 1
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
    neither = replays - hit_t - hit_s
    c_r = plan["costs"]["round_trip_pct"] / plan["risk_pct"]
    green_net = sum(1 for r, x in zip(rs, closes) if r - c_r > 0)
    return {"replays": replays, "seed": seed, "block": block, "steps": steps,
            "target": hit_t, "stop": hit_s, "neither": neither, "gap_stops": gap_s,
            "target_pct": 100.0 * hit_t / replays, "stop_pct": 100.0 * hit_s / replays,
            "neither_pct": 100.0 * neither / replays,
            "green_pct": 100.0 * sum(1 for r in rs if r > 0) / replays,
            "green_after_costs_pct": 100.0 * green_net / replays,
            "close_median": pct(closes_sorted, 0.5), "close_p05": pct(closes_sorted, 0.05),
            "close_p95": pct(closes_sorted, 0.95), "avg_r": sum(rs) / replays,
            "avg_r_net": sum(rs) / replays - c_r, "costs_in_r": c_r, "bands": bands, "paths": paths}


def history(plan, rows, steps):
    """The plan's own rule on every past range in the pool: what really happened."""
    rmin = int(plan.get("range_minutes") or 15)
    vol_x = float(plan.get("vol_x") if plan.get("vol_x") is not None else 1.5)
    max_wait = int(plan.get("max_wait") or 60)
    target_r = float(plan["target_r"])
    rule = str(plan.get("stop_rule", "range-low")).lower()
    by_t = {b["t"]: b for b in rows}
    res = {"ranges": 0, "fired": 0, "target": 0, "stop": 0, "neither": 0, "r": [], "trades": []}
    if plan.get("setup") != "range":
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
        if rule == "range-mid":
            stop = (hi + lo) / 2.0
        elif rule == "range-low":
            stop = lo
        else:  # pct, price, atr: keep the plan's distance in percent
            stop = entry * (1 - plan["risk_pct"] / 100.0)
        if stop >= entry:
            t += rmin * 60
            continue
        risk = entry - stop
        target = entry + target_r * risk
        out, r_val, last = None, None, entry
        v = trig["t"] + 60
        for _ in range(steps):
            b = by_t.get(v)
            v += 60
            if b is None:
                continue
            last = b["c"]
            if b["l"] <= stop:
                out, r_val = "stop", -1.0
                break
            if b["h"] >= target:
                out, r_val = "target", target_r
                break
        if out is None:
            out, r_val = "neither", (last - entry) / risk
        res["fired"] += 1
        res[out] += 1
        res["r"].append(r_val)
        res["trades"].append({"time": trig["t"] + 60, "entry": entry, "risk_pct": round(risk / entry * 100, 3),
                              "outcome": out, "r": round(r_val, 3)})
        step = rmin * 60
        t += max(1, -(-(v - t) // step)) * step  # the first range start after the trade ended
    if res["fired"]:
        c = [plan["costs"]["round_trip_pct"] / tr["risk_pct"] for tr in res["trades"]]
        res["avg_r"] = sum(res["r"]) / res["fired"]
        res["avg_r_net"] = sum(r - ci for r, ci in zip(res["r"], c)) / res["fired"]
    return res


def verdict(plan, mc):
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
        "  plan: entry $%s, stop $%s (-%.2f %%), target $%s (%gR)" % (
            fp(plan["entry"]), fp(plan["stop"]), plan["risk_pct"], fp(plan["target"]), plan["target_r"]),
        "  target first   %5.1f %%" % mc["target_pct"],
        "  stop first     %5.1f %%" % mc["stop_pct"],
        "  neither        %5.1f %%   still open at %s (the time stop)" % (mc["neither_pct"], local_str(end, tz)),
        "  green          %5.1f %%   target first, or above the entry at %s" % (mc["green_pct"], local_str(end, tz)),
        "  green after costs %5.1f %%" % mc["green_after_costs_pct"],
        "  Price at %s: median $%s, 90 %% of replays between $%s and $%s." % (
            local_str(end, tz), fp(mc["close_median"]), fp(mc["close_p05"]), fp(mc["close_p95"])),
        "  Average R: %+.3f before costs, %+.3f after costs." % (mc["avg_r"], mc["avg_r_net"])]
    if mc["gap_stops"]:
        out.append("  %d replays opened a minute below the stop (a gap): counted as -1R, a real fill would be worse." % mc["gap_stops"])
    if hist.get("fired"):
        out.append("History: the same rule on the last %.1f days of real bars (%d ranges) fired %d times: %d target, "
                   "%d stop, %d neither. Average R %+.3f before costs, %+.3f after." % (
                       pool_info["days"], hist["ranges"], hist["fired"], hist["target"], hist["stop"],
                       hist["neither"], hist["avg_r"], hist["avg_r_net"]))
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Time machine (meme-timemachine). Simulates, never trades.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--plan", default=None, help="path to plan.json (default meme/plan.json)")
    p.add_argument("--replays", type=int, default=10000)
    p.add_argument("--seed", type=int, default=19)
    p.add_argument("--block", type=int, default=10, help="minutes per drawn block")
    p.add_argument("--days", type=float, default=3.0, help="days of history in the pool")
    p.add_argument("--minutes", type=int, help="how long each replay runs (default: the plan's time stop)")
    p.add_argument("--offline", help="saved 1-minute bars (.json/.json.gz, Jupiter or GeckoTerminal)")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    c = sub.add_parser("chart")
    c.add_argument("--from", dest="src", default=None, help="a saved meme/timemachine.json")
    a = ap.parse_args(argv)
    cfg = load(os.path.join(mdir(), "config.json"), {}) or {}
    tz = cfg.get("timezone") or "Europe/Berlin"
    if a.cmd == "chart":
        saved = load(a.src or os.path.join(mdir(), "timemachine.json"))
        if not saved:
            print("No saved run. Run: timemachine.py run --write")
            return 1
        print(chart(saved, tz))
        return 0
    try:
        plan = load(a.plan or os.path.join(mdir(), "plan.json"))
        if not plan or "entry" not in plan:
            raise TMError("no plan: run /meme-exit plan --write first")
        if plan["stop"] >= plan["entry"] or plan["target"] <= plan["entry"]:
            raise TMError("the plan does not make sense for a long (stop under the entry, target over it)")
        if a.offline:
            bars = parse_bars(load(a.offline), plan["address"] if "responses" in (load(a.offline) or {}) else None)
        else:
            bars = fetch_history(plan, a.days)
        rows, ratios = pool_of(bars, plan, a.days)
        if len(rows) < MIN_POOL_BARS:
            raise TMError("only %d one-minute bars before the entry (need %d, one day): the coin is too new or too "
                          "thin to replay fairly" % (len(rows), MIN_POOL_BARS))
        steps = a.minutes or int(plan.get("max_hold_minutes") or 60)
        mc = replay(plan, ratios, steps, a.replays, a.seed, a.block)
        hist = history(plan, rows, steps)
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
        save(os.path.join(mdir(), "timemachine.json"), slim)
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


if __name__ == "__main__":
    sys.exit(main())
