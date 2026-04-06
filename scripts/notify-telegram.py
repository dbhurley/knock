#!/usr/bin/env python3
"""
Knock Telegram Notification Helper
Sends messages to a Telegram chat via the Bot API.

Usage:
  python notify-telegram.py "Your message here"
  echo "Message from stdin" | python notify-telegram.py
  python notify-telegram.py --file /path/to/report.txt

Environment variables:
  TELEGRAM_BOT_TOKEN - Bot token from @BotFather (or read from /opt/knock/.env)
  TELEGRAM_CHAT_ID   - Target chat ID (or read from /opt/knock/.telegram_chat_id)
"""

import os
import sys
import argparse
import urllib.request
import urllib.parse
import json


def load_env_file(path="/opt/knock/.env"):
    """Load environment variables from .env file."""
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env


def get_config():
    """Get bot token and chat ID from env vars or config files."""
    env_file = load_env_file()

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or env_file.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not found", file=sys.stderr)
        sys.exit(1)

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        chat_id_file = "/opt/knock/.telegram_chat_id"
        if os.path.exists(chat_id_file):
            with open(chat_id_file) as f:
                chat_id = f.read().strip()

    if not chat_id:
        print("ERROR: TELEGRAM_CHAT_ID not set. Set env var or write to /opt/knock/.telegram_chat_id", file=sys.stderr)
        sys.exit(1)

    return token, chat_id


def send_telegram_message(token, chat_id, text, parse_mode=None):
    """Send a message via Telegram Bot API."""
    # Telegram has a 4096 char limit per message; split if needed
    max_len = 4000
    chunks = []
    while len(text) > max_len:
        # Find a good split point
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    chunks.append(text)

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for i, chunk in enumerate(chunks):
        data = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode

        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                if not result.get("ok"):
                    print(f"WARNING: Telegram API returned not ok: {result}", file=sys.stderr)
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            print(f"ERROR sending to Telegram (chunk {i+1}/{len(chunks)}): {e.code} {body}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"ERROR sending to Telegram: {e}", file=sys.stderr)
            return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Send message to Telegram")
    parser.add_argument("message", nargs="?", help="Message text to send")
    parser.add_argument("--file", "-f", help="Read message from file")
    parser.add_argument("--parse-mode", "-p", choices=["HTML", "Markdown", "MarkdownV2"],
                        help="Telegram parse mode")
    parser.add_argument("--chat-id", "-c", help="Override chat ID")
    args = parser.parse_args()

    token, chat_id = get_config()
    if args.chat_id:
        chat_id = args.chat_id

    # Get message from args, file, or stdin
    if args.file:
        with open(args.file) as f:
            message = f.read()
    elif args.message:
        message = args.message
    elif not sys.stdin.isatty():
        message = sys.stdin.read()
    else:
        print("ERROR: No message provided. Use argument, --file, or pipe stdin.", file=sys.stderr)
        sys.exit(1)

    message = message.strip()
    if not message:
        print("ERROR: Empty message", file=sys.stderr)
        sys.exit(1)

    success = send_telegram_message(token, chat_id, message, args.parse_mode)
    if success:
        print(f"Sent {len(message)} chars to chat {chat_id}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
