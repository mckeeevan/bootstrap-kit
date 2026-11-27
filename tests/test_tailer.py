"""Tests for tools/gui_tailer.py — the live session tailer.

Covers the parts classifier (collect_parts / _iter_parts): resolving each
structure part's ``paths`` globs to real files and marking a part exempt from
tests when all of its files are non-code (docs/config/data).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import gui_tailer  # noqa: E402


# --- _iter_parts ------------------------------------------------------------

def test_iter_parts_flattens_nested():
    structure = [
        {"id": "a", "children": [
            {"id": "a1"},
            {"id": "a2", "children": [{"id": "a21"}]},
        ]},
        {"id": "b"},
    ]
    ids = [n["id"] for n in gui_tailer._iter_parts(structure)]
    assert ids == ["a", "a1", "a2", "a21", "b"]


def test_iter_parts_skips_non_dicts_and_missing():
    assert list(gui_tailer._iter_parts(None)) == []
    assert list(gui_tailer._iter_parts([{"id": "x"}])) == [{"id": "x"}]


# --- collect_parts ----------------------------------------------------------

def _write_state(gui: Path, structure):
    import yaml
    (gui / "state.yaml").write_text(
        yaml.safe_dump({"structure": structure}), encoding="utf-8")


def test_collect_parts_classifies_exempt(tmp_path):
    project, gui = tmp_path / "proj", tmp_path / "proj" / ".claude-gui"
    gui.mkdir(parents=True)
    # A code part and a docs part, with real files on disk.
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("x = 1\n")
    (project / "docs").mkdir()
    (project / "docs" / "guide.md").write_text("# hi\n")
    _write_state(gui, [
        {"id": "code", "paths": ["src/*.py"]},
        {"id": "docs", "paths": ["docs/*.md"]},
    ])
    assert gui_tailer.collect_parts(project, gui) is True
    out = json.loads((gui / "parts.json").read_text(encoding="utf-8"))
    assert out["parts"]["code"]["exempt"] is False
    assert out["parts"]["code"]["files"] == ["src/app.py"]
    assert out["parts"]["docs"]["exempt"] is True
    assert out["parts"]["docs"]["files"] == ["docs/guide.md"]


def test_collect_parts_mixed_files_not_exempt(tmp_path):
    project, gui = tmp_path / "proj", tmp_path / "proj" / ".claude-gui"
    gui.mkdir(parents=True)
    (project / "m").mkdir()
    (project / "m" / "a.py").write_text("x = 1\n")
    (project / "m" / "b.md").write_text("# hi\n")
    _write_state(gui, [{"id": "mixed", "paths": ["m/*"]}])
    gui_tailer.collect_parts(project, gui)
    out = json.loads((gui / "parts.json").read_text(encoding="utf-8"))
    # One code file means the part is NOT exempt.
    assert out["parts"]["mixed"]["exempt"] is False


def test_collect_parts_no_files_skipped(tmp_path):
    project, gui = tmp_path / "proj", tmp_path / "proj" / ".claude-gui"
    gui.mkdir(parents=True)
    # A part whose globs resolve to nothing is omitted entirely: the viewer
    # then defaults it to "no tests" (tests expected), which is right for code.
    _write_state(gui, [{"id": "empty", "paths": ["nothing/*.py"]}])
    assert gui_tailer.collect_parts(project, gui) is False
    assert not (gui / "parts.json").exists()


def test_collect_parts_skips_pycache(tmp_path):
    project, gui = tmp_path / "proj", tmp_path / "proj" / ".claude-gui"
    gui.mkdir(parents=True)
    (project / "src" / "__pycache__").mkdir(parents=True)
    (project / "src" / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"")
    (project / "src" / "app.py").write_text("x = 1\n")
    _write_state(gui, [{"id": "code", "paths": ["src/**/*.py*"]}])
    gui_tailer.collect_parts(project, gui)
    out = json.loads((gui / "parts.json").read_text(encoding="utf-8"))
    assert out["parts"]["code"]["files"] == ["src/app.py"]


def test_collect_parts_missing_state_returns_false(tmp_path):
    project, gui = tmp_path / "proj", tmp_path / "proj" / ".claude-gui"
    gui.mkdir(parents=True)
    assert gui_tailer.collect_parts(project, gui) is False
    assert not (gui / "parts.json").exists()


def test_collect_parts_bad_yaml_returns_false(tmp_path):
    project, gui = tmp_path / "proj", tmp_path / "proj" / ".claude-gui"
    gui.mkdir(parents=True)
    (gui / "state.yaml").write_text(":\n  - not: [valid", encoding="utf-8")
    assert gui_tailer.collect_parts(project, gui) is False


def test_collect_parts_no_paths_key_skipped(tmp_path):
    project, gui = tmp_path / "proj", tmp_path / "proj" / ".claude-gui"
    gui.mkdir(parents=True)
    _write_state(gui, [{"id": "nopaths"}])
    assert gui_tailer.collect_parts(project, gui) is False


# --- extension classification ----------------------------------------------

def test_non_code_exts_covers_docs_and_config():
    assert ".md" in gui_tailer.NON_CODE_EXTS
    assert ".yaml" in gui_tailer.NON_CODE_EXTS
    assert ".json" in gui_tailer.NON_CODE_EXTS
    assert ".py" not in gui_tailer.NON_CODE_EXTS
    assert ".js" not in gui_tailer.NON_CODE_EXTS
