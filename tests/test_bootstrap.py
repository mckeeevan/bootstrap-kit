"""Tests for setup/bootstrap.py — the §8 7-step contract.

Covers the pure helpers (stack detection, repo URL, plan), the file writers
(state skeleton, guard), and the dry-run contract: a dry run must make ZERO
filesystem changes.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "setup"))
import bootstrap  # noqa: E402

PROFILE = """\
tools: [claude, copilot]
model:
  tier: mid
viewer:
  mode: pinned
  pinned_ref: abc123
sources:
  claude_gui: https://github.com/mckeeevan/claude-gui
"""


def make_repo(tmp_path: Path, profile: str = PROFILE) -> Path:
    (tmp_path / "sync").mkdir()
    (tmp_path / "profile.yaml").write_text(profile)
    return tmp_path


# --- detect_stack -----------------------------------------------------------

def test_detect_stack_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    assert bootstrap.detect_stack(tmp_path) == "python-fastapi"


def test_detect_stack_react(tmp_path):
    (tmp_path / "package.json").write_text("{}\n")
    assert bootstrap.detect_stack(tmp_path) == "react-ts"


def test_detect_stack_go(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    assert bootstrap.detect_stack(tmp_path) == "go"


def test_detect_stack_base(tmp_path):
    assert bootstrap.detect_stack(tmp_path) == "base"


# --- _repo_url --------------------------------------------------------------

def test_repo_url_plain():
    assert bootstrap._repo_url("https://github.com/o/r") == \
        "https://github.com/o/r.git"


def test_repo_url_strips_tree():
    assert bootstrap._repo_url("https://github.com/o/r/tree/main") == \
        "https://github.com/o/r.git"


def test_repo_url_already_git():
    assert bootstrap._repo_url("https://github.com/o/r.git") == \
        "https://github.com/o/r.git"


# --- build_plan -------------------------------------------------------------

def test_build_plan_six_steps(tmp_path):
    root = make_repo(tmp_path)
    plan = bootstrap.build_plan(root, bootstrap.load_profile(root))
    assert len(plan) == 6
    assert "stack:" in plan[0]
    assert "vendor" in plan[1]
    assert "state.yaml" in plan[4]
    assert "doctor" in plan[5]


# --- file writers -----------------------------------------------------------

def test_write_state_skeleton(tmp_path):
    root = make_repo(tmp_path)
    bootstrap.write_state_skeleton(root)
    state = (root / ".claude-gui" / "state.yaml").read_text()
    assert "version: 1" in state
    assert f"project: {root.name}" in state


def test_write_guard_disabled(tmp_path):
    root = make_repo(tmp_path)
    bootstrap.write_guard(root, bootstrap.load_profile(root), enabled=False)
    guard = (root / ".claude-gui" / "guard.yaml").read_text()
    assert "enabled: false" in guard
    assert "mode: off" in guard


def test_write_guard_enabled(tmp_path):
    profile = PROFILE.replace("  pinned_ref: abc123",
                              "  pinned_ref: abc123\n  guard: sha256")
    root = make_repo(tmp_path, profile=profile)
    bootstrap.write_guard(root, bootstrap.load_profile(root), enabled=True)
    guard = (root / ".claude-gui" / "guard.yaml").read_text()
    assert "enabled: true" in guard
    assert "mode: sha256" in guard


# --- dry-run contract: zero filesystem changes ------------------------------

def test_dry_run_makes_no_changes(tmp_path):
    root = make_repo(tmp_path)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    rc = bootstrap.bootstrap(root, dry_run=True)
    after = sorted(p.relative_to(root) for p in root.rglob("*"))
    assert rc == 0
    assert before == after, "dry run must not create/modify/delete files"


def test_dry_run_prints_plan(capsys, tmp_path):
    root = make_repo(tmp_path)
    bootstrap.bootstrap(root, dry_run=True)
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "vendor" in out


# --- main -------------------------------------------------------------------

def test_main_dry_run(tmp_path):
    root = make_repo(tmp_path)
    rc = bootstrap.main(["--root", str(root), "--dry-run"])
    assert rc == 0


def test_clone_vendor_requires_pinned_ref(tmp_path):
    root = make_repo(tmp_path, profile="tools: [claude]\n")
    profile = bootstrap.load_profile(root)
    with pytest.raises(SystemExit):
        bootstrap.clone_vendor(root, profile)


def test_clone_vendor_requires_source(tmp_path):
    root = make_repo(tmp_path, profile="tools: [claude]\nviewer:\n  pinned_ref: abc\n")
    profile = bootstrap.load_profile(root)
    with pytest.raises(SystemExit):
        bootstrap.clone_vendor(root, profile)


# --- clone_commands: pinned ref is a SHA, not a branch ----------------------

def test_clone_commands_clone_then_checkout(tmp_path):
    vendor = tmp_path / "vendor" / "claude-gui"
    clone_cmd, checkout_cmd = bootstrap.clone_commands(
        "https://github.com/o/r", "abc123", vendor)
    # A commit SHA cannot be passed to `git clone --branch`; clone the default
    # branch and check out the exact ref instead.
    assert clone_cmd == ["git", "clone", "https://github.com/o/r.git", str(vendor)]
    assert "--branch" not in clone_cmd
    assert checkout_cmd == ["git", "checkout", "--quiet", "abc123"]
