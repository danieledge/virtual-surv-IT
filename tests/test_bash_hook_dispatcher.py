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


def test_module_form_redirect_matches_the_real_hook_exactly(tmp_path):
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "python3 -m scripts.check_artifacts artifacts"},
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
    assert calls == ["guard_raw_data", "document_input_redirect"]


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
    # Two checks apply to a bare Write (guard_consent_writes, then guard_findings_pack_write,
    # 2026-08-03) - each must see its own fresh, complete copy of the payload.
    assert seen == [payload, payload]


def test_missing_guard_file_skips_that_check_without_crashing(monkeypatch, tmp_path):
    """A clone missing one of the underlying scripts (unusual layout, partial checkout)
    must not brick every tool call it would have gated - fail open for that ONE check."""
    monkeypatch.setattr(
        bhd,
        "_CHECKS",
        (("guard_raw_data", tmp_path / "does-not-exist.py", {"Read"}, True),),
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
