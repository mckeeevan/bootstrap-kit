"""Tests for the events.jsonl emitters (Phase 7b acceptance).

Two working emitters are required: hooks/copilot_gui_hook.py (Copilot CLI
hooks) and hooks/claude_gui_hook.py (Claude Code hooks). Both read a JSON
payload from stdin and append one line to .claude-gui/events.jsonl.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import claude_gui_hook  # noqa: E402
import copilot_gui_hook  # noqa: E402


def read_events(gui: Path) -> list[dict]:
    p = gui / "events.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


# --- copilot emitter -------------------------------------------------------

def test_copilot_post_tool_use_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GUI_CWD", str(tmp_path))
    copilot_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "edit",
        "tool_input": {"path": "/x/src/a.py"},
        "session_id": "s1",
    })
    evs = read_events(tmp_path / ".claude-gui")
    assert len(evs) == 1
    ev = evs[0]
    assert ev["type"] == "edit"
    assert ev["target"] == "a.py"
    assert ev["agent"] == "main"
    assert ev["session"] == "s1"
    assert ev["auto"] is True
    assert "t" in ev


def test_copilot_run_reclassified_as_test(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GUI_CWD", str(tmp_path))
    copilot_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "bash",
        "tool_input": {"command": "python3 -m pytest -q"},
    })
    evs = read_events(tmp_path / ".claude-gui")
    assert evs[0]["type"] == "test"


def test_copilot_inspect_commands_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GUI_CWD", str(tmp_path))
    copilot_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "bash",
        "tool_input": {"command": "ls -la && git status"},
    })
    assert read_events(tmp_path / ".claude-gui") == []


def test_copilot_prompt_humanized(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GUI_CWD", str(tmp_path))
    copilot_gui_hook.handle({
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Fix the **bug** in `main.py`\n- a\n- b\n- c\n- d",
    })
    evs = read_events(tmp_path / ".claude-gui")
    assert evs[0]["type"] == "prompt"
    assert evs[0]["agent"] == "user"
    assert "(4 items)" in evs[0]["target"]


def test_copilot_untracked_tool_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GUI_CWD", str(tmp_path))
    copilot_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "some_unknown_tool",
        "tool_input": {"path": "/x"},
    })
    assert read_events(tmp_path / ".claude-gui") == []


def test_copilot_heartbeat_written(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GUI_CWD", str(tmp_path))
    copilot_gui_hook.handle({
        "hook_event_name": "UserPromptSubmit", "prompt": "hi",
    })
    assert (tmp_path / ".claude-gui" / "heartbeat").is_file()


# --- claude emitter --------------------------------------------------------

def test_claude_post_tool_use_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "src" / "a.py")},
        "session_id": "s2",
    })
    evs = read_events(tmp_path / ".claude-gui")
    assert len(evs) == 1
    ev = evs[0]
    assert ev["type"] == "edit"
    assert ev["target"] == "src/a.py"
    assert ev["session"] == "s2"
    assert ev["auto"] is True


def test_claude_test_run_tri_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "python3 -m pytest -q"},
        "tool_response": {"stdout": "5 passed, 2 failed in 1.00s\nFAILED tests/test_a.py::test_x"},
    })
    evs = read_events(tmp_path / ".claude-gui")
    ev = evs[0]
    assert ev["type"] == "test"
    assert ev["ok"] is False
    assert ev["passed"] == 5
    assert ev["failed"] == 2
    assert ev["failures"] == ["tests/test_a.py::test_x"]


def test_claude_test_run_unknown_runner_is_grey(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "tool_response": {"stdout": "some unparseable output"},
    })
    ev = read_events(tmp_path / ".claude-gui")[0]
    assert ev["ok"] is None
    assert ev["runner"] == "unsupported"


def test_claude_test_failure_event_is_red(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "tool_response": {"stdout": ""},
    })
    ev = read_events(tmp_path / ".claude-gui")[0]
    assert ev["type"] == "test"
    assert ev["ok"] is False


def test_claude_secret_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "curl -H 'Authorization: Bearer abcdefgh12345678' https://x"},
    })
    ev = read_events(tmp_path / ".claude-gui")[0]
    assert "abcdefgh12345678" not in ev["target"]
    assert "<redacted>" in ev["target"]


def test_claude_state_file_edit_is_state_type(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / ".claude-gui" / "state.yaml")},
    })
    ev = read_events(tmp_path / ".claude-gui")[0]
    assert ev["type"] == "state"


def test_claude_self_logging_command_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo x >> .claude-gui/events.jsonl"},
    })
    assert read_events(tmp_path / ".claude-gui") == []


def test_claude_spawn_and_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "PreToolUse",
        "tool_name": "Task",
        "tool_input": {"subagent_type": "explore"},
    })
    claude_gui_hook.handle({"hook_event_name": "Stop"})
    evs = read_events(tmp_path / ".claude-gui")
    assert evs[0]["type"] == "spawn"
    assert evs[0]["target"] == "explore"
    assert evs[1]["type"] == "stop"


def test_claude_prompt_event(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    claude_gui_hook.handle({
        "hook_event_name": "UserPromptSubmit", "prompt": "do the thing",
    })
    ev = read_events(tmp_path / ".claude-gui")[0]
    assert ev["type"] == "prompt"
    assert ev["agent"] == "user"


# --- both emitters: fail-open + rotation ------------------------------------

def test_both_emitters_fail_open_on_bad_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COPILOT_GUI_CWD", str(tmp_path))
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    # main() reads stdin; feed it garbage and it must still exit 0.
    monkeypatch.setattr(sys, "stdin", type("S", (), {"read": staticmethod(lambda: "{not json")})())
    assert copilot_gui_hook.main() == 0
    assert claude_gui_hook.main() == 0


def test_rotation_moves_old_lines_to_history(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_GUI_CWD", str(tmp_path))
    gui = tmp_path / ".claude-gui"
    gui.mkdir(parents=True)
    events = gui / "events.jsonl"
    # Pre-fill past MAX_BYTES with old lines.
    old = [json.dumps({"t": "old", "type": "note",
                       "target": f"n{i}" + "x" * 500})
           for i in range(600)]
    events.write_text("\n".join(old) + "\n")
    claude_gui_hook.handle({
        "hook_event_name": "UserPromptSubmit", "prompt": "new",
    })
    lines = events.read_text().splitlines()
    assert len(lines) <= claude_gui_hook.KEEP + 1
    assert '"target":"new"' in lines[-1]
    hist = list((gui / "history").glob("events-*.jsonl"))
    assert len(hist) == 1
    # 600 old + 1 new = 601 lines; rotation keeps the last KEEP.
    assert len(hist[0].read_text().splitlines()) == 601 - claude_gui_hook.KEEP
