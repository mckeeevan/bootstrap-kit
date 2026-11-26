"""Tests for sync/lint.py — one test per §5 hard fail condition.

Each test builds a minimal repo tree in a tmp dir, runs lint, and asserts the
specific condition fires. A final test asserts a clean tree passes and that
--fix never touches .agents/.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sync"))
import lint  # noqa: E402

VALID_RULE = """---
trigger: always_on
description: "A rule."
---
Body.
"""


def make_repo(tmp_path: Path, rules: dict[str, str] | None = None,
              agents_md: str | None = None) -> Path:
    (tmp_path / ".agents" / "rules").mkdir(parents=True)
    (tmp_path / "sync").mkdir()
    if agents_md is not None:
        (tmp_path / ".agents" / "AGENTS.md").write_text(agents_md)
    for name, content in (rules or {}).items():
        (tmp_path / ".agents" / "rules" / name).write_text(content)
    return tmp_path


def run(root: Path, **kw):
    return lint.lint(root, **kw)


# --- condition 1: frontmatter / trigger ------------------------------------

def test_c1_missing_frontmatter(tmp_path):
    root = make_repo(tmp_path, {"a.md": "no frontmatter here\n"})
    res = run(root)
    assert not res.ok
    assert any("[1]" in e and "missing frontmatter" in e for e in res.errors)


def test_c1_missing_trigger(tmp_path):
    root = make_repo(tmp_path, {"a.md": '---\ndescription: "x"\n---\nBody\n'})
    res = run(root)
    assert any("[1]" in e and "missing 'trigger'" in e for e in res.errors)


@pytest.mark.parametrize("bad", ["alwaysOn", "modelDecision", "GLOB", "auto"])
def test_c1_unrecognised_trigger(tmp_path, bad):
    root = make_repo(tmp_path, {"a.md": f'---\ntrigger: {bad}\n---\nBody\n'})
    res = run(root)
    assert any("[1]" in e and "unrecognised trigger" in e for e in res.errors)


# --- condition 2: frontmatter in AGENTS.md ---------------------------------

def test_c2_frontmatter_in_agents_md(tmp_path):
    root = make_repo(tmp_path, agents_md='---\ntrigger: always_on\n---\n# hi\n')
    res = run(root)
    assert any("[2]" in e and "AGENTS.md" in e for e in res.errors)


# --- condition 3: nested rule files ----------------------------------------

def test_c3_nested_rules(tmp_path):
    root = make_repo(tmp_path, {"a.md": VALID_RULE})
    (root / ".agents" / "rules" / "frontend").mkdir()
    (root / ".agents" / "rules" / "frontend" / "react.md").write_text(VALID_RULE)
    res = run(root)
    assert any("[3]" in e and "nested" in e for e in res.errors)


# --- condition 4: size limits ----------------------------------------------

def test_c4_file_too_large(tmp_path):
    big = VALID_RULE + "x" * 25_000
    root = make_repo(tmp_path, {"a.md": big})
    res = run(root)
    assert any("[4]" in e and "bytes" in e for e in res.errors)


def test_c4_aggregate_always_on_over_budget(tmp_path):
    # ~20k tokens ≈ 80k chars of always-on body.
    body = VALID_RULE + ("word " * 20_000)
    root = make_repo(tmp_path, {"a.md": body})
    res = run(root)
    assert any("[4]" in e and "aggregate" in e for e in res.errors)


# --- condition 5: description ----------------------------------------------

def test_c5_description_required_for_model_decision(tmp_path):
    root = make_repo(tmp_path, {"a.md": "---\ntrigger: model_decision\n---\nBody\n"})
    res = run(root)
    assert any("[5]" in e and "required" in e for e in res.errors)


def test_c5_missing_description_is_warning_only(tmp_path):
    root = make_repo(tmp_path, {"a.md": "---\ntrigger: always_on\n---\nBody\n"})
    res = run(root)
    assert res.ok  # warning, not error
    assert any("[5]" in w for w in res.warnings)


# --- condition 6: globs -----------------------------------------------------

def test_c6_globs_required_for_glob_trigger(tmp_path):
    root = make_repo(tmp_path, {"a.md": '---\ntrigger: glob\ndescription: "x"\n---\nBody\n'})
    res = run(root)
    assert any("[6]" in e and "globs" in e for e in res.errors)


# --- condition 7: unknown keys ---------------------------------------------

def test_c7_unknown_frontmatter_key(tmp_path):
    root = make_repo(tmp_path, {"a.md": '---\ntrigger: always_on\nbogus: 1\n---\nBody\n'})
    res = run(root)
    assert any("[7]" in e and "bogus" in e for e in res.errors)


# --- condition 8: manifest drift -------------------------------------------

def test_c8_manifest_drift(tmp_path):
    import hashlib, json
    root = make_repo(tmp_path, {"a.md": VALID_RULE})
    out = root / ".claude" / "rules" / "a.md"
    out.parent.mkdir(parents=True)
    out.write_text(lint.GENERATED_MARKER + "\nBody.\n")
    manifest = {"entries": {".agents/rules/a.md": {
        "source_hash": "x",
        "outputs": {".claude/rules/a.md": "deadbeef" * 8},
    }}}
    (root / "sync" / "manifest.json").write_text(json.dumps(manifest))
    res = run(root)
    assert any("[8]" in e and "drift" in e for e in res.errors)


# --- condition 9: hand-edited generated file -------------------------------

def test_c9_hand_edited_generated_file(tmp_path):
    import json
    root = make_repo(tmp_path, {"a.md": VALID_RULE})
    out = root / ".claude" / "rules" / "a.md"
    out.parent.mkdir(parents=True)
    out.write_text("I edited this by hand, no marker\n")
    manifest = {"entries": {".agents/rules/a.md": {
        "source_hash": "x",
        "outputs": {".claude/rules/a.md": "deadbeef" * 8},
    }}}
    (root / "sync" / "manifest.json").write_text(json.dumps(manifest))
    res = run(root)
    assert any("[9]" in e and "hand-edited" in e for e in res.errors)


# --- --fix never touches .agents/ ------------------------------------------

def test_fix_never_touches_agents(tmp_path):
    import json
    root = make_repo(tmp_path, {"a.md": VALID_RULE})
    out = root / ".claude" / "rules" / "a.md"
    out.parent.mkdir(parents=True)
    out.write_text("stale\n")
    manifest = {"entries": {".agents/rules/a.md": {
        "source_hash": "x",
        "outputs": {".claude/rules/a.md": "deadbeef" * 8},
    }}}
    (root / "sync" / "manifest.json").write_text(json.dumps(manifest))
    before = (root / ".agents" / "rules" / "a.md").read_text()
    res = run(root, fix=True)
    after = (root / ".agents" / "rules" / "a.md").read_text()
    assert before == after, "--fix must never rewrite canonical .agents/ files"
    # and it regenerated the drifted generated file
    assert lint.GENERATED_MARKER in out.read_text()


# --- clean tree passes ------------------------------------------------------

def test_clean_tree_passes(tmp_path):
    root = make_repo(tmp_path, {
        "core.md": VALID_RULE,
        "py.md": '---\ntrigger: glob\ndescription: "py"\nglobs: "*.py"\n---\nBody\n',
    }, agents_md="# AGENTS.md\npointer only\n")
    res = run(root)
    assert res.ok, res.errors
    assert any("coverage report" in r for r in res.report)
