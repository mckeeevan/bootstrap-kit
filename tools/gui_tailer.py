#!/usr/bin/env python3
"""gui_tailer.py — live tail of a Copilot VS Code session's events.jsonl.

The VS Code Copilot session writes a live event log to
~/.copilot/session-state/<session-id>/events.jsonl. This tailer reads new
lines as they appear and appends mapped events to the project's
.claude-gui/events.jsonl, so the claude-gui viewer shows the session's work
live — no manual logging.

Usage:
  python3 tools/gui_tailer.py --session-dir ~/.copilot/session-state/<id> \
      --project /path/to/project [--interval 1.0]

Runs forever (polls every --interval seconds). Fail-open: a bad line is
skipped, never fatal.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 200_000
KEEP = 400

# session tool name -> (gui event type, which argument holds the target).
# Conceptual work is logged: reading files, writing code, running tests,
# spawning agents. Searches (grep/glob) and web lookups are exploration
# churn and are dropped on purpose.
TOOL_MAP = {
    "bash": ("run", "command"),
    "powershell": ("run", "command"),
    "view": ("read", "path"),
    "read": ("read", "path"),
    "create": ("edit", "path"),
    "write": ("edit", "path"),
    "edit": ("edit", "path"),
    "str_replace_editor": ("edit", "path"),
    "apply_patch": ("edit", "path"),
    "task": ("spawn", "description"),
    "agent": ("spawn", "description"),
}

# Assistant messages shorter than this are narration ("let me check X") and
# are dropped; anything longer is a real update worth seeing.
MIN_MESSAGE_LEN = 80

TEST_RE = re.compile(
    r"\b(pytest|npm\s+test|jest|vitest|cargo\s+test|go\s+test|node\s+--test|"
    r"phpunit|rspec|make\s+test|dotnet\s+test)\b"
)

# Shell commands that are just looking around (ls, grep, cat, git status...)
# rather than doing work. Only these are dropped; builds, installs, servers
# and anything else still count as "ran".
INSPECT_RE = re.compile(
    r"^\s*(ls|ll|pwd|cat|head|tail|less|more|file|stat|wc|which|echo|printf|sleep|"
    r"grep|rg|find|tree|du|df|ps|top|env|printenv|date|uname|whoami|hostname|"
    r"git\s+(status|log|diff|show|branch|remote|ls-files|rev-parse|describe)|"
    r"python3?\s+-c\s+['\"]import\s+json|"
    r"python3?\s+-c\s+['\"][^'\"]*(open\(|read_text|stat\(|Counter\(|json\.loads?))"
)

# Leading "cd /path &&" / "cd /path ;" prefixes are navigation, not work.
CD_PREFIX_RE = re.compile(r"^\s*cd\s+\S+\s*(?:&&|;)\s*")


def _segment_is_inspect(seg: str) -> bool:
    seg = seg.strip()
    if not seg:
        return True
    if re.match(r"^cd\s+\S+\s*$", seg):
        return True  # bare "cd /path" is navigation
    return bool(INSPECT_RE.search(seg))


def is_inspect(cmd: str) -> bool:
    """True if the whole command is just looking around.

    A chain (&& / ;) counts as inspect only when every segment is; one real
    step (build, test, commit, server) keeps the command in the feed.
    """
    if "gui_tailer" in cmd:
        return True  # the tailer's own plumbing is not work
    for seg in re.split(r"&&|;", cmd):
        seg = CD_PREFIX_RE.sub("", seg)
        if not _segment_is_inspect(seg):
            return False
    return True


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_event(gui: Path, ev: dict) -> None:
    gui.mkdir(parents=True, exist_ok=True)
    events = gui / "events.jsonl"
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, separators=(",", ":")) + "\n")
    if events.stat().st_size > MAX_BYTES:
        lines = events.read_text(encoding="utf-8").splitlines()
        hist = gui / "history"
        hist.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (hist / f"events-{stamp}.jsonl").write_text(
            "\n".join(lines[:-KEEP]) + "\n", encoding="utf-8"
        )
        events.write_text("\n".join(lines[-KEEP:]) + "\n", encoding="utf-8")
    (gui / "heartbeat").write_text(now_iso(), encoding="utf-8")


def target_from(tool: str, args) -> str:
    if not isinstance(args, dict):
        return ""
    _etype, key = TOOL_MAP.get(tool, (None, None))
    val = args.get(key)
    if isinstance(val, str):
        return val[:200]
    return ""


def shorten(etype: str, target: str) -> str:
    """Make targets read like names, not paths or raw commands."""
    if not target:
        return ""
    if etype in ("read", "edit"):
        # "Edited /Users/.../tools/gui_tailer.py" -> "Edited gui_tailer.py"
        return target.rsplit("/", 1)[-1]
    if etype in ("run", "test"):
        # Drop leading "cd /path &&" so the command reads clean.
        prev = None
        while prev != target:
            prev = target
            target = CD_PREFIX_RE.sub("", target)
        return target[:200]
    return target


def map_event(o: dict, session_id: str):
    """Return a gui event dict for one session event, or None."""
    t = o.get("type")
    d = o.get("data") or {}
    ts = o.get("timestamp") or now_iso()
    base = {"t": ts, "agent": "main", "auto": True, "session": session_id}

    if t == "tool.execution_start":
        tool = d.get("toolName", "")
        etype, _ = TOOL_MAP.get(tool, (None, None))
        if etype is None:
            return None
        target = target_from(tool, d.get("arguments") or {})
        if etype == "run" and is_inspect(target):
            return None  # looking around, not doing work
        if etype == "run" and TEST_RE.search(target):
            etype = "test"
        return {**base, "type": etype, "target": shorten(etype, target)}

    if t == "tool.execution_complete":
        if d.get("success"):
            return None  # only failures are interesting
        return {**base, "type": "run", "ok": False,
                "target": "tool call failed"}

    if t == "user.message":
        content = d.get("content", "")
        return {**base, "agent": "user", "type": "prompt",
                "target": str(content)[:200]}

    if t == "assistant.message":
        content = str(d.get("content", ""))
        if len(content) < MIN_MESSAGE_LEN:
            return None  # short narration, not a real update
        return {**base, "type": "message", "target": content[:200]}

    # Turn boundaries are bookkeeping; the feed reads fine without them.
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-dir", required=True,
                    help="path to ~/.copilot/session-state/<session-id>")
    ap.add_argument("--project", required=True,
                    help="project root containing .claude-gui/")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    session_dir = Path(args.session_dir).expanduser()
    src = session_dir / "events.jsonl"
    gui = Path(args.project).expanduser() / ".claude-gui"
    session_id = session_dir.name
    state = gui / "tailer.offset"

    offset = 0
    if state.exists():
        try:
            offset = int(state.read_text().strip() or 0)
        except ValueError:
            offset = 0

    while True:
        try:
            if src.exists():
                size = src.stat().st_size
                if size < offset:
                    offset = 0  # file was truncated/rotated
                if size > offset:
                    with src.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    for line in chunk.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ev = map_event(o, session_id)
                        if ev:
                            append_event(gui, ev)
                    state.parent.mkdir(parents=True, exist_ok=True)
                    state.write_text(str(offset), encoding="utf-8")
        except Exception as e:
            print(f"gui_tailer: {e}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
