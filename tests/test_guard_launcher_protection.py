"""The guards' own launcher must not be writable, and must not run anything it is handed.

Deep review, 2026-09-11, item 3. `run-guard.sh` reads a cached interpreter name and
EXECUTES it, returning its exit code to Claude Code. Nothing checked what the string was,
and the file holding it was not write-protected. A file containing `/bin/true` made every
hook exit 0, the raw-data wall included, in every session, silently.

Two halves, and neither is sufficient alone:
  - run-guard.sh refuses a cached value whose basename is not a python binary;
  - guard-consent-writes protects the files that decide what runs on every hook call.

These run against the STAGED copies, like the other guard tests: a separate sync test
asserts live matches staged once a human has applied it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONSENT = REPO / "scripts" / "staged_hooks" / "guard-consent-writes.py"
RUN_GUARD = REPO / "scripts" / "staged_hooks" / "run-guard.sh"

# Files that decide what executes on every hook call. Named here rather than imported so a
# change to the guard's regex has to be a deliberate change to this list too.
LAUNCHER_PATHS = (
    ".claude/.guard-interpreter",
    ".claude/.guard-daemon-port",
    ".claude/.guard-coldstart-ms",
    "VSIT/local/guard-interpreter",
    "scripts/guard_daemon.py",
    "scripts/guard_daemon_client.py",
)


def _blocks(payload: dict) -> bool:
    proc = subprocess.run(
        [sys.executable, str(CONSENT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return proc.returncode == 2


def test_the_launcher_files_cannot_be_written():
    """Protecting the guards while leaving the thing that runs them writable is not a
    boundary."""
    for path in LAUNCHER_PATHS:
        assert _blocks(
            {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
        ), path


def test_the_launcher_files_cannot_be_edited():
    for path in LAUNCHER_PATHS:
        assert _blocks(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"},
            }
        ), path


def test_the_staged_copies_stay_editable():
    """The model must keep editing staged_hooks freely: that is the whole mechanism by
    which a guard fix reaches a human to apply."""
    for path in (
        "scripts/staged_hooks/guard_daemon.py",
        "scripts/staged_hooks/guard_daemon_client.py",
        "scripts/staged_hooks/run-guard.sh",
    ):
        assert not _blocks(
            {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
        ), path


# --------------------------------------------------------- what run-guard.sh will execute


def _looks_like_python(candidate: str) -> bool:
    """Drive the shell function itself rather than reimplement its case statement here."""
    script = f"""
    . /dev/stdin <<'SRC'
{_validator_source()}
SRC
    if _looks_like_python {candidate!r}; then echo yes; else echo no; fi
    """
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return proc.stdout.strip() == "yes"


def _validator_source() -> str:
    src = RUN_GUARD.read_text(encoding="utf-8")
    start = src.index("_looks_like_python() {")
    end = src.index("}", src.index("esac", start)) + 1
    return src[start:end]


def test_a_real_interpreter_is_accepted():
    for good in ("python3", "/usr/bin/python3", "python3.12", "python", "py", "python.exe"):
        assert _looks_like_python(good), good


def test_a_disarm_candidate_is_refused():
    """`/bin/true` is the whole attack: cached once, every hook exits 0 forever after."""
    for bad in ("/bin/true", "true", "/bin/sh", "bash", "node", "/usr/bin/env", ""):
        assert not _looks_like_python(bad), bad


def test_the_validator_guards_every_place_the_cache_is_executed():
    """Three sites read the cache and run it: the daemon fast path, the cold-start
    measurement, and the main path whose exit code becomes the guard's verdict. A check on
    two of the three is not a check."""
    src = RUN_GUARD.read_text(encoding="utf-8")
    executions = re.findall(r'\$\{?(?:_fastcached|_known_good|cached)\}?" -S', src)
    assert len(executions) >= 3, "expected three cache-driven executions"
    assert src.count("_looks_like_python \"$") >= 3, (
        "every cache read must be validated, not just some"
    )


# ------------------------------------- whose scripts/ directory is this, anyway


def _exec_guard():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gce_staged", REPO / "scripts" / "staged_hooks" / "guard-code-execution.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_client_repos_own_scripts_are_not_team_tooling(tmp_path, monkeypatch):
    """Deep review item 4. Three _TEAM_ALLOW branches carried no name check, so in plugin
    mode - reviewing a client repo that has its own scripts/ directory, which is very
    common - `python scripts/deploy.py` and `bash scripts/run_all.sh` ran with no consent
    prompt. Executing the code under review is the one thing this gate exists to stop.
    """
    mod = _exec_guard()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.py").touch()
    (tmp_path / "scripts" / "run_all.sh").touch()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    for seg in (
        "python scripts/deploy.py",
        "bash scripts/run_all.sh",
        "python -m scripts.deploy",
    ):
        assert not mod._resolves_into_plugin_scripts(seg), seg


def test_a_whitelisted_basename_still_passes_anywhere(tmp_path, monkeypatch):
    """The pre-existing residual, asserted so nobody "fixes" it by accident.

    The bundled-plugin form carries an unexpanded shell variable
    (`$CLAUDE_SKILL_DIR/../../../scripts/render_html.py`) and cannot be resolved by anyone,
    so the basename whitelist is what allows it and /engage depends on that from a foreign
    project. The cost is that a client repo with a file of the same name also passes. That
    is the whitelist's own trade-off, older than this function, and narrowing it would break
    the bundled case - which it did, on my first attempt, caught by tests/test_guards.py.
    """
    mod = _exec_guard()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "render_html.py").touch()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    assert mod._resolves_into_plugin_scripts("python scripts/render_html.py")


def test_the_teams_own_scripts_still_run(monkeypatch):
    """The allowance has to survive, or every front-door script starts prompting."""
    mod = _exec_guard()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(REPO))

    for seg in (
        "python scripts/render_html.py",
        "python -m scripts.render_html",
        "python3 -m scripts.check_artifacts --fix",
        "bash scripts/check-review-tools.sh",
    ):
        assert mod._resolves_into_plugin_scripts(seg), seg


def test_the_module_form_is_judged_by_what_the_plugin_actually_ships(monkeypatch):
    """`-m` carries no path, so a lexical guard cannot resolve it through sys.path. The
    fallback is "does the plugin ship that script", which is narrower than the old
    "anything under scripts." but is NOT airtight, and the docstring says so."""
    mod = _exec_guard()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(REPO))

    assert mod._resolves_into_plugin_scripts("python -m scripts.engagement_state init")
    assert not mod._resolves_into_plugin_scripts("python -m scripts.not_a_real_script")


def test_a_windows_path_is_matched_by_its_real_basename(tmp_path, monkeypatch):
    """This guard runs on Linux too, where os.path.basename does NOT treat a backslash as a
    separator - so `py C:\\plugin\\scripts\\check_artifacts.py` came back whole and matched
    no whitelisted name, and the bundled Windows form was refused. Caught by
    tests/test_guards.py after the first fix; the rest of this file already splits on
    `[/\\\\]` everywhere for the same reason.
    """
    mod = _exec_guard()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    for seg in (
        r"py C:\plugin\scripts\check_artifacts.py",
        r'python "C:\plugin\scripts\render_html.py" out.md',
    ):
        assert mod._resolves_into_plugin_scripts(seg), seg
