---
name: meme-broker
description: >-
  Order Executor. Turns an approved meme coin trade into a ticket you can
  act on, paper by default, never without your yes. Shows each order as a
  plain ticket (the coin, its contract address to paste, dollars and SOL,
  max slippage, stop, target, time stop and the max loss at the stop),
  records your yes word for word ("yes" or "ja", one order at a time), then
  either fills it on paper at the live price minus the costs, or (live)
  tells you exactly what to do in Fomo, Phantom or Jupiter yourself and
  records what you got. Checks a Solana buy against a live Jupiter quote
  (read only), builds the sell that gets you out at the stop, the target or
  the time stop, records fills with the profit or loss, and keeps the log
  meme-risk uses for the daily loss limit and the losing-streak pause. It
  never touches a wallet or a key. Use when the user says "buy it", "place
  the order", "execute", "kauf", "verkauf", "get me out", "flatten",
  "close my position", "paper trade", "how do I do it in Fomo", or after
  /meme-risk passes.
argument-hint: "[order number]"
---

# meme-broker

The Order Executor is the only skill in this pack that leads to a trade, so
it is the strictest. A trade happens only after three separate gates, every
time, for every order:

1. **meme-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **Paper** (the default): meme-broker fills it at the live price minus the
   costs, no money moves. **Live**: the user makes the trade themselves, in
   their own app, and reports what they got.

There is no wallet connection and no key anywhere in this pack, on purpose.
A meme coin trading bot with your private key can empty your wallet in one
bad call. You press the button in your own app.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                        # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" paper --index 1              # paper: fill at the live price
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --tokens 32010.4 --price 0.0078102 --tx SIG
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --token MINT --price 0.007456 --reason stop
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --token MINT         # a sell-everything order, through meme-risk again
python3 "${CLAUDE_SKILL_DIR}/ticket.py" quote --index 1              # Jupiter, read only
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`--now "2026-11-01 21:58"` pins the clock (your time zone).

## What it reads and writes

| file | what |
| --- | --- |
| `meme/orders.json` | the proposed orders (meme-budget writes it; `flatten` replaces it) |
| `meme/state/risk.json` | meme-risk's verdicts; only a PASS from today is READY |
| `meme/state/broker.json` | every yes, no, placed, failed, denied and fill, with each buy's max loss and each sell's profit or loss |
| `meme/portfolio.json` | cash and coins, updated by `paper`, `result` and `fill` |
| `meme/config.json` | `paper`, `venue`, `timezone`, the cost model |

## The yes

`approve` records the reply word for word and accepts it only if it starts
with "yes", "y", "ja" or "j". It refuses: "ok", "sure", "mach", "go"; "yes
to all", "ja, alle"; a yes with a doubt or a condition ("ja, aber...", "yes
if it dips"); a question; a yes that names another coin or another amount
("yes, buy 100" for a $250 order). Never turn a reply into a yes yourself.
One order per question. Never offer "yes to all".

## Paper (the default)

After the yes, `ticket.py paper --index N` fills the buy at the live
DexScreener price (or `--price`), minus the app's fee, slippage and the
pool's fee, so paper results carry the same costs as real ones. A sell
(`fill` or a flattened order) does the same on the way out and logs the
profit or loss. Watch it work on paper for a while before going live.

## Live: the user trades in their own app

The yes prints the steps for the user's venue (`venue` in the config):

1. Search by the **contract address**, pasted. Never by name: copies with
   the same name and logo are everywhere.
2. Check the ticker and that it is the pool DexScreener shows.
3. Buy the ticket's dollar amount (or SOL amount). Set the max slippage if
   the app lets you.
4. Report the fill: `ticket.py result --index N --status placed --tokens Q
   --price P --tx SIG`. A failed swap: `--status failed --note ...`. Not
   retried without a new check and a new yes.
5. If the price ran well past the plan's entry before the user got there:
   do not chase it. Skip it and say so.

Fomo (fomo.family) is a mobile app for Solana meme coins: 0.5 % a trade with
a $0.95 minimum, network fees covered by the app (TechCrunch, November 2025;
check the app's current fees and which order types it offers before
relying on a stop order there). If the app has no stop order, `/meme-alerts`
rings at the stop and the user sells by hand. Phantom, Jupiter (jup.ag) and
pump.fun work the same way: paste the address, buy, report.

`ticket.py quote --index N` asks Jupiter (read only, no wallet) what the
order would get right now and the pool's round trip at this size. If it is
far above what meme-budget assumed, size again with `size.py --quote`.

## Getting out

- At the stop, the target or the time stop (`/meme-alerts` rings), the user
  sells in their app and records it: `ticket.py fill --token MINT --price P
  [--usd received] --reason stop|target|time|rug`.
- Or `ticket.py flatten --token MINT` writes a sell of everything held to
  `meme/orders.json`; `/meme-risk` (an exit is never blocked by a day
  limit), `show`, the user's yes, then `paper` or the user sells.
- Every closed trade's profit or loss goes into the log. Two losers in a row
  start meme-risk's pause (`losing_streak_pause`, `pause_minutes`).

## Example: the reel

The GATO buy at 21:58 was BLOCKED by meme-risk (the edge check), so with the
example config there was nothing to show:

```
ORDER 1 of 1, PAPER (simulated fills, no money), Fomo
  BUY $250.00 of GATO on Solana, paid with 2.6539 SOL, max slippage 1.5%
  contract  HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump   <- paste this address, never search by name
  plan: stop $0.0074560, target $0.0087878, flat by 22:58
  max loss about $17.62 at the stop incl. costs (a meme coin can gap through a stop: it can be worse)
  BLOCKED by meme-risk: edge: the time machine's average R after costs is -0.39 ...
```

With `"require_edge": false` the same order passed and was READY. "ok" and
"ja, aber nur 100" were not recorded; "ja" was. `ticket.py paper --index 1
--price 0.0077889` bought 31,679.7 GATO for $250.00 on paper.

## What it never does

- Never trades without all three gates, and never two trades on one yes.
- Never trades from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats a seed phrase, a private key or a password.
- Never switches `"paper"` to live. The user does that themselves.
- Never promises a fill price: a swap fills at whatever the pool gives.

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
