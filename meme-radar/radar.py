#!/usr/bin/env python3
"""The Launch Radar (meme-radar). Standard library only.

Listens to every new pump.fun coin the second it is created, and to every
coin that graduates from the bonding curve to a real pool, through
PumpPortal's free data stream (a websocket, no key). Each new coin gets an
instant check (how much the dev bought, a serial launcher, a copycat ticker,
junk names), and the ones that pass get a second look after 90 seconds on
DexScreener (buyers, sellers, volume, the move) and in their metadata
(website, X, Telegram). Coins that hold up are printed as HOT with every
reason; graduations are printed as GRADUATED. It never buys anything.

    python3 radar.py                       # listen for 10 minutes
    python3 radar.py --minutes 60
    python3 radar.py --forever             # until you stop it
    python3 radar.py --delay 120 --min-buys 30
    python3 radar.py --graduations-only    # only coins that reached a real pool
    python3 radar.py show                  # the last coins it saw

The first seconds of a coin say almost nothing: no buyers yet, no pool, no
holders. About 1 % of pump.fun coins ever graduate. The fastest buyers are
bots. A HOT line is a coin that passed a few checks, not a buy.
"""

import argparse
import base64
import calendar
import datetime
import gzip
import json
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
DS_TOKEN = "https://api.dexscreener.com/tokens/v1/solana/%s"
PUMP_SUPPLY = 1000000000.0
JUNK = re.compile(r"(?i)\b(test|rug|scam|honeypot|airdrop|claim|free)\b")
DEFAULTS = {"timezone": "Europe/Berlin", "radar_delay_seconds": 90, "radar_min_buys": 20,
            "radar_min_volume_usd": 3000, "radar_max_dev_buy_pct": 10}


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

    def messages(self):
        """Yield every text message as a dict, forever (reconnects on a drop)."""
        backoff = 2
        while True:
            try:
                if self.sock is None:
                    self.connect()
                    backoff = 2
                parts = b""
                while True:
                    try:
                        self._need(2)
                    except socket.timeout:
                        self._send(0x9, b"radar")
                        continue
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


# ---------------------------------------------------------------- HTTP with record / replay

class Net:
    def __init__(self, bundle=None, record=False):
        self.bundle = bundle
        self.recorded = {} if record else None

    def get(self, url, timeout=10):
        if self.bundle is not None:
            return self.bundle.get(url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            data = None
        if self.recorded is not None:
            self.recorded[url] = data
        return data


GATEWAYS = ("https://ipfs.io/ipfs/%s", "https://gateway.pinata.cloud/ipfs/%s")


def meta_urls(uri):
    """IPFS links through two public gateways in turn (they rate-limit), everything else as is."""
    if not uri:
        return []
    m = re.search(r"/ipfs/([A-Za-z0-9]+)", uri)
    return [g % m.group(1) for g in GATEWAYS] if m else [uri]


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


def follow_up(mint, net, meta_uri, cfg):
    """After the delay: DexScreener's numbers and the metadata's links. -> (verdict, reasons, facts)."""
    facts, good, bad = {}, [], []
    data = net.get(DS_TOKEN % mint)
    pairs = data if isinstance(data, list) else (data or {}).get("pairs") or []
    pairs = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not pairs:
        return "quiet", ["DexScreener has no trades for it yet"], facts
    p = max(pairs, key=lambda x: ((x.get("volume") or {}).get("h24") or 0))
    tx = (p.get("txns") or {}).get("m5") or {}
    buys, sells = int(tx.get("buys") or 0), int(tx.get("sells") or 0)
    vol = float(((p.get("volume") or {}).get("m5")) or 0)
    chg = (p.get("priceChange") or {}).get("m5")
    facts.update(buys=buys, sells=sells, volume_m5=vol, change_m5=chg, mcap=p.get("marketCap"),
                 dex=p.get("dexId"), symbol=(p.get("baseToken") or {}).get("symbol"))
    if buys >= int(cfg["radar_min_buys"]):
        good.append("%d buys vs %d sells in 5 minutes" % (buys, sells))
    else:
        bad.append("only %d buys in 5 minutes (min %d)" % (buys, int(cfg["radar_min_buys"])))
    if sells > buys * 1.5 and sells >= 10:
        bad.append("selling: %d sells vs %d buys" % (sells, buys))
    if vol >= float(cfg["radar_min_volume_usd"]):
        good.append("%s volume in 5 minutes" % money(vol))
    else:
        bad.append("%s volume in 5 minutes (min %s)" % (money(vol), money(float(cfg["radar_min_volume_usd"]))))
    if chg is not None and float(chg) < -30:
        bad.append("down %.0f%% in 5 minutes: dumped" % float(chg))
    socials = []
    meta = None
    if buys >= int(cfg["radar_min_buys"]):  # the metadata is slow to fetch: only for coins with buyers
        for url in meta_urls(meta_uri):
            meta = net.get(url, timeout=6)
            if isinstance(meta, dict):
                break
    if isinstance(meta, dict):
        for key in ("twitter", "telegram", "website"):
            if meta.get(key):
                socials.append(key)
    facts["socials"] = socials
    if socials:
        good.append("links: %s" % ", ".join(socials))
    else:
        bad.append("no website, X or Telegram in its metadata")
    verdict = "hot" if not bad else ("watch" if len(bad) == 1 and buys >= int(cfg["radar_min_buys"]) else "skip")
    return verdict, good + bad, facts


# ---------------------------------------------------------------- the loop

class Radar:
    def __init__(self, cfg, net, tz, out=None, only_grads=False):
        self.cfg, self.net, self.tz, self.out, self.only_grads = cfg, net, tz, out, only_grads
        self.creators, self.queue, self.seen = {}, [], []
        self.hot_symbols = set()
        self.symbols, self.born = {}, {}
        self.counts = {"new": 0, "flagged": 0, "followed": 0, "hot": 0, "watch": 0, "graduated": 0}

    def load_trending(self):
        """Tickers of the coins already in play (the scanner's files): a new coin with one of them is a copycat."""
        for path in ("watchlist.json", "universe.json"):
            for h in (load(os.path.join(mdir(), path), {}) or {}).get("hits" if path == "watchlist.json" else "tokens", []):
                if h.get("symbol"):
                    self.hot_symbols.add(str(h["symbol"]).upper())

    def say(self, line):
        out = self.out or sys.stdout
        out.write(line + "\n")
        out.flush()

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
            self.born[ev.get("mint")] = now
            row = {"mint": ev.get("mint"), "symbol": ev.get("symbol"), "name": ev.get("name"), "created": now,
                   "dev": dev, "uri": ev.get("uri"), "facts": facts, "flags": flags,
                   "status": "flagged" if flags else "waiting"}
            self.seen.append(row)
            if flags:
                self.counts["flagged"] += 1
            elif not self.only_grads:
                self.queue.append((now + float(self.cfg["radar_delay_seconds"]), row))
        elif tx in ("migrate", "migration"):
            mint = ev.get("mint")
            born = self.born.get(mint)
            age = (now - born) if born is not None else None
            self.queue = [q for q in self.queue if q[1].get("mint") != mint]
            for row in self.seen:
                if row.get("mint") == mint and row.get("status") in ("waiting", "flagged"):
                    row["status"] = "bundled" if age is not None and age < 300 else row["status"]
            if age is not None and age < 300:
                self.counts["bundled"] = self.counts.get("bundled", 0) + 1
                self.say("BUNDLED   %s  %s  graduated %.1f s after launch: the whole bonding curve was bought in a "
                         "few transactions, so insiders hold most of it. Stay away." % (local_str(now, self.tz), mint, age))
                self.seen.append({"mint": mint, "created": now, "status": "bundled", "pool": ev.get("pool"), "age": age})
                return
            self.counts["graduated"] += 1
            self.say("GRADUATED %s  %s  -> %s pool%s. Now it has real liquidity: /meme-analyst %s" % (
                local_str(now, self.tz), mint, ev.get("pool") or "a",
                (" after %.0f minutes on the curve" % (age / 60.0)) if age is not None else "", mint))
            self.seen.append({"mint": mint, "created": now, "status": "graduated", "pool": ev.get("pool")})

    def due(self, now):
        ready = [q for q in self.queue if q[0] <= now]
        self.queue = [q for q in self.queue if q[0] > now]
        for _, row in ready:
            self.counts["followed"] += 1
            verdict, reasons, facts = follow_up(row["mint"], self.net, row.get("uri"), self.cfg)
            row["facts"].update(facts)
            row["status"] = verdict
            row["reasons"] = reasons
            if verdict in ("hot", "watch"):
                self.counts[verdict] += 1
                age = int(now - row["created"])
                f = row["facts"]
                self.say("%s %s  %s (%s)  %ds old: %s; mcap %s, 5m %s, dev bought %.1f%%" % (
                    "HOT  " if verdict == "hot" else "WATCH", local_str(now, self.tz), row.get("symbol"), row["mint"],
                    age, "; ".join(reasons), money(f.get("mcap")),
                    ("%+.0f%%" % float(f["change_m5"])) if f.get("change_m5") is not None else "n/a", f["dev_buy_pct"]))
                self.say("      still on the bonding curve: no LP, no holder data yet. Next: /meme-analyst %s" % row["mint"])

    def summary(self, minutes):
        c = self.counts
        return ("Radar, %.0f minutes: %d new coins, %d flagged at birth, %d checked after %ds, %d HOT, %d to watch, "
                "%d graduated, %d bundled launches." % (minutes, c["new"], c["flagged"], c["followed"],
                                                        int(self.cfg["radar_delay_seconds"]), c["hot"], c["watch"],
                                                        c["graduated"], c.get("bundled", 0)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Launch radar (meme-radar). Listens and checks, never buys.")
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "show"))
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--forever", action="store_true")
    ap.add_argument("--delay", type=float, help="seconds before the second look (default 90)")
    ap.add_argument("--min-buys", type=int)
    ap.add_argument("--min-volume", type=float)
    ap.add_argument("--max-dev-buy", type=float)
    ap.add_argument("--graduations-only", action="store_true")
    ap.add_argument("--offline", help="replay a recording (radar.py --save FILE makes one)")
    ap.add_argument("--save", help="record the stream and every lookup to this file (.json.gz)")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (load(os.path.join(mdir(), "config.json"), {}) or {}).items() if v is not None})
    for k, v in (("radar_delay_seconds", a.delay), ("radar_min_buys", a.min_buys), ("radar_min_volume_usd", a.min_volume),
                 ("radar_max_dev_buy_pct", a.max_dev_buy)):
        if v is not None:
            cfg[k] = v
    tz = cfg["timezone"]
    if a.cmd == "show":
        st = load(os.path.join(mdir(), "radar.json"))
        if not st:
            print("No radar run yet. Run: radar.py --minutes 10")
            return 1
        for row in st.get("coins", [])[-30:]:
            print("%s  %-9s %-10s %s  %s" % (local_str(row["created"], tz), row["status"], (row.get("symbol") or "")[:10],
                                             row["mint"], "; ".join(row.get("flags") or row.get("reasons") or [])[:120]))
        return 0
    events = []
    if a.offline:
        rec = load(a.offline)
        if not rec or "events" not in rec:
            print("Radar: %s is not a radar recording" % a.offline)
            return 1
        net = Net(bundle=rec.get("responses", {}))
        radar = Radar(cfg, net, tz, only_grads=a.graduations_only)
        radar.load_trending()
        last = None
        for ev in rec["events"]:
            t = float(ev.get("_t") or 0)
            radar.due(t)
            radar.on_event(ev, t)
            last = t
        minutes = ((last or 0) - float(rec["events"][0].get("_t") or 0)) / 60.0 if rec["events"] else 0
    else:
        net = Net(record=bool(a.save))
        radar = Radar(cfg, net, tz, only_grads=a.graduations_only)
        radar.load_trending()
        subs = [{"method": "subscribeMigration"}] + ([] if a.graduations_only else [{"method": "subscribeNewToken"}])
        stream = Stream(subscribe=subs)
        start = time.time()
        end = None if a.forever else start + a.minutes * 60
        print("Radar on at %s %s: %s. Ctrl-C to stop." % (local_str(start, tz), tz,
              "graduations only" if a.graduations_only else "every new pump.fun coin and every graduation"))
        sys.stdout.flush()
        try:
            for ev in stream.messages():
                now = time.time()
                if ev.get("message"):
                    continue
                ev["_t"] = round(now, 3)
                if a.save:
                    events.append(ev)
                radar.on_event(ev, now)
                radar.due(now)
                if end and now >= end:
                    break
        except KeyboardInterrupt:
            pass
        radar.due(time.time())
        minutes = (time.time() - start) / 60.0
        if radar.queue:
            print("%d coins were younger than %ds when the radar stopped: not checked." % (
                len(radar.queue), int(cfg["radar_delay_seconds"])))
        if a.save:
            save(a.save, {"events": events, "responses": net.recorded, "cfg": {k: cfg[k] for k in DEFAULTS}})
    print(radar.summary(minutes))
    if not a.no_write:
        save(os.path.join(mdir(), "radar.json"), {"as_of": int(time.time()), "counts": radar.counts,
                                                  "coins": radar.seen[-500:]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
