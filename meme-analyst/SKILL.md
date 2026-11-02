---
name: meme-analyst
description: >-
  Token Analyst, the rug check. Reads a meme coin's public record the way an
  earnings analyst reads a 10-Q: the on-chain report from RugCheck (mint and
  freeze authority, Token-2022 traps like transfer fees and permanent
  delegates, LP locked or burned, top holders with the pools left out, the
  creator's bag, insider wallet networks, RugCheck's own risk list) and the
  trading record from DexScreener (pool liquidity and age, volume against
  liquidity for wash trading, buys and sells, market cap, socials), with
  GoPlus as a second opinion on Solana and the contract check on Base, BSC
  and Ethereum (honeypot, buy and sell tax, hidden owner, unlocked LP), and
  the holder count against the last check. Sums it
  up as PASS, CAUTION or AVOID with every reason and writes meme/safety.json,
  which meme-risk requires before any buy. Use when the user says "is this a
  rug", "rug check", "check this token", "is it safe", "who holds it", "is
  the LP burned", "is mint revoked", "ist das ein rug", "prüf den coin",
  "check den contract", or right after /meme-scanner, before /meme-entry.
argument-hint: "[contract address | --watchlist]"
---

# meme-analyst

The Token Analyst answers the first question of every meme coin trade: can
this coin take my money in a way that has nothing to do with the chart? A
dev who can still mint new tokens, a freeze authority that can lock your
tokens so you cannot sell, a pool whose liquidity the owner can pull, three
wallets that hold half the supply: none of that shows on a chart until it is
too late. All of it is public. This skill reads it.

A PASS means no red flag in the data, not that the coin is safe. Most meme
coins go to zero with clean contracts too.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/report.py" MINT                 # print the report
python3 "${CLAUDE_SKILL_DIR}/report.py" MINT --write         # + meme/analyst/MINT.json and meme/safety.json
python3 "${CLAUDE_SKILL_DIR}/report.py" --watchlist --write  # every hit in meme/watchlist.json, one line each
python3 "${CLAUDE_SKILL_DIR}/report.py" MINT --json
python3 "${CLAUDE_SKILL_DIR}/report.py" 0xADDRESS --chain base --write  # Base, BSC, Ethereum: GoPlus
```

Other flags: `--chain solana` (or base, bsc, ethereum, arbitrum),
`--no-goplus`, `--now "2026-11-01 21:58"`, `--offline-dex FILE`,
`--offline-rugcheck FILE`, `--offline-goplus FILE`. Exit code 0 for PASS or CAUTION, 2 for
AVOID, 1 when it could not run.

## What it reads and writes

| source / file | what |
| --- | --- |
| RugCheck `v1/tokens/{mint}/report` | Solana only, free, no key: authorities, Token-2022 extensions, markets and their LP lock, top holders, known accounts, insider networks, risks |
| DexScreener `tokens/v1/{chain}/{mint}` | the pools: liquidity, age, volume, buys and sells, market cap, socials, boosts |
| GoPlus `token_security` | free, no key: Solana (mint, freeze, balance and close authorities, Token-2022 traps) and EVM chains (honeypot, taxes, owner powers, verified code, LP lock, holders) |
| `meme/state/holders.json` | the holder count at each check, for the trend |
| `meme/config.json` | your limits (below) |
| `meme/analyst/<mint>.json` | the full report, with `--write` |
| `meme/safety.json` | one line per coin: verdict, when, liquidity, pool, pool age, reasons. meme-risk reads it |

## The checks

AVOID (meme-risk blocks the buy):

| check | why |
| --- | --- |
| rugged | RugCheck already marks it rugged |
| mint authority active | the dev can print new tokens and sell them into the pool |
| freeze authority active | your tokens can be frozen: a honeypot you cannot sell |
| transfer fee, permanent delegate, frozen by default | Token-2022 traps: a tax on every move, or someone else can move your tokens |
| LP under 90 % locked or burned (`min_lp_locked_pct`) | the owner can pull the liquidity: the classic rug pull |
| pool liquidity under `min_liquidity_usd` (50,000) | a small sell moves the price a lot, and you may not get out |
| top 10 holders over `max_top10_pct` (30 %), pools left out | a few wallets can dump on you |
| one holder over `max_single_holder_pct` (10 %) | one wallet can dump on you |
| creator over `max_creator_pct` (5 %) | the dev still holds a bag to sell |
| insider networks over `max_insider_pct` (15 %) | linked wallets (RugCheck's graph) act as one |
| any RugCheck risk at level danger | RugCheck's own red flags |

GoPlus adds AVOID on Solana for a mintable or freezable token, an
authority that can change balances or close the token, a non-transferable
token or a transfer fee. On Base, BSC and Ethereum it is the contract check:
AVOID for a honeypot (cannot sell), a buy or sell tax over 10 %, unverified
code, a hidden owner, ownership that can be taken back, an owner who can
change balances, pausable transfers, a blacklist, a changeable tax, a
mintable supply, LP under 90 % locked or burned, top 10 over the limit
(Uniswap v4's PoolManager and the pool are left out) or a creator over the
limit; CAUTION for a tax up to 10 % and an owner who has not renounced.

CAUTION (meme-risk warns): a pool younger than `min_pool_age_hours` (6),
fewer than `min_holders` (1,000), metadata that can still change, a transfer
hook, insiders over 5 %, 24h volume over `max_turnover` (50) times the
liquidity (wash trading), twice as many sells as buys in the hour, no
website and no socials, a coin still on its bonding curve, and RugCheck
risks at level warn. INFO only: paid DexScreener boosts (promotion, not
demand) and the creator's bag when it is under the limit.

Holder math leaves out the pools and lockers (RugCheck's `knownAccounts` of
type AMM or LOCKER, and every market's own account), so a pool that holds 70
% of the supply does not count as a whale. Holders falling 3 % or more since
an earlier check in the last day is a CAUTION: people are leaving. On a Meteora DLMM or a CLMM pool
there is no LP token to burn: that is a CAUTION ("positions the owners can
withdraw"), not an AVOID. Off Solana there is no RugCheck: the verdict is
UNVERIFIED when GoPlus has nothing either, which meme-risk treats as a block
while `require_safety` is true. On Solana with GoPlus but no RugCheck report
the verdict is at best CAUTION (LP, insiders and the creator were not checked).

## Steps

1. Run `report.py MINT --write` on the coin the user picked (or
   `--watchlist --write` right after a scan).
2. Read back the verdict first, then every AVOID and CAUTION line in plain
   words. Then the key numbers: liquidity, LP, top 10, creator, insiders,
   holders, pool age.
3. AVOID: say plainly that meme-risk will block a buy and why. Do not look
   for a way around it, and never edit the config to make a coin pass.
4. PASS or CAUTION: hand on to `/meme-news` and `/meme-entry`. Offer
   `/meme-whales dev MINT` to watch the creator's wallet.
5. The report is a snapshot. meme-risk wants it under an hour old
   (`safety_max_age_minutes`); re-run it before a trade.

## Example: the reel

GATO at 21:58 on Sunday 2026-11-01 (`tests/fixtures/meme-analyst/rugcheck-GATO-2158.json`):

```
GATO (GTA6CAT) on solana, HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump
Security
  mint authority   revoked
  freeze authority revoked
  metadata         immutable
  transfer fee     0.00%
Liquidity
  main pool        5E3dXLXGwmTDCokA51WYYaKttjFZBwqCoyUHBUi5gt2m on pumpswap, $278.5k liquidity
  LP locked/burned 100% (pump_fun_amm)
  pool age         68 days
Holders
  holders          13,645
  top 10           15.5% (pools left out), largest 3.3%
  creator          3.32%   insiders 2.11% in 2 networks
Trading
  market cap       $7.69M   24h volume $1.09M (3.9x liquidity)
  last hour        482 buys, 824 sells; change m5 +2.6%, h1 +12.1%, h24 +20.4%
  RugCheck score   1 (lower is better)

  INFO    paid DexScreener boosts active (100): promotion, not demand
  INFO    the creator holds 3.32%: watch that wallet (/meme-whales dev)

Verdict: PASS (0 avoid, 0 caution)
```

The same evening the analyst said AVOID to four other boosted coins: Dacity
($373k pool, 59,000 holders, but linked insider wallets held 23.8 %), PAWCAT
($3.2k pool with $6.1M of 24h volume: 1,928x its liquidity, washed), VICE
(one wallet with 15 %, top 10 at 56 %) and MONEYBIZ ($107 of liquidity,
LP unlocked, one wallet with 51 %). Paid boosts on all five.

## Rules

- Lead with the verdict and the reasons, then the numbers.
- PASS is "no red flag in the data", never "safe", "legit" or "a good coin".
- Never soften an AVOID, and never change a limit to turn one into a PASS.
- Always name the contract address. A ticker is not an identity.
- RugCheck and DexScreener are free third-party services: they can be wrong or late. Say so when it matters.

## What it never does

It never buys or sells, never calls a coin safe, never predicts a price, and
never connects to a wallet.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Meme coins are the riskiest corner of crypto: most new coins go to zero, many are rugs. A clean contract
  does not stop a coin from going to zero.
- This pack never asks for, reads or stores a seed phrase, a private key or a wallet password. Nothing in it
  buys or sells without the user's explicit yes for that one trade.
