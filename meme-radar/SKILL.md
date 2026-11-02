---
name: meme-radar
description: >-
  Launch Radar. Listens to every new pump.fun coin the second it is created
  and to every coin that graduates to a real pool, through PumpPortal's free
  websocket (no key). Each new coin gets an instant check (how much the dev
  bought, a serial launcher, a copycat or a copy race of the same ticker,
  junk names); the ones that pass get a second look after 90 seconds on
  DexScreener (buyers, sellers, volume, the move) and in their metadata
  (website, X, Telegram), and are printed as HOT or WATCH with every reason.
  A coin that graduates seconds after launch is flagged as BUNDLED (insiders
  bought the whole curve). It never buys. Use when the user says "check new
  coins", "neue coins sofort checken", "snipe", "frische coins", "was wurde
  gerade gelauncht", "new pump.fun launches", "launch radar", "what just
  graduated", "radar an", or wants coins earlier than the scanner sees them.
argument-hint: "[--minutes 10 | --forever] [--graduations-only] [show]"
---

# meme-radar

The Launch Radar is the earliest look this pack has: a coin is on screen
within a second of its creation. Be clear about what that second is worth.
In the first seconds a coin has no buyers, no pool, no holders, only a name,
a picture and the dev's own buy. About 1 % of pump.fun coins ever graduate
from the bonding curve; most are dead within the hour. The very first buyers
are bots that buy in the same block. A human who says "buy" after reading a
line is never first, and does not need to be: the radar's job is to throw
out the obvious traps fast and show the few coins that survived their first
minutes with real buyers.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/radar.py"                      # listen 10 minutes
python3 "${CLAUDE_SKILL_DIR}/radar.py" --minutes 60
python3 "${CLAUDE_SKILL_DIR}/radar.py" --forever            # until stopped
python3 "${CLAUDE_SKILL_DIR}/radar.py" --graduations-only   # only coins that reached a real pool
python3 "${CLAUDE_SKILL_DIR}/radar.py" --delay 120 --min-buys 30 --min-volume 5000 --max-dev-buy 5
python3 "${CLAUDE_SKILL_DIR}/radar.py" show                 # the last coins it saw, with reasons
```

Other flags: `--save FILE` (record the stream and every lookup), `--offline
FILE` (replay a recording), `--no-write`.

## What it reads and writes

| source / file | what |
| --- | --- |
| PumpPortal `wss://pumpportal.fun/api/data` | `subscribeNewToken` (every new pump.fun coin) and `subscribeMigration` (graduations), free. Per-trade streams need a paid key; the radar does not use them |
| DexScreener `tokens/v1/solana/{mint}` | buys, sells, volume, change and market cap in the coin's first minutes |
| the coin's metadata (IPFS, two public gateways) | website, X and Telegram links |
| `meme/watchlist.json`, `meme/universe.json` | tickers already in play: a new coin with one of them is a copycat |
| `meme/config.json` | `radar_delay_seconds` (90), `radar_min_buys` (20), `radar_min_volume_usd` (3,000), `radar_max_dev_buy_pct` (10), `timezone` |
| `meme/radar.json` | the last 500 coins with their status and reasons (`show` prints them) |

## The checks

At birth, no network (a coin with any of these is out):

| check | out when |
| --- | --- |
| dev buy | the creator bought more than `radar_max_dev_buy_pct` (10 %) of the supply in the launch |
| serial launcher | the same wallet created 3 or more coins since the radar started |
| copycat | the ticker is already a coin in play (the scanner's lists) |
| copy race | the same ticker was launched before in this session: copies of copies, they usually die |
| junk | test, rug, scam, honeypot, airdrop, claim, free in the name, or no readable ticker |

After `radar_delay_seconds` (90): HOT needs at least `radar_min_buys` buys
in 5 minutes, at least `radar_min_volume_usd` of volume, not twice as many
sells as buys, not down 30 % or more (dumped), and a website, X or Telegram
link in its metadata. One miss with real buyers: WATCH. More: skipped.

Graduations: `GRADUATED` with how long it took. A coin that graduates within
5 minutes of its launch is `BUNDLED`: the whole curve was bought in a few
transactions, so insiders hold most of the supply. Stay away from those.

## Steps

1. In a session, run it in the background (`radar.py --minutes 30`) and read
   its lines as they come; in Claude Code use the Monitor tool on it so every
   HOT, WATCH, GRADUATED or BUNDLED line arrives as an event. In the Claude
   app a push notification can go to the user's phone for a HOT line.
2. For a HOT or WATCH coin: say why, in one line, and that it is still on the
   bonding curve (no LP, no holder data). Only on the user's signal go on:
   `/meme-analyst MINT --write`, `/meme-entry`, `/meme-exit`, and the rest of
   the chain. meme-risk wants a pool at least `min_pool_age_hours` old, so a
   coin this young is blocked unless the user lowers that limit themselves.
3. For a GRADUATED coin: it now has a real pool. `/meme-analyst MINT` is the
   next step.
4. Say the counts at the end (new, flagged, checked, HOT, WATCH, graduated,
   bundled). Most minutes have no HOT coin. That is normal.

## Example: a real recording

Sunday 2026-11-01, 23:09 to 23:15 Europe/Berlin
(`tests/fixtures/meme-radar/radar-2026-11-01-2309.json.gz`):

```
BUNDLED   23:10:04  HV4fcGzFKLBV5Q8fKsgvedKHu7K3XpEZc7pgpgxVpump  graduated 0.2 s after launch: the whole bonding curve was bought in a few transactions, so insiders hold most of it. Stay away.
GRADUATED 23:11:53  Bv9xDKiQzZMwPw7rCzog2dEYuZp3wBGaoK4DacC7pump  -> pump-amm pool. Now it has real liquidity: /meme-analyst Bv9xDKiQzZMwPw7rCzog2dEYuZp3wBGaoK4DacC7pump
WATCH 23:13:08  COVERED (GeLShjLo8XV2iR1pvky4h9F2RzFKq4aDKVmKCNTZpump)  93s old: 166 buys vs 81 sells in 5 minutes; $11.3k volume in 5 minutes; no website, X or Telegram in its metadata; mcap $8.7k, 5m +208%, dev bought 3.4%
Radar, 6 minutes: 58 new coins, 26 flagged at birth, 27 checked after 90s, 0 HOT, 2 to watch, 1 graduated, 1 bundled launches.
```

58 new coins in 6 minutes. One wallet launched the same "Hyperhold" ticker
ten times in a row; a coin called FOMO was created and graduated 0.2
seconds later. No coin passed every check.

## Rules

- A HOT line is a coin that passed a few checks, never a buy signal.
- Always give the full contract address, never only the ticker: the copies share it.
- Say that the coin is still on the bonding curve, with no LP and no holder data.
- Never place, size or schedule a buy from the radar. The user decides, then the normal chain runs.

## What it never does

It never buys or sells, never signs anything, never uses a paid stream, and
never calls a launch safe.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Meme coins are the riskiest corner of crypto: most new coins go to zero, many are rugs, and a stop can
  fill far below its price. Trade only money you can afford to lose completely.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack buys or sells on its own. A trade happens only when all three hold: meme-risk passed
  that exact order today, the user typed an explicit yes for that one order in the chat, and then the user
  made the trade themselves in their own app (live) or meme-broker filled it on paper.
- This pack never asks for, reads or stores a seed phrase, a private key or a wallet password, and never
  connects to a wallet. If the user pastes one, tell them to move their funds to a new wallet right away.
- No leverage, perps or short selling unless the config allows it and the user confirms.
