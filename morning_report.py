"""The daily 8 AM (Israel time / 05:00 UTC) morning report — everything in one package,
sent as separate Telegram messages in this order:

  1. 🎯 Goal-price alerts — one DEDICATED message per watchlist stock that reached the
     target the user set (can't be missed in the stream).
  2. 📋 Watchlist status page — every watched stock vs the strategy: price, chart
     status, health score, revenue check, distance off the low, target progress.
  3. 🌅 News scan — today's catalysts filtered through the quality gates.
  4. 📊 Full market scan — the top MAX_ALERTS best-of-the-best setups.

Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (required); ANTHROPIC_API_KEY, CHAT_MODEL
(recommended). Run by .github/workflows/premarket.yml every day at 05:00 UTC.
"""

import datetime

import chat_bot as cb
import news_scan as ns
import signal_bot as sb


def main():
    # Duplicate guard: two crons back this report up (GitHub fires them hours late and
    # sometimes skips one). Whichever run completes first stamps today's date; the other exits.
    today = datetime.date.today().isoformat()
    history = sb._load_alert_history()
    if history.get("_last_report") == today:
        print(f"Morning report already sent today ({today}) — skipping duplicate run.")
        return

    trades = cb.load_json(cb.TRADES_FILE, {"open": [], "closed": [], "watch": []})

    # 1) goal-price alerts — each one a standalone message
    hits = ns.check_watch_targets()
    for line in hits:
        sb.send_telegram_message(line)
    print(f"Goal-price alerts sent: {len(hits)}")

    # 2) watchlist status page
    if trades.get("watch"):
        try:
            sb.send_long("\U0001F4CB Morning watchlist report\n\n" + cb.handle_watchlist(trades))
        except Exception as e:
            print(f"watchlist report failed: {e}")

    # 3) news scan (targets excluded here — they were sent standalone above)
    try:
        headlines = ns.fetch_market_headlines()
        picks = ns.pick_candidates(headlines)
        results, dropped = ns.evaluate_candidates(picks)
        sb.send_long(ns.build_message(results, dropped, headlines, "8 AM report"))
    except Exception as e:
        print(f"news section failed: {e}")

    # 4) full market scan — sends its own top-MAX_ALERTS summary
    sb.main()

    # stamp AFTER a full run, so a crashed run doesn't stop the backup cron from retrying
    history = sb._load_alert_history()               # reload: sb.main() updated the cooldowns
    history["_last_report"] = today
    sb._save_alert_history(history)


if __name__ == "__main__":
    main()
