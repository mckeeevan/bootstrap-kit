#!/usr/bin/env python3
"""doctor.py — verify a bootstrap-kit install (work order §8, Phase 6).

Read-only and idempotent: safe to re-run any number of times. Exits non-zero
if the install is broken. Checks:

  1. profile.yaml exists and parses (tools, model.tier, viewer, stacks).
  2. sync/sync.py + sync/lint.py import cleanly.
  3. lint gate passes for the profile tier.
  4. sync manifest exists and matches disk (no drift).
  5. vendor/claude-gui is present at the pinned ref (viewer.mode: pinned).
  6. .claude-gui/state.yaml exists and parses (version 1).
  7. state.yaml is fresh: its `updated` stamp is not older than the last
     events.jsonl entry (catches a stale todo list / forgotten update).
  8. .claude-gui/guard.yaml exists (guard state is explicit, not implicit).

Usage: python3 setup/doctor.py [--root PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

# state.yaml may lag the feed by at most this long before doctor complains.
STALE_AFTER_SECONDS = 15 * 60

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sync"))


def _check_vendor(root: Path, pinned_ref: str) -> tuple[bool, str]:
    vendor = root / "vendor" / "claude-gui"
    if not vendor.is_dir():
        return False, "vendor/claude-gui missing (run setup/bootstrap.py)"
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(vendor), capture_output=True, text=True,
        )
        head = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False, "vendor/claude-gui is not a git checkout"
    if not head.startswith(pinned_ref):
        return False, (f"vendor/claude-gui at {head[:12]}, "
                       f"profile pins {pinned_ref[:12]}")
    return True, f"vendor/claude-gui at {head[:12]}"


def doctor(root: Path) -> int:
    root = root.resolve()
    failures: list[str] = []
    oks: list[str] = []

    # 1. profile.yaml
    profile_path = root / "profile.yaml"
    profile: dict = {}
    if not profile_path.is_file():
        failures.append("profile.yaml missing (copy profile.example.yaml)")
    else:
        try:
            loaded = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                profile = loaded
                oks.append(f"profile.yaml: tools={profile.get('tools')} "
                           f"tier={(profile.get('model') or {}).get('tier')}")
            else:
                failures.append("profile.yaml: not a mapping")
        except yaml.YAMLError as e:
            failures.append(f"profile.yaml: parse error: {e}")

    # 2. toolchain imports
    try:
        import lint  # noqa: F401
        import sync  # noqa: F401
        oks.append("sync/sync.py + sync/lint.py import cleanly")
    except Exception as e:  # noqa: BLE001
        failures.append(f"toolchain import failed: {e}")
        print_report(oks, failures)
        return 1

    # 3. lint gate
    try:
        tier = str((profile.get("model") or {}).get("tier", "mid"))
        res = lint.lint(root, tier=tier)
        if res.ok:
            oks.append(f"lint gate: clean (tier={tier})")
        else:
            for e in res.errors:
                failures.append(f"lint: {e}")
    except Exception as e:  # noqa: BLE001
        failures.append(f"lint gate crashed: {e}")

    # 4. manifest drift
    manifest_path = root / "sync" / "manifest.json"
    if not manifest_path.is_file():
        failures.append("sync/manifest.json missing (run sync/sync.py)")
    else:
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        drifted = []
        for rel, entry in manifest.get("entries", {}).items():
            for out_rel, out_hash in entry.get("outputs", {}).items():
                p = root / out_rel
                if not p.is_file():
                    drifted.append(f"{out_rel} (missing)")
                    continue
                import hashlib
                actual = hashlib.sha256(p.read_bytes()).hexdigest()
                if actual != out_hash:
                    drifted.append(out_rel)
        if drifted:
            failures.append("drift: " + ", ".join(sorted(drifted)))
        else:
            oks.append("manifest: no drift")

    # 5. vendor pin
    viewer = profile.get("viewer") or {}
    if str(viewer.get("mode", "pinned")) == "pinned":
        pinned_ref = str(viewer.get("pinned_ref", ""))
        if not pinned_ref:
            failures.append("profile.yaml viewer.pinned_ref missing")
        else:
            ok, msg = _check_vendor(root, pinned_ref)
            (oks if ok else failures).append(msg)

    # 6. state.yaml
    state_path = root / ".claude-gui" / "state.yaml"
    if not state_path.is_file():
        failures.append(".claude-gui/state.yaml missing (run setup/bootstrap.py)")
    else:
        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            if isinstance(state, dict) and state.get("version") == 1:
                oks.append(".claude-gui/state.yaml: version 1")
            else:
                failures.append(".claude-gui/state.yaml: expected version: 1")
        except yaml.YAMLError as e:
            failures.append(f".claude-gui/state.yaml: parse error: {e}")

    # 7. state.yaml freshness vs the events feed
    if state_path.is_file():
        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            updated_raw = (state or {}).get("updated")
            events_path = root / ".claude-gui" / "events.jsonl"
            last_event = None
            if events_path.is_file():
                for line in events_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        last_event = json.loads(line).get("t")
                    except json.JSONDecodeError:
                        continue
            if updated_raw and last_event:
                updated = datetime.fromisoformat(str(updated_raw))
                last = datetime.fromisoformat(str(last_event))
                if (last - updated).total_seconds() > STALE_AFTER_SECONDS:
                    failures.append(
                        f"state.yaml stale: updated {str(updated_raw)[:19]} "
                        f"but feed activity at {str(last_event)[:19]} — "
                        "refresh todos/updated")
                else:
                    oks.append("state.yaml: fresh (updated >= last feed event)")
        except (ValueError, TypeError) as e:
            failures.append(f"state.yaml: unparseable updated stamp: {e}")

    # 8. guard.yaml
    guard_path = root / ".claude-gui" / "guard.yaml"
    if not guard_path.is_file():
        failures.append(".claude-gui/guard.yaml missing (run setup/bootstrap.py)")
    else:
        try:
            guard = yaml.safe_load(guard_path.read_text(encoding="utf-8"))
            if isinstance(guard, dict) and "enabled" in guard:
                oks.append(f"guard: enabled={guard['enabled']} "
                           f"mode={guard.get('mode', 'off')}")
            else:
                failures.append(".claude-gui/guard.yaml: missing 'enabled' key")
        except yaml.YAMLError as e:
            failures.append(f".claude-gui/guard.yaml: parse error: {e}")

    return print_report(oks, failures)


def print_report(oks: list[str], failures: list[str]) -> int:
    for o in oks:
        print(f"ok    {o}")
    for f in failures:
        print(f"FAIL  {f}")
    if failures:
        print(f"doctor: {len(failures)} problem(s) found")
        return 1
    print("doctor: install OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a bootstrap-kit install")
    ap.add_argument("--root", default=".", help="project root (default: cwd)")
    args = ap.parse_args(argv)
    return doctor(Path(args.root))


if __name__ == "__main__":
    sys.exit(main())
