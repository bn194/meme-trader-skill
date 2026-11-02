---
name: meme-whales
description: >-
  Whale Tracker. Watches public Solana wallets: a coin's dev (creator)
  wallet, the big holders the analyst found, or any wallet you name. Every
  Solana transaction is public the second it lands, so it reads them
  straight from a Solana RPC node, turns each new one into a plain row (who,
  buy or sell or transfer, how many tokens of which coin, how much SOL) and
  alerts once per transaction. A dev wallet that sells or moves its own coin
  is flagged first, because that is how many rugs start. When two or more of
  your wallets buy the same coin within 30 minutes it rings a CLUSTER. Flags
  trades in coins you hold or watch, and imports a list of wallets (for
  example top traders from a public leaderboard). Read only. Use when the user says "watch the dev",
  "track this wallet", "did the dev sell", "what are whales buying", "smart
  money", "beobachte die dev wallet", "hat der dev verkauft", "wal
  tracker", "copy trade" (to explain why not), or after /meme-analyst.
argument-hint: "[dev MINT | add WALLET | import FILE | check]"
---

# meme-whales

The Whale Tracker is the meme coin version of watching insiders. On the
stock market you wait 45 days for a politician's disclosure. On Solana every
wallet's every trade is public within seconds. The two wallets that matter
most for a coin you hold are its creator's (a dev who sells or moves the
bag is the classic start of a rug) and the few big holders who can move the
price on their own. This skill watches them and tells you once, in plain
words, when they do something.

A whale's trade is information, not a signal to copy. They can afford
losses you cannot, they often hold several wallets, and by the time you see
a buy, the price has moved.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/whales.py" dev MINT                    # the coin's creator, from /meme-analyst or RugCheck
python3 "${CLAUDE_SKILL_DIR}/whales.py" add WALLET --label "GATO #2 holder"
python3 "${CLAUDE_SKILL_DIR}/whales.py" add WALLET --label "known trader" --role smart
python3 "${CLAUDE_SKILL_DIR}/whales.py" check                       # new transactions since the last check
python3 "${CLAUDE_SKILL_DIR}/whales.py" check --limit 20 --json
python3 "${CLAUDE_SKILL_DIR}/whales.py" import wallets.txt --role smart   # one address a line, ", label" optional
python3 "${CLAUDE_SKILL_DIR}/whales.py" list
python3 "${CLAUDE_SKILL_DIR}/whales.py" remove WALLET
```

Other flags: `--offline FOLDER` (saved RPC answers), `--no-write`.

## What it reads and writes

| source / file | what |
| --- | --- |
| Solana RPC (`api.mainnet-beta.solana.com`, or `solana_rpc` in the config) | `getSignaturesForAddress` (what is new), `getTransaction` (jsonParsed: balances before and after) |
| `meme/analyst/<mint>.json`, RugCheck | the creator wallet for `dev` |
| `meme/wallets.json` | the wallets you watch: address, label, role (dev, whale, smart, other), coin |
| `meme/state/whales.json` | the last signature seen per wallet and every transaction already shown |
| `meme/prices.json`, `safety.json`, `watchlist.json`, `portfolio.json`, `plan.json` | coin names, SOL's price, and what you hold or watch |

## How a transaction becomes a row

For the watched wallet it compares the token balances before and after the
transaction (owner = the wallet; wrapped SOL counts as SOL) and the wallet's
own SOL balance (the network fee is not a trade). Per coin that moved:

| row | when |
| --- | --- |
| BUY | the coin went up and SOL (or USDC/USDT) went down |
| SELL | the coin went down and SOL (or a stablecoin) went up |
| RECEIVED | the coin went up, nothing paid: a transfer in, an airdrop |
| SENT | the coin went down, nothing received: a transfer out (to another wallet, or to an exchange) |

Failed transactions are skipped. A dev wallet with a SELL or SENT of its
own coin gets `DEV SOLD` / `DEV MOVED TOKENS` and goes to the top. A coin
you hold gets "you hold it", a watched one "on your watchlist".

**Rate limits.** The public RPC node allows only a little traffic. The tool
pauses between calls and waits on a 429. For more than a few wallets, put a
free RPC endpoint of your own in `meme/config.json` as `"solana_rpc"` (it
lives in that file only, never in the chat).

## Top traders and clusters

There is no free official list of the best meme coin traders. Public
leaderboards (Kolscan, GMGN, Cielo and others) show wallet addresses; the
user copies the ones they want into a text file and imports it. A single
wallet's buy says little (they often hold several wallets and sell into the
people who follow them). Two or more of your wallets buying the same coin
within 30 minutes is a stronger fact, so `check` puts a CLUSTER line on top:

```
CLUSTER: 2 of your wallets bought MEME within 10 minutes (a, b): MINT
```

Still a fact, not a signal: they bought before you saw it, and the price
has moved since.

## Steps

1. After `/meme-analyst MINT`, offer `whales.py dev MINT` for any coin the
   user trades or holds. Add big holders by hand when the user asks, or
   `import` a list.
2. `whales.py check`. Lead with any DEV line and any CLUSTER line, then rows
   in coins the user holds, then the rest.
3. A DEV SOLD in a coin the user holds: say it plainly and point to the way
   out (`/meme-broker flatten`), but the decision is theirs.
4. On a schedule or a `/loop` (every few minutes while a trade is open), it
   only reads; it never trades.

## Example: the reel

The wallet that held 2.53 % of GATO on Sunday 2026-11-01 (RugCheck's
second-largest holder), checked for the first time
(`tests/fixtures/meme-whales/`):

```
4 new from 1 wallet, newest first (dev alerts on top):
  2026-10-31 21:07  GATO #2 holder RECEIVED 1,681,796.55 DUuHsG..
      DUuHsGnX1cwqYjyL4JwwudH3yyxyNAocxCGBiFtopump  tx 4m4G8wXU..dKK2hY
  2026-10-22 22:40  GATO #2 holder RECEIVED 40.72 A75Xx6..
  2026-10-22 21:06  GATO #2 holder RECEIVED 7,065.15 CLn6y4..
  2026-08-26 17:45  GATO #2 holder RECEIVED 25,000,000.00 GATO
      HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump  tx 3CUukfLy..AKmWqm
      ! on your watchlist
```

Its 25 million GATO arrived by transfer the day after launch, not by a buy:
the pattern RugCheck groups into insider networks. A second check right
after: "Nothing new from 1 wallet."

## Rules

- Each transaction is shown once. Say the time, the wallet's label, the action, the amount and the coin.
- Public on-chain data, read only. Never call a whale's trade a reason to buy or sell.
- Never claim to know who owns a wallet beyond its label and RugCheck's tags.

## What it never does

It never buys, sells or copies a trade, never signs or sends anything, and
never asks for a key.

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
