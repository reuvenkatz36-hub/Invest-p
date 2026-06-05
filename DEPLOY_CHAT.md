# Deploy the chat bot for instant replies (always-on host)

The daily screener (`signal_bot.py`) stays on GitHub Actions. This is only for the
**chat bot**, so it can reply instantly instead of waiting on GitHub's slow cron.

`chat_daemon.py` long-polls Telegram and reuses all the logic in `chat_bot.py`.

## Option A — Railway (recommended, has a persistent volume)

1. Go to https://railway.app and sign in with GitHub (free).
2. **New Project → Deploy from GitHub repo →** pick `reuvenkatz36-hub/Invest-p`.
3. In the service **Settings → Deploy**, set the **Start Command** to:
   ```
   python chat_daemon.py
   ```
4. **Variables** tab — add:
   - `TELEGRAM_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your numeric chat id
   - `DATA_DIR` = `/data`
   - `ANTHROPIC_API_KEY` = your key (optional — unlocks the AI opinion)
   - `CHAT_MODEL` = `claude-haiku-4-5` (optional, cheaper) — defaults to `claude-opus-4-8`
5. **Add a Volume** (service → Variables/Settings → Volumes) mounted at `/data`.
   This keeps your trade journal across restarts.
6. Deploy. The logs should show `Chat daemon started (long-polling...)`.
7. Message your bot — it should reply within a second or two.

## Option B — Render (background worker)

1. https://render.com → New → **Background Worker** → connect this repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `python chat_daemon.py`
4. Add the same environment variables as above (Render's free disk is ephemeral —
   set `DATA_DIR` to a mounted disk if you add one, or accept that the journal
   resets on redeploy).

## CRITICAL: run only one poller

A Telegram bot allows **one** `getUpdates` consumer at a time. Once the daemon is
live, the GitHub Actions chat workflow must be turned off, or the two will fight
(constant 409 errors). Tell me once the daemon is running and I'll disable
`.github/workflows/chat.yml` for you (the daily screener workflow stays untouched).
