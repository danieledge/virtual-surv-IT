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

import pytest

REPO = Path(__file__).resolve().parents[1]
_DISPATCHER = REPO / "scripts" / "bash_hook_dispatcher.py"

# Staged copies live in scripts/staged_hooks/ and are promoted to their live location by a
# human-run scripts/apply-*.sh (ADR-002 rec 5: the model cannot edit .claude/hooks/**).
# Guards and the launcher live under .claude/hooks/; every other staged file is a scripts/ tool.
_STAGED_DIR = REPO / "scripts" / "staged_hooks"


def _live_path_for(staged: Path) -> Path:
    if staged.name.startswith("guard-") or staged.name == "run-guard.sh":
        return REPO / ".claude" / "hooks" / staged.name
    return REPO / "scripts" / staged.name


def _all_hooks(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("hooks", data)  # settings.json nests under "hooks"; hooks.json also does


def _pretooluse(path: Path):
    return _all_hooks(path)["PreToolUse"]


def test_plugin_and_project_hooks_are_identical():
    """Compare the WHOLE hooks object, not just PreToolUse.

    Until the 2026-08-01 audit this compared `PreToolUse` alone, while both files also declare
    Stop, UserPromptSubmit, SessionStart and PostToolUse - four event families that could drift
    between plugin mode and project mode with nothing failing, despite the docstring above
    promising byte-for-byte identity.
    """
    plugin = _all_hooks(REPO / "hooks" / "hooks.json")
    project = _all_hooks(REPO / ".claude" / "settings.json")
    assert plugin == project, (
        "hooks/hooks.json and .claude/settings.json hooks have DRIFTED. "
        "They must stay identical (plugin mode vs project mode). Re-sync them."
    )


def test_every_declared_event_family_is_compared():
    """Pin the family list so a NEW event family cannot be added to only one of the two files
    and quietly sit outside the identity check above."""
    plugin = _all_hooks(REPO / "hooks" / "hooks.json")
    project = _all_hooks(REPO / ".claude" / "settings.json")
    assert set(plugin) == set(project), (
        f"event families differ: plugin={sorted(plugin)} project={sorted(project)}"
    )
    assert set(plugin) >= {"PreToolUse", "Stop", "UserPromptSubmit", "SessionStart", "PostToolUse"}


# --------------------------------------------------------------- staged vs live

_STAGED_FILES = sorted(
    p for p in _STAGED_DIR.iterdir() if p.is_file() and not p.name.startswith(".")
)


def test_staged_dir_is_not_empty():
    assert _STAGED_FILES, "no staged hook files found - the discovery glob is broken"


@pytest.mark.parametrize("staged", _STAGED_FILES, ids=lambda p: p.name)
def test_staged_file_has_a_live_counterpart(staged):
    live = _live_path_for(staged)
    assert live.exists(), (
        f"staged {staged.name} has no live counterpart at {live.relative_to(REPO)} - "
        "either the placement rule in _live_path_for is wrong or the file was never installed"
    )


@pytest.mark.parametrize("staged", _STAGED_FILES, ids=lambda p: p.name)
def test_staged_matches_live(staged):
    """HARD FAILURE, never a skip.

    The 2026-08-01 audit found guard-code-execution.py drifted from its staged copy while the
    full suite reported green, because its sync test called pytest.skip() when the two differed.
    The live guard was missing three team-script allow-list entries, so plugin-mode /engage was
    asking users for execution consent to run its own step-0 probe - and the regression net that
    should have caught it went quiet precisely because the fix was unapplied.

    A control that is silently inert looks identical to a healthy one. That is the failure mode
    this project exists to warn about (FCA Market Watch 79: a feed that never fired for three
    years), so a pending guard fix now FAILS the suite until the human applies it.
    """
    live = _live_path_for(staged)
    if not live.exists():
        pytest.fail(f"no live counterpart for {staged.name}")
    staged_text = staged.read_text(encoding="utf-8")
    live_text = live.read_text(encoding="utf-8")
    assert staged_text == live_text, (
        f"{staged.name} is STAGED but not applied: {live.relative_to(REPO)} differs from "
        f"{staged.relative_to(REPO)}. Run the matching scripts/apply-*.sh (a human action - "
        "the model is blocked from editing .claude/hooks/**), then re-run."
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


# --- apply-all-staged.sh must be able to SEE and ROUTE every staged file -------------------
#
# 2026-08-25. apply-all-staged.sh is the one control a human is told to trust for "is anything
# pending?", and it globbed scripts/staged_hooks/*.py - so run-guard.sh, the single shell file
# there, was invisible to it and it reported "nothing pending" while that file waited to be
# applied. It had never bitten because run-guard.sh had always changed alongside a .py file
# whose apply script installs both. These two tests pin the discovery and the routing, because
# the failure mode is silence: the script cannot tell you about a file it never looked at.

_APPLY_ALL = REPO / "scripts" / "apply-all-staged.sh"


def _staged_files():
    return sorted(
        p
        for p in _STAGED_DIR.iterdir()
        if p.is_file() and p.suffix != ".pyc" and not p.name.startswith(".")
    )


def test_apply_all_staged_globs_every_file_not_just_python():
    """The discovery glob must not filter by extension."""
    body = _APPLY_ALL.read_text(encoding="utf-8")
    assert "staged_hooks/*.py;" not in body and "staged_hooks/*.py " not in body, (
        "apply-all-staged.sh is globbing *.py again - a staged shell file would be invisible "
        "to it and it would report 'nothing pending' while that file waits to be applied"
    )
    assert "for staged in scripts/staged_hooks/*;" in body, (
        "expected the loop to iterate every entry in scripts/staged_hooks/"
    )
    # Non-files must still be skipped, or __pycache__ becomes a phantom pending fix.
    assert '[ -f "$staged" ] || continue' in body, (
        "apply-all-staged.sh must skip directories such as __pycache__"
    )


def test_every_staged_file_is_mapped_to_an_apply_script():
    """Each staged file routes to an apply script that exists.

    The map is only consulted for a file that DIFFERS from live, so a missing entry stays
    latent until the day that file changes on its own - exactly how run-guard.sh, and then
    guard_daemon_client.py and module_form_redirect.py, went unnoticed.
    """
    body = _APPLY_ALL.read_text(encoding="utf-8")
    case_block = body.split("apply_for() {", 1)[1].split("}", 1)[0]
    missing, dangling = [], []
    for staged in _staged_files():
        if staged.name not in case_block:
            missing.append(staged.name)
    for match in re.findall(r'echo "(scripts/apply-[a-z0-9-]+\.sh)"', case_block):
        if not (REPO / match).is_file():
            dangling.append(match)
    assert not missing, f"staged file(s) with no apply_for() mapping: {missing}"
    assert not dangling, f"apply_for() points at non-existent script(s): {dangling}"
