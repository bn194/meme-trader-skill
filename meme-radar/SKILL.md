---
name: meme-radar
description: >-
  Launch Radar with a BUY or SKIP for every new coin in seconds. Listens to
  every new pump.fun coin the second it is created and to every graduation,
  through PumpPortal's free websocket (no key). At birth it throws out the
  obvious traps (a big dev buy, a serial launcher, a copycat or a copy race,
  junk names); at 10 seconds Jupiter's token data rules out the rest of the
  traps (active authorities, Mayhem mode, a dev with many earlier coins, the
  dev's bag, snipers, insiders, bundlers, an instant graduation); at 30
  seconds it decides on the first trading (traders, holders, money bought,
  buys against sells, the move, the top 10). Every BUY is a 5-euro paper
  trade first: the radar follows it as if you bought it 45 s later and sold
  at the stop, the target or the time stop 45 s after the alarm, after your
  app's fee, pump.fun's 1.25 % and slippage, and after 50 signals says
  PASSED or FAILED. It never buys. Use when the user says "check new coins",
  "neue coins sofort checken", "kaufen oder nicht", "snipe", "frische
  coins", "was wurde gerade gelauncht", "launch radar", "radar an", "paper
  test", "wie läuft der test", or wants coins earlier than the scanner sees
  them.
argument-hint: "[--minutes 10 | --forever] [--quiet] [test | show]"
---

# meme-radar

The Launch Radar is the earliest look this pack has: a coin is on screen
within a second of its creation and has a verdict, BUY or SKIP, about 30
seconds later. Be clear about what those seconds are worth. In the first
seconds a coin has no buyers, no pool and few holders. About 1 % of pump.fun
coins ever graduate from the bonding curve; most are dead within the hour.
The very first buyers are bots in the same block. A human on a phone needs
15 to 60 seconds from a line to a filled buy, and the paper test counts
exactly that delay.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/radar.py"                      # listen 10 minutes, a line for every coin
python3 "${CLAUDE_SKILL_DIR}/radar.py" --minutes 60 --quiet # only BUY lines, graduations, paper results
python3 "${CLAUDE_SKILL_DIR}/radar.py" --forever --quiet    # until stopped
python3 "${CLAUDE_SKILL_DIR}/radar.py" test                 # the paper test so far
python3 "${CLAUDE_SKILL_DIR}/radar.py" show                 # the last coins it saw, with reasons
python3 "${CLAUDE_SKILL_DIR}/radar.py" --graduations-only   # only coins that reached a real pool
python3 "${CLAUDE_SKILL_DIR}/radar.py" --decide 45 --min-traders 25 --min-volume 2000
```

Other flags: `--max-dev-buy 5`, `--save FILE` (record the stream and every
lookup), `--offline FILE` (replay a recording; it never touches the paper
test), `--no-write`.

## What it reads and writes

| source / file | what |
| --- | --- |
| PumpPortal `wss://pumpportal.fun/api/data` | `subscribeNewToken` (every new pump.fun coin) and `subscribeMigration` (graduations), free. Per-trade streams need a paid key; the radar does not use them |
| Jupiter `datapi.jup.ag/v1/assets/search` | free, no key, up to 50 coins a request, about 0.2 s: price, liquidity, holders, the audit (mint and freeze authority, the dev's bag, how many coins the dev launched and how many graduated, snipers, insiders, bundlers, top 10) and the first minutes of trading (traders, buys, sells, money bought, the move) |
| Jupiter `lite-api.jup.ag/price/v3` | SOL and EURC in USD, once at the start (for the SOL amount and the euro line) |
| `meme/watchlist.json`, `meme/universe.json` | tickers already in play: a new coin with one of them is a copycat |
| `meme/config.json` | the `fresh_*` rules below, `radar_max_dev_buy_pct` (10), `venue` and `venues` (the app's fee), `slippage_pct`, `eur_usd_fallback`, `testphase_min_profit_factor`, `timezone` |
| `meme/fresh.json` | every paper trade: signal, fill, path, exit, result after costs |
| `meme/radar.json` | the last 500 coins with their verdict and reasons (`show` prints them) |

## The rules

At birth, no network (SKIP):

| check | SKIP when |
| --- | --- |
| dev buy | the creator bought more than `radar_max_dev_buy_pct` (10 %) of the supply in the launch |
| serial launcher | the same wallet created 3 or more coins since the radar started |
| copycat | the ticker is already a coin in play (the scanner's lists) |
| copy race | the same ticker was launched before in this session: copies of copies, they usually die |
| junk | test, rug, scam, honeypot, airdrop, claim, free in the name, or no readable ticker |

At `fresh_first_look_seconds` (10), Jupiter's audit (SKIP), checked again at the verdict:

| check | SKIP when |
| --- | --- |
| authorities | mint or freeze authority still active |
| Mayhem mode | pump.fun's AI agent trades the coin for its first 24 hours, so its buys are partly that bot |
| serial dev | the dev has launched more than `fresh_max_dev_mints` (5) coins, this one included |
| the dev's bag | the dev holds more than `fresh_max_dev_pct` (10 %), or already sold (holds under a tenth of the launch buy) |
| snipers, insiders, bundlers | over `fresh_max_sniper_pct` (15 %), `fresh_max_insider_pct` (15 %), `fresh_max_bundler_pct` (10 %) |
| instant graduation | it graduated within 5 minutes of its launch: insiders bought the whole curve |

At `fresh_decide_seconds` (30), BUY needs all of: at least
`fresh_min_traders` (15) traders and `fresh_min_holders` (15) holders, at
least `fresh_min_buy_volume_usd` ($1,000) bought, no more sells than buys,
not down 30 % or more, liquidity not down 20 % or more, the top 10 wallets
at most `fresh_max_top10_pct` (40 %), and a price. Anything else is SKIP
with every reason. No data from Jupiter 8 seconds after a look: SKIP.

Graduations: `GRADUATED` with how long it took. A coin that graduates within
5 minutes of its launch is `BUNDLED`.

## The paper test

Every BUY is a paper trade of `fresh_max_order_eur` (5 EUR) until the test
is done. The radar follows it with a price every `fresh_poll_seconds` (10):

- **The fill:** the price `fresh_fill_delay_seconds` (45 s) after the
  signal, not the price at the signal. That is the time from a line on a
  phone to a filled buy.
- **The exits:** a stop at `fresh_stop_pct` (-25 %) and a target at
  `fresh_target_pct` (+50 %) from that fill, and a time stop after
  `fresh_hold_minutes` (10). Each one fills at the price 45 s after the
  alarm, so a stop that gaps fills far below -25 %.
- **The costs:** your app's fee each way (with its minimum: Fomo's $0.95 is
  17 % of a 5-euro trade, the radar warns), pump.fun's
  `fresh_curve_fee_pct` (1.25 %) each way and `slippage_pct`. About 4.8 % a
  round trip in Phantom. The token account's rent (about 0.002 SOL) comes
  back when the empty account is closed and is not counted.
- **No price for two minutes:** counted as a total loss, the safe
  assumption. A paper trade that was running when the radar stopped is not
  counted (its outcome is unknown); `test` says how many.

After `fresh_test_signals` (50) closed signals, in order, `radar.py test`
says **PASSED** (money made after costs and a profit factor of at least
`testphase_min_profit_factor`, 1.2) or **FAILED**. Under 50 it says how many
are closed and that luck dominates. The rule is fixed before the test; the
test never picks the best of several rules.

## Steps

1. In a session, run it in the background (`radar.py --minutes 60 --quiet`)
   and use the Monitor tool on it so every BUY, PAPER, GRADUATED or BUNDLED
   line arrives as an event. Send a push notification for a BUY line while
   the user is away.
2. For a BUY line: say it is a paper signal, the coin's full contract
   address, and why it passed, in one line. Nothing is bought.
3. For a PAPER line: read back the result after costs and the running total.
4. `radar.py test` when the user asks how it is going: read the lines as
   printed. Under 50 closed signals, never call it a pattern.
5. For a GRADUATED coin: it now has a real pool. `/meme-analyst MINT` is the
   next step.
6. Say the counts at the end. Most minutes have no BUY. That is normal.

## Real money

While the paper test is running, or after it FAILED, no real money goes into
these signals: say so plainly when the user asks. meme-risk blocks fresh
coins today (its pool age, liquidity and analyst rules are made for coins
hours old), and the pack never lowers those limits on its own. Real orders
on fresh coins need their own path through meme-risk (at most
`fresh_max_order_eur` a trade, the daily loss limit, the losing-streak
pause), and that path is built only after the paper test PASSED and the
user asks for it. Even then each order needs the user's explicit yes and is
bought by the user in their own app.

## Example: two real recordings

Monday 2026-11-02, 07:19 to 07:23 Europe/Berlin, `radar.py --minutes 4
--save` (`tests/fixtures/meme-radar/radar-2026-11-02-0719.json.gz`; the
replay gives the same verdicts as the live run):

```
SKIP  07:19:47  OKCAT (BFdQeGDHWqkQRCV1Zy78t99EEPhBA3CFE8wK4m72759s)  0s: copy race: OKCAT was already launched 1 time since the radar started
BUY   07:20:12  OKCAT (gZRR9VtuyZDdQkUDKCEoheEHUxzps4Zg2Z7RB3Jpump)  30s: 19 traders; 15 holders; $1.3k bought; 19 buys vs 6 sells; the dev's coin no. 3; price $0.000005025, mcap $5.0k
      paper test, signal 1 of 50: 5 EUR ($5.59 = 0.0592 SOL) as if bought 45 s from now; stop -25 %, target +50 %, out after 10 minutes; costs about 4.8 % a round trip. Still on the bonding curve.
SKIP  07:20:30  CI (Gg29Wfhq2nRNziL32wCLEXDdWQ5amuJQC2yH1Qm218iY)  10s: the dev has launched 171 coins (0 graduated): a serial launcher
SKIP  07:22:38  Mayhem (6fJ9Xi7eDS4WoM5AC4rgUvwMwP4tfnvpy8PzKhPKpump)  10s: Mayhem mode: pump.fun's AI agent trades it for its first 24 hours, so its buys are partly that bot; the dev has launched 51 coins (0 graduated): a serial launcher
BUNDLED   07:23:03  EpwR7NhYigWiGQ7PWKscrAbf9pENT9dvbBKaiy7tpump  graduated 0.5 s after launch: the whole bonding curve was bought in a few transactions, so insiders hold most of it. Stay away.
Radar, 4 minutes: 20 new coins: 3 BUY, 16 SKIP (6 at birth, 6 at 10s, 4 at 30s, 0 without data), 0 graduated, 1 bundled launch.
```

45 seconds after its signal OKCAT was already 33 % lower; another BUY of
those minutes, HODL, was 56 % higher. That is why the paper test fills at
the price 45 s later, not at the signal.

The twelve minutes before (07:07 to 07:19,
`radar-2026-11-02-0707.json.gz`, every coin followed for 15 minutes): 74 new
coins, 0 BUY. 37 were out at birth, 22 at 10 seconds (20 from devs with
dozens of earlier coins, 7 in Mayhem mode), 12 at 30 seconds. Of the 58
coins with a price 75 s and 11 minutes after their launch, 8 were up.

## The first paper test: FAILED

Monday 2026-11-02, 07:25 to 18:50 Europe/Berlin, six runs of `radar.py
--minutes 115 --quiet` with the default rules: about 7,200 new coins, 50
BUY signals, 5 EUR each.

```
Paper test: 50 of 50 signals closed (0 still running): 13 won, 37 lost, 26 % win rate
  after costs: average -12.5 % a trade, best +85.1 %, worst -86.9 %; total -31.32 EUR on 5-euro trades; profit factor 0.53
  exits: stop 25, target 11, time 14
  FAILED: after costs this rule lost money on paper over 50 signals. Do not trade it with real money.
```

The 25 stops were planned at -25 % and filled at -48 % on average: a fresh
coin that turns keeps falling in the 45 seconds a human needs to sell. The
11 targets made +58 % on average, the 14 time stops -4 %. Say this result
when the user asks about trading fresh coins; a different rule needs its
own new test of 50 signals, decided before it starts.

## Rules

- A BUY line is a coin that passed these rules, never a promise. Most new coins go to zero.
- Always give the full contract address, never only the ticker: the copies share it.
- Say that the coin is still on the bonding curve.
- Never place, size or schedule a buy from the radar. The paper test counts; the user decides.

## What it never does

It never buys or sells, never signs anything, never uses a paid stream,
never changes the rules to make the test pass, and never calls a launch
safe.

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
