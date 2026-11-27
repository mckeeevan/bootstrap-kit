#!/usr/bin/env python3
"""bootstrap.py — deterministic project setup (work order §8, Phase 6).

Script-owned steps only: clone the pinned claude-gui dependency, detect the
stack, run sync.py, run lint.py, create the .claude-gui/ state skeleton
(state.yaml + guard.yaml). It never writes application code and never
decomposes todos — that is the model's job (BOOTSTRAP.md step 4).

The guard hook stays OFF for the entire bootstrap; it is only enabled by an
explicit ``--enable-guard`` (BOOTSTRAP.md step 6).

Acceptance (Phase 6):
  * ``--dry-run`` prints the plan and makes NO filesystem changes.
  * A real run stops at the plan — no application code is written.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sync"))
import sync  # noqa: E402

STATE_DIR = Path(".claude-gui")
GUARD_FILE = "guard.yaml"
STATE_FILE = "state.yaml"
VENDOR_DIR = Path("vendor") / "claude-gui"

STATE_SKELETON = """\
# Claude GUI state file, format version 1.
# Skeleton written by setup/bootstrap.py — the model fills in structure and
# todos (BOOTSTRAP.md step 4). Mechanical facts go to events.jsonl.
version: 1
project: {project}
updated: null

session:
  goal: null            # model-owned (BOOTSTRAP.md step 4)
  phase: bootstrapped
  focus: null
  thinking: null

structure: []           # model-owned: 3-8 parts with paths globs
todos: []               # model-owned: decomposed plan with sub-items
"""


def load_profile(root: Path) -> sync.Profile:
    return sync.load_profile(root)


def detect_stack(root: Path) -> str:
    """Heuristic stack detection (script-owned). Returns the stack name."""
    if (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file():
        return "python-fastapi"
    if (root / "package.json").is_file():
        return "react-ts"
    if (root / "go.mod").is_file():
        return "go"
    return "base"


def _repo_url(source: str) -> str:
    """https://github.com/o/r/tree/branch -> https://github.com/o/r.git"""
    url = source.split("/tree/")[0]
    if not url.endswith(".git"):
        url += ".git"
    return url


def vendor_at_ref(root: Path, pinned_ref: str) -> bool:
    """True if vendor/claude-gui exists and its HEAD matches pinned_ref."""
    head = root / VENDOR_DIR / ".git" / "HEAD"
    if not head.is_file():
        return False
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root / VENDOR_DIR), capture_output=True, text=True,
        )
        return out.returncode == 0 and out.stdout.strip().startswith(pinned_ref)
    except (OSError, subprocess.SubprocessError):
        return False


def clone_vendor(root: Path, profile: sync.Profile) -> str:
    """Clone claude-gui at the pinned ref. Skips if already at the ref."""
    viewer = profile.raw.get("viewer") or {}
    pinned_ref = str(viewer.get("pinned_ref", ""))
    if not pinned_ref:
        raise SystemExit("bootstrap: profile.yaml viewer.pinned_ref is required")
    if vendor_at_ref(root, pinned_ref):
        return "vendor/claude-gui already at " + pinned_ref
    sources = profile.raw.get("sources") or {}
    source = sources.get("claude_gui")
    if not source:
        raise SystemExit("bootstrap: profile.yaml sources.claude_gui is required")
    vendor = root / VENDOR_DIR
    vendor.parent.mkdir(parents=True, exist_ok=True)
    if vendor.exists():
        subprocess.run(["rm", "-rf", str(vendor)], check=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", pinned_ref,
         _repo_url(str(source)), str(vendor)],
        check=True,
    )
    return f"cloned claude-gui at {pinned_ref} -> vendor/claude-gui"


def run_sync(root: Path) -> str:
    manifest = sync.sync(root)
    n_out = sum(len(e["outputs"]) for e in manifest["entries"].values())
    return f"sync: {len(manifest['entries'])} source(s), {n_out} output(s)"


def run_lint(root: Path, profile: sync.Profile) -> str:
    import lint
    res = lint.lint(root, tier=profile.tier)
    if not res.ok:
        for e in res.errors:
            print(f"  lint error: {e}", file=sys.stderr)
        raise SystemExit("bootstrap: lint gate failed — fix the errors above")
    return f"lint: clean (tier={profile.tier})"


def write_state_skeleton(root: Path) -> str:
    state_dir = root / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / STATE_FILE).write_text(
        STATE_SKELETON.format(project=root.name), encoding="utf-8")
    return "wrote .claude-gui/state.yaml skeleton"


def write_guard(root: Path, profile: sync.Profile, enabled: bool) -> str:
    viewer = profile.raw.get("viewer") or {}
    mode = str(viewer.get("guard", "off"))
    state_dir = root / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / GUARD_FILE).write_text(
        f"enabled: {str(enabled).lower()}\nmode: {mode}\n", encoding="utf-8")
    return f"guard {'enabled' if enabled else 'off'} (mode: {mode})"


def build_plan(root: Path, profile: sync.Profile) -> list[str]:
    stack = detect_stack(root)
    viewer = profile.raw.get("viewer") or {}
    pinned_ref = str(viewer.get("pinned_ref", "?"))
    plan = [
        f"stack: {stack} (profile stacks: {', '.join(profile.raw.get('stacks') or [])})",
        f"clone claude-gui @ {pinned_ref} -> vendor/claude-gui",
        "run sync/sync.py (canonical -> per-tool outputs)",
        f"run sync/lint.py --tier {profile.tier} (blocking gate)",
        "write .claude-gui/state.yaml skeleton + guard.yaml (guard OFF)",
        "run setup/doctor.py (must exit 0)",
    ]
    return plan


def bootstrap(root: Path, dry_run: bool = False, enable_guard: bool = False) -> int:
    root = root.resolve()
    profile = load_profile(root)
    plan = build_plan(root, profile)

    print("bootstrap plan:")
    for step in plan:
        print(f"  - {step}")
    if dry_run:
        print("dry-run: no changes made")
        return 0

    results = [clone_vendor(root, profile), run_sync(root)]
    results.append(run_lint(root, profile))
    results.append(write_state_skeleton(root))
    results.append(write_guard(root, profile, enabled=enable_guard))

    doc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "doctor.py"),
         "--root", str(root)],
        capture_output=True, text=True,
    )
    if doc.stdout.strip():
        print(doc.stdout.strip())
    if doc.returncode != 0:
        print("bootstrap: doctor failed", file=sys.stderr)
        return 1
    results.append("doctor: OK")

    for r in results:
        print(f"  ok: {r}")
    print("bootstrap: done — next: BOOTSTRAP.md step 4 (model writes structure/todos)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic project setup")
    ap.add_argument("--root", default=".", help="project root (default: cwd)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and make no filesystem changes")
    ap.add_argument("--enable-guard", action="store_true",
                    help="enable the workview guard (BOOTSTRAP.md step 6 only)")
    args = ap.parse_args(argv)
    return bootstrap(Path(args.root), dry_run=args.dry_run,
                     enable_guard=args.enable_guard)


if __name__ == "__main__":
    sys.exit(main())
