---
name: meme-exit
description: >-
  Exit Planner. Sets your stop, your target and your time stop before you
  buy a meme coin, and counts what a trade really costs: your app's fee
  (Phantom 0.85 % by default; Jupiter and Fomo profiles built in), slippage
  and the pool's fee, both ways, often 2 to 3.5 % a round trip. Reads the entry from meme-entry (or a
  price you give), puts the stop at the range low by default (or the range
  midpoint, your price, a percent, or a multiple of the ATR), rounds it down
  to 5 significant digits, sets the target at 3R, and shows reward:risk
  before and after costs. Refuses a stop at or above the entry, a target at
  or below it, or a stop closer than the round-trip costs. Optional partial
  take (sell half at 1.5R, stop to the entry) and trailing stop. Writes
  meme/plan.json for the Time Machine, the Budget Manager and Price Alerts.
  Long side only. Use when the user says "where's my stop", "set my stop and
  target", "plan the exit", "take profit", "wo setze ich den stop", "wann
  verkaufe ich", "stop loss", "what's my R", or right after /meme-entry
  triggers, before /meme-timemachine.
argument-hint: "[--stop range-low|range-mid|price:X|pct:X|atr:K] [--target 3R|2R|price:X|pct:X]"
---

# meme-exit

The Exit Planner decides how a trade ends before it starts. The stop is
where the setup has failed. The target is where you take what you came for.
The time stop is when you get out anyway. All three are set BEFORE the buy,
written down and handed on, so nobody decides anything in the middle of a
candle that is moving 5 % a minute.

On a meme coin the costs are part of the plan. Your app takes its fee
(`venue` in the config: Phantom 0.85 %, Jupiter about 0.1 %, Fomo 0.5 % with a
$0.95 minimum; check the fee line in your app), the pool takes its fee, the
price slips while the swap lands, and you pay all of it twice. With Phantom
that is about 3.3 % a round trip. A 2 % stop with a 4 % target loses money
even when it "works". This skill shows that before you trade.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                          # meme/entry.json: range-low stop, 3R target
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop range-mid --target 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:3              # needs the bars (online or --offline)
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --scale 1.5R:50 --trail 1R --write   # partial take and trailing stop
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --entry 0.0077889 --address MINT --symbol GATO --stop pct:5
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

Other flags: `--max-hold 60` (minutes), `--range-high X --range-low Y`,
`--now "2026-11-01 21:58"`, `--offline FILE`, `--json`.

## What it reads and writes

| file | what |
| --- | --- |
| `meme/entry.json` | the trigger from meme-entry: coin, entry price and time, range |
| `meme/config.json` | `venue` (phantom) and its profile in `venues` (fee and fee minimum), `slippage_pct` (0.3), `pool_fee_pct` (0.5), `max_hold_minutes` (60), `min_reward_risk` (1.0, a warning here; meme-risk enforces it) |
| `meme/plan.json` | with `--write`: entry, stop and its rule, target and its R, risk, costs, the after-costs numbers, flat by. meme-timemachine, meme-budget and meme-alerts read it |

## Stops, targets, time stop

| stop | where it goes |
| --- | --- |
| `range-low` | the range low (the default: wide enough to survive the costs) |
| `range-mid` | the range midpoint: tighter, so the costs weigh more |
| `price:X` | your price |
| `pct:X` | X percent under the entry |
| `atr:K` | K times the 14-bar ATR of the 1-minute bars up to the entry bar |

- **Rounding.** The stop rounds DOWN to 5 significant digits (away from the
  entry). The target rounds half up. Risk = entry minus stop. Target =
  entry + R x risk: `3R` by default, `2R`, `1.5R`, `price:X` or `pct:X`.
- **Costs.** Per side: your app's fee + slippage + pool fee (Phantom: 0.85 +
  0.3 + 0.5 = 1.65 %), twice for the round trip (3.3 %). After costs, the
  loss at the stop is risk + 3.3 % and the gain at the target is reward -
  3.3 %. Costs in R = 3.3 % / risk %: the share of every trade the costs eat.
  /meme-budget measures the real costs for your size and compares the apps.
- **Partial take and trailing stop** (optional, written into the plan for
  the Time Machine and the alerts): `--scale 1.5R:50` sells half at 1.5R and
  moves the stop to the entry; `--trail 1R` keeps the stop 1R under the
  highest price since the entry. On an app with a fee minimum the partial
  sale pays one more minimum.
- **Refused, with the reason.** A stop at or above the entry. A target at
  or below it. A stop closer than the round-trip costs (fees alone would be
  more than the risk). An entry that has not triggered (unless `--entry`).
- **Time stop.** `max_hold_minutes` (60) after the entry: out by then, win
  or lose. Meme coin momentum fades fast, and a dead trade ties up money.

## Steps

1. Run it right after `/meme-entry` triggers. Before that, `--entry PRICE`
   plans ahead.
2. Use the default (range low, 3R) unless the user names another. A level
   setup needs a stop: ask.
3. `exit.py plan --write`. Read back the entry, stop, target, risk, the
   costs and the after-costs reward:risk, and the flat-by time.
4. If it warns that reward:risk after costs is under the minimum, say so:
   meme-risk will block it. Never loosen anything on your own.
5. Say once that a stop is a plan, not a guarantee: a meme coin can gap
   through it, or have no buyers there.
6. Hand off to `/meme-timemachine`, then `/meme-budget`. Offer `/meme-alerts`.

## Example: the reel

GATO, Sunday 2026-11-01. Entry 0.0077889 at 21:58 (the 21:57 bar), range
0.0074560 to 0.0077195. `exit.py plan --write`:

```
Exit plan: GATO long, Sun 2026-11-01, 15-minute range breakout on 1-minute bars
  Entry         $0.0077889 at 21:58 (the 21:57 bar)
  Stop          $0.0074560  range low, rounded down
  Target        $0.0087878  3R (3 times the risk)
  Risk          $0.00033295 a token, 4.28% of the entry
  Reward:risk   3.00 before costs
  Costs         about 3.30% a round trip: Phantom fee 0.85% + slippage 0.30% + pool 0.50%, each way
  After costs   -7.58% at the stop, +9.52% at the target: reward:risk 1.26 (costs eat 0.77R)
  Flat by       22:58 Europe/Berlin (60 minutes), win or lose
```

With `--stop range-mid` it refuses: that stop would sit 2.58 % under the
entry, less than the 3.30 % a round trip costs. With `--target 2R` the
after-costs reward:risk falls to 0.69, under the 1.0 minimum, and it warns
that meme-risk will block it. With the Fomo profile the round trip is 2.6 %
(its 0.5 % fee is lower, but its $0.95 minimum makes small buys far dearer;
/meme-budget shows that in dollars). That is why the defaults are a wide
stop and a far target.

## Rules

- The stop, the target and the time stop are set before the entry, never after.
- Never move a stop further from the entry once the trade is on.
- Always show the costs and the after-costs reward:risk next to the plain ones.
- Nothing here promises a winning trade. A 3R target is not a prediction.
- Long side only.

## What it never does

It never buys or sells, never sizes a position, never widens a stop to make
a plan pass, and never calls a stop a guarantee.

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
