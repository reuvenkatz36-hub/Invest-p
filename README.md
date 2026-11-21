# Watchlist News Bot

A Telegram bot that keeps you informed about the stocks you follow:

| What | When |
|---|---|
| 🔴 **Critical / 🟠 High news alerts** (one message per event, with source link and a one-line AI explanation) | Throughout the day, checked every ~15 min |
| 🌅 **Pre-market briefing** (overnight news, futures, previous close, what to watch today) | 60 min before the US open (~15:30 Israel time) |
| 🌆 **After-close recap** (index and per-stock closes, notable moves, company news, what to watch tomorrow) | 20 min after the US close (~23:20 Israel time; earlier on early-close days) |
| 📴 **Market-closed digest** | Weekends and US market holidays, from 09:00 New York time (16:00 Israel) |

Medium-importance news is not pushed; it's collected into the next briefing. Low-importance news is ignored.

Timing uses the real NYSE calendar, so US and Israeli daylight-saving changes, holidays (such as Thanksgiving)
and early closes (such as Black Friday at 13:00 ET) are handled automatically.

## How it works

- **News sources:** Yahoo Finance per-ticker feeds and Google News (which covers Reuters, Bloomberg, CNBC,
  press-release wires and more). Free, no API key. If one feed fails, the others still run.
- **Filtering:** a headline has to name the company or ticker. Listicles and clickbait are dropped,
  syndicated copies of the same story are merged, and the most authoritative source is kept.
- **AI triage (Claude):** new headlines are rated for importance and sentiment and grouped by event,
  so a single earnings report doesn't produce five alerts. Without an `ANTHROPIC_API_KEY`
  the bot falls back to keyword rules and plain headline digests.
- **Briefings** are written by Claude from the price data and headlines only, with `[n]` citations
  and a list of source links. The prompt forbids invented facts and claiming a headline *caused*
  a price move unless the source says so. A price from an older session is marked **STALE**.
- **Quiet hours** (23:00–07:00 Israel time by default): High alerts are held until morning;
  Critical alerts are always sent.
- **No duplicates:** each run remembers every headline it has seen and which briefings went out.
  If that memory is ever lost, the bot takes in the current news without alerting instead of resending old headlines.

## Telegram commands

Commands are picked up on the next run, within about 15 minutes.

```
/list                  your watchlist
/add NVDA [Nvidia]     watch a stock (the company name is looked up if you leave it out)
/remove NVDA           stop watching
/news NVDA             latest headlines for any ticker
/brief                 a briefing right now
/status                market status, today's session times, last scan
/help
```

Only messages from your own `TELEGRAM_CHAT_ID` are accepted.

## Setup (GitHub Actions — free for public repos)

1. Repository **Settings → Secrets and variables → Actions** must have:
   - `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` (required; the same ones the old bot used)
   - `ANTHROPIC_API_KEY` (recommended; enables AI triage and written briefings)
2. The workflow `.github/workflows/newsbot.yml` runs every 15 minutes from the **default branch**.
   You can also start it by hand under **Actions → News Bot → Run workflow**.
3. On the first run you'll get a "News bot is live" message.

Settings live in `config.json`: the watchlist, timezone, quiet hours, how long before the open
and after the close the briefings go out, the maximum article age, and the maximum alerts per run.
`/add` and `/remove` update this file automatically.

The Claude model is set by `CLAUDE_MODEL` in the workflow (default `claude-opus-5-5`).

## Run locally

```bash
pip install -r requirements.txt
python -m newsbot --dry-run            # print messages instead of sending them
python -m newsbot --brief post --dry-run
python -m unittest discover -s tests -v
```
