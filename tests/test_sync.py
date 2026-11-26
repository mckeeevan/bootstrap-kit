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


SKILL_MD = """---
name: commit
description: "Write a conventional commit."
---

# Commit

- Imperative subject.
"""

AGENT_MD = """---
name: tester
description: "Runs the test suite and reports failures."
---

# Tester

- Run pytest.
"""


def make_repo(tmp_path: Path, profile: str | None = None,
              stacks: bool = False, skills: bool = False, agents: bool = False) -> Path:
    (tmp_path / ".agents" / "rules").mkdir(parents=True)
    (tmp_path / ".agents" / "rules" / "always.md").write_text(RULE_ALWAYS)
    (tmp_path / ".agents" / "rules" / "python.md").write_text(RULE_GLOB)
    (tmp_path / ".agents" / "rules" / "commits.md").write_text(RULE_MANUAL)
    if stacks:
        (tmp_path / "stacks" / "base" / "rules").mkdir(parents=True)
        (tmp_path / "stacks" / "base" / "rules" / "coding.md").write_text(RULE_GLOB)
    if skills:
        (tmp_path / ".agents" / "skills" / "commit").mkdir(parents=True)
        (tmp_path / ".agents" / "skills" / "commit" / "SKILL.md").write_text(SKILL_MD)
    if agents:
        (tmp_path / ".agents" / "agents").mkdir(parents=True)
        (tmp_path / ".agents" / "agents" / "tester.md").write_text(AGENT_MD)
    if profile is None:
        profile = "tools: [claude, copilot, antigravity, qwen, codex]\nstacks: [base]\n"
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


# --- Phase 4: stack packs, skills, agents ----------------------------------

def test_stack_rules_flatten_on_emit(tmp_path):
    root = make_repo(tmp_path, stacks=True)
    sync.sync(root)
    # Flattened name: stack-<stack>-<stem> in every per-tool location.
    assert (root / ".claude" / "rules" / "stack-base-coding.md").is_file()
    assert (root / ".github" / "instructions" / "stack-base-coding.instructions.md").is_file()
    # AGENTS.md carries the glob stack rule body (pass-through).
    assert "Annotate." in (root / "AGENTS.md").read_text()


def test_stack_not_in_profile_not_loaded(tmp_path):
    root = make_repo(tmp_path, stacks=True,
                     profile="tools: [claude]\nstacks: [other]\n")
    sync.sync(root)
    assert not (root / ".claude" / "rules" / "stack-base-coding.md").exists()


def test_skills_copied_to_claude_and_recorded(tmp_path):
    root = make_repo(tmp_path, skills=True)
    manifest = sync.sync(root)
    # Claude gets a verbatim copy (with marker).
    out = root / ".claude" / "skills" / "commit" / "SKILL.md"
    assert out.is_file()
    assert sync.GENERATED_MARKER in out.read_text()
    assert "Imperative subject." in out.read_text()
    # Antigravity reads .agents/skills/ in place — no copy, but the source
    # is recorded in the manifest.
    assert ".agents/skills/commit/SKILL.md" in manifest["entries"]
    assert not (root / ".agents" / "skills" / "commit" / "SKILL.md").read_text().startswith(
        sync.GENERATED_MARKER)


def test_agents_emitted_for_claude_copilot_and_agents_md(tmp_path):
    root = make_repo(tmp_path, agents=True)
    sync.sync(root)
    # Claude: .claude/agents/<name>.md
    assert (root / ".claude" / "agents" / "tester.md").is_file()
    # Copilot: .github/agents/<name>.agent.md
    assert (root / ".github" / "agents" / "tester.agent.md").is_file()
    # Codex/AGENTS.md: degraded to a role description section (§4.7).
    agents_md = (root / "AGENTS.md").read_text()
    assert "## Agent Roles" in agents_md
    assert "### tester" in agents_md
    assert "Runs the test suite and reports failures." in agents_md


def test_rules_json_shape_inherits_and_entries(tmp_path):
    root = make_repo(tmp_path, stacks=True)
    sync.sync(root)
    import json
    index = json.loads((root / ".agents" / "rules.json").read_text())
    assert index["inherits"] == [{"path": "~/.config/bootstrap-kit/rules.json"}]
    entries = index["entries"]
    assert entries[0]["path"] == ".agents/rules"
    include = entries[0]["include_only"]
    assert "stack-base-coding" in include
    assert "python" in include
    assert include == sorted(include)


def test_lint_validates_stack_rule_frontmatter(tmp_path):
    root = make_repo(tmp_path, stacks=True)
    # Break a stack rule's frontmatter — lint must flag it like a root rule.
    p = root / "stacks" / "base" / "rules" / "coding.md"
    p.write_text(p.read_text().replace("trigger: glob", "trigger: globby"))
    res = lint.lint(root)
    assert not res.ok
    assert any("[1]" in e and "stacks/base" in e for e in res.errors)
