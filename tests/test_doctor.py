"""Tests for setup/doctor.py — the install verifier.

Covers the report printer, the vendor pin check, and the full doctor() run
against a broken and a healthy tmp repo, including the state.yaml freshness
gate (check #7).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "setup"))
import doctor  # noqa: E402


# --- print_report -----------------------------------------------------------

def test_print_report_clean(capsys):
    assert doctor.print_report(["a", "b"], []) == 0
    out = capsys.readouterr().out
    assert "install OK" in out
    assert "FAIL" not in out


def test_print_report_failures(capsys):
    assert doctor.print_report(["a"], ["bad"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  bad" in out
    assert "1 problem(s)" in out


# --- _check_vendor ----------------------------------------------------------

def test_check_vendor_missing(tmp_path):
    ok, msg = doctor._check_vendor(tmp_path, "abc123")
    assert not ok
    assert "missing" in msg


def test_check_vendor_not_git(tmp_path):
    (tmp_path / "vendor" / "claude-gui").mkdir(parents=True)
    ok, msg = doctor._check_vendor(tmp_path, "abc123")
    assert not ok
    # Empty HEAD (not a git checkout) never matches the pinned ref.
    assert "profile pins" in msg


# --- doctor() on a broken repo ----------------------------------------------

def test_doctor_broken_repo(tmp_path):
    rc = doctor.doctor(tmp_path)
    assert rc == 1


def test_doctor_reports_missing_profile(tmp_path, capsys):
    doctor.doctor(tmp_path)
    out = capsys.readouterr().out
    assert "profile.yaml missing" in out


# --- doctor() on a healthy repo ---------------------------------------------

def _healthy_repo(tmp_path: Path) -> Path:
    """A repo that passes every doctor check except the vendor pin."""
    (tmp_path / "sync").mkdir()
    (tmp_path / ".claude-gui").mkdir()
    (tmp_path / "profile.yaml").write_text(
        "tools: [claude]\nmodel:\n  tier: mid\n"
        "viewer:\n  mode: pinned\n  pinned_ref: abc123\n")
    (tmp_path / "sync" / "manifest.json").write_text(
        json.dumps({"entries": {}}))
    (tmp_path / ".claude-gui" / "state.yaml").write_text(
        "version: 1\nupdated: '2026-11-26T20:00:00-05:00'\n")
    (tmp_path / ".claude-gui" / "guard.yaml").write_text(
        "enabled: false\nmode: off\n")
    return tmp_path


def test_doctor_healthy_repo(tmp_path, capsys):
    _healthy_repo(tmp_path)
    rc = doctor.doctor(tmp_path)
    out = capsys.readouterr().out
    # Only the vendor pin should fail (no real git checkout in tmp).
    assert rc == 1
    assert "vendor/claude-gui missing" in out
    assert "guard: enabled=False" in out
    # No events feed yet -> freshness check is skipped, not a failure.
    assert "state.yaml stale" not in out


# --- freshness gate (check #7) ----------------------------------------------

def test_doctor_stale_state_fails(tmp_path, capsys):
    _healthy_repo(tmp_path)
    # updated = 15:00 UTC; feed activity at 22:00 UTC -> 7h stale.
    (tmp_path / ".claude-gui" / "state.yaml").write_text(
        "version: 1\nupdated: '2026-11-26T10:00:00-05:00'\n")
    (tmp_path / ".claude-gui" / "events.jsonl").write_text(
        json.dumps({"t": "2026-11-26T22:00:00+00:00"}) + "\n")
    rc = doctor.doctor(tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "state.yaml stale" in out


def test_doctor_fresh_state_passes(tmp_path, capsys):
    _healthy_repo(tmp_path)
    # Feed activity within the 15-minute window -> fresh.
    (tmp_path / ".claude-gui" / "events.jsonl").write_text(
        json.dumps({"t": "2026-11-26T20:05:00-05:00"}) + "\n")
    doctor.doctor(tmp_path)
    out = capsys.readouterr().out
    assert "state.yaml: fresh" in out
    assert "state.yaml stale" not in out


def test_doctor_no_events_is_fresh(tmp_path, capsys):
    _healthy_repo(tmp_path)
    # No feed yet -> nothing to be stale against.
    doctor.doctor(tmp_path)
    out = capsys.readouterr().out
    assert "state.yaml stale" not in out


# --- main -------------------------------------------------------------------

def test_main(tmp_path):
    rc = doctor.main(["--root", str(tmp_path)])
    assert rc == 1
