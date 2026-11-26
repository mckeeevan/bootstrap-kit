#!/usr/bin/env python3
"""gui.py — keep bootstrap-kit/.claude-gui current while the agent works.

Usage:
  python3 tools/gui.py event <type> <target> [node] [note] [--agent main]
  python3 tools/gui.py test <suite> <passed> <failed> [node]
  python3 tools/gui.py heartbeat

Types: prompt|read|edit|run|search|spawn|done|message|pr|test|note|state|stop
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / ".claude-gui"
EVENTS = GUI / "events.jsonl"
HEARTBEAT = GUI / "heartbeat"
MAX_BYTES = 200_000


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_event(**kw) -> None:
    GUI.mkdir(parents=True, exist_ok=True)
    line = json.dumps(kw, separators=(",", ":"))
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    # rotate past 200KB: keep last 400 lines
    if EVENTS.stat().st_size > MAX_BYTES:
        lines = EVENTS.read_text(encoding="utf-8").splitlines()
        (GUI / "history").mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (GUI / "history" / f"events-{stamp}.jsonl").write_text(
            "\n".join(lines[:-400]) + "\n", encoding="utf-8"
        )
        EVENTS.write_text("\n".join(lines[-400:]) + "\n", encoding="utf-8")
    HEARTBEAT.write_text(now_iso(), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "event":
        etype, target = sys.argv[2], sys.argv[3]
        node = sys.argv[4] if len(sys.argv) > 4 else None
        note = sys.argv[5] if len(sys.argv) > 5 else None
        agent = "main"
        if "--agent" in sys.argv:
            agent = sys.argv[sys.argv.index("--agent") + 1]
        ev = {"t": now_iso(), "agent": agent, "type": etype, "target": target, "auto": False}
        if node:
            ev["node"] = node
        if note:
            ev["note"] = note
        append_event(**ev)
    elif cmd == "test":
        suite, passed, failed = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
        node = sys.argv[5] if len(sys.argv) > 5 else None
        ev = {"t": now_iso(), "agent": "main", "type": "test", "target": suite,
              "ok": failed == 0, "passed": passed, "failed": failed, "auto": False}
        if node:
            ev["node"] = node
        append_event(**ev)
    elif cmd == "heartbeat":
        HEARTBEAT.write_text(now_iso(), encoding="utf-8")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
