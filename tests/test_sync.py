"""Tests for sync/sync.py — Phase 3 acceptance criteria.

Covers: idempotency (second run → zero diff), profile gating (only listed
tools emit), drift detection (hand-edited generated file → lint [8]/[9]),
--clean removing stale files, and the coverage report.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sync"))
import lint  # noqa: E402
import sync  # noqa: E402

RULE_ALWAYS = """---
trigger: always_on
description: "Always-on rule."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Always

- Do the thing.
"""

RULE_GLOB = """---
trigger: glob
description: "Python rule."
globs: "*.py"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Python

- Annotate.
"""

RULE_MANUAL = """---
trigger: manual
description: "Commit rule."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Commits

- Imperative subject.
"""


def make_repo(tmp_path: Path, profile: str | None = None) -> Path:
    (tmp_path / ".agents" / "rules").mkdir(parents=True)
    (tmp_path / ".agents" / "rules" / "always.md").write_text(RULE_ALWAYS)
    (tmp_path / ".agents" / "rules" / "python.md").write_text(RULE_GLOB)
    (tmp_path / ".agents" / "rules" / "commits.md").write_text(RULE_MANUAL)
    if profile is not None:
        (tmp_path / "profile.yaml").write_text(profile)
    return tmp_path


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


# --- idempotency -----------------------------------------------------------

def test_idempotent_second_run_zero_diff(tmp_path):
    root = make_repo(tmp_path)
    sync.sync(root)
    first = snapshot(root)
    sync.sync(root)
    second = snapshot(root)
    assert first == second


# --- profile gating --------------------------------------------------------

def test_only_profile_tools_emit(tmp_path):
    root = make_repo(tmp_path, profile="tools: [claude, copilot]\n")
    sync.sync(root)
    assert (root / "CLAUDE.md").is_file()
    assert (root / ".github" / "copilot-instructions.md").is_file()
    assert not (root / "AGENTS.md").exists()
    assert not (root / "GEMINI.md").exists()
    assert not (root / "QWEN.md").exists()


def test_all_tools_emit_all_outputs(tmp_path):
    root = make_repo(tmp_path)
    sync.sync(root)
    for rel in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "QWEN.md",
                ".github/copilot-instructions.md",
                ".github/instructions/python.instructions.md",
                ".github/prompts/commits.prompt.md",
                ".claude/rules/python.md",
                ".claude/commands/commits.md"]:
        assert (root / rel).is_file(), f"missing {rel}"


def test_agents_md_written_once_for_union(tmp_path):
    root = make_repo(tmp_path)
    sync.sync(root)
    # AGENTS.md contains the always-on rule body (union of AGENTS.md tools).
    assert "Do the thing." in (root / "AGENTS.md").read_text()


# --- drift / hand-edit detection -------------------------------------------

def test_drift_hand_appended_line(tmp_path):
    root = make_repo(tmp_path)
    sync.sync(root)
    (root / "CLAUDE.md").write_text(
        (root / "CLAUDE.md").read_text() + "hand edit\n")
    res = lint.lint(root)
    assert not res.ok
    assert any("[8]" in e for e in res.errors)


def test_hand_edit_stripped_marker(tmp_path):
    root = make_repo(tmp_path)
    sync.sync(root)
    p = root / ".github" / "copilot-instructions.md"
    lines = p.read_text().splitlines(keepends=True)
    p.write_text("".join(lines[1:]))  # strip the generated marker
    res = lint.lint(root)
    assert not res.ok
    assert any("[9]" in e for e in res.errors)


def test_clean_tree_passes_lint(tmp_path):
    root = make_repo(tmp_path)
    sync.sync(root)
    res = lint.lint(root)
    assert res.ok, res.errors


# --- --clean ----------------------------------------------------------------

def test_clean_removes_stale_files(tmp_path):
    root = make_repo(tmp_path)
    sync.sync(root)
    assert (root / "AGENTS.md").is_file()
    (root / "profile.yaml").write_text("tools: [claude, copilot]\n")
    sync.sync(root, clean=True)
    assert not (root / "AGENTS.md").exists()
    assert not (root / "GEMINI.md").exists()
    assert not (root / "QWEN.md").exists()
    assert (root / "CLAUDE.md").is_file()


# --- manifest ----------------------------------------------------------------

def test_manifest_records_outputs(tmp_path):
    root = make_repo(tmp_path)
    manifest = sync.sync(root)
    assert ".agents/rules/python.md" in manifest["entries"]
    entry = manifest["entries"][".agents/rules/python.md"]
    assert entry["source_hash"]
    assert any("python" in out for out in entry["outputs"])
    assert "CLAUDE.md" in manifest["generated"]
