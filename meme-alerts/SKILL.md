---
name: meme-alerts
description: >-
  Price Alerts. Rings when a meme coin hits your stop, your target or your
  time stop, and when its pool's liquidity drops (the rug alarm). Turns the
  plan from meme-exit into four alerts in one go (stop, target, flat by the
  time stop, and liquidity down 30 % from now), plus above / below levels,
  a percent move either way, a reminder at a time, or your own liquidity
  drop, each ringing once so you are not spammed. Reads free DexScreener
  prices (up to 30 coins a request, no key), works in your time zone, and
  writes meme/prices.json for sizing and the risk check. Use when the user
  says "alert me when", "tell me if it hits", "watch my stop", "watch my
  trade", "rug alarm", "sag mir wenn", "alarm bei", "überwach meinen
  trade", "get me a price", "what is it at now", or right after
  /meme-broker fills a buy, or after /meme-exit writes a plan.
argument-hint: "[add --from-plan | add --token MINT --above X | check | watch | quote MINT]"
---

# meme-alerts

Price Alerts watch the trade so you do not have to stare at the chart. On a
meme coin three things end a trade: the stop, the target and the clock. A
fourth one ends it badly: the pool emptying. This skill rings once for each,
in plain words, with what to do next. It never sells anything itself.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                 # stop, target, time stop, rug alarm
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --token MINT --above 0.0081
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --token MINT --below 0.0070
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --token MINT --pct 15       # 15 % either way from now
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --token MINT --at 23:30     # a reminder (your time zone)
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --token MINT --liq-drop 25  # liquidity down 25 % from now
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                           # rings what hit, once
python3 "${CLAUDE_SKILL_DIR}/alerts.py" watch --every 30                # check until everything rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote MINT --write              # price and liquidity now
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clear --token MINT
```

Other flags: `--symbol`, `--chain`, `--note`, `--now "2026-11-01 21:58"`,
`--offline FILE` (a saved DexScreener answer), `--json`.

## What it reads and writes

| source / file | what |
| --- | --- |
| DexScreener `tokens/v1/{chain}/{up to 30}` | price, pool liquidity, market cap, changes, per coin (its most liquid pool) |
| Jupiter `price/v3` | SOL's price, for the SOL amounts |
| `meme/plan.json` | for `--from-plan`: stop, target, flat-by time |
| `meme/portfolio.json` | coins you hold are always quoted |
| `meme/alerts.json` | the alerts and when each rang (example: `alerts.example.json`) |
| `meme/prices.json` | every quote with its time; meme-budget and meme-risk use one under 3 minutes old |

## The alerts

| kind | rings when |
| --- | --- |
| `stop` / `below` | the price is at or under the level |
| `target` / `above` | the price is at or over the level |
| `pct` | the price moved that many percent either way from when you added it |
| `time` | the clock passed the time (the time stop: get out, win or lose) |
| `liq_drop` | the pool's liquidity fell that many percent from when you added it (the rug alarm, 30 % with `--from-plan`) |

Each alert rings once and stays in the file with when and at what price.
The prices are the last trade on DexScreener, checked when you run it: not a
tick-by-tick feed, and a fast coin can be well past the level by the time it
rings. That is why the stop text says "get out now, no second thoughts".

## Steps

1. Right after a fill (paper or live): `alerts.py add --from-plan`. Read
   back the four alerts.
2. Keep `alerts.py watch --every 30` running in the background, or a `/loop`
   with `alerts.py check`, while the trade is open. Only Claude's check
   rings; there is no push to the phone from this tool.
3. When one rings, say it and what it means:
   - STOP or TIME STOP: get out now, in the user's app, or `/meme-broker
     flatten`. Then record it: `ticket.py fill ... --reason stop|time`.
   - TARGET: take it. Same steps, `--reason target`.
   - RUG ALARM: the pool is draining. If the user holds the coin, get out
     now; there may be nobody to sell to soon.
4. After the trade: `alerts.py clear --token MINT`.

## Example: the reel

The GATO plan of Sunday 2026-11-01 (entry 0.0077889 at 21:58):

```
Added: stop GATO at or below $0.0074560
Added: target GATO at or above $0.0087878
Added: time stop GATO at 22:58
Added: rug alarm GATO: pool liquidity down 30% from $278,504
```

What GATO did in that hour (the real 1-minute bars, and 30 DexScreener
snapshots two minutes apart in `tests/fixtures/meme-alerts/`): it never
reached the stop (the low was 0.0076998 at 22:08) and never reached the
target (the high was 0.0085188 at 22:35). Nothing rang until the clock:

```
TIME STOP 22:58: it is 22:58. If GATO is still open, get out now, win or lose: /meme-broker flatten.
```

The 22:57 bar closed at 0.0082146: +5.46 % from the entry, +1.28R before
costs, about +0.67R after the plan's 2.6 % (roughly +$6.50 on the $250).
So the trade meme-risk blocked would have made a small profit this time.
One trade proves nothing either way: the 35 real trades of the same rule
before it averaged -0.45R after costs, and that is the number the edge
check looks at.

## Rules

- Each alert rings once. Say the price and the time it rang at.
- A stop that rang means get out. Never move it, never "give it a minute".
- DexScreener prices are free and can lag. The app's price is the one that fills.

## What it never does

It never buys or sells, never moves a stop, never places a stop order for
you, and never calls a price real time.

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
