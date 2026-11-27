#!/usr/bin/env python3
"""claude_gui_hook.py — automatic events.jsonl emitter for the claude-gui viewer.

Wired as a Claude Code hook (settings.json, see BOOTSTRAP.md step 5). On each
lifecycle event it reads the JSON payload from stdin and appends a matching
line to .claude-gui/events.jsonl, then bumps the heartbeat. The viewer polls
that file every second, so the page updates live with no manual logging.

Design rules (same contract as copilot_gui_hook.py):
  * Fail-open: any error is swallowed (exit 0) so the hook never blocks a turn.
  * Writes only to .claude-gui/ — never touches source files.
  * Secrets in commands are redacted at write time (the log is shareable).
  * Test runs carry the tri-state `ok` (True/False/None) plus passed/failed
    counts and failure names, so the viewer can show green/red/grey.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 200_000
KEEP = 400
MAX_TEXT = 160

READ_TOOLS = {"Read", "NotebookRead"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SEARCH_TOOLS = {"Grep", "Glob", "WebSearch", "WebFetch", "ToolSearch"}
AGENT_TOOLS = {"Task", "Agent"}

# Commands that run tests. Loose on purpose: a false positive only adds a
# test run to the page.
TEST_RE = re.compile(
    r"(^|[\s;&|(])(npm|pnpm|yarn|bun)\s+(run\s+)?test\b"
    r"|\b(pytest|jest|vitest|mocha|rspec|phpunit|ctest|tox|nox)\b"
    r"|\b(cargo|go|dotnet|mix|swift|deno)\s+test\b"
    r"|\bnode\s+--test\b"
    r"|\bpython3?\s+-m\s+(pytest|unittest)\b"
    r"|\bmake\s+(test|check)\b"
)

# Summary lines from common runners: (regex, passed group, failed group).
SUMMARIES = [
    (re.compile(r"^# pass (\d+)\s*$.*?^# fail (\d+)", re.M | re.S), 1, 2),  # node:test / TAP
    (re.compile(r"Tests:\s+(?:(\d+) failed, )?(?:\d+ skipped, )?(\d+) passed"), 2, 1),  # jest
    (re.compile(r"Tests\s+(?:(\d+) failed \| )?(\d+) passed"), 2, 1),  # vitest
    (re.compile(r"test result: \w+\. (\d+) passed; (\d+) failed"), 1, 2),  # cargo
    (re.compile(r"(\d+) examples?, (\d+) failures?"), 1, 2),  # rspec (total, failed)
]
PYTEST = re.compile(r"=+ (.*?(?:passed|failed|error).*?) in [\d.]+s")
PYTEST_SHORT = re.compile(r"((?:\d+ passed(?:, \d+ (?:failed|error))?))\b")
FAIL_NAMES = [
    re.compile(r"^not ok \d+ - (.+)$", re.M),   # TAP
    re.compile(r"^FAILED (\S+)", re.M),         # pytest -rf summary
    re.compile(r"^\s*● (.+?)$", re.M),          # jest
    re.compile(r"^--- FAIL: (\S+)", re.M),      # go
    re.compile(r"^test (\S+) \.\.\. FAILED$", re.M),  # cargo
]

# Bug 7 (claude-gui): secrets in bash commands leaked into the event log.
REDACTIONS = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_\.=+/]{8,}"), "Bearer <redacted>"),
    (re.compile(r"(?i)\b(token|api[_-]?key|secret|password|passwd|auth)\b\s*[=:]\s*\S+"), r"\1=<redacted>"),
    (re.compile(r"\b[A-Za-z0-9+.\-]+://[^/\s:@]+:[^/\s@]+@"), "<scheme>://<redacted>@"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "<redacted-base64>"),
]


def redact(text: str) -> str:
    for rx, sub in REDACTIONS:
        text = rx.sub(sub, text)
    return text


def short(s, n: int = MAX_TEXT) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def rel(path, root: str) -> str | None:
    """Project-relative path; files outside the project become ../<basename>."""
    if not path:
        return None
    try:
        a, b = os.path.abspath(path), os.path.abspath(root)
        if os.path.commonpath([a, b]) == b:
            return os.path.relpath(a, b)
        return os.path.join("..", os.path.basename(path))
    except ValueError:
        return os.path.basename(path)


def is_test_command(cmd: str) -> bool:
    return bool(TEST_RE.search(cmd or ""))


def parse_test_output(text: str) -> tuple[int | None, int | None, list[str]]:
    """Return (passed, failed, failure_names) from a runner's output."""
    for rx, pg, fg in SUMMARIES:
        m = rx.search(text or "")
        if m:
            passed = int(m.group(pg))
            failed = int(m.group(fg))
            break
    else:
        m = PYTEST.search(text or "") or PYTEST_SHORT.search(text or "")
        if m:
            summary = m.group(1)
            pm = re.search(r"(\d+) passed", summary)
            fm = re.search(r"(\d+) (?:failed|error)", summary)
            passed = int(pm.group(1)) if pm else None
            failed = int(fm.group(1)) if fm else (0 if pm else None)
        else:
            passed = failed = None
    names: list[str] = []
    for rx in FAIL_NAMES:
        names.extend(rx.findall(text or ""))
    return passed, failed, names[:10]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def gui_dir() -> Path:
    cwd = Path(os.environ.get("CLAUDE_GUI_CWD") or Path.cwd())
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


def in_state_dir(path: str, root: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.abspath(os.path.join(root, path)),
             os.path.abspath(os.path.join(root, ".claude-gui"))]) == os.path.abspath(
                os.path.join(root, ".claude-gui"))
    except ValueError:
        return False


def output_of(data: dict) -> str:
    out = data.get("tool_response")
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        return str(out.get("stdout") or out.get("content") or "")
    return ""


def to_event(data: dict, root: str) -> dict | None:
    name = data.get("hook_event_name")
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}

    if name == "UserPromptSubmit":
        return {"agent": "user", "type": "prompt",
                "target": short(redact(str(data.get("prompt") or "")))}

    if name == "PreToolUse" and tool in AGENT_TOOLS:
        target = ti.get("subagent_type") or ti.get("name") or "general-purpose"
        return {"agent": "main", "type": "spawn", "target": str(target)}

    if name == "SubagentStop":
        return {"agent": "main", "type": "done", "target": "subagent finished"}

    if name == "Stop":
        return {"agent": "main", "type": "stop", "target": "turn finished"}

    if tool == "Bash" and is_test_command(ti.get("command")):
        cmd = redact(short(ti.get("command"), 80))
        if name == "PreToolUse":
            return {"agent": "main", "type": "test", "target": cmd, "ok": None}
        if name in ("PostToolUse", "PostToolUseFailure"):
            passed, failed, names = parse_test_output(output_of(data))
            # Tri-state: a real count decides; a crashed exit is a failure;
            # anything else is "unknown" (None) so the viewer shows it grey.
            if failed is not None or passed is not None:
                ok = not failed
            elif name == "PostToolUseFailure":
                ok = False
            else:
                ok = None
            ev = {"agent": "main", "type": "test", "target": cmd,
                  "ok": ok, "passed": passed, "failed": failed,
                  "failures": names}
            if ok is None:
                ev["runner"] = "unsupported"
            return ev

    if name != "PostToolUse":
        return None

    if tool in EDIT_TOOLS or tool in READ_TOOLS:
        path = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
        target = rel(path, root)
        if path and in_state_dir(path, root):
            if tool in READ_TOOLS:
                return None  # reading its own state file is noise
            return {"agent": "main", "type": "state", "target": target}
        return {"agent": "main", "type": "edit" if tool in EDIT_TOOLS else "read",
                "target": target}

    if tool == "Bash":
        cmd = ti.get("command", "")
        if "events.jsonl" in cmd or "artifact_state.py" in cmd:
            return None  # Claude logging its own events by shell
        return {"agent": "main", "type": "run",
                "target": redact(short(cmd, 80))}

    if tool in SEARCH_TOOLS:
        q = ti.get("pattern") or ti.get("query") or ti.get("url") or ""
        return {"agent": "main", "type": "search", "target": short(q, 80)}

    if tool.startswith("mcp__"):
        op = tool.split("__", 2)[-1]
        if op in ("post_message", "send_message", "message_coordinator", "message_thread"):
            return {"agent": "main", "type": "message",
                    "target": short(ti.get("text") or ti.get("message"))}
        if op == "create_pull_request":
            return {"agent": "main", "type": "pr",
                    "target": short(str(ti.get("head") or "")),
                    "text": short(ti.get("title"))}
        return {"agent": "main", "type": "run", "target": op}

    return None


def handle(payload: dict) -> None:
    gui = gui_dir()
    root = str(gui.parent)
    ev = to_event(payload, root)
    if ev is None:
        return
    ev["t"] = now_iso()
    ev["auto"] = True
    session = payload.get("session_id")
    if session:
        ev["session"] = session
    append_event(gui, ev)


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
