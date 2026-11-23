import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from newsbot import ai, market, news, run
from newsbot.config import Config, Stock, load_config, save_watchlist
from newsbot.state import empty_state, load_state, save_state
from newsbot.telegram import Telegram, split_message

UTC = dt.timezone.utc
SHOP = Stock("SHOP", "Shopify")


def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


def rss(items):
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate>"
        + (f"<source url='x'>{s}</source>" if s else "") + "</item>"
        for t, u, d, s in items)
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>".encode()


def pubdate(ts: dt.datetime) -> str:
    return ts.strftime("%a, %d %b %Y %H:%M:%S GMT")


class MarketTests(unittest.TestCase):
    def test_regular_session_dst_winter_and_summer(self):
        winter = market.session_for(dt.date(2026, 12, 1))
        self.assertEqual(winter.open, utc(2026, 12, 1, 14, 30))
        self.assertEqual(winter.close, utc(2026, 12, 1, 21, 0))
        summer = market.session_for(dt.date(2026, 7, 1))
        self.assertEqual(summer.open, utc(2026, 7, 1, 13, 30))

    def test_holidays_weekends_and_early_close(self):
        self.assertIsNone(market.session_for(dt.date(2026, 11, 26)))   # Thanksgiving
        self.assertIsNone(market.session_for(dt.date(2026, 12, 25)))   # Christmas
        self.assertIsNone(market.session_for(dt.date(2026, 11, 21)))   # Saturday
        black_friday = market.session_for(dt.date(2026, 11, 27))
        self.assertTrue(black_friday.early_close)
        self.assertEqual(black_friday.close, utc(2026, 11, 27, 18, 0))  # 13:00 ET

    def test_due_briefing_windows(self):
        sent = {}
        # Mon 23 Nov 2026: open 14:30Z, close 21:00Z
        self.assertIsNone(market.due_briefing(utc(2026, 11, 23, 13, 0), sent, 60, 20))
        pre = market.due_briefing(utc(2026, 11, 23, 13, 45), sent, 60, 20)
        self.assertEqual((pre.kind, pre.late), ("pre", False))
        late = market.due_briefing(utc(2026, 11, 23, 15, 0), sent, 60, 20)
        self.assertTrue(late.late)
        sent[pre.key] = 1
        self.assertIsNone(market.due_briefing(utc(2026, 11, 23, 20, 0), sent, 60, 20))
        self.assertIsNone(market.due_briefing(utc(2026, 11, 23, 21, 10), sent, 60, 20))
        post = market.due_briefing(utc(2026, 11, 23, 21, 25), sent, 60, 20)
        self.assertEqual(post.kind, "post")
        sent[post.key] = 1
        self.assertIsNone(market.due_briefing(utc(2026, 11, 23, 23, 0), sent, 60, 20))

    def test_early_close_post_briefing_follows_real_close(self):
        post = market.due_briefing(utc(2026, 11, 27, 18, 25), {"2026-11-27:pre": 1}, 60, 20)
        self.assertEqual(post.kind, "post")

    def test_closed_day_digest_once(self):
        self.assertIsNone(market.due_briefing(utc(2026, 11, 26, 13, 0), {}, 60, 20))  # 08:00 ET
        d = market.due_briefing(utc(2026, 11, 26, 15, 0), {}, 60, 20)
        self.assertEqual(d.key, "2026-11-26:closed")
        self.assertIsNone(market.due_briefing(utc(2026, 11, 26, 18, 0), {d.key: 1}, 60, 20))


class NewsTests(unittest.TestCase):
    def test_clean_title_and_dedupe_key(self):
        self.assertEqual(news.clean_title("Shopify beats estimates - Reuters"), ("Shopify beats estimates", "Reuters"))
        self.assertEqual(news.dedupe_key("SHOP", "Shopify beats estimates - Reuters"),
                         news.dedupe_key("SHOP", "Shopify Beats Estimates!"))

    def test_relevance(self):
        self.assertTrue(news.is_relevant(SHOP, "Shopify shares jump after earnings"))
        self.assertTrue(news.is_relevant(SHOP, "SHOP stock rallies"))
        self.assertFalse(news.is_relevant(SHOP, "Shopping season starts early"))
        self.assertFalse(news.is_relevant(SHOP, "Is it time to buy Shopify?"))
        goog, tsm = Stock("GOOGL", "Alphabet (Google)"), Stock("TSM", "Taiwan Semiconductor (TSMC)")
        self.assertTrue(news.is_relevant(goog, "Google unveils new Gemini model"))
        self.assertTrue(news.is_relevant(tsm, "TSMC sales jump 30% in October"))
        self.assertFalse(news.is_relevant(tsm, "Taiwan holds military drills"))
        self.assertEqual(news.aliases(goog), ["Alphabet", "Google"])

    def test_parse_and_near_duplicate_removal(self):
        now = dt.datetime.now(UTC)
        body = rss([
            ("Shopify raises full-year guidance - CNBC", "https://a/1", pubdate(now), "CNBC"),
            ("Shopify raises full-year guidance", "https://b/2", pubdate(now), "Reuters"),
            ("Shopify raises its full-year guidance - Benzinga", "https://c/3", pubdate(now), None),
            ("Old Shopify story", "https://d/4", pubdate(now - dt.timedelta(days=5)), "WSJ"),
            ("Weather is nice", "https://e/5", pubdate(now), "X"),
        ])
        got = news.fetch_stock_news(SHOP, 36, fetch=lambda url: body)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].source, "Reuters")   # most authoritative copy kept


class TelegramTests(unittest.TestCase):
    def test_split_never_loses_content(self):
        text = "\n\n".join(["a" * 1000] * 9 + ["b" * 9000])
        parts = split_message(text, limit=3900)
        self.assertTrue(all(len(p) <= 3900 for p in parts))
        self.assertEqual("".join(parts).replace("\n", ""), text.replace("\n", ""))


class HeuristicTests(unittest.TestCase):
    def test_keyword_levels(self):
        now = dt.datetime.now(UTC)
        arts = [news.Article("SHOP", t, "u", "s", now) for t in
                ("Shopify agrees to acquire Foo", "Shopify Q3 earnings beat", "Shopify hosts event")]
        levels = [c.importance for c in ai.heuristic_classify(arts)]
        self.assertEqual(levels, ["critical", "high", "medium"])


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(watchlist=[SHOP], quiet_enabled=True, quiet_start="23:00", quiet_end="07:00")
        self.secrets = mock.Mock(anthropic_key="", claude_model="m", use_fallbacks=False)
        self.state = empty_state()
        self.tg = Telegram("", "", dry_run=True)

    def art(self, title, minutes_ago=5, source="Reuters"):
        return news.Article("SHOP", title, f"https://x/{abs(hash(title))}", source,
                            dt.datetime.now(UTC) - dt.timedelta(minutes=minutes_ago))

    def test_bootstrap_is_silent_then_alerts_only_new(self):
        day = utc(2026, 11, 23, 12, 0)   # 14:00 Israel, not quiet
        run.scan(self.cfg, self.state, self.tg, self.secrets, [self.art("Shopify Q3 earnings beat")], day)
        self.assertEqual(len(self.tg.sent), 1)                       # welcome only
        self.assertIn("live", self.tg.sent[0])
        new = [self.art("Shopify Q3 earnings beat"), self.art("Shopify CEO resigns"),
               self.art("Shopify hosts developer event")]
        run.scan(self.cfg, self.state, self.tg, self.secrets, new, day)
        self.assertEqual(len(self.tg.sent), 2)                       # only CEO alert
        self.assertTrue(self.tg.sent[1].startswith("\U0001F534 SHOP"))
        self.assertEqual(len(self.state["queue"]), 1)                # medium -> briefing
        run.scan(self.cfg, self.state, self.tg, self.secrets, new, day)
        self.assertEqual(len(self.tg.sent), 2)                       # no repeats

    def test_quiet_hours_hold_high_but_send_critical(self):
        self.state["bootstrapped"] = True
        self.state["known_tickers"] = ["SHOP"]
        night = utc(2026, 11, 23, 23, 0)  # 01:00 Israel
        run.scan(self.cfg, self.state, self.tg, self.secrets,
                 [self.art("Shopify downgraded at Goldman"), self.art("Shopify files for bankruptcy")], night)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertTrue(self.tg.sent[0].startswith("\U0001F534 SHOP"))
        self.assertEqual(len(self.state["held"]), 1)
        run.scan(self.cfg, self.state, self.tg, self.secrets, [], utc(2026, 11, 24, 6, 0))  # 08:00 Israel
        self.assertEqual(len(self.tg.sent), 2)
        self.assertIn("held during quiet hours", self.tg.sent[1])

    def test_overflow_alerts_are_queued_not_dropped(self):
        self.state.update(bootstrapped=True, known_tickers=["SHOP"])
        self.cfg.max_alerts_per_run = 2
        arts = [self.art(f"Shopify earnings item number {w}") for w in ("alpha", "bravo", "charlie", "delta")]
        run.scan(self.cfg, self.state, self.tg, self.secrets, arts, utc(2026, 11, 23, 12, 0))
        self.assertEqual(len(self.tg.sent), 2)
        self.assertEqual(len(self.state["queue"]), 2)

    def test_briefing_sent_once_with_sources_and_clears_queue(self):
        self.state["queue"] = [self.art("Shopify hosts developer event").to_dict()]
        quotes = {}
        with mock.patch("newsbot.prices.daily_quotes", return_value=quotes):
            now = utc(2026, 11, 23, 13, 50)
            run.maybe_brief(self.cfg, self.state, self.tg, self.secrets, [], now)
            run.maybe_brief(self.cfg, self.state, self.tg, self.secrets, [], now)
        self.assertEqual(len(self.tg.sent), 1)
        msg = self.tg.sent[0]
        self.assertIn("Before the open", msg)
        self.assertIn("Shopify hosts developer event", msg)
        self.assertNotIn("http", msg)                      # no links / sources
        self.assertIn("price n/a", msg)
        self.assertEqual(self.state["queue"], [])

    def test_stale_close_is_flagged(self):
        from newsbot.prices import Quote
        q = {"SHOP": Quote("SHOP", "SHOP", 100, 98, dt.date(2026, 11, 20))}
        lines = run._price_block(q, [("SHOP", "SHOP")], dt.date(2026, 11, 23))
        self.assertIn("STALE", lines[0])

    def test_commands_add_remove(self):
        with mock.patch("newsbot.run.lookup_name", return_value="NVIDIA Corp"):
            changed = run.handle_command("/add nvda", self.cfg, self.state, self.tg, self.secrets, dt.datetime.now(UTC))
        self.assertTrue(changed)
        self.assertEqual(self.cfg.find("NVDA").name, "NVIDIA Corp")
        self.assertTrue(run.handle_command("/remove NVDA", self.cfg, self.state, self.tg, self.secrets, dt.datetime.now(UTC)))
        self.assertFalse(run.handle_command("/add !!", self.cfg, self.state, self.tg, self.secrets, dt.datetime.now(UTC)))


    def test_clear_command(self):
        self.assertTrue(run.handle_command("/clear", self.cfg, self.state, self.tg, self.secrets, dt.datetime.now(UTC)))
        self.assertEqual(self.cfg.watchlist, [])

    def test_plain_english_request(self):
        intent = ai.Intent(actions=[ai.Action(type="clear", ticker="", name=""),
                                    ai.Action(type="add", ticker="nvda", name="Nvidia"),
                                    ai.Action(type="add", ticker="GOOGL", name="Alphabet"),
                                    ai.Action(type="add", ticker="TSM", name="TSMC")], reply="")
        with mock.patch("newsbot.ai.parse_request", return_value=intent):
            changed = run.handle_command("delete my old watchlist and add nvidia google and tsm",
                                         self.cfg, self.state, self.tg, self.secrets, dt.datetime.now(UTC))
        self.assertTrue(changed)
        self.assertEqual(self.cfg.tickers(), ["NVDA", "GOOGL", "TSM"])
        self.assertEqual(len(self.tg.sent), 1)                 # one combined reply
        self.assertIn("Now watching: NVDA, GOOGL, TSM", self.tg.sent[0])

    def test_plain_english_without_ai_explains_commands(self):
        with mock.patch("newsbot.ai.parse_request", return_value=None):
            self.assertFalse(run.handle_command("hello", self.cfg, self.state, self.tg, self.secrets, dt.datetime.now(UTC)))
        self.assertIn("/add", self.tg.sent[0])


class PersistenceTests(unittest.TestCase):
    def test_state_roundtrip_and_watchlist_save(self):
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / "state.json"
            st = empty_state()
            st["seen"]["k"] = 9e12
            save_state(st, sp)
            self.assertIn("k", load_state(sp)["seen"])
            cp = Path(d) / "config.json"
            cp.write_text(json.dumps({"timezone": "Asia/Jerusalem", "watchlist": [{"ticker": "SHOP", "name": "Shopify"}]}))
            cfg = load_config(cp)
            cfg.watchlist.append(Stock("NVDA", "Nvidia"))
            save_watchlist(cfg, cp)
            raw = json.loads(cp.read_text())
            self.assertEqual(raw["timezone"], "Asia/Jerusalem")
            self.assertEqual([s["ticker"] for s in raw["watchlist"]], ["SHOP", "NVDA"])


if __name__ == "__main__":
    unittest.main()
