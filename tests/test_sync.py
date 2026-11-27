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


# --- Phase 7a: tier rendering (§4.6) ---------------------------------------

def _sync_tier(tmp_path: Path, tier: str) -> Path:
    root = make_repo(tmp_path,
                     profile=f"tools: [claude, copilot, antigravity, qwen, codex]\n"
                             f"model:\n  tier: {tier}\n")
    sync.sync(root)
    return root


def test_three_tiers_emit_three_distinct_trees(tmp_path):
    trees = {}
    for i, tier in enumerate(["frontier", "mid", "small"]):
        trees[tier] = snapshot(_sync_tier(tmp_path / f"t{i}", tier))
    # Every root file differs across tiers (preamble + pointer vs body).
    for rel in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "QWEN.md",
                ".github/copilot-instructions.md"]:
        assert trees["frontier"][rel] != trees["mid"][rel], rel
        assert trees["frontier"][rel] != trees["small"][rel], rel
        assert trees["mid"][rel] != trees["small"][rel], rel


def test_frontier_is_pointer_only_mid_inlines_body(tmp_path):
    frontier = _sync_tier(tmp_path / "f", "frontier")
    mid = _sync_tier(tmp_path / "m", "mid")
    f_claude = (frontier / "CLAUDE.md").read_text()
    m_claude = (mid / "CLAUDE.md").read_text()
    # Frontier: no inlined rule body, just a pointer at the canonical source.
    assert "Do the thing." not in f_claude
    assert "See `.agents/rules/always.md` (canonical source — read on demand)." in f_claude
    # Mid: the full body is inlined.
    assert "Do the thing." in m_claude
    # Same for the AGENTS.md family.
    f_agents = (frontier / "AGENTS.md").read_text()
    m_agents = (mid / "AGENTS.md").read_text()
    assert "Do the thing." not in f_agents
    assert "Do the thing." in m_agents


def test_tier_preamble_in_every_root_file(tmp_path):
    root = _sync_tier(tmp_path, "small")
    for rel in ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "QWEN.md",
                ".github/copilot-instructions.md"]:
        assert "Tier: **small**" in (root / rel).read_text(), rel


def test_all_three_tiers_lint_clean(tmp_path):
    for i, tier in enumerate(["frontier", "mid", "small"]):
        root = _sync_tier(tmp_path / f"t{i}", tier)
        res = lint.lint(root)
        assert res.ok, f"{tier}: {res.errors}"


def test_tier_idempotent_second_run_zero_diff(tmp_path):
    root = _sync_tier(tmp_path, "frontier")
    first = snapshot(root)
    sync.sync(root)
    assert first == snapshot(root)


def test_tier_min_filters_rules_above_tier(tmp_path):
    # A rule with tier_min: frontier must not appear when tier is small.
    root = make_repo(tmp_path, profile="tools: [claude]\nmodel:\n  tier: small\n")
    (root / ".agents" / "rules" / "big.md").write_text(
        "---\ntrigger: always_on\ndescription: \"Big model only.\"\n"
        "tools: [claude]\ntier_min: frontier\n---\n\n# Big\n\n- Frontier only.\n")
    sync.sync(root)
    claude = (root / "CLAUDE.md").read_text()
    assert "## big" not in claude
    # Same rule appears at tier: frontier.
    root2 = make_repo(tmp_path / "big", profile="tools: [claude]\nmodel:\n  tier: frontier\n")
    (root2 / ".agents" / "rules" / "big.md").write_text(
        "---\ntrigger: always_on\ndescription: \"Big model only.\"\n"
        "tools: [claude]\ntier_min: frontier\n---\n\n# Big\n\n- Frontier only.\n")
    sync.sync(root2)
    # Present at frontier — as a pointer (frontier is pointer-only).
    assert "See `.agents/rules/big.md` (canonical source — read on demand)." in (
        root2 / "CLAUDE.md").read_text()


# --- Phase 7c: read-only notice for tools without an emitter (§4.8) ---------

def test_read_only_notice_for_tools_without_emitter(tmp_path, capsys):
    root = make_repo(tmp_path)  # all five tools
    sync.sync(root)
    out = capsys.readouterr().out
    for tool in ("antigravity", "qwen", "codex"):
        assert f"degrade: {tool} has no events.jsonl emitter" in out, tool
        assert "viewer is read-only in this tool" in out
    # Tools with an emitter are not flagged.
    assert "degrade: claude has no events.jsonl emitter" not in out
    assert "degrade: copilot has no events.jsonl emitter" not in out


def test_no_read_only_notice_when_only_emitter_tools(tmp_path, capsys):
    root = make_repo(tmp_path, profile="tools: [claude, copilot]\n")
    sync.sync(root)
    out = capsys.readouterr().out
    assert "read-only" not in out
