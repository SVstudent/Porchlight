"""Set up and prove the Telegram channel, end to end, without anyone pasting a secret into a chat.

Run it after putting TELEGRAM_BOT_TOKEN into backend/.env:

    python scripts/telegram_setup.py

It verifies the token against the real Telegram API, waits for you to message the bot so it can learn
your chat id, writes that id to backend/.env as the demo override, and sends you a real message to
prove the round trip. Nothing here is simulated; every step is a live call to api.telegram.org.

    --send-only    just send a test message using what is already configured
    --no-write     do everything but leave backend/.env alone
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.channels.telegram import get_updates  # noqa: E402

import httpx  # noqa: E402

ENV = BACKEND / ".env"
OK, BAD, INFO = "\033[32m  ok  \033[0m", "\033[31m fail \033[0m", "\033[36m ---- \033[0m"


def api(method: str, **params):
    """One call to the Telegram Bot API. The token never leaves this process."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    with httpx.Client(timeout=20.0) as c:
        return c.get(url, params=params).json()


def set_env(key: str, value: str) -> None:
    """Add or replace one key in backend/.env, leaving every other line untouched."""
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")
    print(f"{OK} wrote {key} to backend/.env")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-only", action="store_true", help="just send a test message")
    ap.add_argument("--no-write", action="store_true", help="do not modify backend/.env")
    args = ap.parse_args()

    # ---------------------------------------------------------------- token
    if not settings.TELEGRAM_BOT_TOKEN:
        print(f"{BAD} TELEGRAM_BOT_TOKEN is not set.\n")
        print("  1. Open Telegram and message @BotFather")
        print("  2. Send /newbot and answer its two questions")
        print("  3. It replies with a token like 8123456789:AAH...")
        print("  4. Put this line in backend/.env (the file is git-ignored):\n")
        print("       TELEGRAM_BOT_TOKEN=<the token>\n")
        print("  5. Run this script again.")
        return 1

    me = api("getMe")
    if not me.get("ok"):
        print(f"{BAD} Telegram rejected the token: {me.get('description')}")
        print("      Check for a stray space or a truncated paste in backend/.env.")
        return 1
    bot = me["result"]
    handle = bot.get("username", "?")
    print(f"{OK} token works — bot is @{handle} ({bot.get('first_name','')})")

    # ---------------------------------------------------------------- chat id
    chat_id = settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID
    if args.send_only and not chat_id:
        print(f"{BAD} nothing to send to: DEMO_OVERRIDE_TELEGRAM_CHAT_ID is not set. Run without --send-only.")
        return 1

    if not args.send_only:
        # Telegram will not let a bot message someone who has never messaged it first. That is a spam
        # guard, not a bug, and it is why this step cannot be skipped.
        print(f"{INFO} now open Telegram, find @{handle}, and send it any message (\"hi\" is fine).")
        print(f"{INFO} waiting up to 3 minutes…")
        found = None
        offset = None
        deadline = time.time() + 180
        while time.time() < deadline and not found:
            for u in get_updates(offset):
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message") or {}
                chat = msg.get("chat") or {}
                if chat.get("id"):
                    found = chat
                    break
            if not found:
                time.sleep(2)

        if not found:
            print(f"{BAD} no message arrived. Make sure you messaged @{handle} and not a different bot.")
            return 1
        chat_id = str(found["id"])
        who = found.get("first_name") or found.get("title") or found.get("username") or "you"
        print(f"{OK} got a message from {who} — chat id {chat_id}")
        if not args.no_write:
            set_env("DEMO_OVERRIDE_TELEGRAM_CHAT_ID", chat_id)

    # ---------------------------------------------------------------- prove it
    body = (
        "Porchlight is connected.\n\n"
        "During the demo this is where a neighbour's check-in message arrives, with a one-tap link. "
        "You can reply OK or HELP to any of them and the coordinator's dashboard updates within a few seconds."
    )
    sent = api("sendMessage", chat_id=chat_id, text=body)
    if not sent.get("ok"):
        print(f"{BAD} could not send: {sent.get('description')}")
        return 1
    print(f"{OK} sent you a real message (id {sent['result']['message_id']}) — check Telegram")

    # ---------------------------------------------------------------- what is left
    print()
    if settings.SEND_MODE != "live":
        print(f"{INFO} SEND_MODE is '{settings.SEND_MODE}', so the agents still only log messages.")
        print("      Set SEND_MODE=live in backend/.env when you want approvals to really send.")
    else:
        print(f"{OK} SEND_MODE=live — approved messages will really be sent")
    if not args.no_write:
        print(f"{INFO} every outbound message is routed to your chat id while the override is set,")
        print("      so the demo roster's fictional contacts are never messaged.")
    print(f"{INFO} restart the backend to pick up the new values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
