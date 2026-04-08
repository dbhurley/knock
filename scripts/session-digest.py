#!/usr/bin/env python3
"""
session-digest.py — Capture Janet's Telegram conversations into daily memory files.

OpenClaw stores every conversation as JSONL in
/root/.openclaw/agents/main/sessions/. The Telegram group session lives at:
  agent:main:telegram:group:-1003814956035 -> 7f3ad0ef-...jsonl

The problem: Janet doesn't have an automatic mechanism to surface old session
content into new sessions. Her context window is finite, so old conversations
fall off and she "forgets" things she discussed yesterday.

This script:
  1. Reads new lines from each session JSONL since the last run
  2. Extracts user/assistant message pairs
  3. Uses Claude to distill them into a one-paragraph memory note
  4. Appends to /root/.openclaw/workspace/memory/YYYY-MM-DD.md
  5. Re-embeds with qmd so semantic search picks up the new content

Run via cron every 30 minutes.
"""

import os
import sys
import json
import re
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Install: pip install anthropic")
    sys.exit(1)

ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY")
MODEL            = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
SESSIONS_DIR     = Path("/root/.openclaw/agents/main/sessions")
MEMORY_DIR       = Path("/root/.openclaw/workspace/memory")
STATE_FILE       = Path("/root/.openclaw/workspace/memory/.session-digest-state.json")
LOG_FILE         = Path("/opt/knock/logs/session-digest.log")

# Telegram session keys we care about (Knock team chat)
TARGET_SESSIONS = {
    "agent:main:telegram:group:-1003814956035",  # Knock Telegram group
    "agent:main:main",                             # Janet's main session
}

if not ANTHROPIC_KEY:
    print("ANTHROPIC_API_KEY not set")
    sys.exit(1)


def log(msg):
    line = f"{datetime.now().isoformat()} {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_target_session_files():
    """Map session_key -> session_file_path."""
    sessions_index = SESSIONS_DIR / "sessions.json"
    if not sessions_index.exists():
        return {}
    try:
        idx = json.loads(sessions_index.read_text())
    except json.JSONDecodeError:
        return {}
    out = {}
    for key, info in idx.items():
        if key in TARGET_SESSIONS:
            sf = info.get("sessionFile")
            if sf and Path(sf).exists():
                out[key] = Path(sf)
    return out


def extract_messages(jsonl_path, since_offset=0):
    """Read messages from a JSONL file starting at the given byte offset.
    Returns (messages, new_offset)."""
    messages = []
    with open(jsonl_path, "rb") as f:
        f.seek(since_offset)
        new_data = f.read()
        new_offset = f.tell()

    if not new_data:
        return [], new_offset

    for raw_line in new_data.split(b"\n"):
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "message":
            continue
        role = entry.get("role")
        if role not in ("user", "assistant"):
            continue
        text = extract_text(entry.get("content"))
        if not text or len(text) < 5:
            continue
        # Skip system reminders
        if "<system-reminder>" in text:
            continue
        messages.append({
            "role": role,
            "text": text[:2000],  # cap individual messages
            "ts": entry.get("timestamp") or entry.get("createdAt"),
        })
    return messages, new_offset


def extract_text(content):
    """Pull human-readable text from various OpenClaw content shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if "text" in c:
                    parts.append(c["text"])
                elif c.get("type") == "text" and "text" in c:
                    parts.append(c["text"])
        return "\n".join(parts)
    if isinstance(content, dict) and "text" in content:
        return content["text"]
    return ""


DIGEST_PROMPT = """You are summarizing a chunk of a Telegram conversation between Dan Hurley (founder of Knock Executive Search) and Janet (his AI office manager). Extract the persistent memory: what was discussed, decisions made, new entities mentioned, and follow-up actions.

CONVERSATION:
{conversation}

Output a structured Markdown digest with these sections (omit any that don't apply). Be concrete and specific — names, school names, search numbers, dates, decisions. Skip filler.

```
## Session Digest — {date}

### Topics
- (1-3 bullet points on what was discussed)

### People & Schools mentioned
- (name) — (role/school) — (any key facts)

### Active Searches referenced
- (search name/number) — (status, what was discussed)

### Decisions / Standing instructions
- (anything Dan said Janet should remember going forward)

### Follow-ups
- (open items Janet should track)

### New facts to remember
- (1-line statements Janet should add to MEMORY.md)
```

Be concise. Each bullet should be one sentence. Skip sections with no content."""


def digest_messages(client, messages, date_str):
    """Send messages to Claude and get a digest."""
    if not messages:
        return None

    # Build conversation text
    convo_lines = []
    for m in messages[-100:]:  # cap at last 100 messages per digest
        prefix = "Dan" if m["role"] == "user" else "Janet"
        convo_lines.append(f"{prefix}: {m['text']}")
    conversation = "\n\n".join(convo_lines)

    # Truncate to ~30K chars to fit comfortably
    if len(conversation) > 30000:
        conversation = conversation[-30000:]

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": DIGEST_PROMPT.format(conversation=conversation, date=date_str),
            }],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log(f"  LLM error: {e}")
        return None


def append_to_daily_memory(digest_text, date_str):
    """Append a digest section to the day's memory file."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    daily_file = MEMORY_DIR / f"{date_str}.md"

    timestamp = datetime.now().strftime("%H:%M")
    header = f"\n\n---\n## {timestamp} Auto-digest\n\n"

    if not daily_file.exists():
        # Initialize with a header
        daily_file.write_text(f"# Memory — {date_str}\n\nAuto-captured conversation digests from Janet's Telegram sessions.\n")

    with open(daily_file, "a") as f:
        f.write(header + digest_text + "\n")

    return daily_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-full", action="store_true", help="Re-process entire session files from start")
    parser.add_argument("--max-bytes", type=int, default=200000, help="Max bytes to process per session per run")
    args = parser.parse_args()

    log("=== Session digest run starting ===")

    state = {} if args.force_full else load_state()
    sessions = get_target_session_files()

    if not sessions:
        log("No target sessions found")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for session_key, session_file in sessions.items():
        prev_offset = state.get(session_key, {}).get("offset", 0)
        file_size = session_file.stat().st_size

        # Cap how much we process per run to keep LLM costs sane
        if file_size - prev_offset > args.max_bytes:
            # Move forward but not past max_bytes
            target = prev_offset + args.max_bytes
        else:
            target = file_size

        if target <= prev_offset:
            log(f"  {session_key}: no new content")
            continue

        log(f"  {session_key}: processing {prev_offset}..{target} of {file_size} bytes")

        # Read just the slice we want
        with open(session_file, "rb") as f:
            f.seek(prev_offset)
            data = f.read(target - prev_offset)

        # Find a clean line boundary at the end
        last_newline = data.rfind(b"\n")
        if last_newline > 0:
            data = data[:last_newline + 1]
            actual_end = prev_offset + len(data)
        else:
            actual_end = target

        # Parse messages from this slice
        messages = []
        for raw_line in data.split(b"\n"):
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "message":
                continue
            # OpenClaw nests role/content under "message"
            msg = entry.get("message", entry)
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            text = extract_text(msg.get("content"))
            if not text or len(text) < 5:
                continue
            # Skip system reminders, bootstrap truncation warnings, and untrusted-metadata blocks
            if "<system-reminder>" in text:
                continue
            if "Conversation info (untrusted metadata)" in text:
                # Strip the metadata block, keep just the actual message
                lines = text.split("\n")
                # Find the end of the metadata block
                stripped = []
                in_block = False
                for line in lines:
                    if "untrusted metadata" in line or in_block:
                        in_block = True
                        if line.startswith("```") and stripped:
                            in_block = False
                            continue
                        if in_block and not line.startswith("```"):
                            continue
                        if line.startswith("```"):
                            in_block = True
                            continue
                    else:
                        stripped.append(line)
                text = "\n".join(stripped).strip()
                if not text or len(text) < 5:
                    continue
            # Strip the bootstrap truncation warning that openclaw appends
            if "[Bootstrap truncation warning]" in text:
                text = text.split("[Bootstrap truncation warning]")[0].strip()
            if not text or len(text) < 5:
                continue
            messages.append({"role": role, "text": text[:2000]})

        log(f"    Extracted {len(messages)} messages")

        if len(messages) < 2:
            # Not enough to digest, but still advance the offset
            state[session_key] = {"offset": actual_end, "updated": datetime.now().isoformat()}
            continue

        digest = digest_messages(client, messages, today)
        if digest:
            daily_file = append_to_daily_memory(digest, today)
            log(f"    ✓ Wrote digest to {daily_file}")

        state[session_key] = {"offset": actual_end, "updated": datetime.now().isoformat()}

    save_state(state)

    # Re-embed the memory directory so qmd can find the new content
    try:
        os.system("qmd embed >> /root/.openclaw/workspace/memory/qmd-embed.log 2>&1")
        log("  ✓ qmd re-embedded")
    except Exception as e:
        log(f"  qmd embed error: {e}")

    log("=== Session digest run complete ===")


if __name__ == "__main__":
    main()
