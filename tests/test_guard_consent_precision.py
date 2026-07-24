"""Precision pass on the consent-write guard (staged at scripts/staged_hooks/ until the human
installs it - hook files are model-edit-blocked by this very guard).

Pins BOTH directions: the four observed false-block classes now ALLOW (read-only commands whose
argument text mentions a protected filename), and every write path still BLOCKS - including
command substitution hiding inside double quotes behind a safe verb.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STAGED = _ROOT / "scripts" / "staged_hooks" / "guard-consent-writes.py"

ALLOW, BLOCK = 0, 2


def _run(payload) -> int:
    proc = subprocess.run(
        [sys.executable, str(_STAGED)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


# --- observed false-block classes -> now ALLOW ------------------------------------------------


def test_echo_mentioning_settings_is_allowed():
    assert _run(_bash('echo "=== is .claude/settings.json tracked? ==="')) == ALLOW


def test_grep_with_quoted_pipe_pattern_on_settings_is_allowed():
    # the quoted `|`s must not shatter the segment away from its real verb (grep = read-only)
    assert _run(_bash("grep -cE 'deny|Read\\(|Edit\\(' .claude/settings.json")) == ALLOW


def test_for_loop_reading_config_files_is_allowed():
    cmd = (
        "for f in .claude/settings.json hooks/hooks.json; do "
        'grep -q "dod_stop_gate" "$f" && echo ok; done'
    )
    assert _run(_bash(cmd)) == ALLOW


def test_printf_mentioning_marker_is_allowed():
    assert _run(_bash('printf "consent marker is %s\\n" .claude/.exec-consent')) == ALLOW


# --- every write path still BLOCKS ------------------------------------------------------------


def test_echo_redirect_into_marker_still_blocks():
    assert _run(_bash("echo consented > .claude/.exec-consent")) == BLOCK


def test_echo_append_into_precommit_still_blocks():
    assert _run(_bash('echo "  - repo: local" >> .pre-commit-config.yaml')) == BLOCK


def test_touch_marker_still_blocks():
    assert _run(_bash("touch .claude/.exec-consent")) == BLOCK


def test_substitution_inside_double_quotes_still_blocks():
    # $() executes inside double quotes - it must not hide behind echo's safe verb
    assert _run(_bash('echo "$(touch .claude/.exec-consent)"')) == BLOCK


def test_backtick_substitution_still_blocks():
    assert _run(_bash('echo "`touch .claude/.exec-consent`"')) == BLOCK


def test_sed_inplace_on_settings_still_blocks():
    assert _run(_bash("sed -i 's/a/b/' .claude/settings.json")) == BLOCK


def test_cp_over_settings_still_blocks():
    assert _run(_bash("cp /tmp/x.json .claude/settings.json")) == BLOCK


def test_loop_body_write_still_blocks():
    # the loop HEADER is safe, but a writing BODY segment is judged on its own verb
    assert _run(_bash("for f in .claude/settings.json; do touch $f; done")) == BLOCK


def test_rm_marker_still_allowed_fail_safe():
    assert _run(_bash("rm -f .claude/.exec-consent")) == ALLOW


def test_write_tool_on_staged_hooks_is_not_blocked_path():
    # staging area is scripts/, not .claude/hooks/ - the Write channel must not confuse them
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(_STAGED)}}
    assert _run(payload) == ALLOW
