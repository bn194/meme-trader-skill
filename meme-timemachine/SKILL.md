---
name: meme-timemachine
description: >-
  Time Machine. Replays every possible outcome of a meme coin trade before
  you risk a dollar: 10,000 simulated next hours plus every past time the
  same setup fired on that coin. Takes the plan from meme-exit (entry, stop,
  target, time stop), rebuilds the next 60 minutes 10,000 times from the
  coin's own 1-minute bars of the last 3 days (in 10-minute blocks, so
  bursts and streaks survive), and re-runs the same rule on every past range.
  Prints the odds of target first, stop first, or neither by the time stop,
  where the price sits then, the average R before AND after costs, the real
  history, and one honest verdict that weighs the costs, then hands off to
  /meme-budget. Use when the user says "run the time machine", "replay this
  trade", "what are the odds", "simulate this trade", "monte carlo",
  "backtest this setup", "lohnt sich der trade", "wie stehen die chancen",
  "is this a coin flip", or after /meme-exit writes a plan, before
  /meme-budget.
argument-hint: "[--days 3] [--block 10] [--replays 10000] [--seed 19]"
---

# meme-timemachine

The Time Machine sits between the plan and the money. meme-exit has set the
entry, the stop, the target and the time stop. Before anything is sized,
this skill asks one question: if the next hour of this coin plays out like
its last three days, how often does this plan hit the target first, the stop
first, or neither? And after the fees, does it pay at all?

It is a simulation built from the coin's own recent bars, not a prediction.
A rug, a dev wallet selling or a listing can do what those three days never
did. Most people who trade meme coins lose money, and a good-looking replay
does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                 # meme/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write         # + meme/timemachine.json (meme-risk reads it)
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --days 2 --block 15
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart               # text fan chart of the saved run
```

Other flags: `--plan FILE`, `--replays N`, `--seed N` (19), `--minutes N`
(default: the plan's time stop), `--offline FILE` (saved 1-minute bars).

## What it reads and writes

| source / file | what |
| --- | --- |
| `meme/plan.json` | the plan from meme-exit: coin, entry, entry time, stop and its rule, target and its R, costs, time stop, range |
| Jupiter `datapi.jup.ag/v2/charts` | Solana: 1,000 one-minute bars a request, paged back 3 days (unofficial, free) |
| GeckoTerminal `ohlcv/minute` | other chains, by pool |
| `meme/timemachine.json` | with `--write`: `{plan, mc, history, verdict, notes, pool}`; `mc` holds the odds, the percentiles, the fan bands and 160 sample paths |

## How it works

1. **The pool.** Every completed 1-minute bar of the last `--days` (3)
   before the entry. Each bar becomes four ratios to the close before it:
   open, high, low and close. At least one day of bars, or it refuses: the
   coin is too new to replay fairly.
2. **One replay.** Start at the entry. Draw the next minutes in blocks of
   `--block` (10) consecutive real minutes, each block from a random place
   in the pool, scaled to the current price. Blocks keep what makes meme
   coins meme coins: bursts, streaks and sudden flushes. Bar by bar it
   checks the stop first, then the target. A bar that touches both counts as
   the stop. A minute that opens below the stop (a gap) still counts as -1R,
   and it says how many did: a real fill would be worse.
3. **10,000 replays** give: target first, stop first, neither (still open at
   the time stop), green (target first, or above the entry at the time
   stop), green after costs, the price at the time stop (median and the 5 to
   95 % range), and the average R before and after costs. Costs in R = the
   plan's round trip % / its risk %; every trade pays them.
4. **The history.** The plan's own rule (the same range length, volume bar,
   wait, stop rule, target R and time stop) runs on every non-overlapping
   range in those 3 days. That is what really happened, not a simulation.
5. **The verdict** looks at the replays that hit a side and asks how often
   the target came first, against the break-even AFTER costs:
   (1 + costs in R) / (1 + target R). At 3R with costs of 0.61R that is
   40.2 %, not the 25 % a fee-free world would need. Less than 5 points
   from it: "Close to break-even after costs". 5 to 15: "Leans toward the
   target / stop". 15 or more: "Strongly toward". Under it: a line when over
   40 % hit neither, a line when the average R after costs points the other
   way, and always the line that says what the costs take.

**The seed.** `random.Random(seed)`, 19 by default: same plan, same bars,
same seed, same numbers on any machine. Say the seed with every result.

**meme-risk reads this run.** With `require_edge` on (the example config),
a trade whose replay shows a negative average R after costs is blocked.

## Steps

1. Make sure `meme/plan.json` is the plan from `/meme-exit` just now.
2. `timemachine.py run --write`.
3. Tell the user, in this order: the odds, the price at the time stop, the
   average R before and after costs, the history line, then the verdict and
   every line under it exactly as printed. Say the seed.
4. If the verdict leans toward the stop or the average R after costs is
   negative, say so plainly: on this coin's recent bars this plan lost money
   after costs. Do not dress it up, and do not hunt for parameters until it
   looks good (that is curve fitting).
5. Say once that this is built from the last 3 days and is not a prediction.
6. If the user still wants the trade, hand off to `/meme-budget`.

## Example: the reel

GATO, Sunday 2026-11-01: entry 0.0077889 at 21:58, stop 0.0074560 (range
low, 4.28 %), target 0.0087878 (3R), time stop 22:58.

```
10,000 replays of the next 60 minutes (21:58 to 22:58 Europe/Berlin), drawn in 10-minute blocks from GATO's own 1-minute bars
of the last 3.0 days (4,312 bars), seed 19.
  plan: entry $0.0077889, stop $0.0074560 (-4.28 %), target $0.0087878 (3R)
  target first    12.1 %
  stop first      44.1 %
  neither         43.7 %   still open at 22:58 (the time stop)
  green           45.2 %   target first, or above the entry at 22:58
  green after costs  34.0 %
  Price at 22:58: median $0.0078366, 90 % of replays between $0.0069821 and $0.0088299.
  Average R: +0.221 before costs, -0.387 after costs.
History: the same rule on the last 3.0 days of real bars (120 ranges) fired 35 times: 3 target, 11 stop, 21 neither. Average R +0.032 before costs, -0.446 after.
Strongly toward the stop: target first in 21.5 % of the decided replays, break-even after costs is 40.2 %.
43.7 % of the replays hit neither by the time stop; the price then decides those.
Costs take 0.61R a trade (2.60 % round trip on a 4.28 % risk).
```

Before costs this setup was slightly positive on GATO (+0.22R replayed,
+0.03R in 35 real trades). After costs it lost 0.39R and 0.45R a trade.
That is the honest answer, and it is what the user hears before
/meme-budget, and what meme-risk blocks on.

## Rules

- Every number comes from the run. Never round a loser up into an edge.
- Repeat the verdict and the lines under it; do not rewrite them.
- Always give the after-costs numbers next to the before-costs ones.
- Simulated odds are not predictions and not promises. Say it once, plainly.
- Always say the seed. One plan per run: a changed plan is a new run.

## What it never does

It never buys, sizes or changes the plan, never calls a result a sure thing,
never uses a bar that has not closed, and never mixes bars from after the
entry into the pool.

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
