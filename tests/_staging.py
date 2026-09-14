"""Where a hook under test lives: the staged copy while one is pending, else the live file.

Step 3.6 (2026-09-13 framework review). `scripts/staged_hooks/` is EMPTY at rest: a file is
there only while the model has a change waiting for a human to promote it with
`scripts/apply-staged.sh`, and `tests/test_hooks_in_sync.py` stays red until the directory is
empty again. The tests that drive a hook therefore resolve their target here: the staged copy
when it exists (so a pending change is what gets tested), the live file otherwise. The
placement rule is the one the installer and the apply script use: `guard-*` files and
`run-guard.sh` live under `.claude/hooks/`, everything else under `scripts/`.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGED_DIR = REPO / "scripts" / "staged_hooks"


def live_path_for(name: str) -> Path:
    if name.startswith("guard-") or name == "run-guard.sh":
        return REPO / ".claude" / "hooks" / name
    return REPO / "scripts" / name


def staged_or_live(name: str) -> Path:
    staged = STAGED_DIR / name
    return staged if staged.is_file() else live_path_for(name)


def pending() -> list[Path]:
    """Every staged file, which by construction is a change waiting for the human."""
    if not STAGED_DIR.is_dir():
        return []
    return sorted(p for p in STAGED_DIR.iterdir() if p.is_file() and not p.name.startswith("."))


def launcher_copy() -> Path:
    """run-guard.sh, copied to a temp path that does NOT end in `.claude/hooks/run-guard.sh`.

    The live launcher derives its root from its own `$0` (`${_self%/.claude/hooks/run-guard.sh}`)
    and only falls back to CLAUDE_PLUGIN_ROOT / CLAUDE_PROJECT_DIR when that fails. Tests that
    build a fake plugin layout and steer the launcher by those variables relied on the staged
    copy's path not stripping; with the staging directory empty at rest they drive this copy
    instead, which behaves exactly as the staged copy did."""
    import shutil
    import tempfile

    src = staged_or_live("run-guard.sh")
    target = Path(tempfile.mkdtemp(prefix="run-guard-under-test-")) / "run-guard.sh"
    shutil.copy2(src, target)
    target.chmod(0o755)
    return target
