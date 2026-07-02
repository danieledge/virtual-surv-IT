"""
Behavioural tests for the consent-write guard (.claude/hooks/guard-consent-writes.py).

ADR-002 Tier-1 rec 5: the model must not grant itself execution consent (write
`.claude/.exec-consent`) or edit harness config (`.claude/settings*.json`). Closing the gate
(deleting the marker) and read-only inspection stay allowed; CST_ALLOW_CONFIG_EDIT is the
human-set maintenance override. Same protocol as the other guards: PreToolUse JSON on stdin,
exit 2 = block, exit 0 = allow; unexpected crashes fail closed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_GUARD = _ROOT / ".claude" / "hooks" / "guard-consent-writes.py"

BLOCK = 2
ALLOW = 0


def _run(payload, env_extra: dict | None = None, raw_stdin: str | None = None) -> int:
    env = {k: v for k, v in os.environ.items() if k != "CST_ALLOW_CONFIG_EDIT"}
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(_GUARD)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    return proc.returncode


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def _write(path: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}


# --- the headline: no consent self-grant ---------------------------------------


def test_blocks_write_of_consent_marker():
    assert _run(_write(".claude/.exec-consent")) == BLOCK
    assert _run(_write("/some/project/.claude/.exec-consent")) == BLOCK


def test_blocks_edit_of_settings():
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": ".claude/settings.json", "old_string": "a", "new_string": "b"},
    }
    assert _run(payload) == BLOCK


def test_blocks_edit_of_settings_local():
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": ".claude/settings.local.json",
            "old_string": "a",
            "new_string": "b",
        },
    }
    assert _run(payload) == BLOCK


def test_blocks_bash_touch_of_marker():
    assert _run(_bash("touch .claude/.exec-consent")) == BLOCK


def test_blocks_bash_redirect_into_marker():
    assert _run(_bash("echo consented > .claude/.exec-consent")) == BLOCK
    assert _run(_bash("cat notes.txt > .claude/.exec-consent")) == BLOCK


def test_blocks_bash_sed_on_settings():
    # Unknown/mutating verb touching a protected file -> default deny.
    assert _run(_bash("sed -i 's/deny/allow/' .claude/settings.json")) == BLOCK


def test_blocks_marker_write_chained_after_benign_segment():
    assert _run(_bash("git status && touch .claude/.exec-consent")) == BLOCK


def test_blocks_editing_the_guards_themselves():
    # Self-protection: a model that can edit a guard can neuter it. Write/Edit channel only.
    assert _run(_write(".claude/hooks/guard-raw-data.py")) == BLOCK
    assert _run(_write(".claude/hooks/run-guard.sh")) == BLOCK
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "hooks/hooks.json", "old_string": "a", "new_string": "b"},
    }
    assert _run(payload) == BLOCK


def test_allows_hook_edit_with_human_override():
    env = {"CST_ALLOW_CONFIG_EDIT": "1"}
    assert _run(_write(".claude/hooks/guard-raw-data.py"), env) == ALLOW


# --- safe directions stay allowed ----------------------------------------------


def test_allows_deleting_the_marker():
    # Closing the gate is fail-safe (the "No" flow deletes the marker).
    assert _run(_bash("rm .claude/.exec-consent")) == ALLOW
    assert _run(_bash("rm -f .claude/.exec-consent")) == ALLOW


def test_allows_readonly_inspection():
    assert _run(_bash("ls -la .claude/.exec-consent")) == ALLOW
    assert _run(_bash("cat .claude/settings.json")) == ALLOW
    assert _run(_bash("test -f .claude/.exec-consent")) == ALLOW


def test_allows_read_with_harmless_stderr_redirect():
    # Live false positive (2026-07-01): `2>/dev/null` is a read, not a write to the marker.
    assert _run(_bash("ls -la .claude/.exec-consent 2>/dev/null")) == ALLOW


def test_blocks_redirect_into_protected_even_as_stderr_target():
    assert _run(_bash("some-tool 2> .claude/.exec-consent")) == BLOCK
    assert _run(_bash("cat notes.txt >> .claude/settings.json")) == BLOCK


def test_allows_unrelated_writes_and_commands():
    assert _run(_write("artifacts/report.md")) == ALLOW
    assert _run(_bash("git diff --stat")) == ALLOW


def test_allows_config_edit_with_human_override():
    env = {"CST_ALLOW_CONFIG_EDIT": "1"}
    assert _run(_write(".claude/.exec-consent"), env) == ALLOW
    assert _run(_bash("touch .claude/.exec-consent"), env) == ALLOW


# --- failure semantics ----------------------------------------------------------


def test_blocks_non_dict_payload():
    # Crash path fails CLOSED (exit 1 would let the write proceed).
    assert _run(None, raw_stdin="[]") == BLOCK


def test_allows_malformed_payload():
    # Not-JSON keeps the documented never-brick-the-session carve-out.
    assert _run(None, raw_stdin="not json") == ALLOW
