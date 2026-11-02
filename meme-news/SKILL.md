---
name: meme-news
description: >-
  News Monitor. Tracks what moves the meme coins you watch and the market
  around them: crypto headlines from public RSS feeds (Cointelegraph,
  Decrypt, CoinDesk) that name your coin, the market headlines that move all
  of them (exchange hacks, listings, regulation, SOL and BTC), DexScreener
  events per coin (paid boosts, new token profiles, community takeovers),
  and each coin's move and pool liquidity compared with your last check, so a
  pool that is draining shows up as a rug warning, plus the public Telegram
  channels you follow (which coins they name, which contract addresses they
  post most). X is not read: its API is paid per post. Shows only what is new
  since the last check, newest first, in your time zone, tags each item and
  never repeats one. Use when the user says "any news on this coin", "why is
  it pumping", "why is it dumping", "what's happening in crypto", "morning
  briefing", "gibt es news", "warum pumpt das", "was ist los am markt",
  "check the news", "what are the telegram channels saying", "was sagt
  telegram", or after /meme-analyst, before /meme-entry.
argument-hint: "[--tokens MINT,...] [--hours 12] [--market] [--telegram ch1,ch2]"
---

# meme-news

The News Monitor answers "why is it moving?" and "is something about to hit
all of these coins?". For a meme coin the news is rarely a press release.
It is a paid boost, a community takeover, a pool that suddenly holds less
money, or a market headline (an exchange hack, a regulator) that drags every
coin at once. This skill gathers those in one list.

Headlines are context, not signals. A coin that is in the news has often
already moved.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                         # plan, entry, watchlist and portfolio coins
python3 "${CLAUDE_SKILL_DIR}/news.py" --tokens MINT1,MINT2 --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --market                # the market only
python3 "${CLAUDE_SKILL_DIR}/news.py" --all                   # repeat what was already shown
python3 "${CLAUDE_SKILL_DIR}/news.py" --telegram pumpfun,channel2  # public Telegram channels (or telegram_channels in the config)
```

Other flags: `--chain solana`, `--no-telegram`, `--now "2026-11-01 21:58"`,
`--offline FOLDER` (saved feeds, DexScreener files and `tg-NAME.html`
pages), `--no-write`, `--json`.

## What it reads and writes

| source / file | what |
| --- | --- |
| RSS: cointelegraph.com/rss, decrypt.co/feed, coindesk.com/arc/outboundfeeds/rss/ | the headlines, with their times |
| DexScreener `tokens/v1` | each coin's price, change (5m, 1h, 6h, 24h) and pool liquidity |
| DexScreener `token-boosts`, `token-profiles`, `community-takeovers` | promotion and takeover events per coin |
| `meme/plan.json`, `entry.json`, `watchlist.json`, `portfolio.json` | which coins to watch when you name none |
| `t.me/s/CHANNEL` | the public web preview of each Telegram channel in `telegram_channels`: the last posts, their time and views, the subscriber count. Groups and channels with the preview switched off cannot be read |
| `meme/state/news.json` | what was shown (never repeated) and each coin's last price and liquidity |

## Telegram

Put the public channels you trust in `meme/config.json` as
`"telegram_channels": ["pumpfun", "..."]` (the name after t.me/). For each
coin it lists the posts that name its contract address, its ticker or its
name, and across all posts the contract addresses posted most. Calls in
channels are often paid, or the caller's own bags being sold to the readers:
a mention is a fact, never a reason to buy. X (Twitter) is not read: its
official API costs about $0.005 per post read since 2026, and scraping it
breaks its rules.

## How it matches and tags

A headline belongs to a coin when it names the ticker as a word (`GATO` or
`$GATO`, three letters or more) or the coin's name (four letters or more).
Short or common tickers miss or over-match: say so when it happens.

Tags: `hack`, `rug`, `listing`, `exchange`, `whale`, `launch`, `regulatory`,
`macro`, `memecoin`, `solana`, `bitcoin`, plus `promo` (a paid boost or a new
profile) and `cto` (a community takeover: the original team may be gone).
A market headline is one tagged hack, listing, exchange, regulatory, macro,
memecoin, solana or whale.

**The rug warning.** Every run stores each coin's pool liquidity. When the
next run finds it down 20 % or more, it prints a `[rug] RUG WARNING` line.
For a held coin, `/meme-alerts` rings on that by itself (the rug alarm).

## Steps

1. Run `news.py` (or with `--tokens`). Lead with anything tagged rug, hack,
   or a RUG WARNING line, then the coin's own headlines, then the market.
2. For each item say what it is and why it might matter, in one line. Do
   not turn a headline into a buy or a sell.
3. If the market is in a hack or a crash, say that every meme coin trades
   with it: a breakout on a bad market day fails more often.
4. Hand on to `/meme-entry`. If the coin is held, offer `/meme-alerts`.

## Example: the reel

GATO at 21:58 on Sunday 2026-11-01, the last 24 hours (`tests/fixtures/meme-news/`):

```
GATO (HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump)
  now $0.0077880 at 21:58: 5m +2.6%, 1h +12.1%, 6h +2.3%, 24h +20.4%; pool liquidity $278,504
  now       [promo] paid DexScreener boost: 100 active (promotion, not demand) (DexScreener)
Market, last 24 hours (8 new):
  Sun 17:01 [hack, exchange, macro] Bitcoin ETF Investors Head for the Exits After Record Binance Hack (Decrypt)
  Sun 11:35 [hack, exchange] Binance opens crypto withdrawals in phases starting with bitcoin following $6.3 billion hack (CoinDesk)
  Sun 02:10 [hack, listing, exchange, regulatory, solana] FBI confirms North Korea's role in $6 billion Binance hack, asks DeFi community to block BTC, ETH, SOL addresses (CoinDesk)
  ...
```

No headline named GATO. Its only "news" was a paid boost. The market that
weekend was the $6.3 billion Binance hack: worth saying before any trade,
because every coin trades in that weather.

## Rules

- New items only, newest first, in the user's time zone. Never repeat one.
- Context, not signals: never "this news means it will pump".
- Say which source each item came from, and when a source did not answer.
- A paid boost or an ad is promotion. Never present it as demand.

## What it never does

It never buys or sells, never predicts a price, never logs in anywhere,
never reads X, never reads a private Telegram group, and never calls a
headline or a call a reason to trade.

## Safety

- Education and tooling, not financial advice.
- Meme coins are the riskiest corner of crypto: most new coins go to zero, many are rugs.
- This pack never asks for, reads or stores a seed phrase, a private key or a wallet password. Nothing in it
  buys or sells without the user's explicit yes for that one trade.
