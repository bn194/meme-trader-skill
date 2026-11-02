#!/usr/bin/env python3
"""The Token Analyst (meme-analyst). Standard library only.

Reads a meme coin's public record the way an earnings analyst reads a 10-Q:
the on-chain token report from RugCheck (Solana: mint and freeze authority,
Token-2022 traps, LP locked or burned, top holders, the creator's bag,
insider networks, RugCheck's own risk list) and the trading record from
DexScreener (pool liquidity, age, volume, buys and sells, market cap,
socials). It sums it up as PASS, CAUTION or AVOID with every reason, and
writes meme/safety.json, which meme-risk reads before any buy.

    python3 report.py GATO_MINT_ADDRESS                 # print the report
    python3 report.py GATO_MINT_ADDRESS --write         # + meme/analyst/<mint>.json, meme/safety.json
    python3 report.py --watchlist --write               # every hit in meme/watchlist.json
    python3 report.py MINT --json

A PASS means no red flag in the data, not that the coin is safe. Most meme
coins go to zero, rugs or not.
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
DEX = "https://api.dexscreener.com/tokens/v1/%s/%s"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/%s/report"
GOPLUS_SOL = "https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses=%s"
GOPLUS_EVM = "https://api.gopluslabs.io/api/v1/token_security/%s?contract_addresses=%s"
EVM_IDS = {"ethereum": 1, "bsc": 56, "base": 8453, "arbitrum": 42161, "polygon": 137, "avalanche": 43114}
ZERO = ("0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead")
# Uniswap v4 keeps every pool's tokens in one PoolManager contract per chain: a pool, not a whale
POOL_MANAGERS = ("0x000000000004444c5dc75cb358380d2e3de08a90", "0x498581ff718922c3f8e6a244956af099b2652b2b",
                 "0x28e2ea090877bf75740558f6bfb36a5ffee9e9df")
POOL_TYPES = ("AMM", "LOCKER", "POOL", "BURN")  # RugCheck knownAccounts types that are not people
DEFAULTS = {"min_liquidity_usd": 50000, "min_pool_age_hours": 6, "min_holders": 1000,
            "max_top10_pct": 30, "max_single_holder_pct": 10, "max_creator_pct": 5,
            "max_insider_pct": 15, "max_turnover": 50, "min_lp_locked_pct": 90,
            "timezone": "Europe/Berlin"}


class AnalystError(Exception):
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
    """Minutes east of UTC in zone tz at unix time ts (EU and US daylight saving built in)."""
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


def parse_now(text, tz):
    """--now "2026-11-01 19:40" in the user's time zone -> unix time."""
    if not text:
        return int(time.time())
    dt = datetime.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    guess = calendar.timegm(dt.timetuple())
    return guess - utc_offset(guess - utc_offset(guess, tz) * 60, tz) * 60


# ---------------------------------------------------------------- fetching

def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < tries - 1:
                time.sleep(5 * (i + 1))
                continue
            raise AnalystError("%s answered HTTP %d" % (url.split("/")[2], e.code))
        except (urllib.error.URLError, OSError, ValueError) as e:
            if i < tries - 1:
                time.sleep(2)
                continue
            raise AnalystError("could not read %s (%s)" % (url.split("/")[2], e))


def best_pair(pairs, address):
    mine = [p for p in pairs or [] if (p.get("baseToken") or {}).get("address") == address] or list(pairs or [])
    if not mine:
        return None
    return max(mine, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0, (p.get("volume") or {}).get("h24") or 0))


def resolve(token, chain):
    """An address, a DexScreener URL, or a symbol from meme/watchlist.json -> (chain, address)."""
    t = token.strip()
    m = re.search(r"dexscreener\.com/([a-z0-9]+)/([A-Za-z0-9]+)", t)
    if m:
        return m.group(1), m.group(2)
    if re.match(r"^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$", t):
        return chain, t
    wl = load(os.path.join(mdir(), "watchlist.json"), {}) or {}
    for h in wl.get("hits", []):
        if str(h.get("symbol", "")).upper() == t.lstrip("$").upper():
            return h.get("chain", chain), h["address"]
    raise AnalystError("'%s' is not an address; give the contract address (symbols are not unique for meme coins)" % token)


# ---------------------------------------------------------------- the analysis

def _num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def goplus_result(gp, address):
    """GoPlus answers {code, result: {address: {...}}}; pick ours (EVM addresses come back lowercased)."""
    res = (gp or {}).get("result") or {}
    for k, v in res.items():
        if k.lower() == address.lower():
            return v
    return None


def _on(v):
    """GoPlus flags are "1"/"0" strings, or {"status": "1"} objects."""
    if isinstance(v, dict):
        v = v.get("status")
    return str(v) == "1"


def goplus_flags(chain, g, c, flag, pools=()):
    """GoPlus as a second opinion (Solana) or the main contract check (Base, BSC, Ethereum...). -> metrics."""
    gm = {"goplus": True}
    if chain == "solana":
        checks = (("mintable", "mint", "GoPlus: the supply can still be minted"),
                  ("freezable", "freeze", "GoPlus: accounts can still be frozen"),
                  ("balance_mutable_authority", "balance", "GoPlus: an authority can change balances"),
                  ("closable", "closable", "GoPlus: the token can be closed"))
        for key, code, text in checks:
            if _on(g.get(key)):
                flag("avoid", "goplus_" + code, text)
        if str(g.get("non_transferable")) == "1":
            flag("avoid", "goplus_frozen", "GoPlus: the token cannot be transferred")
        if g.get("transfer_fee"):
            flag("avoid", "goplus_fee", "GoPlus: a transfer fee is set")
        if g.get("transfer_hook"):
            flag("caution", "goplus_hook", "GoPlus: a transfer hook runs on every transfer")
        gm["goplus_holders"] = int(g.get("holder_count") or 0) or None
        return gm
    tax_b = float(g.get("buy_tax") or 0) * 100
    tax_s = float(g.get("sell_tax") or 0) * 100
    gm.update(buy_tax_pct=round(tax_b, 2), sell_tax_pct=round(tax_s, 2), holders=int(g.get("holder_count") or 0) or None,
              owner=g.get("owner_address"), open_source=g.get("is_open_source") == "1")
    if _on(g.get("is_honeypot")) or _on(g.get("cannot_sell_all")) or _on(g.get("cannot_buy")):
        flag("avoid", "honeypot", "GoPlus: a honeypot, you cannot sell (or not all of it)")
    if tax_b > 10 or tax_s > 10:
        flag("avoid", "tax", "GoPlus: buy tax %.1f%%, sell tax %.1f%%" % (tax_b, tax_s))
    elif tax_b > 0 or tax_s > 0:
        flag("caution", "tax", "GoPlus: buy tax %.1f%%, sell tax %.1f%%: add it to your costs" % (tax_b, tax_s))
    if g.get("is_open_source") != "1":
        flag("avoid", "closed_source", "GoPlus: the contract code is not verified")
    for key, text in (("hidden_owner", "a hidden owner"), ("can_take_back_ownership", "ownership can be taken back"),
                      ("owner_change_balance", "the owner can change balances"),
                      ("transfer_pausable", "transfers can be paused"), ("is_blacklisted", "wallets can be blacklisted"),
                      ("slippage_modifiable", "the tax can be changed"), ("selfdestruct", "the contract can self-destruct")):
        if _on(g.get(key)):
            flag("avoid", key, "GoPlus: %s" % text)
    if _on(g.get("is_mintable")):
        flag("avoid", "mint", "GoPlus: new tokens can be minted")
    owner = (g.get("owner_address") or "").lower()
    if owner and owner not in ZERO:
        flag("caution", "owner", "GoPlus: the owner (%s) has not renounced the contract" % owner)
    lps = g.get("lp_holders") or []
    if lps:
        locked = 0.0
        for h in lps:
            pct = float(h.get("percent") or 0) * 100
            if _on(h.get("is_locked")) or (h.get("address") or "").lower() in ZERO or "dead" in (h.get("tag") or "").lower() \
                    or "null" in (h.get("tag") or "").lower():
                locked += pct
        gm["lp_locked_pct"] = round(locked, 1)
        if locked < float(c["min_lp_locked_pct"]):
            flag("avoid", "lp_unlocked", "GoPlus: only %.0f%% of the LP is locked or burned: the liquidity can be pulled" % locked)
    skip = set(a.lower() for a in pools) | set(POOL_MANAGERS) | set(ZERO)
    holders = [h for h in (g.get("holders") or []) if (h.get("address") or "").lower() not in skip and not _on(h.get("is_locked"))]
    top10 = sum(float(h.get("percent") or 0) * 100 for h in holders[:10])
    gm["top10_pct"] = round(top10, 2)
    if top10 > float(c["max_top10_pct"]):
        flag("avoid", "top10", "GoPlus: the top 10 wallets hold %.1f%%" % top10)
    creator = float(g.get("creator_percent") or 0) * 100
    gm["creator_pct"] = round(creator, 2)
    if creator > float(c["max_creator_pct"]):
        flag("avoid", "creator", "GoPlus: the creator still holds %.1f%%" % creator)
    if gm.get("holders") is not None and gm["holders"] < int(c["min_holders"]):
        flag("caution", "holders", "%s holders, under your %s minimum" % (gm["holders"], c["min_holders"]))
    return gm


def holder_trend(history, now, holders):
    """history: [[ts, holders], ...] from earlier checks -> (change, hours since) against the oldest in the last day."""
    old = [h for h in (history or []) if now - 86400 <= h[0] < now - 60 and h[1]]
    if not old or not holders:
        return None
    ts, n = old[0]
    return {"since": ts, "before": n, "change": holders - n, "pct": (holders / float(n) - 1) * 100,
            "hours": (now - ts) / 3600.0}


def analyze(chain, address, pairs, rc, cfg, now, gp=None, holder_history=None):
    """Pure function: the DexScreener pairs and the RugCheck report -> the report dict."""
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    pair = best_pair(pairs, address)
    flags = []

    def flag(level, code, text):
        flags.append({"level": level, "code": code, "text": text})

    m = {"liquidity_usd": None, "pair": None, "dex": None, "pool_created_at": None, "pool_age_hours": None,
         "price_usd": None, "market_cap": None, "fdv": None, "volume_h24": None, "turnover": None,
         "buys_h1": None, "sells_h1": None, "price_change": {}, "socials": 0, "websites": 0, "boosts": 0}
    symbol = name = None
    if pair:
        symbol = pair["baseToken"].get("symbol")
        name = pair["baseToken"].get("name")
        liq = _num((pair.get("liquidity") or {}).get("usd"))
        vol = _num((pair.get("volume") or {}).get("h24"), 0.0)
        created = pair.get("pairCreatedAt")
        m.update({"liquidity_usd": liq, "pair": pair.get("pairAddress"), "dex": pair.get("dexId"),
                  "pool_created_at": int(created // 1000) if created else None,
                  "price_usd": _num(pair.get("priceUsd")), "market_cap": _num(pair.get("marketCap")),
                  "fdv": _num(pair.get("fdv")), "volume_h24": vol,
                  "turnover": round(vol / liq, 1) if liq else None,
                  "buys_h1": ((pair.get("txns") or {}).get("h1") or {}).get("buys"),
                  "sells_h1": ((pair.get("txns") or {}).get("h1") or {}).get("sells"),
                  "price_change": pair.get("priceChange") or {},
                  "socials": len((pair.get("info") or {}).get("socials") or []),
                  "websites": len((pair.get("info") or {}).get("websites") or []),
                  "boosts": (pair.get("boosts") or {}).get("active") or 0})
        if created:
            m["pool_age_hours"] = round((now - created / 1000.0) / 3600.0, 1)
    else:
        flag("avoid", "no_pool", "DexScreener lists no trading pool for this token")

    # liquidity and the pool
    if m["dex"] in ("pumpfun", "moonshot", "launchlab", "bonk") and not m["liquidity_usd"]:
        flag("caution", "curve", "still on the launchpad's bonding curve (%s): no pool yet, the price moves fast "
             "and graduation can gap it either way" % m["dex"])
    elif pair is not None:
        if (m["liquidity_usd"] or 0) < c["min_liquidity_usd"]:
            flag("avoid", "liquidity", "pool liquidity $%s, under your $%s minimum: a small sell moves the price "
                 "a lot and you may not get out" % (_k(m["liquidity_usd"]), _k(c["min_liquidity_usd"])))
    if m["pool_age_hours"] is not None and m["pool_age_hours"] < c["min_pool_age_hours"]:
        flag("caution", "young", "the pool is %.1f hours old (your minimum %s): most rugs happen in the first hours"
             % (m["pool_age_hours"], c["min_pool_age_hours"]))
    if m["turnover"] is not None and m["turnover"] > c["max_turnover"]:
        flag("caution", "wash", "24h volume is %.0fx the pool's liquidity: likely bots trading with themselves "
             "(wash trading), so the volume says little" % m["turnover"])
    if m["buys_h1"] is not None and m["sells_h1"] and m["sells_h1"] >= 2 * max(1, m["buys_h1"]):
        flag("caution", "selling", "%d sells vs %d buys in the last hour" % (m["sells_h1"], m["buys_h1"]))
    if pair is not None and not m["socials"] and not m["websites"]:
        flag("caution", "no_socials", "no website and no socials listed on DexScreener")
    if m["boosts"]:
        flag("info", "boosted", "paid DexScreener boosts active (%s): promotion, not demand" % m["boosts"])

    # the on-chain report (Solana, RugCheck)
    rcm = {}
    if rc:
        token = rc.get("token") or {}
        supply = _num(token.get("supply"), 0.0)
        ext = rc.get("token_extensions") or {}
        meta = rc.get("tokenMeta") or {}
        known = rc.get("knownAccounts") or {}
        markets = rc.get("markets") or []
        holders = rc.get("topHolders") or []
        pool_owners = {mk.get("pubkey") for mk in markets}
        people = [h for h in holders
                  if (known.get(h.get("owner")) or {}).get("type") not in POOL_TYPES
                  and h.get("owner") not in pool_owners and h.get("address") not in pool_owners]
        top10 = sum(_num(h.get("pct"), 0.0) for h in people[:10])
        largest = max([_num(h.get("pct"), 0.0) for h in people] or [0.0])
        creator = rc.get("creator")
        creator_pct = (_num(rc.get("creatorBalance"), 0.0) / supply * 100.0) if supply else 0.0
        for h in holders:
            if h.get("owner") == creator or (known.get(h.get("owner")) or {}).get("type") == "CREATOR":
                creator_pct = max(creator_pct, _num(h.get("pct"), 0.0))
        insider_pct = 0.0
        for net in rc.get("insiderNetworks") or []:
            insider_pct += (_num(net.get("currentHolding"), 0.0) / supply * 100.0) if supply else 0.0
        main = None
        for mk in markets:
            if m["pair"] and mk.get("pubkey") == m["pair"]:
                main = mk
        if main is None and markets:
            main = max(markets, key=lambda mk: _num((mk.get("lp") or {}).get("quoteUSD"), 0.0))
        lp_locked = _num(((main or {}).get("lp") or {}).get("lpLockedPct"))
        transfer_fee = _num((rc.get("transferFee") or {}).get("pct"), 0.0)
        rcm = {"mint_authority": token.get("mintAuthority", rc.get("mintAuthority")),
               "freeze_authority": token.get("freezeAuthority", rc.get("freezeAuthority")),
               "metadata_mutable": bool(meta.get("mutable")), "transfer_fee_pct": transfer_fee,
               "permanent_delegate": ext.get("permanentDelegate"), "non_transferable": bool(ext.get("nonTransferable")),
               "default_frozen": str(ext.get("defaultAccountState") or "").lower() == "frozen",
               "transfer_hook": ext.get("transferHook"),
               "holders": rc.get("totalHolders"), "top10_pct": round(top10, 2), "largest_holder_pct": round(largest, 2),
               "creator": creator, "creator_pct": round(creator_pct, 2), "insider_pct": round(insider_pct, 2),
               "insider_networks": len(rc.get("insiderNetworks") or []),
               "insiders_detected": rc.get("graphInsidersDetected"),
               "main_market": (main or {}).get("marketType"), "lp_locked_pct": lp_locked,
               "total_market_liquidity": _num(rc.get("totalMarketLiquidity")),
               "rugcheck_score": rc.get("score_normalised"), "rugged": bool(rc.get("rugged")),
               "launchpad": (rc.get("launchpad") or {}).get("name"),
               "risks": [{"name": r.get("name"), "level": r.get("level"), "value": r.get("value")}
                         for r in rc.get("risks") or []]}
        symbol = symbol or meta.get("symbol")
        name = name or meta.get("name")
        if rcm["rugged"]:
            flag("avoid", "rugged", "RugCheck marks this token as rugged")
        if rcm["mint_authority"]:
            flag("avoid", "mint", "mint authority is still active: the dev can print new tokens and dump them")
        if rcm["freeze_authority"]:
            flag("avoid", "freeze", "freeze authority is still active: your tokens can be frozen so you cannot sell "
                 "(a honeypot)")
        if transfer_fee > 0:
            flag("avoid", "transfer_fee", "a %.2f%% transfer fee on every move (Token-2022)" % transfer_fee)
        if rcm["permanent_delegate"]:
            flag("avoid", "delegate", "a permanent delegate can move tokens out of any wallet (Token-2022)")
        if rcm["non_transferable"] or rcm["default_frozen"]:
            flag("avoid", "frozen", "new token accounts start frozen or the token cannot be transferred")
        if rcm["transfer_hook"]:
            flag("caution", "hook", "a transfer hook runs code on every transfer (Token-2022)")
        if main is not None and main.get("marketType") == "pump_fun":
            pass  # still on the bonding curve: no LP yet, flagged above as a curve
        elif main is not None and lp_locked is not None and lp_locked < c["min_lp_locked_pct"]:
            if "dlmm" in (main.get("marketType") or "").lower() or "clmm" in (main.get("marketType") or "").lower():
                flag("caution", "lp_positions", "the main pool (%s) holds liquidity in positions its owners can "
                     "withdraw at any time; there is no LP token to burn or lock" % main.get("marketType"))
            else:
                flag("avoid", "lp_unlocked", "only %.0f%% of the main pool's LP is locked or burned: the owner can "
                     "pull the liquidity (a rug pull)" % lp_locked)
        if top10 > c["max_top10_pct"]:
            flag("avoid", "top10", "the top 10 wallets (pools left out) hold %.1f%%, over your %s%%: a few people "
                 "can dump on you" % (top10, c["max_top10_pct"]))
        if largest > c["max_single_holder_pct"]:
            flag("avoid", "whale", "one wallet holds %.1f%% of the supply (your limit %s%%)" % (largest, c["max_single_holder_pct"]))
        if creator_pct > c["max_creator_pct"]:
            flag("avoid", "creator", "the creator still holds %.1f%% (your limit %s%%)" % (creator_pct, c["max_creator_pct"]))
        elif creator_pct > 0:
            flag("info", "creator_bag", "the creator holds %.2f%%: watch that wallet (/meme-whales dev)" % creator_pct)
        if insider_pct > c["max_insider_pct"]:
            flag("avoid", "insiders", "linked insider wallets hold %.1f%% (your limit %s%%)" % (insider_pct, c["max_insider_pct"]))
        elif insider_pct > 5:
            flag("caution", "insiders", "linked insider wallets hold %.1f%%" % insider_pct)
        if rcm["metadata_mutable"]:
            flag("caution", "mutable", "the name, ticker and image can still be changed")
        if rcm["holders"] is not None and rcm["holders"] < c["min_holders"]:
            flag("caution", "holders", "%s holders, under your %s minimum" % (rcm["holders"], c["min_holders"]))
        seen = {f["text"] for f in flags}
        for r in rc.get("risks") or []:
            lvl = "avoid" if r.get("level") == "danger" else "caution"
            text = "RugCheck: %s%s" % (r.get("name"), (" (%s)" % r["value"]) if r.get("value") else "")
            if text not in seen:
                flag(lvl, "rugcheck", text)
    g = goplus_result(gp, address) if gp else None
    gm = {}
    if g:
        gm = goplus_flags(chain, g, c, flag, [p.get("pairAddress") or "" for p in pairs or []])
    if not rc and chain == "solana" and not g:
        flag("avoid", "no_report", "no RugCheck or GoPlus report: mint, freeze and holder checks could not run")
    elif not rc and chain == "solana":
        flag("caution", "no_rugcheck", "no RugCheck report: LP lock, insiders and the creator's bag were not checked")
    elif not rc and not g:
        flag("caution", "unverified", "no contract report for %s: mint, tax, holder and LP checks did not run, so "
             "check the contract yourself" % chain)
    holders_now = (rcm.get("holders") if rcm else None) or gm.get("holders")
    trend = holder_trend(holder_history, now, holders_now)
    if trend:
        m["holder_trend"] = trend
        if trend["pct"] <= -3:
            flag("caution", "holders_falling", "holders fell %.1f%% (%+d) in the last %.1f hours: people are leaving" % (
                trend["pct"], trend["change"], trend["hours"]))

    n_avoid = sum(1 for f in flags if f["level"] == "avoid")
    n_caution = sum(1 for f in flags if f["level"] == "caution")
    if n_avoid:
        verdict = "AVOID"
    elif not rc and not g:
        verdict = "UNVERIFIED"
    elif n_caution:
        verdict = "CAUTION"
    else:
        verdict = "PASS"
    for k, v in gm.items():
        if k not in rcm or rcm.get(k) is None:
            m[k] = v
    m.update(rcm)
    return {"as_of": now, "chain": chain, "address": address, "symbol": symbol, "name": name,
            "metrics": m, "flags": flags, "verdict": verdict, "avoid": n_avoid, "caution": n_caution,
            "sources": ["DexScreener"] + (["RugCheck"] if rc else []) + (["GoPlus"] if g else [])}


# ---------------------------------------------------------------- output

def _k(v):
    if v is None:
        return "n/a"
    v = float(v)
    if v >= 1e9:
        return "%.2fB" % (v / 1e9)
    if v >= 1e6:
        return "%.2fM" % (v / 1e6)
    if v >= 1e3:
        return "%.1fk" % (v / 1e3)
    return "%.0f" % v


def _pct(v):
    return "n/a" if v is None else "%+.1f%%" % float(v)


def render(rep, tz):
    m = rep["metrics"]
    out = ["%s (%s) on %s, %s" % (rep.get("symbol") or "?", rep.get("name") or "?", rep["chain"], rep["address"]),
           "  checked %s (%s)" % (local_str(rep["as_of"], tz), tz)]
    if "mint_authority" in m:
        out.append("Security")
        out.append("  mint authority   %s" % ("revoked" if not m["mint_authority"] else "ACTIVE: %s" % m["mint_authority"]))
        out.append("  freeze authority %s" % ("revoked" if not m["freeze_authority"] else "ACTIVE: %s" % m["freeze_authority"]))
        out.append("  metadata         %s" % ("mutable" if m["metadata_mutable"] else "immutable"))
        out.append("  transfer fee     %.2f%%" % (m["transfer_fee_pct"] or 0))
    out.append("Liquidity")
    out.append("  main pool        %s on %s, $%s liquidity" % (m.get("pair") or "none", m.get("dex") or "?", _k(m.get("liquidity_usd"))))
    if m.get("lp_locked_pct") is not None:
        out.append("  LP locked/burned %.0f%% (%s)" % (m["lp_locked_pct"], m.get("main_market") or "GoPlus"))
    if m.get("pool_age_hours") is not None:
        age = m["pool_age_hours"]
        out.append("  pool age         %s" % ("%.1f hours" % age if age < 48 else "%.0f days" % (age / 24)))
    if m.get("buy_tax_pct") is not None:
        out.append("Contract (GoPlus)")
        out.append("  tax              buy %.1f%%, sell %.1f%%; code %s; owner %s" % (
            m["buy_tax_pct"], m["sell_tax_pct"], "verified" if m.get("open_source") else "NOT verified",
            "renounced" if (m.get("owner") or "").lower() in ZERO or not m.get("owner") else m["owner"]))
    if "holders" in m:
        out.append("Holders")
        tr = m.get("holder_trend")
        out.append("  holders          %s%s" % ("{:,}".format(m["holders"]) if m["holders"] is not None else "n/a",
                                             ("   %+d (%+.1f%%) since %s" % (tr["change"], tr["pct"], local_str(tr["since"], tz, "%H:%M")))
                                             if tr else ""))
        if "largest_holder_pct" in m:
            out.append("  top 10           %.1f%% (pools left out), largest %.1f%%" % (m["top10_pct"], m["largest_holder_pct"]))
            out.append("  creator          %.2f%%   insiders %.2f%% in %d networks" % (m["creator_pct"], m["insider_pct"], m["insider_networks"]))
        elif m.get("top10_pct") is not None:
            out.append("  top 10           %.1f%%, creator %.2f%%" % (m["top10_pct"], m.get("creator_pct") or 0))
    out.append("Trading")
    pc = m.get("price_change") or {}
    out.append("  market cap       $%s   24h volume $%s (%sx liquidity)" % (_k(m.get("market_cap")), _k(m.get("volume_h24")),
                                                                         m.get("turnover") if m.get("turnover") is not None else "n/a"))
    out.append("  last hour        %s buys, %s sells; change m5 %s, h1 %s, h24 %s" % (
        m.get("buys_h1"), m.get("sells_h1"), _pct(pc.get("m5")), _pct(pc.get("h1")), _pct(pc.get("h24"))))
    if m.get("rugcheck_score") is not None:
        out.append("  RugCheck score   %s (lower is better)" % m["rugcheck_score"])
    out.append("")
    for f in rep["flags"]:
        out.append("  %-7s %s" % (f["level"].upper(), f["text"]))
    if not rep["flags"]:
        out.append("  no red flags in the data")
    out.append("")
    out.append("Verdict: %s (%d avoid, %d caution)" % (rep["verdict"], rep["avoid"], rep["caution"]))
    if rep["verdict"] == "PASS":
        out.append("No red flag in the data. That is a check, not a promise: most meme coins still go to zero.")
    elif rep["verdict"] == "AVOID":
        out.append("meme-risk blocks any buy of this token while this verdict stands.")
    return "\n".join(out)


def write(rep):
    base = mdir()
    save(os.path.join(base, "analyst", "%s.json" % rep["address"]), rep)
    hp = os.path.join(base, "state", "holders.json")
    hist = load(hp, {}) or {}
    n = rep["metrics"].get("holders")
    if n:
        rows = [r for r in hist.get(rep["address"], []) if rep["as_of"] - r[0] <= 7 * 86400] + [[rep["as_of"], n]]
        hist[rep["address"]] = rows[-200:]
        save(hp, hist)
    path = os.path.join(base, "safety.json")
    idx = load(path, {}) or {}
    m = rep["metrics"]
    idx[rep["address"]] = {"symbol": rep.get("symbol"), "chain": rep["chain"], "verdict": rep["verdict"],
                           "checked_at": rep["as_of"], "avoid": rep["avoid"], "caution": rep["caution"],
                           "liquidity_usd": m.get("liquidity_usd"), "pair": m.get("pair"),
                           "pool_created_at": m.get("pool_created_at"),
                           "reasons": [f["text"] for f in rep["flags"] if f["level"] in ("avoid", "caution")]}
    save(path, idx)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Token report and rug check (meme-analyst). Never trades.")
    ap.add_argument("token", nargs="?", help="contract address (mint), a DexScreener URL, or a symbol in the watchlist")
    ap.add_argument("--chain", default="solana")
    ap.add_argument("--watchlist", action="store_true", help="analyze every hit in meme/watchlist.json")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" in your time zone')
    ap.add_argument("--offline-dex", help="a saved DexScreener tokens/v1 JSON")
    ap.add_argument("--offline-rugcheck", help="a saved RugCheck report JSON")
    ap.add_argument("--offline-goplus", help="a saved GoPlus token_security JSON")
    ap.add_argument("--no-goplus", action="store_true", help="skip GoPlus")
    a = ap.parse_args(argv)
    cfg = load(os.path.join(mdir(), "config.json"), {}) or {}
    tz = cfg.get("timezone") or DEFAULTS["timezone"]
    try:
        now = parse_now(a.now, tz)
        if a.watchlist:
            wl = load(os.path.join(mdir(), "watchlist.json"), {}) or {}
            targets = [(h.get("chain", a.chain), h["address"]) for h in wl.get("hits", [])]
            if not targets:
                raise AnalystError("meme/watchlist.json has no hits; run /meme-scanner first")
        elif a.token:
            targets = [resolve(a.token, a.chain)]
        else:
            raise AnalystError("give a contract address, or --watchlist")
        reports = []
        for i, (chain, address) in enumerate(targets):
            if i:
                time.sleep(1.0)
            pairs = load(a.offline_dex) if a.offline_dex else get_json(DEX % (chain, address))
            rc = None
            if a.offline_rugcheck:
                rc = load(a.offline_rugcheck)
            elif chain == "solana":
                try:
                    rc = get_json(RUGCHECK % address)
                except AnalystError as e:
                    print("RugCheck: %s" % e, file=sys.stderr)
            gp = None
            if a.offline_goplus:
                gp = load(a.offline_goplus)
            elif not a.no_goplus and (chain == "solana" or chain in EVM_IDS):
                try:
                    gp = get_json(GOPLUS_SOL % address if chain == "solana" else GOPLUS_EVM % (EVM_IDS[chain], address))
                except AnalystError as e:
                    print("GoPlus: %s" % e, file=sys.stderr)
            hh = (load(os.path.join(mdir(), "state", "holders.json"), {}) or {}).get(address)
            rep = analyze(chain, address, pairs if isinstance(pairs, list) else (pairs or {}).get("pairs"), rc, cfg, now,
                          gp, hh)
            reports.append(rep)
            if a.write:
                write(rep)
    except AnalystError as e:
        print("Cannot analyze: %s" % e)
        return 1
    if a.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    elif len(reports) == 1:
        print(render(reports[0], tz))
    else:
        for r in reports:
            print("%-8s %-12s %s  %s" % (r["verdict"], r.get("symbol"), r["address"],
                                          "; ".join(f["text"] for f in r["flags"] if f["level"] == "avoid")[:110]))
    if a.write:
        print("\nWrote meme/safety.json (%d token%s)." % (len(reports), "" if len(reports) == 1 else "s"))
    return 0 if all(r["verdict"] != "AVOID" for r in reports) else 2


if __name__ == "__main__":
    sys.exit(main())
