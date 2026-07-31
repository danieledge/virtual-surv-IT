"""Guard against hook-config drift between plugin mode and project mode.

The PreToolUse guards (raw-data + code-execution + consent-writes, plus the two
convenience redirects) are declared in TWO places by design:
- `hooks/hooks.json`     - loaded when installed as a Claude Code plugin.
- `.claude/settings.json` - loaded when the repo is opened as a project.

Both must stay byte-for-byte identical so the defence-critical guards can't silently
diverge between the two run modes. This test fails loudly if they drift.

P4 (2026-07-31 corp report) consolidated the five individual Bash-matching hooks into
one dispatcher (scripts/bash_hook_dispatcher.py, wired via ONE PreToolUse entry) to cut
process-spawn overhead - so a guard's OWN hooks.json entry no longer exists to check
directly. Its registration now lives in the dispatcher's own _CHECKS table instead,
which tests/test_bash_hook_dispatcher.py covers in far more depth (fidelity against the
real guards, matcher scope, per-guard crash-policy preservation). The checks here stay
focused on what's still genuinely THIS file's job: config-file drift and confirming the
dispatcher itself is reachable and portable.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_DISPATCHER = REPO / "scripts" / "bash_hook_dispatcher.py"


def _pretooluse(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
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
    """Each guard's own hooks.json entry is gone since P4 - registration now lives in
    the dispatcher's _CHECKS table, which the dispatcher entry must actually reach."""
    pre = _pretooluse(REPO / "hooks" / "hooks.json")
    commands = " ".join(h["command"] for entry in pre for h in entry["hooks"])
    assert "bash_hook_dispatcher.py" in commands, "consolidated dispatcher missing from hooks"
    source = _DISPATCHER.read_text(encoding="utf-8")
    assert "guard-raw-data.py" in source, "raw-data guard missing from the dispatcher"
    assert "guard-code-execution.py" in source, "code-execution guard missing from the dispatcher"
    assert "guard-consent-writes.py" in source, "consent-write guard missing from the dispatcher"


def test_consent_guard_covers_write_tools():
    """ADR-002 rec 5: the consent-write guard must match the file-writing tools, or the model
    could Write/Edit the consent marker and settings unimpeded. Two layers now: the ONE
    dispatcher entry's matcher must be broad enough to even reach the dispatcher for these
    tools, AND the dispatcher's own internal tool-scope for guard_consent_writes specifically
    must still cover all five - a broad outer matcher alone doesn't guarantee that."""
    pre = _pretooluse(REPO / "hooks" / "hooks.json")
    for entry in pre:
        if any("bash_hook_dispatcher.py" in h["command"] for h in entry["hooks"]):
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"):
                assert tool in entry["matcher"], f"dispatcher matcher misses {tool}"
            break
    else:
        raise AssertionError("consolidated dispatcher not found in hooks")

    source = _DISPATCHER.read_text(encoding="utf-8")
    match = re.search(r'"guard_consent_writes".*?\{([^}]*)\}', source, re.DOTALL)
    assert match, "guard_consent_writes entry not found in the dispatcher's _CHECKS table"
    tool_set_text = match.group(1)
    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"):
        assert f'"{tool}"' in tool_set_text, (
            f"dispatcher's guard_consent_writes tool-scope misses {tool}"
        )


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
