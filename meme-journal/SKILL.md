---
name: meme-journal
description: >-
  Trade Journal. Every real trade, what it cost and what it made, after
  fees: win rate, average profit and loss, expectancy in R, profit factor,
  the worst run down, best and worst trade, average hold, split by exit
  (stop, target, time stop), setup, app and hour of the day, live and paper
  kept apart. Reads meme-broker's log and trades you add by hand from your
  app. Runs the test phase: the first 20 real trades stay small (22 USD,
  about 20 EUR) until the journal shows they made money after costs; then it
  says PASSED or FAILED, and meme-risk keeps the cap on a FAILED. Use when
  the user says "how am I doing", "my stats", "trade journal", "lohnt sich
  das", "wie läuft es", "bin ich im plus", "test phase", "export my trades",
  "add a trade I made in Fomo", or after every closed trade.
argument-hint: "[stats | trades | testphase | add | export FILE] [--paper]"
---

# meme-journal

The Trade Journal answers the question every other skill can only guess
at: does this make money for you, with real fills, real fees and your real
reactions? The Time Machine replays the past; the journal counts the
present. Twenty trades are the minimum before the numbers mean much, and
that is why the first twenty real trades are small.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/journal.py"                    # live stats after costs + the test phase
python3 "${CLAUDE_SKILL_DIR}/journal.py" --paper            # paper trades, kept apart
python3 "${CLAUDE_SKILL_DIR}/journal.py" trades             # every closed trade, newest first
python3 "${CLAUDE_SKILL_DIR}/journal.py" testphase
python3 "${CLAUDE_SKILL_DIR}/journal.py" add --symbol WIF --token MINT --buy-usd 20 --sell-usd 23.50 \
    --opened "2026-11-02 14:05" --closed "2026-11-02 14:40" --max-loss 2 --reason target --venue phantom
python3 "${CLAUDE_SKILL_DIR}/journal.py" export trades.csv
```

`--json` on any command. Times are in your time zone (`timezone` in the config).

## What it reads and writes

| file | what |
| --- | --- |
| `meme/state/broker.json` | meme-broker's log: each buy (spent, tokens, max loss, setup, app, paper or live) and each sell (received, profit or loss, reason) |
| `meme/journal.json` | trades you add by hand (bought and sold outside the chain, in your app) |
| `meme/config.json` | `testphase_trades` (20), `testphase_max_order_usd` (22), `testphase_min_profit_factor` (1.2), `paper`, `timezone` |

A trade closes when everything bought is sold (partial sells add up). R =
the profit or loss divided by the max loss the plan allowed, so +1R means
you made what you were willing to lose.

## The test phase

While `paper` is false: the first `testphase_trades` real trades (20) are
capped at `testphase_max_order_usd` (22 USD, about 20 EUR) by meme-budget
and meme-risk. After the 20th closed real trade the journal decides:

- **PASSED** when those 20 trades made money in total, their expectancy is
  above 0R, and the profit factor (money won / money lost) is at least
  `testphase_min_profit_factor` (1.2). The cap lifts; a bigger size is still
  the user's decision and stays inside their other limits.
- **FAILED** otherwise. meme-risk keeps the cap. Say it plainly: after costs
  it did not pay. The honest options are a different setup (check it with
  `/meme-timemachine compare` and `multi` first), staying small, or stopping.

Paper trades never count toward the test phase.

## Steps

1. After every closed trade, run `journal.py` and read back the line that
   changed: the trade's result, the running total, and the test phase.
2. If the user traded in their app outside the chain, record it with `add`
   (what they paid, what they got back after the app's fee, the times, and
   the max loss they planned). Never guess numbers: ask.
3. Under 20 trades, say that luck dominates and the numbers are not yet a
   verdict. At 20, read the PASSED or FAILED line as printed.
4. Point to the weakest group (an hour, a setup, an app) when it is clear
   in the numbers, and say the sample size.

## Example

Two real trades closed and one on paper:

```
Live trades, after costs:
  2 closed (0 open): 1 winners, 1 losers, 50 % win rate
  total $1.00, average $0.50 a trade (winners $3.00, losers -$2.00)
  expectancy +0.25R, profit factor 1.50, worst run down -$2.00
  ...
  2 trades are too few to judge: luck dominates under about 20.
test phase: 2 of 20 real trades closed; orders stay at $22.00 or less
```

## Rules

- Numbers after costs only, from the log or from the user. Never estimate a fill.
- Live and paper are never mixed.
- Under 20 trades, never call anything a pattern.
- A PASSED test phase is not a promise about the next 20 trades.

## What it never does

It never trades, never changes the config, never lifts the cap by itself
(meme-risk reads the same rule), and never hides a losing trade.

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
