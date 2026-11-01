---
name: meme-scanner
description: >-
  Coin Scanner. Scans the meme coins people are trading right now for
  setups. Collects the tokens in play from DexScreener (paid boosts, new
  token profiles, community takeovers, ads) and GeckoTerminal (trending and
  new pools), reads each token's main pool, drops what is too thin, too
  young or washed by bots, and tags setups from the pool stats (momentum,
  volume surge, dip in an uptrend, new pool). Then a 1-minute range breakout
  scan: which charts just CLOSED above the high of the 15 minutes before, on
  rising volume. Writes meme/watchlist.json for meme-analyst, meme-news and
  meme-entry. Free data, no key. Use when the user says "scan meme coins",
  "what is pumping", "find me setups", "what is breaking out on Solana",
  "trending on DexScreener", "was pumpt gerade", "scanne meme coins",
  "finde mir coins", "build my watchlist", or at the start of a session
  before /meme-analyst.
argument-hint: "[universe | pairs | range] [--tokens MINT,...]"
---

# meme-scanner

The Coin Scanner is the first step of a meme coin trade. It reads what is in
play right now and lists the coins that match a rule. That is all it does. A
scan is a list of charts that match a rule, not a list of coins to buy. Most
meme coins go to zero, and most people who trade them lose money; the
scanner does not change that. It only saves you from scrolling DexScreener
and Fomo's feed by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                    # -> meme/universe.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" pairs                       # pool stats + setups -> meme/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" range                       # 1-minute breakouts -> meme/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" range --tokens MINT1,MINT2  # your own list
python3 "${CLAUDE_SKILL_DIR}/scan.py" pairs --setup momentum --json
```

Flags: `--chains solana` (default from `meme/config.json`), `--min-liquidity`
(default `min_liquidity_usd`, 50,000), `--min-age-hours` (6), `--min-mcap`
(100,000), `--max-mcap`, `--min-txns 100` (buys plus sells in the last
hour), `--max-turnover` (50: 24h volume over 50x the liquidity is washed),
`--include-curve` (keep coins still on a bonding curve), `--range-minutes
15`, `--fresh 10`, `--vol-x 1.5`, `--max-confirm 25`, `--no-gecko`, `--now
"2026-11-01 21:58"` (your time zone), `--offline FILE` and `--save FILE` (a
replayable bundle of every response), `--no-write`, `--show N`. Exit code 0
when the scan found something, 1 when it found nothing or could not run.

## What it reads and writes

| file | what |
| --- | --- |
| `meme/config.json` | `chains`, `timezone`, `min_liquidity_usd`, `min_pool_age_hours`, `max_turnover` |
| `meme/universe.json` | written by `universe` (and `pairs`): every token in play with its main pool's stats |
| `meme/watchlist.json` | written by `pairs` and `range`: `mode`, `as_of`, the counts and `hits[]`. meme-analyst, meme-news, meme-entry and meme-whales read `hits[].address` |

## The universe

DexScreener's free endpoints (60 requests a minute) list the tokens people
are paying to promote or just set up: `token-boosts/top`, `token-boosts/latest`,
`token-profiles/latest`, `community-takeovers/latest`, `ads/latest`.
GeckoTerminal adds `trending_pools` and `new_pools` (30 a minute; when it
rate-limits, the scanner says "skipped" and goes on). Every token is then
matched to its most liquid pool through `tokens/v1/{chain}/{up to 30
addresses}`. A paid boost is promotion, not demand: the scanner uses the
lists to find coins, never as a reason to like one.

## The pairs scan (pool stats)

Out, in this order: still on a bonding curve (pump.fun and friends: no pool
yet, unless `--include-curve`), pool liquidity under the minimum, pool
younger than the minimum, market cap under the minimum, fewer than
`--min-txns` trades in the last hour, and 24h volume over `--max-turnover`
times the liquidity (bots trading with themselves). Then the setups:

| setup | the rule on DexScreener's pool stats |
| --- | --- |
| `momentum` | up 5 % or more in the last hour, the last 5 minutes not red, more buys than sells in the hour, the hour's volume at least the 6-hour average |
| `volume_surge` | the last hour's volume at least twice the 6-hour hourly average |
| `dip` | up 20 % or more in 24 hours, down 3 to 15 % in the last hour, the last 5 minutes not red |
| `new_pool` | the pool is under 24 hours old (and over the minimum age) |

Hits are listed most traded in the last hour first.

## The range scan (1-minute bars)

The candidates are every coin that passed the pairs filters, setup or not
(or `--tokens`, or `--watchlist FILE`). For each, the last 30 or so
1-minute bars: Jupiter's chart data for Solana (by mint), GeckoTerminal for
other chains (by pool). A hit is the first of the last `--fresh` completed
bars that CLOSED above the highest high of the `--range-minutes` bars before
it, with volume at least `--vol-x` times their average. A range with a
missing minute is skipped (no trades in a minute means a thin coin). A bar
counts only once it is complete. `--max-confirm` caps how many charts it
reads (most traded first) and says PARTIAL when it skipped some.

## Steps

1. `scan.py pairs` (it builds the universe if it is missing or old). Tell
   the user the counts (universe, with a pool, passed, washed, hits) and the
   top few with their setups.
2. `scan.py range`. Tell the user which coins just broke out, when, by how
   much, on what volume, and the price now. A hit from 9 minutes ago is not
   the price now.
3. The user picks one coin. Hand it on: `/meme-analyst MINT` (is it a rug?)
   first, always, then `/meme-news` and `/meme-entry`. Never pick for them.
4. Always say the contract address, never only the ticker: tickers are not
   unique for meme coins and copies use the same name.

## Example: the reel

Sunday 2026-11-01, Europe/Berlin. The pairs scan at 21:55 (the real
responses are in `tests/fixtures/meme-scanner/pairs-2026-11-01-2155.json.gz`):

```
Pairs scan at Sun 2026-11-01 21:55 (Europe/Berlin), DexScreener stats:
  104 tokens in the universe, 62 with a pool, 42 still on a bonding curve (left out).
  19 passed the filters (liquidity >= $50.0k, pool >= 6h old, market cap >= $100.0k, >= 100 trades in the last hour); 1 left out as washed (24h volume over 50x liquidity).
4 matched a setup, most traded in the last hour first:
  Anakin     $0.0034780   liq $177.3k mcap $3.3M   5m  -6.5% 1h +36.3% 24h +252.0%  volume_surge
  ...
```

Three minutes later the range scan over the liquid coins
(`range-2026-11-01-2158.json.gz`):

```
Range scan at Sun 2026-11-01 21:58 (Europe/Berlin), 1-minute bars:
  checked 7 charts (0 had no bars).
1 closed above the high of the 15 minutes before, on volume >= 1.5x, in the last 10 bars:
  21:58  GATO       $0.0077889   range 0.0074560 to 0.0077195 (21:42 to 21:57)  +0.90% over, volume 2.7x
         HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump  now $0.0077889
```

GATO (GTA6CAT, a pump.fun coin now on PumpSwap, $278k pool) broke its
21:42 to 21:57 range on the 21:57 bar, 0.90 % over the high on 2.7x volume.
It matched no pairs setup (more sells than buys in the hour), which is fine:
the two scans ask different questions. The user picks GATO and Claude hands
it to `/meme-analyst HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump`.

## Rules

- Say what was scanned: how many tokens, how many charts, how many usable, the time of the data.
- Say "matched a rule", never "a buy", "a gem", "a winner" or "going to moon".
- Never print a profit figure or a price prediction.
- A hit is stale within minutes on a meme coin. Re-run before acting on it.
- Always give the contract address with the ticker.

## What it never does

It never buys, sizes or checks a trade, never says which coin to buy, never
calls the data real time, and never promises that a setup works.

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
