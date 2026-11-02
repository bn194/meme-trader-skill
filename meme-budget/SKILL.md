---
name: meme-budget
description: >-
  Budget Manager. Sizes every meme coin buy to your budget and your max loss
  per trade, with the costs inside the loss. Reads the plan from meme-exit
  (entry, stop, target), finds the dollar amount that fits six limits (max
  loss at the stop INCLUDING the app's fee with its minimum, slippage and the
  pool's fee and price impact; position cap; max order; cash after your
  buffer; a share of the pool's liquidity; price impact per side), says
  which limit decided it, compares what the same trade costs in each app
  (Jupiter, Phantom, Fomo), shows it in euros, keeps the test phase cap,
  can measure the pool's real round trip with two Jupiter quotes, and writes
  ONE buy to meme/orders.json: dollars, the SOL to pay, slippage, and a
  Jupiter quote request. A stop too far for your max
  loss is a refusal, not a smaller trade. Nothing is bought. Use when the
  user says "how much should I buy", "size this trade", "I have 100 euros",
  "I only want to risk 3 euros", "wie viel soll ich kaufen", "mein budget
  ist", "welche app ist am billigsten", "set my rules", or after
  /meme-timemachine.
argument-hint: "[--quote] [--price X]"
---

# meme-budget

The Budget Manager turns a plan ("buy GATO at 0.0077889, stop 0.0074560")
into one exact buy ("$33 of GATO, 0.3503 SOL"), inside rules the user sets
once. The stop and the costs decide the size: the further the stop and the
higher the costs, the smaller the buy. It writes a proposal only. meme-risk
checks it and meme-broker asks the user yes or no.

Sizing to a max loss keeps each loss small. It does not make a trade win,
and on a meme coin the loss can be bigger than planned: a coin can gap
through the stop, or the pool can empty.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                  # meme/plan.json + meme/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write          # write meme/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --quote --write  # measure the pool's round trip with Jupiter first (Solana)
python3 "${CLAUDE_SKILL_DIR}/size.py" --json
```

Other flags: `--price X` (a fresh price; only a higher one changes the
size), `--liquidity USD`, `--sol-price USD`, `--roundtrip PCT
--roundtrip-usd USD` (a measured round trip), `--eur-usd RATE` (default: EURC
on Jupiter), `--plan FILE`, `--config FILE`, `--now "2026-11-01 21:58"`.

## What it reads and writes

| source / file | what |
| --- | --- |
| `meme/config.json` | the rules (start from `config.example.json` in this folder) |
| `meme/plan.json` | the trade from meme-exit |
| `meme/prices.json` | a fresh price (under 3 minutes) above the plan's entry means a bigger risk; SOL's price |
| `meme/safety.json` | the pool's liquidity and age from meme-analyst |
| `meme/portfolio.json` | its cash caps the size (meme-broker keeps it) |
| `meme/state/broker.json` | how many real buys so far: the test phase cap holds for the first 20 |
| Jupiter `lite-api.jup.ag` | with `--quote`: SOL -> coin -> SOL quotes for this size (read only); SOL's price |
| `meme/orders.json` | the one proposed buy, with `--write` |

## Step 1: set the rules once

If `meme/config.json` does not exist, copy `config.example.json` into
`meme/config.json` and ask the user for each value in plain words:

The example is sized for **100 euros** (the tools count in dollars, 1 EUR is
about 1.11 USD, and `"currency": "EUR"` adds a euro line):

- **budget_usd** (111, about 100 EUR): how much money this is for. Only money they can afford to lose completely.
- **max_loss_per_trade_usd** (3.30, about 3 EUR): the most one trade may lose at the stop, costs included.
- **cash_buffer_pct** (10), **max_position_pct** (30), **max_order_usd** (33, about 30 EUR), **min_order_usd** (10).
- The test phase: **testphase_trades** (20) real trades capped at **testphase_max_order_usd** (22, about 20 EUR),
  until /meme-journal shows they paid after costs (**testphase_min_profit_factor** 1.2). Only while `paper` is false.
- The day limits meme-risk enforces: **max_daily_loss_usd** (11, about 10 EUR), **max_trades_per_day** (4),
  **max_open_positions** (2), **losing_streak_pause** (2 losers in a row) and **pause_minutes** (120),
  **min_reward_risk** (1.0, after costs), **require_stop**, **require_edge** (the time machine must show a
  positive average R after costs), optional **no_entries_before** / **no_entries_after** (no 3 a.m. trades).
- The coin rules: **min_liquidity_usd** (50,000), **min_pool_age_hours** (6), **max_pct_of_liquidity** (0.5),
  **max_price_impact_pct** (1.0), and the holder limits meme-analyst checks.
- The costs: **venue** (phantom) and **venues**, a fee profile per app: phantom 0.85 %, jupiter 0.1 %
  (assumed: check the fee line on jup.ag), fomo 0.5 % with a $0.95 minimum. The venue's profile wins over a
  plain **fee_pct** / **fee_min_usd**. Then **slippage_pct** (0.3), **pool_fee_pct** (0.5), **slippage_bps**
  (150, the tolerance on the ticket), **pay_with** (SOL or USDC).
- **timezone** (Europe/Berlin), **chains** (["solana"]), **blocked** (coins they never want to trade).
- Keep **paper** true until they have watched it work for a while.

## Step 2: size the trade

The size is the smallest of six limits, in whole dollars:

| limit | dollars |
| --- | --- |
| max loss | the most where (risk % x size) + all costs <= `max_loss_per_trade_usd` |
| position cap | budget x `max_position_pct` |
| max order | `max_order_usd` |
| cash | budget (or the portfolio's cash) minus the buffer |
| liquidity | the pool's liquidity x `max_pct_of_liquidity` |
| price impact | the most where the estimated impact a side <= `max_price_impact_pct` |
| test phase | `testphase_max_order_usd` while live, until /meme-journal says the first `testphase_trades` real trades PASSED (it stays after a FAILED) |

**The costs** for a size: the app's fee each way (`fee_pct`, never less
than `fee_min_usd`), slippage each way (`slippage_pct`), and the pool: its
fee plus the price impact of a constant-product pool, `size / (liquidity / 2
+ size)`, each way. With `--quote` (or `--roundtrip`), the pool part is the
real round trip Jupiter quotes for SOL -> coin -> SOL at this size, which is
what the pool will actually charge right now. The fee minimum matters: on a
$20 buy, $0.95 is 4.75 % a side.

**The entry** it sizes at: the plan's, or a fresh price from
`meme/prices.json` if it is higher. A price that ran up means a bigger loss
at the same stop. It refuses (no order, one line why) when the size is $0,
under the minimum order, reward:risk after costs is under the minimum, the
price is already at the stop or the target, the plan is older than
`max_plan_age_minutes` (10: meme coins move fast), the coin is blocked, the
chain is not allowed, or the pool's liquidity is unknown.

## Step 3: show the user

Show the limits, which one decided, the dollars, euros and SOL, the costs
split into fees, slippage and pool, the loss at the stop and the gain at the
target after costs, and what the same trade would cost in the other apps.
Point out the cheapest app when it is not the user's. Say that a stop is a
plan, not a promise. Then hand over to `/meme-risk`.

**Why the app matters with 100 euros.** Fomo's $0.95 minimum fee is 2.9 % of
a $33 buy, each way. The same trade costs $2.43 at Fomo, $1.08 at Phantom and
$0.60 at Jupiter: with Fomo the costs alone eat most of a winning trade.

## Example: the reel

GATO, Sunday 2026-11-01 at 21:58: entry 0.0077889, stop 0.0074560 (4.28 %),
target 0.0087878 (3R). The example config (100 EUR, about 3 EUR max loss,
Phantom). Jupiter measured the pool's round trip for 2.7 SOL ($254) at
1.213 %. SOL $94.20, 1 EUR = 1.1132 USD.

```
GATO: entry $0.0077889 (the plan's entry), stop $0.0074560, target $0.0087878; risk 4.28% a token, reward 12.82%.
  limit         size       the math
  max loss      $43.00     loss at the stop incl. costs <= $3.30
  position cap  $33.00     30% of $111.00   <- decides it
  max order     $33.00     your max order
  cash          $99.00     $99.90 cash after the 10% buffer
  liquidity     $1,392.00  0.5% of the pool's $278,503.92
  price impact  $100.00    impact <= 1% a side
Buy $33.00 of GATO with 0.3503 SOL. Costs about $1.08 (3.28%): Phantom fees $0.55, slippage $0.19, pool $0.34 (measured round trip 1.03%).
At the stop: -$2.49. At the target: +$3.15. Reward:risk after costs 1.26. Flat by 22:58.
Same trade at each app: Jupiter $0.60 (1.81%), Phantom $1.08 (3.28%), Fomo $2.43 (7.37%). Cheapest: Jupiter.
In euros (1 EUR = 1.1132 USD): buy 29.64 EUR, -2.24 EUR at the stop, +2.83 EUR at the target.
```

On a live account in the test phase the cap is $22 instead (`test phase
$22.00  real trade 1 of 20 in the test phase  <- decides it`).

It writes:

```json
{"chain": "solana", "venue": "phantom", "side": "buy", "token": "HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump",
 "symbol": "GATO", "amount_usd": "33.00", "pay_with": "SOL", "slippage_bps": 150, "amount_in": "0.3503",
 "jupiter_quote": {"inputMint": "So11111111111111111111111111111111111111112",
                   "outputMint": "HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump", "amount": "350309918", "slippageBps": 150},
 "why": "range breakout on GATO: $33.00, bound by your position cap ($2.49 at the stop incl. $1.08 of costs)",
 "plan": {"entry": 0.007788948492760063, "stop": 0.007456, "target": 0.0087878, "max_loss": 2.49, "...": "..."}}
```

`why` and `plan` are notes for meme-risk and meme-broker.

## Rules

- Proposals only. This skill never touches a wallet or an app.
- Never size money the user has not said is for this. Ask for the budget and the max loss.
- Every number comes from the config, the plan, the prices or a quote. Nothing is guessed.
- No projections: never say what a trade will make. A target is a plan, not a forecast.

## What it never does

It never buys, approves or schedules a trade, never raises a limit on its
own, never shrinks a stop to fit a bigger buy, and never sizes leverage.

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
