---
name: meme-budget
description: >-
  Budget Manager. Sizes every meme coin buy to your budget and your max loss
  per trade, with the costs inside the loss. Reads the plan from meme-exit
  (entry, stop, target), finds the dollar amount that fits six limits (max
  loss at the stop INCLUDING the app's fee with its minimum, slippage and the
  pool's fee and price impact; position cap; max order; cash after your
  buffer; a share of the pool's liquidity; price impact per side), says
  which limit decided it, can measure the pool's real round trip with two
  Jupiter quotes, and writes ONE buy to meme/orders.json: dollars, the SOL to
  pay, slippage, and a Jupiter quote request. A stop too far for your max
  loss is a refusal, not a smaller trade. Nothing is bought. Use when the
  user says "how much should I buy", "size this trade", "I have $1,000", "I
  only want to risk $20", "wie viel soll ich kaufen", "mein budget ist",
  "set my rules", or after /meme-timemachine.
argument-hint: "[--quote] [--price X]"
---

# meme-budget

The Budget Manager turns a plan ("buy GATO at 0.0077889, stop 0.0074560")
into one exact buy ("$250 of GATO, 2.6539 SOL"), inside rules the user sets
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
--roundtrip-usd USD` (a measured round trip), `--plan FILE`, `--config FILE`,
`--now "2026-11-01 21:58"`.

## What it reads and writes

| source / file | what |
| --- | --- |
| `meme/config.json` | the rules (start from `config.example.json` in this folder) |
| `meme/plan.json` | the trade from meme-exit |
| `meme/prices.json` | a fresh price (under 3 minutes) above the plan's entry means a bigger risk; SOL's price |
| `meme/safety.json` | the pool's liquidity and age from meme-analyst |
| `meme/portfolio.json` | its cash caps the size (meme-broker keeps it) |
| Jupiter `lite-api.jup.ag` | with `--quote`: SOL -> coin -> SOL quotes for this size (read only); SOL's price |
| `meme/orders.json` | the one proposed buy, with `--write` |

## Step 1: set the rules once

If `meme/config.json` does not exist, copy `config.example.json` into
`meme/config.json` and ask the user for each value in plain words:

- **budget_usd**: how much money this is for. Only money they can afford to lose completely.
- **max_loss_per_trade_usd** (20): the most one trade may lose at the stop, costs included.
- **cash_buffer_pct** (10), **max_position_pct** (25), **max_order_usd** (250), **min_order_usd** (20).
- The day limits meme-risk enforces: **max_daily_loss_usd** (60), **max_trades_per_day** (3),
  **max_open_positions** (2), **losing_streak_pause** (2 losers in a row) and **pause_minutes** (120),
  **min_reward_risk** (1.0, after costs), **require_stop**, **require_edge** (the time machine must show a
  positive average R after costs), optional **no_entries_before** / **no_entries_after** (no 3 a.m. trades).
- The coin rules: **min_liquidity_usd** (50,000), **min_pool_age_hours** (6), **max_pct_of_liquidity** (0.5),
  **max_price_impact_pct** (1.0), and the holder limits meme-analyst checks.
- The costs: **venue** (fomo), **fee_pct** (0.5), **fee_min_usd** (0.95), **slippage_pct** (0.3),
  **pool_fee_pct** (0.5), **slippage_bps** (150, the tolerance on the ticket), **pay_with** (SOL or USDC).
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

Show the six limits, which one decided, the dollars and the SOL, the costs
split into fees, slippage and pool, the loss at the stop and the gain at the
target after costs. Say that a stop is a plan, not a promise. Then hand over
to `/meme-risk`.

## Example: the reel

GATO, Sunday 2026-11-01 at 21:58: entry 0.0077889, stop 0.0074560 (4.28 %),
target 0.0087878 (3R). The example config: $1,000, $20 max loss. Jupiter
measured the pool's round trip for 2.7 SOL ($254) at 1.213 %. SOL $94.20.

```
GATO: entry $0.0077889 (the plan's entry), stop $0.0074560, target $0.0087878; risk 4.28% a token, reward 12.82%.
  limit         size       the math
  max loss      $282.00    loss at the stop incl. costs <= $20.00
  position cap  $250.00    25% of $1,000.00   <- decides it
  max order     $250.00    your max order
  cash          $900.00    $900.00 cash after the 10% buffer
  liquidity     $1,392.00  0.5% of the pool's $278,503.92
  price impact  $901.00    impact <= 1% a side
Buy $250.00 of GATO with 2.6539 SOL. Costs about $6.94 (2.78%): Fomo fees $2.45, slippage $1.47, pool $3.02 (measured round trip 1.21%).
At the stop: -$17.62. At the target: +$25.12. Reward:risk after costs 1.43. Flat by 22:58.
```

It writes:

```json
{"chain": "solana", "venue": "fomo", "side": "buy", "token": "HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump",
 "symbol": "GATO", "amount_usd": "250.00", "pay_with": "SOL", "slippage_bps": 150, "amount_in": "2.6539",
 "jupiter_quote": {"inputMint": "So11111111111111111111111111111111111111112",
                   "outputMint": "HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump", "amount": "2653863016", "slippageBps": 150},
 "why": "range breakout on GATO: $250.00, bound by your position cap ($17.62 at the stop incl. $6.94 of costs)",
 "plan": {"entry": 0.007788948492760063, "stop": 0.007456, "target": 0.0087878, "max_loss": 17.62, "...": "..."}}
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
