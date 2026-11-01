---
name: meme-risk
description: >-
  Risk Manager. Checks every meme coin trade against your limits and stops
  anything over them before it can reach your yes. The coin: the analyst's
  verdict (no AVOID, under an hour old), pool liquidity and age, price
  impact and your share of the pool. The trade: a stop, the loss at the
  stop INCLUDING fees, slippage and pool costs under your max loss,
  reward:risk after costs, and the Time Machine's edge after costs. The day:
  daily loss limit, trades per day, open positions, a pause after a losing
  streak (no revenge trades), no second buy of the same coin, optional entry
  hours. The basics: format, chain, leverage and perps, blocked coins, size,
  position cap, cash buffer, orders per day. Getting out is never blocked by
  a day limit. Prints PASS or BLOCK with the reason and records it so
  meme-broker only shows what passed. Use when the user says "check my
  order", "is this safe", "risk check", "can I take this trade", "prüf den
  trade", "darf ich kaufen", "how much have I risked today", or before
  /meme-broker, always.
argument-hint: "[path to orders.json]"
---

# meme-risk

The Risk Manager is the gate between a proposal and your yes. Every order
written by meme-budget or meme-broker's flatten passes through it. A BLOCK
is final for that order: it is not shown for a yes. These limits keep each
loss and each day's losses small, keep you out of coins that can take your
money by contract, and keep you from trading setups that lost money after
costs. They do not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                        # meme/ files; writes meme/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write             # look without recording
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-01 21:58"
```

## What it reads and writes

| file | what |
| --- | --- |
| `meme/orders.json` | the proposed orders (meme-budget, or meme-broker's flatten) |
| `meme/config.json` | the limits (meme-budget ships `config.example.json`) |
| `meme/safety.json` | meme-analyst's verdicts, with their time |
| `meme/timemachine.json` | the last replay, matched to the exact plan |
| `meme/portfolio.json` | cash and holdings; if missing, a fresh paper account funded with the budget |
| `meme/prices.json` | a fresh price (under 3 minutes) raises the entry it measures risk from |
| `meme/state/broker.json` | today's trades and their max losses, closed trades for the streak |
| `meme/state/risk.json` | the verdicts it writes, with a fingerprint of each exact order |

## Entries and exits

An **entry** is a buy. An **exit** only sells what you hold. Getting out
must always be possible, so an exit is checked for format and "do you hold
it" only; every other rule turns into a warning for an exit, never a BLOCK.

## The checks

Orders are checked in file order, as if each passed order had filled.

| check | blocks when |
| --- | --- |
| format | side not buy or sell; the token not a contract address; a buy without `amount_usd` as a positive string; a sell without `tokens`; `slippage_bps` outside 1 to 5000 (over 300 warns: a sandwich bot can take it all) |
| chain | the chain is not in `chains` |
| asset | leverage, perps or margin while `allow_leverage` / `allow_perps` are false |
| short | a sell of more than you hold |
| blocked | (entries) the coin is on `blocked` |
| safety | (entries) no meme-analyst report, an AVOID, an UNVERIFIED (while `require_safety`), or a report older than `safety_max_age_minutes` (60). CAUTION warns |
| liquidity | (entries) pool liquidity under `min_liquidity_usd`, or the buy over `max_pct_of_liquidity` of the pool |
| impact | (entries) estimated price impact a side over `max_price_impact_pct` |
| age | (entries) the pool younger than `min_pool_age_hours` |
| stale | (entries) the plan older than `max_plan_age_minutes` (10) |
| stop | (entries) no stop while `require_stop`; a stop at or above the entry |
| loss | (entries) risk % x amount + all costs over `max_loss_per_trade_usd` |
| target, reward:risk | (entries) the price already at the target; reward:risk after costs under `min_reward_risk` |
| edge | (entries, with `require_edge`) no time machine run for this exact plan, or its average R after costs below 0. A negative real history warns |
| daily loss | (entries) the max losses of today's buys plus this one over `max_daily_loss_usd` |
| trades | (entries) `max_trades_per_day` buys already today |
| pause | (entries) `losing_streak_pause` losing trades in a row: no entries for `pause_minutes` after the last one |
| positions | (entries) `max_open_positions` other coins already held |
| window | (entries) before `no_entries_before` or after `no_entries_after` (your time zone; off by default) |
| size, position, cash | (entries) under the minimum or over the max order; over `max_position_pct` in one coin; less than the buffer left in cash |
| duplicate | (entries) the same coin bought twice in a batch or already today: a second buy after a stop is a revenge trade |
| daily limit | `max_orders_per_day` orders already today |

**The entry it measures from**: the plan's, or a fresh price from
`meme/prices.json` if it is higher. **The costs** are meme-budget's model:
the app's fee with its minimum, slippage, and the pool (estimated, or the
Jupiter round trip meme-budget measured). **The day** is your local day in
`timezone`. Warnings do not block but say them: CAUTION from the analyst, a
LIVE account, a wide slippage, a price too old to use.

## Steps

1. If the price may have moved, refresh it: `/meme-alerts quote MINT --write`.
2. Run `check.py`. Exit code 0: everything passed. 1: at least one BLOCK.
3. Tell the user order by order: the max loss at the stop with the costs,
   reward:risk after costs, the analyst's verdict, the time machine's edge,
   and how much of today's limits it uses. For a BLOCK, the reason and the
   honest fix (a closer stop from meme-exit, a smaller buy, wait for the
   pause to end, or skip the coin). Never change a limit yourself.
4. If the order changes in any way, check it again: meme-broker matches each
   order to its verdict by fingerprint, and yesterday's verdict does not count.

## Example: the reel

The GATO buy from meme-budget at 21:58 on Sunday 2026-11-01, a fresh $1,000
paper account, the example config:

```
BLOCK #1 buy $250.00 of GATO, entry
          entry 0.0077889 (the plan's entry), stop 0.0074560, target 0.0087878: risk 4.28%
          max loss $17.62 incl. $6.94 costs (limit $20.00), reward:risk 1.43 after costs (min 1)
          analyst: PASS, checked 0 minutes ago
          time machine: -0.39R after costs, history -0.45R over 35 trades
          today before this: 0 of 3 trades, $0.00 of $60.00 daily loss
        - edge: the time machine's average R after costs is -0.39 (history -0.45 over 35 real trades): this setup has lost money after costs on this coin's recent bars

0 passed, 1 blocked at 2026-11-01 21:58 Europe/Berlin. Cash after the passed orders: $1,000.00 (paper).
```

Every other check passed: a clean coin, a $17.62 max loss under the $20
limit, 1.43 after costs. The edge check stopped it: on GATO's last three
days this exact setup lost money once the fees were paid. With
`"require_edge": false` the same order passes, and meme-broker shows it on
paper.

## Rules

- A PASS only means the order may be shown to the user. It is not a yes and not a recommendation.
- Every number comes from the config, the order, the analyst, the time machine, the prices or the log.
- Free data can lag. The price your app fills at is the real one, and a stop can fill far worse.

## What it never does

It never buys or sells, never edits an order to make it pass, never loosens
a limit, never blocks a sell that only gets the user out, and never treats a
PASS as the user's yes.

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
