"""Telegram delivery and command polling (plain text — no parse_mode, so headlines with
special characters can never break a message)."""

from __future__ import annotations

import time

import requests

LIMIT = 3900  # Telegram hard cap is 4096 chars


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Split on paragraph, then line, then raw characters. Never drops content."""
    parts: list[str] = []
    cur = ""
    for para in text.split("\n\n"):
        blocks = [para]
        if len(para) > limit:
            blocks, line_buf = [], ""
            for ln in para.split("\n"):
                while len(ln) > limit:
                    blocks.append(ln[:limit])
                    ln = ln[limit:]
                if line_buf and len(line_buf) + 1 + len(ln) > limit:
                    blocks.append(line_buf)
                    line_buf = ln
                else:
                    line_buf = f"{line_buf}\n{ln}" if line_buf else ln
            if line_buf:
                blocks.append(line_buf)
        for b in blocks:
            if cur and len(cur) + 2 + len(b) > limit:
                parts.append(cur)
                cur = b
            else:
                cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        parts.append(cur)
    return parts


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False):
        self.token, self.chat_id = token, str(chat_id)
        self.dry_run = dry_run or not token or not chat_id
        self.sent: list[str] = []

    def _api(self, method: str, **payload):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        for attempt in range(4):
            try:
                r = requests.post(url, json=payload, timeout=20)
                if r.status_code == 429:
                    wait = r.json().get("parameters", {}).get("retry_after", 3)
                    time.sleep(min(int(wait), 30))
                    continue
                if r.ok:
                    return r.json()
                print(f"Telegram {method} error {r.status_code}: {r.text[:200]}")
                if r.status_code < 500:
                    return None
            except requests.RequestException as e:
                print(f"Telegram {method} network error: {e}")
            time.sleep(2 ** attempt)
        return None

    def send(self, text: str) -> bool:
        ok = True
        for part in split_message(text):
            self.sent.append(part)
            if self.dry_run:
                print("---- [dry-run telegram] ----\n" + part)
                continue
            res = self._api("sendMessage", chat_id=self.chat_id, text=part,
                            disable_web_page_preview=True)
            ok = ok and res is not None
            time.sleep(0.4)
        return ok

    def get_commands(self, offset: int) -> tuple[list[str], int]:
        """Text messages from the authorized chat since `offset`. Returns (texts, new_offset)."""
        if self.dry_run:
            return [], offset
        res = self._api("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
        if not res:
            return [], offset
        texts = []
        for upd in res.get("result", []):
            offset = max(offset, upd["update_id"] + 1)
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != self.chat_id:
                continue  # ignore anyone who isn't you
            if msg.get("text"):
                texts.append(msg["text"].strip())
        return texts, offset
