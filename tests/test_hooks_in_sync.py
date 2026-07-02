"""Guard against hook-config drift between plugin mode and project mode.

The PreToolUse guards (raw-data + code-execution) are declared in TWO places by design:
- `hooks/hooks.json`     - loaded when installed as a Claude Code plugin.
- `.claude/settings.json` - loaded when the repo is opened as a project.

Both must stay byte-for-byte identical so the two defence-critical guards can't silently
diverge between the two run modes. This test fails loudly if they drift.
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _pretooluse(path: Path):
    data = json.loads(path.read_text())
    hooks = data.get("hooks", data)  # settings.json nests under "hooks"; hooks.json also does
    return hooks["PreToolUse"]


def test_plugin_and_project_hooks_are_identical():
    plugin = _pretooluse(REPO / "hooks" / "hooks.json")
    project = _pretooluse(REPO / ".claude" / "settings.json")
    assert plugin == project, (
        "hooks/hooks.json and .claude/settings.json PreToolUse hooks have DRIFTED. "
        "They must stay identical (plugin mode vs project mode). Re-sync them."
    )


def test_all_guards_are_registered():
    pre = _pretooluse(REPO / "hooks" / "hooks.json")
    commands = " ".join(h["command"] for entry in pre for h in entry["hooks"])
    assert "guard-raw-data.py" in commands, "raw-data guard missing from hooks"
    assert "guard-code-execution.py" in commands, "code-execution guard missing from hooks"
    assert "guard-consent-writes.py" in commands, "consent-write guard missing from hooks"


def test_consent_guard_covers_write_tools():
    """ADR-002 rec 5: the consent-write guard must match the file-writing tools, or the model
    could Write/Edit the consent marker and settings unimpeded."""
    pre = _pretooluse(REPO / "hooks" / "hooks.json")
    for entry in pre:
        if any("guard-consent-writes.py" in h["command"] for h in entry["hooks"]):
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"):
                assert tool in entry["matcher"], f"consent-write guard matcher misses {tool}"
            break
    else:
        raise AssertionError("consent-write guard not found in hooks")


def test_guards_use_portable_python_launcher():
    """Guards must launch via the portable wrapper, never a bare `python3`.

    Windows has no `python3` (the interpreter is `python` or the `py` launcher), so a hardcoded
    `python3` meant the guards failed to start there ("python3: command not found") and did not
    run at all. `.claude/hooks/run-guard.sh` finds whichever interpreter exists and execs it, so
    the guards run identically on Linux, macOS and Windows (Git Bash). This test fails if anyone
    reverts to a bare `python3` or drops the launcher.
    """
    assert (REPO / ".claude" / "hooks" / "run-guard.sh").exists(), (
        "portable python launcher .claude/hooks/run-guard.sh is missing"
    )
    pre = _pretooluse(REPO / "hooks" / "hooks.json")
    for entry in pre:
        for h in entry["hooks"]:
            cmd = h["command"]
            assert "run-guard.sh" in cmd, f"hook bypasses the portable launcher: {cmd}"
            assert "python3 " not in cmd, f"hook hardcodes python3 (breaks on Windows): {cmd}"
