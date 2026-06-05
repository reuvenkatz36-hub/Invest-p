"""Always-on version of the chat bot for a free host (Railway/Render/Fly).

Unlike chat_bot.py (which polls once per GitHub Actions run), this runs forever and
LONG-POLLS Telegram, so replies are near-instant. It reuses all the analysis,
trade-journal and learning logic from chat_bot.py.

Persistence: reads/writes bot_state.json + trades.json under $DATA_DIR (default ".").
On an ephemeral host, mount a persistent volume and set DATA_DIR to it (e.g. /data),
otherwise your trade journal resets on every restart/redeploy.

Env vars: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (required); ANTHROPIC_API_KEY, CHAT_MODEL,
DATA_DIR (optional).

IMPORTANT: run only ONE poller for a given bot token. If you deploy this, disable the
GitHub Actions chat workflow (chat.yml) — two pollers fight over getUpdates (409s).
"""

import os
import time

import requests

import chat_bot as cb   # reuse handlers, analysis, persistence, send

DATA_DIR = os.environ.get("DATA_DIR", ".")
cb.STATE_FILE = os.path.join(DATA_DIR, "bot_state.json")
cb.TRADES_FILE = os.path.join(DATA_DIR, "trades.json")

TOKEN = cb.TOKEN
POLL_TIMEOUT = 50   # seconds the server holds the connection open waiting for a message


def long_poll(offset):
    params = {"timeout": POLL_TIMEOUT}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                     params=params, timeout=POLL_TIMEOUT + 20)
    if r.status_code == 409:
        print("getUpdates 409 — clearing webhook, backing off.")
        cb.delete_webhook()
        time.sleep(5)
        return None
    r.raise_for_status()
    return r.json().get("result", [])


def main():
    cb.delete_webhook()
    state = cb.load_json(cb.STATE_FILE, {"offset": None})
    trades = cb.load_json(cb.TRADES_FILE, {"open": [], "closed": []})
    offset = state.get("offset")
    print(f"Chat daemon started (long-polling, DATA_DIR={DATA_DIR}).")

    while True:
        try:
            updates = long_poll(offset)
        except requests.RequestException as e:
            print(f"poll error: {e}")
            time.sleep(5)
            continue
        if not updates:
            continue
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message")
            if not msg or "text" not in msg:
                continue
            if str(msg["chat"]["id"]) != cb.OWNER_CHAT_ID:
                continue   # only talk to the owner
            print(f"> {msg['text']}")
            try:
                reply = cb.handle_message(msg["text"], trades)
            except Exception as e:
                reply = f"Something went wrong handling that: {e}"
                print(f"handler error: {e}")
            cb.send(msg["chat"]["id"], reply)
        state["offset"] = offset
        cb.save_json(cb.STATE_FILE, state)
        cb.save_json(cb.TRADES_FILE, trades)


if __name__ == "__main__":
    main()
