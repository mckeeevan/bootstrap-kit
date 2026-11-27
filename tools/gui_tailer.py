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

# Runner summary lines: (regex, group that is passed, group that is failed).
# Mirrors hooks/claude_gui_hook.py so the live tailer and the hook agree on
# what a test run's output means.
SUMMARIES = [
    (re.compile(r"^# pass (\d+)\s*$.*?^# fail (\d+)", re.M | re.S), 1, 2),   # node:test / TAP
    (re.compile(r"Tests:\s+(?:(\d+) failed, )?(?:\d+ skipped, )?(\d+) passed"), 2, 1),  # jest
    (re.compile(r"Tests\s+(?:(\d+) failed \| )?(\d+) passed"), 2, 1),        # vitest
    (re.compile(r"test result: \w+\. (\d+) passed; (\d+) failed"), 1, 2),    # cargo
    (re.compile(r"(\d+) examples?, (\d+) failures?"), 1, 2),                 # rspec (total, failed)
]
PYTEST = re.compile(r"=+ (.*?(?:passed|failed|error).*?) in [\d.]+s")
FAIL_NAMES = [
    re.compile(r"^not ok \d+ - (.+)$", re.M),       # TAP
    re.compile(r"^FAILED (\S+)", re.M),             # pytest -rf summary
    re.compile(r"^\s*● (.+?)$", re.M),              # jest
    re.compile(r"^--- FAIL: (\S+)", re.M),          # go
    re.compile(r"^test (\S+) \.\.\. FAILED$", re.M),  # cargo
]


def parse_test_output(text):
    """Pull passed/failed counts and up to 8 failing test names out of runner output."""
    text = text or ""
    passed = failed = None
    for rx, gp, gf in SUMMARIES:
        m = rx.search(text)
        if m:
            passed, failed = int(m.group(gp) or 0), int(m.group(gf) or 0)
            if rx.pattern.startswith("(\\d+) examples"):
                passed -= failed  # rspec reports a total
            break
    if passed is None:
        m = PYTEST.search(text)
        if m:
            counts = dict((k, int(v)) for v, k in re.findall(r"(\d+) (passed|failed|errors?)", m.group(1)))
            passed = counts.get("passed", 0)
            failed = counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    if passed is None:
        # pytest piped through `tail` loses the === separator lines, leaving a
        # bare "1 failed, 17 passed in 0.2s" summary; pull the counts from that
        # line directly.
        m = re.search(r"((?:\d+ \w+, )*\d+ \w+) in [\d.]+s", text)
        if m:
            counts = dict((k, int(v)) for v, k in re.findall(r"(\d+) (passed|failed|errors?)", m.group(1)))
            passed = counts.get("passed", 0)
            failed = counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    names = []
    for rx in FAIL_NAMES:
        for n in rx.findall(text):
            n = n[:120]
            if n not in names:
                names.append(n)
    return passed, failed, names[:8]


def _output_of(d):
    """The tool's output text from a completion event's data dict."""
    res = d.get("result")
    if isinstance(res, dict):
        return str(res.get("content", ""))
    return str(res or "")


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


def humanize(text: str, limit: int = 160) -> str:
    """Make a chat message read like a sentence, not a markdown dump."""
    t = text
    t = re.sub(r"```.*?```", " [code] ", t, flags=re.S)  # code blocks
    t = re.sub(r"`([^`]*)`", r"\1", t)                    # inline code
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)            # images
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)        # links -> label
    # A message that is mostly a bullet list reads as a dump; collapse it to
    # the first line plus a count of the rest. (Detected before the markers
    # are stripped.)
    raw_lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    bullets = [ln for ln in raw_lines
               if ln.startswith(("-", "*", "•")) or re.match(r"^\d+\.\s", ln)]
    if len(bullets) >= 3:
        lead = next((ln for ln in raw_lines if ln not in bullets), "")
        lead = re.sub(r"[*_#>|]+", " ", lead)
        lead = re.sub(r"\s+", " ", lead).strip()
        t = (lead + " " if lead else "") + f"({len(bullets)} items)"
    else:
        t = re.sub(r"[*_#>|]+", " ", t)                   # emphasis/bullets
        t = re.sub(r"\s+", " ", t).strip()

    if len(t) > limit:
        cut = t[:limit]
        # clip at the last real space so we don't cut mid-word
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        t = cut.rstrip(",;:") + "…"
    return t


# Coverage reports the tailer understands, relative to the project root. After a
# test command completes the freshest one (written in the last 15 minutes) is
# reduced to covered/total lines per file and saved as .claude-gui/coverage.json,
# which the viewer maps onto parts through their `paths` globs.
COVERAGE_FILES = [
    "coverage/coverage-summary.json", "coverage/coverage-final.json", "coverage/lcov.info",
    "lcov.info", "coverage.json", "coverage.xml", "coverage/cobertura-coverage.xml",
    "cover.out", "coverage.out",
]


def _read_coverage_report(path: Path) -> dict:
    """Return {file: (covered, total)} for one report file."""
    name = path.name
    if name == "coverage-summary.json":  # istanbul
        data = json.loads(path.read_text(encoding="utf-8"))
        return {f: (v["lines"]["covered"], v["lines"]["total"])
                for f, v in data.items() if f != "total" and isinstance(v, dict) and "lines" in v}
    if name == "coverage.json":  # coverage.py
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, dict):
            raise ValueError("not a coverage.py report")
        return {f: (v["summary"]["covered_lines"], v["summary"]["num_statements"]) for f, v in files.items()}
    if name.endswith(".info"):  # lcov
        out, cur, lf, lh = {}, None, 0, 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("SF:"):
                cur, lf, lh = line[3:], 0, 0
            elif line.startswith("LF:"):
                lf = int(line[3:] or 0)
            elif line.startswith("LH:"):
                lh = int(line[3:] or 0)
            elif line == "end_of_record" and cur:
                out[cur] = (lh, lf)
                cur = None
        return out
    raise ValueError(f"unsupported coverage format: {name}")


def collect_coverage(project: Path, gui: Path, max_age: int = 900) -> bool:
    """Write .claude-gui/coverage.json from the freshest report, if there is one."""
    now = time.time()
    found = [project / f for f in COVERAGE_FILES if (project / f).is_file()]
    found = [f for f in found if now - f.stat().st_mtime < max_age]
    if not found:
        return False
    src = max(found, key=lambda f: f.stat().st_mtime)
    files = {}
    for f, (covered, total) in _read_coverage_report(src).items():
        if total:
            # Report keys are project-relative strings (coverage.py, istanbul, lcov).
            # Absolute paths (some lcov variants) are made relative; outside-project
            # paths are dropped rather than leaking into the shareable state.
            p = Path(f)
            if p.is_absolute():
                try:
                    p = p.relative_to(project)
                except ValueError:
                    continue
            files[p.as_posix()] = [int(covered), int(total)]
    if not files:
        return False
    out = {"t": now_iso(), "source": src.name, "files": files}
    (gui / "coverage.json").write_text(json.dumps(out), encoding="utf-8")
    return True


def map_event(o: dict, session_id: str, pending: dict, project: Path = None, gui: Path = None):
    """Return a gui event dict for one session event, or None.

    ``pending`` maps a bash toolCallId to its start info so a test command's
    completion can be matched to the command that produced it and its output
    parsed into ok/passed/failed. ``project``/``gui`` enable coverage
    collection after a test run.
    """
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
            # Remember the command so its completion can be parsed into a
            # real result; emit test_start so the viewer shows it running.
            pending[d.get("toolCallId")] = {
                "target": shorten("test", target), "agent": "main",
                "session": session_id,
            }
            if len(pending) > 500:
                pending.clear()
            return {**base, "type": "test_start", "target": shorten("test", target)}
        return {**base, "type": etype, "target": shorten(etype, target)}

    if t == "tool.execution_complete":
        cid = d.get("toolCallId")
        if cid in pending:
            info = pending.pop(cid)
            passed, failed, names = parse_test_output(_output_of(d))
            # Tri-state: a real count decides; a crashed exit is a failure;
            # anything else is unknown (None) and tagged runner: unsupported.
            if failed is not None or passed is not None:
                ok = not failed
            elif not d.get("success"):
                ok = False
            else:
                ok = None
            ev = {**base, "type": "test", "target": info["target"],
                  "ok": ok, "passed": passed, "failed": failed, "failures": names}
            if ok is None:
                ev["runner"] = "unsupported"
            if project is not None and gui is not None:
                try:
                    collect_coverage(project, gui)
                except Exception:
                    pass  # a broken or unknown report never stops the run from being logged
            return ev
        if d.get("success"):
            return None  # only failures are interesting
        return {**base, "type": "run", "ok": False,
                "target": "tool call failed"}

    if t == "user.message":
        content = str(d.get("content", ""))
        return {**base, "agent": "user", "type": "prompt",
                "target": humanize(content)}

    if t == "assistant.message":
        content = str(d.get("content", ""))
        if len(content) < MIN_MESSAGE_LEN:
            return None  # short narration, not a real update
        return {**base, "type": "message", "target": humanize(content)}

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

    pending = {}  # toolCallId -> start info for in-flight test commands

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
                        ev = map_event(o, session_id, pending,
                                       project=Path(args.project).expanduser(), gui=gui)
                        if ev:
                            append_event(gui, ev)
                    state.parent.mkdir(parents=True, exist_ok=True)
                    state.write_text(str(offset), encoding="utf-8")
        except Exception as e:
            print(f"gui_tailer: {e}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
