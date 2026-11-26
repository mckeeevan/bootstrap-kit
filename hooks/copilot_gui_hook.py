#!/usr/bin/env python3
"""copilot_gui_hook.py — automatic events.jsonl emitter for the claude-gui viewer.

Wired as a Copilot CLI hook (see .github/hooks/copilot-gui.json). On each
lifecycle event it reads the JSON payload from stdin and appends a matching
line to .claude-gui/events.jsonl, then bumps the heartbeat. The viewer polls
that file every second, so the page updates live with no manual logging.

Design rules:
  * Fail-open: any error is swallowed (exit 0) so the hook never blocks a turn.
  * Handles both camelCase and VS Code snake_case payload field names.
  * Writes only to .claude-gui/ — never touches source files.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 200_000
KEEP = 400

# tool name -> (event type, which arg holds the target).
# Conceptual work only: reads, edits, runs, spawns. Searches and web lookups
# are exploration churn and are dropped on purpose (same policy as
# tools/gui_tailer.py).
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

TEST_RE = re.compile(
    r"\b(pytest|npm\s+test|jest|vitest|cargo\s+test|go\s+test|node\s+--test|"
    r"phpunit|rspec|make\s+test|dotnet\s+test)\b"
)

# Shell commands that are just looking around (ls, grep, cat, git status...)
# rather than doing work. Same policy as tools/gui_tailer.py.
INSPECT_RE = re.compile(
    r"^\s*(ls|ll|pwd|cat|head|tail|less|more|file|stat|wc|which|echo|printf|sleep|"
    r"grep|rg|find|tree|du|df|ps|top|env|printenv|date|uname|whoami|hostname|"
    r"git\s+(status|log|diff|show|branch|remote|ls-files|rev-parse|describe)|"
    r"python3?\s+-c\s+['\"]import\s+json|"
    r"python3?\s+-c\s+['\"][^'\"]*(open\(|read_text|stat\(|Counter\(|json\.loads?))"
)

CD_PREFIX_RE = re.compile(r"^\s*cd\s+\S+\s*(?:&&|;)\s*")


def _segment_is_inspect(seg: str) -> bool:
    seg = seg.strip()
    if not seg:
        return True
    if re.match(r"^cd\s+\S+\s*$", seg):
        return True
    return bool(INSPECT_RE.search(seg))


def is_inspect(cmd: str) -> bool:
    """True if the whole command is just looking around."""
    if "gui_tailer" in cmd:
        return True
    for seg in re.split(r"&&|;", cmd):
        seg = CD_PREFIX_RE.sub("", seg)
        if not _segment_is_inspect(seg):
            return False
    return True


def shorten(etype: str, target: str) -> str:
    """Make targets read like names, not paths or raw commands."""
    if not target:
        return ""
    if etype in ("read", "edit"):
        return target.rsplit("/", 1)[-1]
    if etype in ("run", "test"):
        prev = None
        while prev != target:
            prev = target
            target = CD_PREFIX_RE.sub("", target)
        return target[:200]
    return target


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def get(payload: dict, *names, default=None):
    """Return the first present field among `names` (camelCase or snake_case)."""
    for n in names:
        if n in payload and payload[n] is not None:
            return payload[n]
    return default


def gui_dir() -> Path:
    cwd = Path(os.environ.get("COPILOT_GUI_CWD") or Path.cwd())
    return cwd / ".claude-gui"


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


def handle(payload: dict) -> None:
    gui = gui_dir()
    event_name = get(payload, "hook_event_name", "hookEventName", default="")
    tool = get(payload, "tool_name", "toolName", default="")
    args = get(payload, "tool_input", "toolArgs", default={})
    session = get(payload, "session_id", "sessionId", default="")

    # --- tool lifecycle ----------------------------------------------------
    if event_name in ("PostToolUse", "postToolUse"):
        etype, _ = TOOL_MAP.get(tool, (None, None))
        if etype is None:
            return  # not a tool we track
        target = target_from(tool, args)
        if etype == "run" and is_inspect(target):
            return  # looking around, not doing work
        if etype == "run" and TEST_RE.search(target):
            etype = "test"
        ev = {"t": now_iso(), "agent": "main", "type": etype,
              "target": shorten(etype, target), "auto": True}
        if session:
            ev["session"] = session
        append_event(gui, ev)
        return

    if event_name in ("PostToolUseFailure", "postToolUseFailure"):
        if TOOL_MAP.get(tool) is None:
            return  # only failures of tracked tools are interesting
        ev = {"t": now_iso(), "agent": "main", "type": "run",
              "target": shorten("run", target_from(tool, args)),
              "ok": False, "auto": True}
        err = get(payload, "error", default="")
        if err:
            ev["note"] = str(err)[:200]
        append_event(gui, ev)
        return

    # --- prompts -----------------------------------------------------------
    if event_name in ("UserPromptSubmit", "userPromptSubmitted"):
        prompt = get(payload, "prompt", default="")
        append_event(gui, {"t": now_iso(), "agent": "user", "type": "prompt",
                           "target": str(prompt)[:200], "auto": True})
        return

    # --- subagents ---------------------------------------------------------
    if event_name in ("SubagentStart", "subagentStart"):
        name = get(payload, "agent_name", "agentName", default="")
        append_event(gui, {"t": now_iso(), "agent": "main", "type": "spawn",
                           "target": str(name), "auto": True})
        return
    if event_name in ("SubagentStop", "subagentStop"):
        name = get(payload, "agent_name", "agentName", default="")
        append_event(gui, {"t": now_iso(), "agent": str(name) or "subagent",
                           "type": "done", "target": "subagent finished",
                           "auto": True})
        return

    # --- turn end ----------------------------------------------------------
    # Turn boundaries are bookkeeping; the feed reads fine without them.
    # (Stop / agentStop intentionally not logged.)


def main() -> int:
    try:
        raw = sys.stdin.read()
        if raw.strip():
            handle(json.loads(raw))
    except Exception:
        # fail-open: never block the session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
