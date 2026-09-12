"""scripts/bash_hook_dispatcher.py (P4, 2026-07-31 corp report): one PreToolUse
process for what used to be five separate hooks (guard-raw-data, guard-code-execution,
guard-consent-writes, document_input_redirect, module_form_redirect), each previously
its own hooks.json entry -> its own process spawn. Live report: 5 process-creation
events per single Bash call, on a corporate Windows box where each one gets scanned by
endpoint security, added up to real minutes across a typical /engage open even after
every individual hang was fixed.

This file has two halves:
  - subprocess, end-to-end fidelity checks against the REAL guard scripts (unmodified) -
    the dispatcher must produce byte-identical decisions to invoking each guard alone;
  - in-process unit tests of the dispatcher's OWN mechanics (matcher scoping, per-guard
    crash policy, short-circuit) using small stand-in guard modules, since reproducing
    a genuine crash in a real guard would mean sabotaging it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = REPO_ROOT / "scripts" / "bash_hook_dispatcher.py"
STAGED = REPO_ROOT / "scripts" / "staged_hooks" / "bash_hook_dispatcher.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import bash_hook_dispatcher as bhd  # noqa: E402


def _run_dispatcher(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(DISPATCHER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


def _run_guard(script: Path, payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


# ------------------------------------------------------------------ fidelity: real guards


def test_raw_data_block_matches_the_real_guard_exactly(tmp_path):
    marker = "data" + "/" + "raw"
    payload = {"tool_name": "Read", "tool_input": {"file_path": f"{marker}/customer.csv"}}
    dispatched = _run_dispatcher(payload)
    direct = _run_guard(REPO_ROOT / ".claude" / "hooks" / "guard-raw-data.py", payload)
    assert dispatched.returncode == direct.returncode == 2
    assert dispatched.stderr.strip() == direct.stderr.strip()


def test_harmless_read_allowed_matches_the_real_guard(tmp_path):
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "notes.txt")}}
    dispatched = _run_dispatcher(payload)
    direct = _run_guard(REPO_ROOT / ".claude" / "hooks" / "guard-raw-data.py", payload)
    assert dispatched.returncode == direct.returncode == 0


def test_consent_write_block_matches_the_real_guard_exactly():
    marker_path = ".claude/." + "exec" + "-" + "consent"
    payload = {"tool_name": "Write", "tool_input": {"file_path": marker_path, "content": "x"}}
    dispatched = _run_dispatcher(payload)
    direct = _run_guard(REPO_ROOT / ".claude" / "hooks" / "guard-consent-writes.py", payload)
    assert dispatched.returncode == direct.returncode == 2
    assert dispatched.stderr.strip() == direct.stderr.strip()


def test_module_form_redirect_transparent_rewrite_matches_the_real_hook_exactly(tmp_path):
    """2026-08-04: a full match now rewrites transparently (exit 0, JSON stdout with
    updatedInput) instead of blocking - the dispatcher must forward that stdout exactly
    like the standalone hook, not just the exit code. `print()` inside a guard's own
    main() is never redirected by the dispatcher (only stdin is), so this also pins that
    the JSON isn't lost or interleaved with anything else in _CHECKS."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "python3 -m scripts.check_artifacts artifacts"},
        "cwd": str(tmp_path),
    }
    env = {"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    dispatched = _run_dispatcher(payload, env=env)
    direct = _run_guard(REPO_ROOT / "scripts" / "module_form_redirect.py", payload, env=env)
    assert dispatched.returncode == direct.returncode == 0
    assert dispatched.stdout == direct.stdout
    assert dispatched.stderr == direct.stderr == ""
    out = json.loads(dispatched.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert "check_artifacts.py" in out["updatedInput"]["command"]


def test_module_form_redirect_partial_match_block_matches_the_real_hook_exactly(tmp_path):
    """The other branch: when only SOME matched names resolve to a bundled copy, the
    hook still falls back to blocking - pinned separately from the transparent-rewrite
    case above so a regression in either branch is caught."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "python3 -m scripts.check_artifacts artifacts && "
                "python3 -m scripts.totally_made_up_script run"
            )
        },
        "cwd": str(tmp_path),
    }
    env = {"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    dispatched = _run_dispatcher(payload, env=env)
    direct = _run_guard(REPO_ROOT / "scripts" / "module_form_redirect.py", payload, env=env)
    assert dispatched.returncode == direct.returncode == 2
    assert dispatched.stderr.strip() == direct.stderr.strip()


def test_todowrite_has_no_applicable_check_and_allows_instantly():
    """A tool_name matching none of the five checks must never even attempt to load
    them - the whole point of preserving matcher scope."""
    payload = {"tool_name": "TodoWrite", "tool_input": {}}
    result = _run_dispatcher(payload)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_malformed_stdin_allows_and_never_raises():
    result = subprocess.run(
        [sys.executable, str(DISPATCHER)],
        input="not valid json{{{",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_findings_pack_guard_blocks_edit_through_the_real_dispatched_path():
    """2026-08-14 Fable-model audit finding, BLOCKER: guard-findings-pack-write.py's own
    main() checks `tool_name not in ("Write", "Edit")` and CLAUDE.md documents its scope
    as "Write and Edit, both scoped ... mechanically enforced" - but this dispatcher's own
    _CHECKS entry only ever registered {"Write"}, so an Edit call from one of the four
    scoped review agents never reached this guard at all in the live dispatched path
    (the ONLY path a real Claude Code session actually uses - there is no standalone
    hooks.json entry for this guard). The guard's own test suite invoked it as a direct
    subprocess, bypassing this dispatcher entirely, so it stayed green while the real
    enforcement was dead code for Edit. This test exercises the REAL dispatcher against
    the REAL guard (both unmodified, exactly like every other fidelity test in this
    file) with an Edit call outside the allowed findings-pack path from a scoped agent -
    the one case that must be blocked and, before this fix, silently wasn't."""
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "src/app.py"},
        "agent_type": "code-reviewer",
    }
    result = _run_dispatcher(payload)
    assert result.returncode == 2, (
        "an Edit outside the findings-pack path from a scoped review agent must be "
        "BLOCKED - if this is 0, the dispatcher's _CHECKS entry for "
        "guard_findings_pack_write has regressed back to {'Write'} only"
    )


def test_findings_pack_guard_still_allows_edit_inside_the_pack_path():
    """The other half of the same fix, proven together so a too-broad fix (blocking
    ALL Edits) would be caught just as fast as the too-narrow one above: a scoped
    agent editing its OWN findings pack must still be allowed through the real
    dispatched path."""
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "artifacts/my-slug/data/findings-code-reviewer.jsonl"},
        "agent_type": "code-reviewer",
    }
    result = _run_dispatcher(payload)
    assert result.returncode == 0


def test_staged_and_live_are_byte_synced():
    if not STAGED.is_file():
        pytest.skip("not staged yet")
    assert DISPATCHER.read_bytes() == STAGED.read_bytes()


# ------------------------------------------------------------------ dispatcher mechanics (in-process)


def _fake_module(*, returns=None, raises=None, sees_payload: list | None = None):
    """A stand-in guard module whose main() reads stdin (proving the dispatcher really
    re-injects a fresh, readable stream per check) then returns/raises as directed."""
    mod = types.ModuleType("fake_guard")

    def main():
        text = sys.stdin.read()
        if sees_payload is not None:
            sees_payload.append(json.loads(text or "{}"))
        if raises is not None:
            raise raises
        return returns

    mod.main = main
    return mod


def test_only_applicable_checks_run_for_the_tool(monkeypatch):
    """A Read call must never even load the Bash-only checks (guard-code-execution,
    module_form_redirect) - matcher scope, preserved exactly."""
    calls = []

    def fake_load(name, path):
        calls.append(name)
        return _fake_module(returns=0)

    monkeypatch.setattr(bhd, "_load", fake_load)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"tool_name": "Read"})))
    assert bhd.main() == 0
    # exploration_redirect joined on 2026-08-26 (Read + Grep). The Bash-only checks must
    # still be absent - that scoping is what this test exists to protect.
    assert calls == ["guard_raw_data", "document_input_redirect", "exploration_redirect"]
    assert "guard_code_execution" not in calls
    assert "module_form_redirect" not in calls


def test_safety_guard_crash_fails_closed(monkeypatch, capsys):
    """guard-raw-data/guard-code-execution/guard-consent-writes are safety guards whose
    OWN if __name__ wrapper fails closed on an unexpected crash - the dispatcher must
    reproduce that even though it bypasses that wrapper entirely."""

    def fake_load(name, path):
        if name == "guard_raw_data":
            return _fake_module(raises=RuntimeError("boom"))
        return _fake_module(returns=0)

    monkeypatch.setattr(bhd, "_load", fake_load)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"tool_name": "Read"})))
    assert bhd.main() == 2
    assert "failing closed" in capsys.readouterr().err


def test_redirect_hook_crash_fails_open(monkeypatch):
    """document_input_redirect/module_form_redirect are convenience redirects whose OWN
    docstrings say "never block work it cannot improve" - a crash there must not block."""

    def fake_load(name, path):
        if name == "document_input_redirect":
            return _fake_module(raises=RuntimeError("boom"))
        return _fake_module(returns=0)

    monkeypatch.setattr(bhd, "_load", fake_load)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"tool_name": "Read"})))
    assert bhd.main() == 0


def test_first_block_short_circuits_remaining_checks(monkeypatch):
    """Equivalent to 'would at least one of the five have blocked' - once one blocks,
    running the rest can only waste the very process-spawn savings this exists for."""
    calls = []

    def fake_load(name, path):
        calls.append(name)
        if name == "guard_raw_data":
            return _fake_module(returns=2)
        return _fake_module(returns=0)

    monkeypatch.setattr(bhd, "_load", fake_load)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"tool_name": "Read"})))
    assert bhd.main() == 2
    assert calls == ["guard_raw_data"]  # document_input_redirect never even loaded


def test_every_applicable_check_sees_the_full_original_payload(monkeypatch):
    """stdin is a stream, consumed once - but each of the five guards independently
    reads it in their own main(). The dispatcher must re-inject a FRESH, complete copy
    before every single check, not just the first one."""
    seen: list = []
    payload = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x", "content": "y"}}

    def fake_load(name, path):
        return _fake_module(returns=0, sees_payload=seen)

    monkeypatch.setattr(bhd, "_load", fake_load)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(payload)))
    assert bhd.main() == 0
    # Every check whose tool-scope includes Write applies (consent_writes and
    # findings_pack_write since 2026-08-03, raw_data since the 2026-09-12 audit blocked writes
    # into the raw dir) - derived from the registry so a new Write-scoped check does not
    # silently break this test. Each must see its own fresh, complete copy.
    applicable = sum(1 for _n, _p, tools, _f in bhd._CHECKS if tools is None or "Write" in tools)
    assert applicable >= 2
    assert seen == [payload] * applicable


def test_missing_safety_guard_file_fails_closed(monkeypatch, tmp_path, capsys):
    """2026-08-07 fix (found by a framework-wide audit): a missing FILE for a fail_closed
    guard used to unconditionally skip that check (fail OPEN), asymmetric with a file that
    exists but fails to LOAD, which already failed closed below. There is no legitimate
    reason for a shipped safety-guard file to be missing from a working install - a
    missing file and a load failure are both "this guard cannot run", and now follow the
    identical fail_closed policy."""
    monkeypatch.setattr(
        bhd,
        "_CHECKS",
        (("guard_raw_data", tmp_path / "does-not-exist.py", {"Read"}, True),),
    )
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"tool_name": "Read"})))
    assert bhd.main() == 2
    assert "failing closed" in capsys.readouterr().err


def test_missing_redirect_file_still_skips_without_blocking(monkeypatch, tmp_path):
    """document_input_redirect/module_form_redirect are fail_closed=False (convenience
    redirects, never a safety control) - a missing file for THESE must still skip that one
    check without blocking, unchanged by the 2026-08-07 fix above, which is conditional on
    fail_closed."""
    monkeypatch.setattr(
        bhd,
        "_CHECKS",
        (("document_input_redirect", tmp_path / "does-not-exist.py", {"Read"}, False),),
    )
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"tool_name": "Read"})))
    assert bhd.main() == 0


def test_load_failure_itself_fails_closed_for_safety_guards(monkeypatch, tmp_path):
    """If a safety guard's file exists but fails to even IMPORT (syntax error, etc.),
    that is exactly the kind of surprise its own fail-closed policy exists for."""
    broken = tmp_path / "broken.py"
    broken.write_text("this is not valid python (((", encoding="utf-8")
    monkeypatch.setattr(bhd, "_CHECKS", (("guard_raw_data", broken, {"Read"}, True),))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"tool_name": "Read"})))
    assert bhd.main() == 2


# ==================================== 2026-09-12 safety-hook audit: H-11, H-14, H-24
#
# These drive the STAGED dispatcher; the byte-sync test above says when the live one has
# caught up. Note H-11 also needs the TOP-LEVEL PreToolUse matcher in settings.json and
# hooks.json widened to `*` by hand - this file's own opening comment says to check both
# places whenever a guard's tool coverage changes.


def _staged_install(tmp_path):
    """A plugin-shaped install of the STAGED dispatcher and STAGED guards.

    The staged dispatcher resolves its guards relative to its own location
    (``<parent>/.claude/hooks``), which from scripts/staged_hooks/ points nowhere - so it can
    only be driven end-to-end from a directory laid out the way the applied copy will be.
    Returns (dispatcher path, env).
    """
    scripts = tmp_path / "scripts"
    hooks = tmp_path / ".claude" / "hooks"
    scripts.mkdir(parents=True)
    hooks.mkdir(parents=True)
    (scripts / "bash_hook_dispatcher.py").write_text(
        STAGED.read_text(encoding="utf-8"), encoding="utf-8"
    )
    staged_dir = REPO_ROOT / "scripts" / "staged_hooks"
    for guard in (
        "guard-raw-data.py",
        "guard-code-execution.py",
        "guard-consent-writes.py",
        "guard-findings-pack-write.py",
    ):
        (hooks / guard).write_text((staged_dir / guard).read_text(encoding="utf-8"), "utf-8")
    for redirect in (
        "document_input_redirect.py",
        "module_form_redirect.py",
        "enumeration_redirect.py",
        "exploration_redirect.py",
    ):
        source = REPO_ROOT / "scripts" / redirect
        if not (staged_dir / redirect).is_file():
            (scripts / redirect).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            (scripts / redirect).write_text(
                (staged_dir / redirect).read_text(encoding="utf-8"), encoding="utf-8"
            )
    return scripts / "bash_hook_dispatcher.py", {"CLAUDE_PROJECT_DIR": str(tmp_path)}


def _run_staged_install(tmp_path, payload: dict) -> subprocess.CompletedProcess:
    import os

    dispatcher, env = _staged_install(tmp_path)
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "trades.csv").write_text("account,amount\nACC1,100\n", encoding="utf-8")
    full_env = dict(os.environ)
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(dispatcher)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


def test_a_tool_nobody_has_heard_of_still_reaches_the_raw_data_guard(tmp_path):
    """H-11. guard-raw-data.py has claimed since 2026-08-01 that "any UNKNOWN tool gets a
    defence-in-depth substring scan of its string inputs rather than a free pass" (ADR-002
    rec 22). The registry here was a closed allow-list, so that branch could never fire: an
    MCP filesystem reader, a future first-party read tool, Task, WebSearch - all skipped
    before the guard saw them."""
    payload = {
        "tool_name": "mcp__somefs__read_file",
        "tool_input": {"path": str(tmp_path / "data" / "raw" / "trades.csv")},
    }
    assert _run_staged_install(tmp_path, payload).returncode == 2


def test_an_unknown_tool_with_unrelated_inputs_is_untouched(tmp_path):
    payload = {"tool_name": "mcp__jira__create_issue", "tool_input": {"summary": "fix the parser"}}
    assert _run_staged_install(tmp_path, payload).returncode == 0


def test_the_raw_path_backstop_blocks_a_read_without_the_guard_module(tmp_path):
    """H-24. Three documented fail-open paths are each justified by "the settings.json deny
    list still backs Read/Grep/Glob" - and that list only exists in repo-as-project mode. A
    plugin install ships hooks/hooks.json and no settings.json at all."""
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "data" / "raw" / "trades.csv")},
    }
    proc = _run_staged_install(tmp_path, payload)
    assert proc.returncode == 2
    # With the guard present the GUARD speaks (first live apply, 2026-09-12: the backstop
    # ran first and hid the guard's message, which another test pins exactly). Either
    # voice is a block that names the raw directory; the backstop's own voice is checked
    # in the next test, where the guard really is absent.
    assert "data/" + "raw" in proc.stderr


def test_the_raw_path_backstop_speaks_when_the_guard_is_absent(tmp_path):
    """H-24, the case the backstop exists for: the raw-data guard file is missing from the
    install (plugin mode, no permissions.deny behind it). The dispatcher fails closed
    either way; the backstop makes the message say what was hit."""
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "data" / "raw" / "trades.csv")},
    }
    dispatcher, env = _staged_install(tmp_path)
    (tmp_path / ".claude" / "hooks" / "guard-raw-data.py").unlink()
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "trades.csv").write_text("account,amount\nACC1,100\n", encoding="utf-8")
    import os

    full_env = dict(os.environ)
    full_env.update(env)
    proc = subprocess.run(
        [sys.executable, str(dispatcher)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "raw-data wall" in proc.stderr


def test_the_raw_path_backstop_leaves_everything_else_alone(tmp_path):
    (tmp_path / "data" / "masked").mkdir(parents=True)
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "data" / "masked" / "trades.csv")},
    }
    proc = _run_staged_install(tmp_path, payload)
    assert proc.returncode == 0
    assert "raw-data wall" not in proc.stderr


def test_the_findings_pack_guard_is_registered_for_bash(tmp_path):
    """H-14 / W-7: the four scoped reviewers all hold Bash, and the guard was registered for
    Write and Edit only, so the shell was an unrestricted write channel out of a grant
    CLAUDE.md §6 calls mechanically enforced."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("bhd_staged", STAGED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    entry = next(c for c in mod._CHECKS if c[0] == "guard_findings_pack_write")
    assert "Bash" in entry[2]
    raw_entry = next(c for c in mod._CHECKS if c[0] == "guard_raw_data")
    assert raw_entry[2] is None, "the raw-data guard must see every tool - scope lives in it"
