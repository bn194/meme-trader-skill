---
name: meme-entry
description: >-
  Entry Timer. Watches one meme coin bar by bar and tells you the moment to
  get in. Reads free 1-minute bars (Jupiter's chart data for Solana,
  GeckoTerminal for other chains), builds a range from the first 15 minutes
  after you start watching (or the range the scanner found) and calls the
  entry on the first completed bar that CLOSES above the range high on
  volume of at least 1.5x the range's average, or above a level you give
  it. Says building, waiting and how far, triggered with the time and the
  price, failed (closed under the range low first), or expired, and flags a
  stale trigger. Writes meme/entry.json for /meme-exit. Long side only, it
  never buys. Use when the user says "tell me when to get in", "watch this
  coin", "has it broken out", "entry signal", "time my entry", "sag mir wann
  ich rein soll", "beobachte den coin", "ist er ausgebrochen", or after
  /meme-analyst and /meme-news, before /meme-exit.
argument-hint: "[contract address] [--from HH:MM] [--setup range|level --level X]"
---

# meme-entry

The Entry Timer turns "this coin looks like it wants to go" into a rule you
can check: a 1-minute close above a range, on volume. On a meme coin an
entry without a rule is a FOMO buy at the top of a candle. This skill waits
for the bar to close, checks the volume, and says it plainly. It never buys.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check MINT                  # range from now, or the scanner's, or entry.json's
python3 "${CLAUDE_SKILL_DIR}/entry.py" check MINT --from 21:42     # the range starts at 21:42 (your time zone)
python3 "${CLAUDE_SKILL_DIR}/entry.py" check MINT --setup level --level 0.0081
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch MINT --every 30       # check every 30 s until it ends
python3 "${CLAUDE_SKILL_DIR}/entry.py" show
```

Other flags: `--range-minutes 15`, `--vol-x 1.5` (0 switches the volume
check off), `--max-wait 60` (minutes after the range), `--chain`, `--symbol`,
`--now "2026-11-01 21:58"`, `--offline FILE` (saved bars, or a scanner
bundle), `--no-write`, `--json`. MINT can also be a DexScreener URL or a
ticker that is in `meme/watchlist.json`. Exit code 0 when triggered.

## What it reads and writes

| source / file | what |
| --- | --- |
| Jupiter `datapi.jup.ag/v2/charts/{mint}` | Solana 1-minute bars (unofficial, free) |
| GeckoTerminal `pools/{pool}/ohlcv/minute` | other chains (30 requests a minute) |
| `meme/watchlist.json` | a range scan hit's range start, used when you give no `--from` |
| `meme/entry.json` | the state it writes: range, status, trigger, last close. Reused by the next check of the same coin |

## The rule

- **The range** is the 15 one-minute bars from `--from` (default: the
  scanner's range for that coin, else the range already in entry.json, else
  the current minute: the range builds from now). High = the highest high,
  low = the lowest low. Fewer than 80 % of the minutes traded: "too thin for
  a range", no setup.
- **The trigger** is the first COMPLETED bar after the range that closes
  above the range high with volume >= `--vol-x` times the range's average
  minute. A wick above the high does not count. The bar in progress never
  counts.
- **Failed**: a bar closed under the range low before any trigger. The
  setup is off; do not buy the dip into it.
- **Expired**: nothing within `--max-wait` minutes after the range.
- **Stale**: a trigger more than 5 minutes ago. It still says triggered, and
  the price now; a late entry has more risk, so plan from the current price
  or skip it.
- **Level setup**: `--setup level --level X` triggers on a 1-minute close
  above X, with the volume of the 15 minutes before the watch as the
  baseline. It has no range, so /meme-exit needs a stop you name.

## Steps

1. Run `check` on the coin the user picked. Read back the state.
2. Building or waiting: offer `watch --every 30` in the background (or a
   `/loop`), and say when the range closes and when it expires.
3. Triggered: say the time, the bar, the close and the volume, then hand
   straight to `/meme-exit`. The plan comes BEFORE the buy.
4. Failed, expired or thin: say so and stop. No entry is also a result.

## Example: the reel

GATO, Sunday 2026-11-01, Europe/Berlin. The scanner's range for GATO was
21:42 to 21:57; at 21:58 (`tests/fixtures/meme-timemachine/GATO-1m-2026-11-01-2158.json.gz`):

```
GATO (HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump), 15-minute range breakout on 1-minute bars, checked 21:58 Europe/Berlin
  range 21:42 to 21:57: high $0.0077195, low $0.0074560 (15 bars)
TRIGGERED at 21:58: the 21:57 bar closed at $0.0077889, 0.90% over $0.0077195, volume 2.73x the range average.
Next: /meme-exit plans the stop and the target before anything is bought.
```

The same rule on GATO earlier that evening: at 19:46 it said WAITING (the
19:30 range's high was 0.0074900, the last close 0.66 % under it), at 19:47
TRIGGERED (the 19:46 bar closed at 0.0075741 on 2.89x volume), and at 20:30
a 20:00 range FAILED when the 20:15 bar closed under its low.

## Rules

- Only completed 1-minute bars count, never the live one. Never call it real time.
- A trigger is a rule that fired, not a prediction and not a buy.
- Say how stale a trigger is. Never let the user chase a coin that already ran.
- Long side only.

## What it never does

It never buys, sizes or plans a trade, never lowers the volume bar to make
something trigger, and never calls a breakout a sure thing.

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
