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
focused on what's still THIS file's job: config-file drift and confirming the
dispatcher itself is reachable and portable.
"""

import json
import re
from pathlib import Path


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
            # Since the 2026-09-12 audit (H-11) the dispatcher matcher is "*": every tool,
            # so the raw-data guard's unknown-tool scan can fire for an MCP or future tool.
            # A wildcard covers the five by definition; a list must still name each.
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"):
                assert entry["matcher"] == "*" or tool in entry["matcher"], (
                    f"dispatcher matcher misses {tool}"
                )
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


# ---------------------------------------------- 2026-09-13 framework review, step 3.2
def _load_module(path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dispatcher_registered_scripts() -> dict[str, str]:
    """basename -> dispatcher, for every script one of the three dispatchers already runs."""
    out: dict[str, str] = {}
    for rel, attr in (
        ("scripts/bash_hook_dispatcher.py", "_CHECKS"),
        ("scripts/prompt_hook_dispatcher.py", "_PROMPT_HOOKS"),
        ("scripts/stop_hook_dispatcher.py", "_CHECKS"),
    ):
        for entry in getattr(_load_module(REPO / rel), attr):
            out[Path(entry[1]).name] = rel
    return out


def test_no_script_wired_both_in_dispatcher_and_top_level():
    """A script a dispatcher already runs must not ALSO carry its own top-level hook entry:
    that runs it twice per event (one extra sh + Python spawn per prompt) and, for a context
    injector, injects its block twice. Found live 2026-09-13: engage_probe_prefetch.py was
    wired both ways because apply-all.sh ran apply-engage-probe-prefetch.sh (which appends
    unconditionally) after the dispatcher had subsumed it (5fc5174 re-added what 7d2898a
    removed). The fix is a human edit of both JSON files; this test stays red until then."""
    registered = _dispatcher_registered_scripts()
    offenders = []
    for cfg in ("hooks/hooks.json", ".claude/settings.json"):
        for event, entries in _all_hooks(REPO / cfg).items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    cmd = hook.get("command", "")
                    for name, dispatcher in registered.items():
                        if name in cmd:
                            offenders.append(f"{cfg}:{event}: {name} (already run by {dispatcher})")
    assert not offenders, "hook wired twice - " + "; ".join(offenders)


# ------------------------------------------------ 2026-09-13 framework review, step 3.6
def test_staged_dir_is_empty_at_rest():
    """scripts/staged_hooks/ holds a file only while the model has a change waiting for the
    human. A non-empty directory is pending work, and the suite stays red - naming the file
    and the one command - until `bash scripts/apply-staged.sh` promotes it and deletes the
    copy. This replaces the tracked mirror of every hook (8,325 duplicated lines) and 28
    per-fix apply scripts (2026-09-13 framework review); the human gate is unchanged."""
    pending = (
        sorted(p.name for p in _STAGED_DIR.iterdir() if p.is_file() and not p.name.startswith("."))
        if _STAGED_DIR.is_dir()
        else []
    )
    assert not pending, (
        "staged hook change(s) waiting for a human: " + ", ".join(pending) + " - a human runs "
        "`bash scripts/apply-staged.sh` (never the model), then re-run the suite"
    )
