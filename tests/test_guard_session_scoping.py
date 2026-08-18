"""Session scoping of the execution gate and the consent guard's settings tier
(2026-08-17, user decision after a live /doctor report: a dormant session in a
plugin-ENABLED project got interpreter reads of config paths blocked, and ordinary dev
work in such projects paid the execution gate).

The decision, with carve-outs: the execution gate and the settings*.json write
protection arm only in sessions that actually invoked the team (positive match between
the hook payload's session_id and the acting-session stamp engage_probe/engagement_state
write to artifacts/.team-session.json). ALWAYS-ON regardless: the raw-data wall
(untouched by this change), the consent marker, the hook files, git execution config,
pre-commit config, and the stamp itself (write-protected everywhere, and rm of it is a
disarm, not a fail-safe close). Fail direction: a payload with NO session id cannot be
told apart from an engaged session and a SAFETY gate fails toward ARMED - the opposite
of the advisory lifecycle hooks, deliberately - which also keeps every legacy
payload-without-session-id test green before and after the human applies these staged
copies (sync tests flag them until then).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_EXEC = _ROOT / "scripts" / "staged_hooks" / "guard-code-execution.py"
_CONSENT = _ROOT / "scripts" / "staged_hooks" / "guard-consent-writes.py"

BLOCK = 2
ALLOW = 0

_SID = "sess-scoping"


def _run(guard: Path, payload: dict, project: Path) -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CST_")}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    proc = subprocess.run(
        [sys.executable, str(guard)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=60,
    )
    return proc.returncode


def _stamp(project: Path, sid: str = _SID) -> None:
    art = project / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / ".team-session.json").write_text(json.dumps({"session": sid}), encoding="utf-8")


def _bash(cmd: str, sid: str | None = _SID) -> dict:
    payload: dict = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if sid is not None:
        payload["session_id"] = sid
    return payload


def _write(path: str, sid: str | None = _SID) -> dict:
    payload: dict = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
    if sid is not None:
        payload["session_id"] = sid
    return payload


# --- execution gate ------------------------------------------------------------------


def test_exec_gate_dormant_session_runs_tests_freely(tmp_path):
    """The live complaint: pytest in an enabled-but-never-engaged project was gated."""
    assert _run(_EXEC, _bash("pytest -q"), tmp_path) == ALLOW


def test_exec_gate_arms_on_stamp_match(tmp_path):
    _stamp(tmp_path)
    assert _run(_EXEC, _bash("pytest -q"), tmp_path) == BLOCK


def test_exec_gate_other_sessions_stamp_does_not_arm(tmp_path):
    _stamp(tmp_path, sid="sess-somebody-else")
    assert _run(_EXEC, _bash("pytest -q"), tmp_path) == ALLOW


def test_exec_gate_missing_session_id_fails_toward_armed(tmp_path):
    """An older Claude Code sends no session_id - a safety gate cannot tell dormant from
    engaged and must stay armed (also what keeps the legacy guard tests green)."""
    assert _run(_EXEC, _bash("pytest -q", sid=None), tmp_path) == BLOCK


def test_exec_gate_team_tooling_still_consent_free_when_armed(tmp_path):
    _stamp(tmp_path)
    assert _run(_EXEC, _bash("python -m scripts.engagement_state list"), tmp_path) == ALLOW


# --- consent guard: the engaged-only settings tier -----------------------------------


def test_settings_write_allowed_in_dormant_session(tmp_path):
    """A dormant session managing its own harness config is plain Claude Code."""
    assert _run(_CONSENT, _write(".claude/settings.json"), tmp_path) == ALLOW


def test_doctor_style_interpreter_read_of_settings_allowed_when_dormant(tmp_path):
    """The reported /doctor case verbatim: a node read of a config path."""
    cmd = "node -e \"require('fs').readFileSync('.claude/settings.json','utf8')\""
    assert _run(_CONSENT, _bash(cmd), tmp_path) == ALLOW


def test_settings_write_blocked_in_engaged_session(tmp_path):
    _stamp(tmp_path)
    assert _run(_CONSENT, _write(".claude/settings.json"), tmp_path) == BLOCK


# --- consent guard: the always-on tier holds in dormant sessions ---------------------


def test_marker_write_blocked_even_when_dormant(tmp_path):
    """A dormant session could otherwise pre-forge the grant a later engaged session
    inherits - the marker stays human-only everywhere."""
    assert _run(_CONSENT, _write(".claude/.exec-consent"), tmp_path) == BLOCK
    assert _run(_CONSENT, _bash("touch .claude/.exec-consent"), tmp_path) == BLOCK


def test_hook_file_write_blocked_even_when_dormant(tmp_path):
    assert _run(_CONSENT, _write(".claude/hooks/guard-raw-data.py"), tmp_path) == BLOCK


def test_git_exec_config_blocked_even_when_dormant(tmp_path):
    assert _run(_CONSENT, _bash("git config core.hooksPath /tmp/evil"), tmp_path) == BLOCK


# --- the stamp itself is not a disarm channel ----------------------------------------


def test_stamp_write_blocked_on_every_channel_and_state(tmp_path):
    assert _run(_CONSENT, _write("artifacts/.team-session.json"), tmp_path) == BLOCK
    _stamp(tmp_path)
    assert _run(_CONSENT, _write("artifacts/.team-session.json"), tmp_path) == BLOCK
    assert (
        _run(_CONSENT, _bash("echo x > artifacts/.team-session.json"), tmp_path) == BLOCK
    )


def test_stamp_delete_blocked_unlike_the_marker(tmp_path):
    """rm of the MARKER closes the gate (fail-safe, allowed); rm of the STAMP disarms
    the session-scoped gates (blocked)."""
    _stamp(tmp_path)
    assert _run(_CONSENT, _bash("rm artifacts/.team-session.json"), tmp_path) == BLOCK
    assert _run(_CONSENT, _bash("rm .claude/.exec-consent"), tmp_path) == ALLOW


def test_stamp_read_stays_allowed(tmp_path):
    _stamp(tmp_path)
    assert _run(_CONSENT, _bash("cat artifacts/.team-session.json"), tmp_path) == ALLOW
