#!/usr/bin/env python3
"""The Launch Radar (meme-radar). Standard library only.

Listens to every new pump.fun coin the second it is created, and to every
coin that graduates from the bonding curve to a real pool, through
PumpPortal's free data stream (a websocket, no key), and gives every coin a
verdict within seconds: BUY or SKIP, with the reasons.

  at birth   no network: how much the dev bought, a serial launcher in this
             session, a copycat or a copy race of the same ticker, junk names
  ~10 s      Jupiter's token data (one request for many coins): mint and
             freeze authority, Mayhem mode, how many coins the dev launched
             before, the dev's bag, snipers, insiders, bundlers, a launch
             that graduated at once
  ~30 s      the same again, plus the first minute of trading: traders,
             holders, money bought, buys against sells, the move, the top 10

A BUY is a paper trade until the paper test passes: the radar follows the
coin as if you had bought it 45 s after the signal (the time it takes on a
phone), sells it at the stop, the target or the time stop 45 s after each
trigger, and counts the result after your app's fee, pump.fun's 1.25 % and
slippage. After 50 signals the test says PASSED or FAILED.

    python3 radar.py                       # listen for 10 minutes
    python3 radar.py --minutes 60 --quiet  # only BUY lines, graduations and the results
    python3 radar.py --forever
    python3 radar.py --graduations-only
    python3 radar.py test                  # the paper test so far
    python3 radar.py show                  # the last coins it saw

About 1 % of pump.fun coins ever graduate, the fastest buyers are bots in
the same block, and most coins are dead within the hour. A BUY is a coin
that passed these rules, not a promise.
"""

import argparse
import base64
import calendar
import datetime
import gzip
import json
import math
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "meme-trader-skill/1.0 (+https://github.com/bn194/meme-trader-skill)"
WS_HOST, WS_PATH = "pumpportal.fun", "/api/data"
JUP_ASSETS = "https://datapi.jup.ag/v1/assets/search?query=%s"
JUP_PRICE = "https://lite-api.jup.ag/price/v3?ids=%s"
SOL = "So11111111111111111111111111111111111111112"
EURC = "HzwqbKZw8HxMN6bF2yFZNrht3c2iXXzpKcFu7uBEDKtr"
PUMP_SUPPLY = 1000000000.0
JUNK = re.compile(r"(?i)\b(test|rug|scam|honeypot|airdrop|claim|free)\b")
DEFAULTS = {"timezone": "Europe/Berlin", "radar_max_dev_buy_pct": 10,
            "fresh_first_look_seconds": 10, "fresh_decide_seconds": 30,
            "fresh_max_dev_mints": 5, "fresh_max_dev_pct": 10, "fresh_max_sniper_pct": 15,
            "fresh_max_insider_pct": 15, "fresh_max_bundler_pct": 10, "fresh_max_top10_pct": 40,
            "fresh_min_traders": 15, "fresh_min_holders": 15, "fresh_min_buy_volume_usd": 1000,
            "fresh_max_order_eur": 5, "fresh_stop_pct": 25, "fresh_target_pct": 50, "fresh_hold_minutes": 10,
            "fresh_fill_delay_seconds": 45, "fresh_poll_seconds": 10, "fresh_curve_fee_pct": 1.25,
            "fresh_test_signals": 50, "testphase_min_profit_factor": 1.2, "eur_usd_fallback": 1.11,
            "venue": "phantom", "venues": {}, "fee_pct": 0.85, "fee_min_usd": 0, "slippage_pct": 0.3}
LOOK_RETRY_SECONDS = 8  # Jupiter can lag a few seconds behind a brand-new coin


class RadarError(Exception):
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
    opener = gzip.open if path.endswith(".gz") else open
    with opener(tmp, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)
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


def local_str(ts, tz, fmt="%H:%M:%S"):
    return time.strftime(fmt, time.gmtime(int(ts) + utc_offset(int(ts), tz) * 60))


def price_str(p):
    """A price with four significant digits and no exponent: 0.000002684, 0.003042."""
    if not p:
        return "n/a"
    p = float(p)
    if p >= 1:
        return "$%.2f" % p
    return "$%.*f" % (3 - int(math.floor(math.log10(p))), p)


def money(v):
    if v is None:
        return "n/a"
    v = float(v)
    for div, suf in ((1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            return "$%.1f%s" % (v / div, suf)
    return "$%.0f" % v


# ---------------------------------------------------------------- the stream (a small websocket client)

class Stream:
    """PumpPortal's websocket: direct, or through HTTPS_PROXY with CONNECT. Answers pings, reconnects."""

    def __init__(self, host=WS_HOST, path=WS_PATH, subscribe=()):
        self.host, self.path, self.subscribe = host, path, list(subscribe)
        self.sock, self.buf = None, b""

    def connect(self):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            u = urllib.parse.urlparse(proxy)
            raw = socket.create_connection((u.hostname, u.port or 443), timeout=30)
            req = "CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n" % (self.host, self.host)
            if u.username:
                cred = "%s:%s" % (urllib.parse.unquote(u.username), urllib.parse.unquote(u.password or ""))
                req += "Proxy-Authorization: Basic %s\r\n" % base64.b64encode(cred.encode()).decode()
            raw.sendall((req + "\r\n").encode())
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = raw.recv(4096)
                if not chunk:
                    raise RadarError("the proxy closed the connection")
                head += chunk
            if b" 200" not in head.split(b"\r\n", 1)[0]:
                raise RadarError("the proxy refused the tunnel: %s" % head.split(b"\r\n", 1)[0].decode("latin-1"))
        else:
            raw = socket.create_connection((self.host, 443), timeout=30)
        ctx = ssl.create_default_context()
        cafile = os.environ.get("SSL_CERT_FILE")
        if cafile and os.path.exists(cafile):
            ctx.load_verify_locations(cafile)
        self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nUser-Agent: %s\r\n\r\n"
                           % (self.path, self.host, key, UA)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RadarError("the stream closed during the handshake")
            head += chunk
        if b" 101" not in head.split(b"\r\n", 1)[0]:
            raise RadarError("no websocket: %s" % head.split(b"\r\n", 1)[0].decode("latin-1"))
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.sock.settimeout(30)
        for sub in self.subscribe:
            self.send_json(sub)

    def _send(self, opcode, data):
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            hdr = bytes([0x80 | opcode, 0x80 | n])
        elif n < 65536:
            hdr = bytes([0x80 | opcode, 0x80 | 126]) + n.to_bytes(2, "big")
        else:
            hdr = bytes([0x80 | opcode, 0x80 | 127]) + n.to_bytes(8, "big")
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def send_json(self, obj):
        self._send(0x1, json.dumps(obj).encode("utf-8"))

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RadarError("the stream closed")
            self.buf += chunk

    def messages(self, tick=1.0):
        """Yield every text message as a dict, and None about every `tick` seconds while the stream is quiet,
        so the caller can do its timed work. Answers pings, pings a quiet server, reconnects on a drop."""
        backoff = 2
        while True:
            try:
                if self.sock is None:
                    self.connect()
                    self.sock.settimeout(tick)
                    backoff = 2
                parts, pinged = b"", time.time()
                while True:
                    try:
                        self._need(2)
                        b1, b2 = self.buf[0], self.buf[1]
                        n, off = b2 & 0x7f, 2
                        if n == 126:
                            self._need(4)
                            n, off = int.from_bytes(self.buf[2:4], "big"), 4
                        elif n == 127:
                            self._need(10)
                            n, off = int.from_bytes(self.buf[2:10], "big"), 10
                        if b2 & 0x80:
                            off += 4  # servers do not mask, but be safe
                        self._need(off + n)
                    except socket.timeout:
                        if time.time() - pinged > 20:
                            self._send(0x9, b"radar")
                            pinged = time.time()
                        yield None
                        continue
                    payload, self.buf = self.buf[off:off + n], self.buf[off + n:]
                    op = b1 & 0x0f
                    if op == 0x9:
                        self._send(0xA, payload)
                    elif op == 0x8:
                        raise RadarError("the server closed the stream")
                    elif op in (0x1, 0x0):
                        parts += payload
                        if b1 & 0x80:
                            try:
                                yield json.loads(parts.decode("utf-8"))
                            except ValueError:
                                pass
                            parts = b""
            except (RadarError, OSError, ssl.SSLError) as e:
                try:
                    if self.sock:
                        self.sock.close()
                except OSError:
                    pass
                self.sock = None
                sys.stderr.write("stream: %s; reconnecting in %d s\n" % (e, backoff))
                time.sleep(backoff)
                backoff = min(60, backoff * 2)


# ---------------------------------------------------------------- Jupiter's token data, live or replayed

def http_json(url, timeout=8):
    """GET a JSON document; one retry after a rate limit. -> data or None."""
    for i in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and i == 0:
                time.sleep(1.5)
                continue
            return None
        except (urllib.error.URLError, OSError, ValueError):
            return None
    return None


def slim(a):
    """What a price poll keeps of a token record."""
    s5 = a.get("stats5m") or {}
    return {"id": a.get("id"), "usdPrice": a.get("usdPrice"), "liquidity": a.get("liquidity"),
            "holderCount": a.get("holderCount"), "mcap": a.get("mcap"), "bondingCurve": a.get("bondingCurve"),
            "graduatedPool": a.get("graduatedPool"),
            "stats5m": {k: s5.get(k) for k in ("numBuys", "numSells", "numTraders", "priceChange")}}


class Jup(object):
    """Jupiter's token records (datapi), up to 50 coins a request. Live, recording, or replaying a recording."""

    def __init__(self, recording=None, record=False):
        self.rec = None
        if recording is not None:
            self.rec = {m: sorted(v, key=lambda x: x[0]) for m, v in recording.items()}
        self.saved = {} if record else None
        self.requests = 0

    def assets(self, mints, now, full=True):
        """-> {mint: record}. full=False is a price poll (a replay may answer it from a slim record)."""
        mints = [m for m in dict.fromkeys(mints) if m]
        out = {}
        if self.rec is not None:
            for m in mints:
                best = None
                for t, a in self.rec.get(m, []):
                    if t > now + 1.5:
                        break
                    if full and "audit" not in a:
                        continue
                    best = (t, a)
                if best is not None and (full or best[0] >= now - 60):  # a price poll wants a fresh price
                    out[m] = best[1]
            return out
        for i in range(0, len(mints), 50):
            chunk = mints[i:i + 50]
            self.requests += 1
            data = http_json(JUP_ASSETS % ",".join(chunk))
            t = round(time.time(), 2)
            for a in data if isinstance(data, list) else []:
                m = a.get("id")
                if m in chunk:
                    out[m] = a
                    if self.saved is not None:
                        self.saved.setdefault(m, []).append([t, a if full else slim(a)])
        return out


def live_rates(cfg):
    """SOL in USD and USD per EUR from Jupiter's price API. -> (sol_usd or None, eur_usd)."""
    d = http_json(JUP_PRICE % ",".join((SOL, EURC))) or {}
    sol = (d.get(SOL) or {}).get("usdPrice")
    eur = (d.get(EURC) or {}).get("usdPrice")
    eur = float(eur) if eur and 0.8 < float(eur) < 1.6 else float(cfg["eur_usd_fallback"])
    return (float(sol) if sol else None), eur


# ---------------------------------------------------------------- the checks

def instant(ev, creators, hot_symbols, cfg, session_symbols=None):
    """No network: what the creation event alone says. -> (flags, facts)."""
    flags, facts = [], {}
    dev_pct = float(ev.get("initialBuy") or 0) / PUMP_SUPPLY * 100.0
    facts["dev_buy_pct"] = round(dev_pct, 2)
    facts["dev_sol"] = round(float(ev.get("solAmount") or 0), 3)
    facts["mcap_sol"] = round(float(ev.get("marketCapSol") or 0), 1)
    if dev_pct > float(cfg["radar_max_dev_buy_pct"]):
        flags.append("dev bought %.1f%% of the supply at launch (limit %g%%)" % (dev_pct, float(cfg["radar_max_dev_buy_pct"])))
    n = creators.get(ev.get("traderPublicKey"), 0)
    if n >= 3:
        flags.append("serial launcher: this wallet created %d coins since the radar started" % n)
    name = "%s %s" % (ev.get("name") or "", ev.get("symbol") or "")
    if JUNK.search(name):
        flags.append("junk name: %s" % name.strip())
    if not re.search(r"[A-Za-z0-9]", ev.get("symbol") or ""):
        flags.append("no readable ticker")
    sym = (ev.get("symbol") or "").upper().lstrip("$")
    if sym and sym in hot_symbols:
        flags.append("copycat: %s is already a trending coin's ticker" % sym)
    if sym and session_symbols is not None:
        n_before = session_symbols.get(sym, 0)
        if n_before:
            flags.append("copy race: %s was already launched %d time%s since the radar started" % (
                sym, n_before, "" if n_before == 1 else "s"))
    return flags, facts


def plural(n, word, many=None):
    return "%d %s" % (n, word if n == 1 else (many or word + "s"))


def _pct(v):
    return ("%.1f" % v) if v >= 1 else ("%.2f" % v)


def hard_nos(a, row, cfg, now):
    """Jupiter's audit: what rules a coin out no matter how it trades. -> reasons."""
    au = a.get("audit") or {}
    bad = []
    if au.get("mintAuthorityDisabled") is False:
        bad.append("mint authority is still active: the dev can print more")
    if au.get("freezeAuthorityDisabled") is False:
        bad.append("freeze authority is still active: your tokens could be frozen")
    if a.get("isMayhem"):
        bad.append("Mayhem mode: pump.fun's AI agent trades it for its first 24 hours, so its buys are partly that bot")
    mints = au.get("devMints")
    if mints is not None and int(mints) > int(cfg["fresh_max_dev_mints"]):
        bad.append("the dev has launched %d coins (%d graduated): a serial launcher" % (int(mints), int(au.get("devMigrations") or 0)))
    for key, limit, text in (("devBalancePercentage", "fresh_max_dev_pct", "the dev holds %s%%"),
                             ("sniperPct", "fresh_max_sniper_pct", "snipers hold %s%%"),
                             ("insiderPct", "fresh_max_insider_pct", "insiders hold %s%%")):
        v = au.get(key)
        if v is not None and float(v) > float(cfg[limit]):
            bad.append("%s (limit %g%%)" % (text % _pct(float(v)), float(cfg[limit])))
    bund = (au.get("bundlerStats") or {}).get("holdingPct")
    if bund is not None and float(bund) > float(cfg["fresh_max_bundler_pct"]):
        bad.append("bundlers hold %s%% (limit %g%%)" % (_pct(float(bund)), float(cfg["fresh_max_bundler_pct"])))
    if a.get("graduatedPool") and now - row["created"] < 300:
        bad.append("it graduated within seconds of its launch: insiders bought the whole curve (bundled)")
    bought = row["facts"].get("dev_buy_pct") or 0
    held = au.get("devBalancePercentage")
    if bought >= 1 and held is not None and float(held) < bought * 0.1:
        bad.append("the dev already sold: bought %s%%, holds %s%% now" % (_pct(bought), _pct(float(held))))
    return bad


def decide(a, row, cfg, now):
    """~30 s: the hard no's again plus the first trading. -> (verdict, good, bad)."""
    bad = hard_nos(a, row, cfg, now)
    au = a.get("audit") or {}
    s5 = a.get("stats5m") or {}
    good = []
    traders, buys, sells = int(s5.get("numTraders") or 0), int(s5.get("numBuys") or 0), int(s5.get("numSells") or 0)
    bought, holders = float(s5.get("buyVolume") or 0), int(a.get("holderCount") or 0)
    if traders >= int(cfg["fresh_min_traders"]):
        good.append("%d traders" % traders)
    else:
        bad.append("only %s (min %d)" % (plural(traders, "trader"), int(cfg["fresh_min_traders"])))
    if holders >= int(cfg["fresh_min_holders"]):
        good.append("%d holders" % holders)
    else:
        bad.append("only %s (min %d)" % (plural(holders, "holder"), int(cfg["fresh_min_holders"])))
    if bought >= float(cfg["fresh_min_buy_volume_usd"]):
        good.append("%s bought" % money(bought))
    else:
        bad.append("%s bought (min %s)" % (money(bought), money(float(cfg["fresh_min_buy_volume_usd"]))))
    if sells > buys:
        bad.append("more selling than buying: %d sells vs %d buys" % (sells, buys))
    elif buys:
        good.append("%d buys vs %d sells" % (buys, sells))
    chg, liq_chg = s5.get("priceChange"), s5.get("liquidityChange")
    if chg is not None and float(chg) <= -30:
        bad.append("down %.0f%% already: dumped" % -float(chg))
    if liq_chg is not None and float(liq_chg) <= -20:
        bad.append("liquidity down %.0f%%: money is leaving" % -float(liq_chg))
    top10 = au.get("topHoldersPercentage")
    if top10 is not None and float(top10) > float(cfg["fresh_max_top10_pct"]):
        bad.append("the top 10 wallets hold %.0f%% (limit %g%%)" % (float(top10), float(cfg["fresh_max_top10_pct"])))
    if not a.get("usdPrice"):
        bad.append("no price yet")
    mints = au.get("devMints")
    if mints is not None and not bad:
        good.append("the dev's first coin" if int(mints) <= 1 else "the dev's coin no. %d" % int(mints))
    return ("buy" if not bad else "skip"), good, bad


def side_costs(cfg, stake_usd):
    """The cost of one buy or one sell, as a fraction: your app's fee (with its minimum), pump.fun's fee, slippage."""
    venue = (cfg.get("venues") or {}).get(cfg.get("venue")) or {}
    fee_pct = float(venue.get("fee_pct", cfg.get("fee_pct", 0.85)))
    fee_min = float(venue.get("fee_min_usd", cfg.get("fee_min_usd", 0)))
    app = max(stake_usd * fee_pct / 100.0, fee_min) / stake_usd if stake_usd else 0.0
    return app + (float(cfg["fresh_curve_fee_pct"]) + float(cfg.get("slippage_pct", 0.3))) / 100.0


def net_result(entry, exit_, cost):
    """Price in and out -> the result after costs on both sides, as a fraction."""
    return (exit_ / entry) * (1 - cost) / (1 + cost) - 1


def test_stats(trades, cfg):
    """The paper test: the first `fresh_test_signals` closed signals, in order, after costs."""
    need = int(cfg["fresh_test_signals"])
    closed = sorted([t for t in trades if t.get("status") == "closed"], key=lambda t: t["signal_t"])
    sample = closed[:need]
    won = sum(t["net_usd"] for t in sample if t["net_usd"] > 0)
    lost = -sum(t["net_usd"] for t in sample if t["net_usd"] <= 0)
    total = won - lost
    pf = (won / lost) if lost > 0 else None
    reasons = {}
    for t in sample:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    verdict = None
    if len(sample) >= need:
        paid = total > 0 and (pf is None or pf >= float(cfg["testphase_min_profit_factor"]))
        verdict = "PASSED" if paid else "FAILED"
    return {"signals": len(trades), "closed": len(sample), "need": need, "open": sum(1 for t in trades if t.get("status") in ("waiting", "open", "exiting")),
            "untracked": sum(1 for t in trades if t.get("status") in ("untracked", "unfilled")),
            "wins": sum(1 for t in sample if t["net_usd"] > 0), "total_usd": total, "won_usd": won, "lost_usd": lost,
            "profit_factor": pf, "avg_pct": (sum(t["net_pct"] for t in sample) / len(sample)) if sample else None,
            "best_pct": max([t["net_pct"] for t in sample] or [0]), "worst_pct": min([t["net_pct"] for t in sample] or [0]),
            "reasons": reasons, "verdict": verdict}


def test_lines(st, eur_usd):
    """The paper test, in a few lines."""
    if not st["signals"]:
        return ["Paper test: no BUY signal yet. Most minutes have none; that is normal."]
    out = []
    if st["closed"]:
        out.append("Paper test: %d of %d signals closed (%d still running%s): %d won, %d lost, %.0f %% win rate" % (
            st["closed"], st["need"], st["open"], (", %d not tracked" % st["untracked"]) if st["untracked"] else "",
            st["wins"], st["closed"] - st["wins"], 100.0 * st["wins"] / st["closed"]))
        out.append("  after costs: average %+.1f %% a trade, best %+.1f %%, worst %+.1f %%; total %+.2f EUR on 5-euro trades%s" % (
            st["avg_pct"] * 100, st["best_pct"] * 100, st["worst_pct"] * 100, st["total_usd"] / eur_usd,
            ("; profit factor %.2f" % st["profit_factor"]) if st["profit_factor"] is not None else ""))
        out.append("  exits: %s" % ", ".join("%s %d" % (k, v) for k, v in sorted(st["reasons"].items())))
    else:
        out.append("Paper test: %d signal%s, none closed yet." % (st["signals"], "" if st["signals"] == 1 else "s"))
    if st["verdict"] == "PASSED":
        out.append("  PASSED: the rule made money after costs on paper over %d signals. That is not a promise for the "
                   "next %d. Real money on fresh coins is your decision." % (st["need"], st["need"]))
    elif st["verdict"] == "FAILED":
        out.append("  FAILED: after costs this rule lost money on paper over %d signals. Do not trade it with real money." % st["need"])
    else:
        out.append("  %d of %d: too few to judge, luck dominates. No real money on these signals yet." % (st["closed"], st["need"]))
    return out


# ---------------------------------------------------------------- the loop

class Radar(object):
    def __init__(self, cfg, jup, tz, out=None, only_grads=False, quiet=False, trades=None, on_change=None,
                 sol_usd=None, eur_usd=1.11):
        self.cfg, self.jup, self.tz, self.out, self.only_grads, self.quiet = cfg, jup, tz, out, only_grads, quiet
        self.creators, self.seen, self.looks, self.rows = {}, [], [], {}
        self.hot_symbols, self.symbols = set(), {}
        self.trades = trades if trades is not None else []
        self.on_change = on_change
        self.sol_usd, self.eur_usd = sol_usd, eur_usd
        self.next_poll = 0.0
        self.counts = {"new": 0, "buy": 0, "skip": 0, "skip_birth": 0, "skip_first": 0, "skip_decide": 0,
                       "skip_nodata": 0, "graduated": 0, "bundled": 0, "paper_closed": 0}

    def load_trending(self):
        """Tickers of the coins already in play (the scanner's files): a new coin with one of them is a copycat."""
        for path in ("watchlist.json", "universe.json"):
            for h in (load(os.path.join(mdir(), path), {}) or {}).get("hits" if path == "watchlist.json" else "tokens", []):
                if h.get("symbol"):
                    self.hot_symbols.add(str(h["symbol"]).upper())

    def say(self, line, always=True):
        if self.quiet and not always:
            return
        out = self.out or sys.stdout
        out.write(line + "\n")
        out.flush()

    def changed(self):
        if self.on_change:
            self.on_change(self.trades)

    def _name(self, row):
        return "%s (%s)" % (row.get("symbol") or "?", row["mint"])

    def skip(self, row, now, reasons, stage):
        row["status"], row["reasons"], row["stage"] = "skip", reasons, stage
        self.counts["skip"] += 1
        self.counts["skip_" + stage] += 1
        self.say("SKIP  %s  %s  %ds: %s" % (local_str(now, self.tz), self._name(row), int(now - row["created"]),
                                           "; ".join(reasons)), always=False)

    def on_event(self, ev, now):
        tx = ev.get("txType")
        if tx == "create":
            self.counts["new"] += 1
            dev = ev.get("traderPublicKey")
            self.creators[dev] = self.creators.get(dev, 0) + 1
            flags, facts = instant(ev, self.creators, self.hot_symbols, self.cfg, self.symbols)
            sym = (ev.get("symbol") or "").upper().lstrip("$")
            if sym:
                self.symbols[sym] = self.symbols.get(sym, 0) + 1
            row = {"mint": ev.get("mint"), "symbol": ev.get("symbol"), "name": ev.get("name"), "created": now,
                   "dev": dev, "facts": facts, "flags": flags, "status": "waiting"}
            self.seen.append(row)
            self.rows[row["mint"]] = row
            if flags:
                self.skip(row, now, flags, "birth")
            elif not self.only_grads:
                first = now + float(self.cfg["fresh_first_look_seconds"])
                self.looks.append([first, "first", row, first + LOOK_RETRY_SECONDS])
        elif tx in ("migrate", "migration"):
            mint = ev.get("mint")
            row = self.rows.get(mint)
            age = (now - row["created"]) if row else None
            self.looks = [lk for lk in self.looks if lk[2]["mint"] != mint]
            if age is not None and age < 300:
                self.counts["bundled"] += 1
                if row.get("status") == "waiting":
                    row["status"] = "bundled"
                self.say("BUNDLED   %s  %s  graduated %.1f s after launch: the whole bonding curve was bought in a "
                         "few transactions, so insiders hold most of it. Stay away." % (local_str(now, self.tz), mint, age))
                return
            self.counts["graduated"] += 1
            self.say("GRADUATED %s  %s  -> %s pool%s. Now it has a real pool: /meme-analyst %s" % (
                local_str(now, self.tz), mint, ev.get("pool") or "a",
                (" after %.0f minutes on the curve" % (age / 60.0)) if age is not None else "", mint))
            self.seen.append({"mint": mint, "created": now, "status": "graduated", "pool": ev.get("pool")})

    def tick(self, now):
        """The timed work: the 10-second and 30-second looks, and the paper trades."""
        due = [lk for lk in self.looks if lk[0] <= now]
        if due:
            self.looks = [lk for lk in self.looks if lk[0] > now]
            got = self.jup.assets([lk[2]["mint"] for lk in due], now, full=True)
            for when, stage, row, give_up in due:
                a = got.get(row["mint"])
                if a is None:
                    if now < give_up:
                        self.looks.append([now + 2, stage, row, give_up])
                    else:
                        self.skip(row, now, ["Jupiter had no data for it yet"], "nodata")
                    continue
                au = a.get("audit") or {}
                row["facts"].update(dev_mints=au.get("devMints"), holders=a.get("holderCount"), mcap=a.get("mcap"))
                if stage == "first":
                    bad = hard_nos(a, row, self.cfg, now)
                    if bad:
                        self.skip(row, now, bad, "first")
                    else:
                        at = row["created"] + float(self.cfg["fresh_decide_seconds"])
                        self.looks.append([at, "decide", row, at + LOOK_RETRY_SECONDS])
                else:
                    verdict, good, bad = decide(a, row, self.cfg, now)
                    if verdict == "buy":
                        self.buy(row, a, now, good)
                    else:
                        self.skip(row, now, bad, "decide")
        self.poll(now)

    # ------------------------------------------------ the paper test

    def buy(self, row, a, now, good):
        c = self.cfg
        price = float(a["usdPrice"])
        stake = float(c["fresh_max_order_eur"]) * self.eur_usd
        cost = side_costs(c, stake)
        t = {"n": len(self.trades) + 1, "mint": row["mint"], "symbol": row.get("symbol"), "signal_t": round(now, 1),
             "signal_price": price, "stake_usd": round(stake, 2), "eur_usd": round(self.eur_usd, 5), "cost_side": round(cost, 5),
             "stop_pct": float(c["fresh_stop_pct"]), "target_pct": float(c["fresh_target_pct"]),
             "hold_minutes": float(c["fresh_hold_minutes"]), "fill_due": round(now + float(c["fresh_fill_delay_seconds"]), 1),
             "status": "waiting", "paper": True, "path": [[round(now, 1), price]], "why": good}
        self.trades.append(t)
        self.changed()
        row["status"], row["reasons"] = "buy", good
        self.counts["buy"] += 1
        sol = (" = %.4f SOL" % (stake / self.sol_usd)) if self.sol_usd else ""
        self.say("BUY   %s  %s  %ds: %s; price %s, mcap %s" % (
            local_str(now, self.tz), self._name(row), int(now - row["created"]), "; ".join(good), price_str(price),
            money(a.get("mcap"))))
        self.say("      paper test, signal %d of %d: %g EUR ($%.2f%s) as if bought %g s from now; stop -%g %%, target +%g %%, "
                 "out after %g minutes; costs about %.1f %% a round trip. Still on the bonding curve." % (
                     t["n"], int(c["fresh_test_signals"]), float(c["fresh_max_order_eur"]), stake, sol,
                     float(c["fresh_fill_delay_seconds"]), t["stop_pct"], t["target_pct"], t["hold_minutes"], cost * 200))
        if cost * 2 > 0.10:
            self.say("      ! %s's fee eats %.0f %% of a %g-euro trade there and back: use Jupiter or Phantom for trades this small" % (
                c.get("venue"), cost * 200, float(c["fresh_max_order_eur"])))

    def poll(self, now):
        live = [t for t in self.trades if t["status"] in ("waiting", "open", "exiting")]
        if not live or now < self.next_poll:
            return
        self.next_poll = now + float(self.cfg["fresh_poll_seconds"])
        got = self.jup.assets([t["mint"] for t in live], now, full=False)
        for t in live:
            a = got.get(t["mint"])
            price = float(a["usdPrice"]) if a and a.get("usdPrice") else None
            if price is not None and t["path"][-1][0] < now - 0.5:
                t["path"].append([round(now, 1), price])
                if len(t["path"]) > 400:
                    del t["path"][1]
            self.step(t, price, now)

    def step(self, t, price, now):
        """Move one paper trade on: filled after the delay, then out at the stop, the target or the time stop,
        again after the delay. No price for two minutes counts as a total loss (the safe assumption)."""
        delay = float(self.cfg["fresh_fill_delay_seconds"])
        if t["status"] == "waiting":
            if now < t["fill_due"]:
                return
            if price is not None:
                t.update(status="open", entry_t=round(now, 1), entry=price, stop=price * (1 - t["stop_pct"] / 100.0),
                         target=price * (1 + t["target_pct"] / 100.0), until=round(now + t["hold_minutes"] * 60, 1))
                self.changed()
            elif now > t["fill_due"] + 120:
                t["status"] = "unfilled"
                self.changed()
            return
        if t["status"] == "open":
            if price is None:
                if now > max(t["until"], t["path"][-1][0]) + 120:
                    self.close(t, None, now, "no price")
                return
            reason = ("stop" if price <= t["stop"] else "target" if price >= t["target"]
                      else "time" if now >= t["until"] else None)
            if reason:
                t.update(status="exiting", exit_reason=reason, trigger_t=round(now, 1), trigger_price=price,
                         exit_due=round(now + delay, 1))
                self.changed()
            return
        if t["status"] == "exiting":
            if now >= t["exit_due"] and price is not None:
                self.close(t, price, now, t["exit_reason"])
            elif price is None and now > t["exit_due"] + 120:
                self.close(t, None, now, "no price")

    def close(self, t, price, now, reason):
        net = net_result(t["entry"], price, t["cost_side"]) if price else -1.0
        t.update(status="closed", exit_t=round(now, 1), exit=price, exit_reason=reason,
                 gross_pct=round(price / t["entry"] - 1, 5) if price else -1.0, net_pct=round(net, 5),
                 net_usd=round(t["stake_usd"] * net, 4))
        self.changed()
        self.counts["paper_closed"] += 1
        st = test_stats(self.trades, self.cfg)
        self.say("PAPER %s  %s (%s)  %s: in %s, out %s (%s), after costs %+.1f %% = %+.2f EUR | test: %d of %d closed, total %+.2f EUR" % (
            local_str(now, self.tz), t.get("symbol") or "?", t["mint"], reason, price_str(t["entry"]),
            price_str(price) if price else "nothing", ("%+.1f %%" % (t["gross_pct"] * 100)) if price else "counted as -100 %",
            net * 100, t["net_usd"] / self.eur_usd, st["closed"], st["need"], st["total_usd"] / self.eur_usd))

    def summary(self, minutes):
        c = self.counts
        return ("Radar, %s: %s: %d BUY, %d SKIP (%d at birth, %d at %ds, %d at %ds, %d without data), "
                "%d graduated, %s." % (
                    plural(int(round(minutes)), "minute"), plural(c["new"], "new coin"), c["buy"], c["skip"], c["skip_birth"],
                    c["skip_first"], int(self.cfg["fresh_first_look_seconds"]), c["skip_decide"],
                    int(self.cfg["fresh_decide_seconds"]), c["skip_nodata"], c["graduated"],
                    plural(c["bundled"], "bundled launch", "bundled launches")))


def resume(trades, now):
    """Paper trades left running by an earlier radar: what happened while it was off is unknown, so they do not count."""
    n = 0
    for t in trades:
        if t.get("status") in ("waiting", "open", "exiting") and t["path"][-1][0] < now - 60:
            t["status"] = "untracked"
            n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Launch radar (meme-radar). Listens, decides BUY or SKIP, never buys.")
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "show", "test"))
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--forever", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="only BUY lines, graduations, paper results and the summary")
    ap.add_argument("--decide", type=float, help="seconds after launch for the verdict (default 30)")
    ap.add_argument("--min-traders", type=int)
    ap.add_argument("--min-volume", type=float, help="USD bought in the first minutes (default 1000)")
    ap.add_argument("--max-dev-buy", type=float)
    ap.add_argument("--graduations-only", action="store_true")
    ap.add_argument("--offline", help="replay a recording (radar.py --save FILE makes one)")
    ap.add_argument("--save", help="record the stream and every lookup to this file (.json.gz)")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (load(os.path.join(mdir(), "config.json"), {}) or {}).items() if v is not None})
    for k, v in (("fresh_decide_seconds", a.decide), ("fresh_min_traders", a.min_traders),
                 ("fresh_min_buy_volume_usd", a.min_volume), ("radar_max_dev_buy_pct", a.max_dev_buy)):
        if v is not None:
            cfg[k] = v
    tz = cfg["timezone"]
    fresh_path = os.path.join(mdir(), "fresh.json")
    if a.cmd == "show":
        st = load(os.path.join(mdir(), "radar.json"))
        if not st:
            print("No radar run yet. Run: radar.py --minutes 10")
            return 1
        for row in st.get("coins", [])[-30:]:
            print("%s  %-9s %-10s %s  %s" % (local_str(row["created"], tz), row["status"], (row.get("symbol") or "")[:10],
                                             row["mint"], "; ".join(row.get("reasons") or row.get("flags") or [])[:140]))
        return 0
    if a.cmd == "test":
        trades = (load(fresh_path, {}) or {}).get("trades", [])
        eur = float(([t["eur_usd"] for t in trades if t.get("eur_usd")] or [cfg["eur_usd_fallback"]])[-1])  # the radar's own rate
        for line in test_lines(test_stats(trades, cfg), eur):
            print(line)
        for t in sorted(trades, key=lambda x: -x["signal_t"])[:10]:
            res = ("%+.1f %% after costs (%s)" % (t["net_pct"] * 100, t["exit_reason"])) if t["status"] == "closed" else t["status"]
            print("  #%-3d %s  %-10s %s  %s" % (t["n"], local_str(t["signal_t"], tz, "%m-%d %H:%M"), (t.get("symbol") or "")[:10],
                                               t["mint"], res))
        return 0
    if a.offline:
        rec = load(a.offline)
        if not rec or "events" not in rec or "assets" not in rec:
            print("Radar: %s is not a recording of this radar (radar.py --save FILE makes one)" % a.offline)
            return 1
        jup = Jup(recording=rec["assets"])
        radar = Radar(cfg, jup, tz, only_grads=a.graduations_only, quiet=a.quiet, sol_usd=rec.get("sol_usd"),
                      eur_usd=float(rec.get("eur_usd") or cfg["eur_usd_fallback"]))
        radar.load_trending()
        evs = [e for e in rec["events"] if not e.get("message")]
        if not evs:
            print("Radar: the recording has no events")
            return 1
        t0 = float(evs[0]["_t"])
        clock = t0
        for ev in evs:
            t = float(ev["_t"])
            while clock < t:
                radar.tick(clock)
                clock += 1.0
            radar.on_event(ev, t)
            radar.tick(t)
        last = float(evs[-1]["_t"])
        end = max([last] + [s[0] for v in rec["assets"].values() for s in v])
        while clock <= end + 1 and (radar.looks or any(x["status"] in ("waiting", "open", "exiting") for x in radar.trades)):
            radar.tick(clock)
            clock += 1.0
        minutes = (last - t0) / 60.0
        still = sum(1 for x in radar.trades if x["status"] in ("waiting", "open", "exiting"))
        if still:
            print("%d paper trades were still running when the recording ended." % still)
    else:
        trades = (load(fresh_path, {}) or {}).get("trades", [])
        gone = resume(trades, time.time())
        write = None if a.no_write else (lambda tr: save(fresh_path, {"trades": tr, "updated": int(time.time())}))
        if gone and write:
            write(trades)
        jup = Jup(record=bool(a.save))
        sol_usd, eur_usd = live_rates(cfg)
        radar = Radar(cfg, jup, tz, only_grads=a.graduations_only, quiet=a.quiet, trades=trades, on_change=write,
                      sol_usd=sol_usd, eur_usd=eur_usd)
        radar.load_trending()
        subs = [{"method": "subscribeMigration"}] + ([] if a.graduations_only else [{"method": "subscribeNewToken"}])
        stream = Stream(subscribe=subs)
        start = time.time()
        end = None if a.forever else start + a.minutes * 60
        print("Radar on at %s %s: %s. Ctrl-C to stop.%s" % (
            local_str(start, tz), tz, "graduations only" if a.graduations_only else
            "every new pump.fun coin gets BUY or SKIP within %ds" % int(cfg["fresh_decide_seconds"]),
            (" %d paper trades from an earlier run were left running and do not count." % gone) if gone else ""))
        sys.stdout.flush()
        events = []
        try:
            for ev in stream.messages():
                now = time.time()
                if ev is not None and not ev.get("message"):
                    ev["_t"] = round(now, 3)
                    if a.save:
                        events.append(ev)
                    radar.on_event(ev, now)
                radar.tick(now)
                if end and now >= end:
                    break
        except KeyboardInterrupt:
            pass
        radar.tick(time.time())
        minutes = (time.time() - start) / 60.0
        waiting = len(radar.looks)
        if waiting:
            print("%d coins were too young for a verdict when the radar stopped." % waiting)
        still = sum(1 for x in radar.trades if x["status"] in ("waiting", "open", "exiting"))
        if still:
            print("%d paper trades are still running: they only count while the radar is on." % still)
        if a.save:
            save(a.save, {"kind": "radar-jupiter-recording", "events": events, "assets": jup.saved,
                          "sol_usd": sol_usd, "eur_usd": eur_usd})
    print(radar.summary(minutes))
    for line in test_lines(test_stats(radar.trades, cfg), radar.eur_usd):
        print(line)
    if not a.no_write:
        save(os.path.join(mdir(), "radar.json"), {"as_of": int(time.time()), "counts": radar.counts,
                                                  "coins": radar.seen[-500:]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
