#!/usr/bin/env python3
"""The Whale Tracker (meme-whales). Standard library only.

Watches public Solana wallets: a coin's dev (creator) wallet, the big holders
the analyst found, or any wallet you name. Every Solana transaction is public
the second it lands, so this reads them straight from a Solana RPC node,
turns each one into a plain row (who, buy or sell or transfer, how many
tokens of which coin, how much SOL) and alerts once per new transaction. A
dev wallet that sells or moves its own coin is flagged first: that is the
classic start of a rug.

    python3 whales.py dev MINT                       # watch this coin's creator (from /meme-analyst)
    python3 whales.py add WALLET --label "big GATO holder"
    python3 whales.py check                          # new transactions since the last check
    python3 whales.py check --limit 10
    python3 whales.py list
    python3 whales.py remove WALLET

Public wallets, public data. It reads only; it never signs or sends anything.
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
RPC = "https://api.mainnet-beta.solana.com"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/%s/report"
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT"}
ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class WhaleError(Exception):
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


def local_str(ts, tz, fmt="%Y-%m-%d %H:%M"):
    return time.strftime(fmt, time.gmtime(ts + utc_offset(ts, tz) * 60))


# ---------------------------------------------------------------- the RPC

class Chain:
    def __init__(self, url=RPC, offline=None, pause=0.6):
        self.url, self.offline, self.pause, self.calls = url, offline, pause, 0

    def call(self, method, params):
        if self.offline:
            if method == "getSignaturesForAddress":
                d = load(os.path.join(self.offline, "sigs-%s.json" % params[0]))
            else:
                d = load(os.path.join(self.offline, "tx-%s.json" % params[0]))
            if d is None:
                raise WhaleError("the offline folder has no answer for %s %s" % (method, params[0][:12]))
            return d.get("result") if isinstance(d, dict) and "result" in d else d
        if self.calls:
            time.sleep(self.pause)
        self.calls += 1
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
        for i in range(4):
            try:
                req = urllib.request.Request(self.url, data=body, headers={"User-Agent": UA, "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                if "error" in d:
                    raise WhaleError("the RPC said: %s" % (d["error"].get("message") if isinstance(d["error"], dict) else d["error"]))
                return d.get("result")
            except urllib.error.HTTPError as e:
                if e.code == 429 and i < 3:
                    time.sleep(8 * (i + 1))
                    continue
                raise WhaleError("the Solana RPC answered HTTP %d (public nodes are rate limited; set solana_rpc in "
                                 "meme/config.json to your own endpoint)" % e.code)
            except (urllib.error.URLError, OSError, ValueError) as e:
                if i == 3:
                    raise WhaleError("could not reach the Solana RPC (%s)" % e)
                time.sleep(3)


# ---------------------------------------------------------------- reading a transaction

def deltas(tx, wallet):
    """A jsonParsed transaction -> ({mint: token delta}, SOL delta) for this wallet. WSOL counts as SOL."""
    meta = tx.get("meta") or {}
    msg = (tx.get("transaction") or {}).get("message") or {}
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in msg.get("accountKeys") or []]
    sol = 0.0
    if wallet in keys:
        i = keys.index(wallet)
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        if i < len(pre) and i < len(post):
            sol = (post[i] - pre[i]) / 1e9
    pre_t, post_t = {}, {}
    for src, dst in ((meta.get("preTokenBalances") or [], pre_t), (meta.get("postTokenBalances") or [], post_t)):
        for b in src:
            if b.get("owner") != wallet:
                continue
            amt = float((b.get("uiTokenAmount") or {}).get("uiAmountString") or 0)
            dst[b["mint"]] = dst.get(b["mint"], 0.0) + amt
    toks = {}
    for mint in set(pre_t) | set(post_t):
        d = post_t.get(mint, 0.0) - pre_t.get(mint, 0.0)
        if abs(d) > 1e-12:
            if mint == WSOL:
                sol += d
            else:
                toks[mint] = d
    return toks, sol


def classify(toks, sol, fee_sol=0.0):
    """-> [(action, mint, amount, sol, stable)] one row per coin that moved."""
    stable_moves = {m: d for m, d in toks.items() if m in STABLES}
    rows = []
    paid = sol + fee_sol  # the fee is not a trade
    for mint, d in toks.items():
        if mint in STABLES:
            continue
        stable = sum(stable_moves.values())
        if d > 0 and (paid < -0.001 or stable < -0.01):
            act = "BUY"
        elif d < 0 and (paid > 0.001 or stable > 0.01):
            act = "SELL"
        elif d > 0:
            act = "RECEIVED"
        else:
            act = "SENT"
        rows.append((act, mint, d, paid, stable))
    if not rows and stable_moves:
        for mint, d in stable_moves.items():
            rows.append(("RECEIVED" if d > 0 else "SENT", mint, d, paid, 0.0))
    return rows


# ---------------------------------------------------------------- commands

def names():
    """mint -> symbol from everything the other skills wrote."""
    base = mdir()
    out = dict(STABLES)
    for a, q in (load(os.path.join(base, "prices.json"), {}) or {}).items():
        if isinstance(q, dict) and q.get("symbol"):
            out[a] = q["symbol"]
    for a, s in (load(os.path.join(base, "safety.json"), {}) or {}).items():
        if s.get("symbol"):
            out.setdefault(a, s["symbol"])
    for h in (load(os.path.join(base, "watchlist.json"), {}) or {}).get("hits", []):
        out.setdefault(h["address"], h.get("symbol"))
    for f in ("plan.json", "entry.json"):
        d = load(os.path.join(base, f)) or {}
        if d.get("address"):
            out.setdefault(d["address"], d.get("symbol"))
    return out


def mine():
    """(held, watched) sets of mints."""
    base = mdir()
    held = set(((load(os.path.join(base, "portfolio.json"), {}) or {}).get("positions") or {}).keys())
    watched = {h["address"] for h in (load(os.path.join(base, "watchlist.json"), {}) or {}).get("hits", [])}
    for f in ("plan.json", "entry.json"):
        d = load(os.path.join(base, f)) or {}
        if d.get("address"):
            watched.add(d["address"])
    return held, watched


def signed_by(account_keys, wallet):
    """Did the wallet sign this transaction itself? jsonParsed keys say so; plain keys cannot, so assume yes.

    A transfer the wallet did not sign was made by a program or by someone else: a fee payout, an
    airdrop, a spam token. That is not the wallet trading."""
    if not any(isinstance(k, dict) and "signer" in k for k in account_keys):
        return True
    return any(isinstance(k, dict) and k.get("pubkey") == wallet and k.get("signer") for k in account_keys)


def quiet(r):
    """A transfer the wallet did not sign, in a coin you neither hold nor watch: noise, summed up in one line."""
    return r.get("signed") is False and r["action"] in ("RECEIVED", "SENT") and not r["flags"]


def check(chain, wallets, state, limit, tz, window=1800):
    nm = names()
    held, watched = mine()
    sol_px = ((load(os.path.join(mdir(), "prices.json"), {}) or {}).get("SOL") or {}).get("price")
    alerts = []
    for w in wallets:
        addr = w["address"]
        last = state["last_sig"].get(addr)
        opts = {"limit": limit}
        if last:
            opts["until"] = last
        sigs = chain.call("getSignaturesForAddress", [addr, opts]) or []
        if sigs:
            state["last_sig"][addr] = sigs[0]["signature"]
        for s in reversed(sigs):
            sig = s["signature"]
            if sig in state["seen"] or s.get("err") is not None:
                continue
            state["seen"].append(sig)
            tx = chain.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
            if not tx:
                continue
            toks, sol = deltas(tx, addr)
            raw = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
            keys = [k["pubkey"] if isinstance(k, dict) else k for k in raw]
            fee = ((tx.get("meta") or {}).get("fee") or 0) / 1e9 if keys and keys[0] == addr else 0.0
            signed = signed_by(raw, addr)
            for act, mint, amt, paid, stable in classify(toks, sol, fee):
                flags = []
                if w.get("role") == "dev" and act in ("SELL", "SENT") and (not w.get("token") or w.get("token") == mint):
                    flags.append("DEV %s: %s" % ("SOLD" if act == "SELL" else "MOVED TOKENS",
                                                 "the creator is moving out of its own coin" if w.get("token") else
                                                 "a dev wallet is moving tokens out (no coin set for it: whales.py dev "
                                                 "MINT rings only for its own coin)"))
                if mint in held:
                    flags.append("you hold it")
                elif mint in watched:
                    flags.append("on your watchlist")
                alerts.append({"time": tx.get("blockTime") or s.get("blockTime"), "wallet": addr, "label": w.get("label"),
                               "role": w.get("role"), "action": act, "mint": mint, "symbol": nm.get(mint),
                               "amount": amt, "sol": round(paid, 6), "stable": stable,
                               "usd": round(abs(paid) * sol_px, 2) if sol_px and abs(paid) > 0.001 else None,
                               "signature": sig, "signed": signed, "flags": flags})
    state["seen"] = state["seen"][-5000:]
    clusters = find_clusters(alerts, state, window)
    alerts.sort(key=lambda r: (-(1 if any(f.startswith("DEV") for f in r["flags"]) else 0), -(r["time"] or 0)))
    return alerts, clusters


def find_clusters(alerts, state, window=1800):
    """Two or more of your wallets buying the same coin within `window` seconds (this check and the last ones)."""
    recent = [r for r in state.get("recent_buys", []) if r[0] and r[0] >= max(a["time"] or 0 for a in alerts) - 86400] \
        if alerts else list(state.get("recent_buys", []))
    for a in alerts:
        if a["action"] == "BUY" and a["time"]:
            recent.append([a["time"], a["wallet"], a["mint"], a.get("symbol"), a.get("label")])
    state["recent_buys"] = recent[-2000:]
    out = []
    by_mint = {}
    for r in recent:
        by_mint.setdefault(r[2], []).append(r)
    for mint, rows in by_mint.items():
        rows.sort(key=lambda r: r[0])
        for i in range(len(rows)):
            group = [r for r in rows if rows[i][0] <= r[0] <= rows[i][0] + window]
            wallets = sorted(set(r[1] for r in group))
            if len(wallets) >= 2:
                out.append({"mint": mint, "symbol": group[0][3], "wallets": wallets,
                            "labels": sorted(set(r[4] or r[1][:8] for r in group)), "first": group[0][0],
                            "last": group[-1][0]})
                break
    return out


def render(alerts, tz, n_wallets, clusters=()):
    out = []
    for c in clusters or []:
        out.append("CLUSTER: %d of your wallets bought %s within %d minutes (%s): %s" % (
            len(c["wallets"]), c.get("symbol") or c["mint"], max(1, int((c["last"] - c["first"]) / 60)),
            ", ".join(c["labels"]), c["mint"]))
    if not alerts:
        out.append("Nothing new from %d wallet%s." % (n_wallets, "" if n_wallets == 1 else "s"))
        return "\n".join(out)
    out.append("%d new from %d wallet%s, newest first (dev alerts on top):" % (len(alerts), n_wallets, "" if n_wallets == 1 else "s"))
    hush = [r for r in alerts if quiet(r)]
    for r in alerts:
        if quiet(r):
            continue
        amt = "{:,.2f}".format(abs(r["amount"]))
        coin = r["symbol"] or (r["mint"][:6] + "..")
        money = ""
        if r["action"] in ("BUY", "SELL") and abs(r["sol"]) > 0.001:
            money = " for %.4f SOL%s" % (abs(r["sol"]), (" (about $%s)" % "{:,.0f}".format(r["usd"])) if r.get("usd") else "")
        out.append("  %s  %-14s %-8s %s %s%s" % (local_str(r["time"], tz) if r["time"] else "?", (r["label"] or r["wallet"][:8])[:14],
                                                r["action"], amt, coin, money))
        out.append("      %s  tx %s..%s" % (r["mint"], r["signature"][:8], r["signature"][-6:]))
        for f in r["flags"]:
            out.append("      ! %s" % f)
        if r.get("signed") is False:
            out.append("      not signed by this wallet: a program or someone else moved it")
    if hush:
        coins = sorted(set(r["symbol"] or (r["mint"][:6] + "..") for r in hush))
        out.append("  + %d transfer%s of %s that the wallet did not sign itself (a program paid out or moved them: fee "
                   "payouts, airdrops, spam tokens): not trades, so not listed. --json shows them." % (
                       len(hush), "" if len(hush) == 1 else "s", ", ".join(coins)))
    out.append("Public on-chain data. A whale's trade is information, not a signal to copy: they can afford losses you cannot.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Whale and dev wallet tracker (meme-whales). Reads, never trades.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("wallet")
    p.add_argument("--label")
    p.add_argument("--role", choices=("dev", "whale", "smart", "other"), default="whale")
    p.add_argument("--token", help="for a dev wallet: its coin")
    p = sub.add_parser("dev")
    p.add_argument("token", help="the coin's contract address")
    p.add_argument("--offline-rugcheck")
    p = sub.add_parser("import")
    p.add_argument("file", help="one wallet a line, optionally followed by a comma and a label")
    p.add_argument("--role", choices=("dev", "whale", "smart", "other"), default="smart")
    p = sub.add_parser("remove")
    p.add_argument("wallet")
    sub.add_parser("list")
    p = sub.add_parser("check")
    p.add_argument("--limit", type=int, default=10, help="transactions to read per wallet (first check)")
    p.add_argument("--offline", help="a folder with sigs-<wallet>.json and tx-<signature>.json")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    base = mdir()
    cfg = load(os.path.join(base, "config.json"), {}) or {}
    tz = cfg.get("timezone") or "Europe/Berlin"
    wpath = os.path.join(base, "wallets.json")
    book = load(wpath, {"wallets": []}) or {"wallets": []}
    try:
        if a.cmd == "add":
            if not ADDRESS.match(a.wallet):
                raise WhaleError("'%s' is not a Solana address" % a.wallet)
            book["wallets"] = [w for w in book["wallets"] if w["address"] != a.wallet]
            book["wallets"].append({"address": a.wallet, "label": a.label, "role": a.role, "token": a.token,
                                    "added_at": int(time.time())})
            save(wpath, book)
            print("Watching %s (%s, %s)." % (a.wallet, a.label or "no label", a.role))
            return 0
        if a.cmd == "dev":
            rep = load(os.path.join(base, "analyst", "%s.json" % a.token)) or {}
            creator = (rep.get("metrics") or {}).get("creator")
            sym = rep.get("symbol")
            if not creator:
                rc = load(a.offline_rugcheck) if a.offline_rugcheck else None
                if rc is None:
                    req = urllib.request.Request(RUGCHECK % a.token, headers={"User-Agent": UA})
                    try:
                        with urllib.request.urlopen(req, timeout=30) as r:
                            rc = json.load(r)
                    except (urllib.error.URLError, OSError, ValueError) as e:
                        raise WhaleError("no analyst report and RugCheck did not answer (%s)" % e)
                creator = rc.get("creator")
                sym = sym or (rc.get("tokenMeta") or {}).get("symbol")
            if not creator:
                raise WhaleError("no creator wallet known for %s" % a.token)
            book["wallets"] = [w for w in book["wallets"] if w["address"] != creator]
            book["wallets"].append({"address": creator, "label": "%s dev" % (sym or a.token[:6]), "role": "dev",
                                    "token": a.token, "added_at": int(time.time())})
            save(wpath, book)
            print("Watching the creator of %s: %s. A sell or a transfer of %s from it rings first." % (
                sym or a.token, creator, sym or "the coin"))
            return 0
        if a.cmd == "import":
            added = 0
            with open(a.file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    addr, _, label = line.partition(",")
                    addr = addr.strip()
                    if not ADDRESS.match(addr):
                        print("skipped (not a Solana address): %s" % addr)
                        continue
                    book["wallets"] = [w for w in book["wallets"] if w["address"] != addr]
                    book["wallets"].append({"address": addr, "label": label.strip() or None, "role": a.role,
                                            "added_at": int(time.time())})
                    added += 1
            save(wpath, book)
            print("Imported %d wallets (%d watched in all)." % (added, len(book["wallets"])))
            return 0
        if a.cmd == "remove":
            n = len(book["wallets"])
            book["wallets"] = [w for w in book["wallets"] if w["address"] != a.wallet]
            save(wpath, book)
            print("Removed %d." % (n - len(book["wallets"])))
            return 0
        if a.cmd == "list":
            if not book["wallets"]:
                print("No wallets yet. whales.py dev MINT, or whales.py add WALLET --label NAME")
            for w in book["wallets"]:
                print("%-6s %-44s %s" % (w.get("role"), w["address"], w.get("label") or ""))
            return 0
        if not book["wallets"]:
            print("No wallets to check. whales.py dev MINT, or whales.py add WALLET --label NAME")
            return 1
        spath = os.path.join(base, "state", "whales.json")
        state = load(spath, {"last_sig": {}, "seen": []}) or {"last_sig": {}, "seen": []}
        chain = Chain(cfg.get("solana_rpc") or RPC, a.offline)
        alerts, clusters = check(chain, book["wallets"], state, a.limit, tz)
        if not a.no_write:
            save(spath, state)
        print(json.dumps({"alerts": alerts, "clusters": clusters}, indent=2) if a.json
              else render(alerts, tz, len(book["wallets"]), clusters))
        return 0
    except WhaleError as e:
        print("Whales: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
