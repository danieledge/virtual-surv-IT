"""Consent-write guard hardening from the 2026-09-12 safety-hook audit.

Every case here is a both-directions pair: the disarm the audit found now blocks, and the
legitimate command next to it still runs. All of it drives the STAGED copy
(scripts/staged_hooks/guard-consent-writes.py) - the live guard is identical until a human
runs the apply script, and tests/test_guard_git_config.py's sync test is what says so.

Findings covered: H-1 (settings `env` CST_ keys), H-2 (the staging surface, engaged + consent
only), H-7 (case-insensitive filesystems), H-8 (path normalisation), H-9 (`cd`), H-13 (the
multi-session stamp), H-16 (the hook registry), H-18 (deleting config that does not fail
safe), H-21 (heredoc bodies and search patterns), W-2 (the human sign-off marker).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "staged_hooks" / "guard-consent-writes.py"

ALLOW, BLOCK = 0, 2
_SID = "sess-consent-hardening"


def _run(payload: dict, project: Path) -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CST_")}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    return proc.returncode


def _bash(cmd: str, sid: str | None = None) -> dict:
    payload: dict = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if sid is not None:
        payload["session_id"] = sid
    return payload


def _stamp(project: Path, payload: dict) -> None:
    art = project / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / ".team-session.json").write_text(json.dumps(payload), encoding="utf-8")


def _consent(project: Path) -> None:
    claude = project / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / ".exec-consent").write_text("", encoding="utf-8")


# --------------------------------------------------------------- H-1: settings `env` CST_


def test_a_dormant_session_cannot_add_a_cst_key_to_the_settings_env_block(tmp_path):
    """The escalation the audit rated Critical: settings.json's `env` block is exported into
    hook subprocesses, so `{"env": {"CST_ALLOW_EXEC": "1"}}` opens the execution gate for
    every future session - through the one channel both guards' docstrings say the model does
    not have. Dormant (no stamp match) is the session that could do it."""
    payload = {
        "tool_name": "Write",
        "session_id": "some-other-session",
        "tool_input": {
            "file_path": ".claude/settings.json",
            "content": json.dumps({"env": {"CST_ALLOW_EXEC": "1"}}),
        },
    }
    assert _run(payload, tmp_path) == BLOCK


def test_an_edit_introducing_a_cst_key_is_blocked_too(tmp_path):
    payload = {
        "tool_name": "Edit",
        "session_id": "some-other-session",
        "tool_input": {
            "file_path": ".claude/settings.json",
            "old_string": '"hooks": {',
            "new_string": '"env": {"CST_ALLOW_CONFIG_EDIT": "1"},\n  "hooks": {',
        },
    }
    assert _run(payload, tmp_path) == BLOCK


def test_an_ordinary_settings_edit_in_a_dormant_session_still_runs(tmp_path):
    """Owner decision, kept: a dormant session manages its own permissions. Only the CST_
    env keys are lifted out of that."""
    payload = {
        "tool_name": "Write",
        "session_id": "some-other-session",
        "tool_input": {
            "file_path": ".claude/settings.json",
            "content": json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}),
        },
    }
    assert _run(payload, tmp_path) == ALLOW


def test_a_bash_write_of_a_cst_variable_into_settings_is_blocked(tmp_path):
    cmd = "printf 'CST_ALLOW_EXEC=1' >> .claude/settings.json"
    assert _run(_bash(cmd, "some-other-session"), tmp_path) == BLOCK


def test_a_settings_env_declaration_disarms_the_config_edit_override(tmp_path):
    """CST_ALLOW_CONFIG_EDIT is honoured only when it came from the launch environment. A
    value the settings file put there is the very channel the human-only claim excludes."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"env": {"CST_ALLOW_CONFIG_EDIT": "1"}}), encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("CST_")}
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["CST_ALLOW_CONFIG_EDIT"] = "1"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": ".claude/hooks/guard-raw-data.py", "content": "x"},
    }
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert proc.returncode == BLOCK
    assert "Ignoring CST_ALLOW_CONFIG_EDIT" in proc.stderr


def test_a_launch_environment_override_still_works(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CST_")}
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["CST_ALLOW_CONFIG_EDIT"] = "1"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": ".claude/hooks/guard-raw-data.py", "content": "x"},
    }
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert proc.returncode == ALLOW


# ------------------------------------------------------- H-2 / W-16: the staging surface


def test_staging_is_locked_only_when_engaged_and_already_execution_authorised(tmp_path):
    """The pair is what matters. A session that can stage a guard fix OR execute, but not
    both, is the ordinary workflow; a session holding both can promote its own edit."""
    target = {
        "tool_name": "Write",
        "session_id": _SID,
        "tool_input": {"file_path": "scripts/staged_hooks/guard-raw-data.py", "content": "x"},
    }
    # engaged, no consent marker - the ordinary staging workflow
    _stamp(tmp_path, {"session": _SID})
    assert _run(target, tmp_path) == ALLOW
    # consent marker, dormant session - plain Claude Code, also fine
    _consent(tmp_path)
    dormant = dict(target, session_id="another-session")
    assert _run(dormant, tmp_path) == ALLOW
    # both - refused
    assert _run(target, tmp_path) == BLOCK


def test_an_apply_script_cannot_be_rewritten_by_an_authorised_engaged_session(tmp_path):
    _stamp(tmp_path, {"session": _SID})
    _consent(tmp_path)
    payload = {
        "tool_name": "Write",
        "session_id": _SID,
        "tool_input": {"file_path": "scripts/apply-guard-exec-allow.sh", "content": "x"},
    }
    assert _run(payload, tmp_path) == BLOCK
    assert _run(_bash("cp /tmp/x scripts/apply-guard-exec-allow.sh", _SID), tmp_path) == BLOCK


def test_reading_a_staged_hook_is_never_blocked(tmp_path):
    _stamp(tmp_path, {"session": _SID})
    _consent(tmp_path)
    assert _run(_bash("cat scripts/staged_hooks/guard-raw-data.py", _SID), tmp_path) == ALLOW


# --------------------------------------------------- H-7 / H-8: case and path normalisation


@pytest.mark.parametrize(
    "path",
    (
        ".claude/.EXEC-CONSENT",
        ".CLAUDE/hooks/guard-raw-data.py",
        ".claude/./hooks/guard-raw-data.py",
        ".claude/hooks/../hooks/guard-consent-writes.py",
        "artifacts/./.team-session.json",
    ),
)
def test_a_case_or_dot_variant_of_a_protected_path_is_still_protected(path, tmp_path):
    payload = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
    assert _run(payload, tmp_path) == BLOCK


def test_an_ordinary_project_file_is_still_writable(tmp_path):
    payload = {"tool_name": "Write", "tool_input": {"file_path": "docs/notes.md", "content": "x"}}
    assert _run(payload, tmp_path) == ALLOW


# ------------------------------------------------------------------------------ H-9: cd


def test_cd_then_delete_the_session_stamp_is_blocked(tmp_path):
    assert _run(_bash("cd artifacts && rm .team-session.json"), tmp_path) == BLOCK


def test_cd_then_write_the_daemon_port_file_is_blocked(tmp_path):
    assert _run(_bash("cd .claude && printf '1\\nx\\n' > .guard-daemon-port"), tmp_path) == BLOCK


def test_cd_then_an_unrelated_file_still_runs(tmp_path):
    assert _run(_bash("cd docs && cat notes.md"), tmp_path) == ALLOW


# --------------------------------------------------------------------- H-16: the registry


@pytest.mark.parametrize(
    "path",
    (
        "scripts/prompt_hook_dispatcher.py",
        "scripts/stop_hook_dispatcher.py",
        "scripts/locked_menu_guard.py",
        "scripts/module_form_redirect.py",
        "scripts/enumeration_redirect.py",
        "scripts/exploration_redirect.py",
        "scripts/document_input_redirect.py",
        "scripts/post_edit_lint.py",
        "scripts/subagent_return_budget.py",
        "scripts/session_resume_brief.py",
        "scripts/vsit_paths.py",
    ),
)
def test_every_registered_hook_script_is_write_protected(path, tmp_path):
    payload = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
    assert _run(payload, tmp_path) == BLOCK


def test_a_non_hook_script_is_still_writable(tmp_path):
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "scripts/ingest.py", "content": ""},
    }
    assert _run(payload, tmp_path) == ALLOW


# ------------------------------------------------------------- H-18: delete is not fail-safe


@pytest.mark.parametrize(
    "cmd",
    (
        "rm .claude/settings.json",
        "rm -f .pre-commit-config.yaml",
        "rm .git/config",
    ),
)
def test_deleting_config_that_does_not_fail_safe_is_blocked(cmd, tmp_path):
    """`rm` is a safe verb because deleting the CONSENT MARKER closes the gate. Deleting
    settings.json takes the hook wiring and the permissions.deny backstop with it, which is
    the opposite direction. Stamped, because settings.json is the engaged tier by owner
    decision - the pre-commit and git-config entries are protected in every session."""
    _stamp(tmp_path, {"session": _SID})
    assert _run(_bash(cmd, _SID), tmp_path) == BLOCK


def test_deleting_the_consent_marker_is_still_allowed(tmp_path):
    assert _run(_bash("rm -f .claude/.exec-consent"), tmp_path) == ALLOW


# ------------------------------------------------------------------ W-2: human sign-off


def test_the_human_sign_off_marker_cannot_be_created(tmp_path):
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "VSIT/engagements/x/.human-sign-off", "content": "ok"},
    }
    assert _run(payload, tmp_path) == BLOCK
    assert _run(_bash("touch artifacts/x/.human-sign-off"), tmp_path) == BLOCK


# ------------------------------------------------- H-21: heredoc bodies and search patterns


def test_a_heredoc_body_mentioning_a_protected_path_is_not_a_write(tmp_path):
    """Reproduced live during the audit itself: writing an unrelated analysis script into a
    scratchpad was blocked because the heredoc body contained the string `.exec-consent`."""
    cmd = "cat > /tmp/note.py <<'PYEOF'\n_MARKER = \".exec-consent\"\nPYEOF"
    assert _run(_bash(cmd, _SID), tmp_path) == ALLOW


def test_a_heredoc_writing_INTO_a_protected_path_is_still_blocked(tmp_path):
    _stamp(tmp_path, {"session": _SID})
    cmd = "cat > .claude/settings.json <<'EOF'\n{}\nEOF"
    assert _run(_bash(cmd, _SID), tmp_path) == BLOCK


def test_a_grep_pattern_naming_git_config_is_not_a_write(tmp_path):
    assert _run(_bash("grep -r '.git/config' docs/", _SID), tmp_path) == ALLOW


def test_a_settings_backup_is_not_the_live_wiring(tmp_path):
    assert _run(_bash("cp .claude/settings.json.bak /tmp/x", _SID), tmp_path) == ALLOW


# ----------------------------------------------------------------- H-13: the stamp format


def test_the_new_stamp_format_arms_every_listed_session(tmp_path):
    """Two engaged sessions in one project must both be armed; the single-id stamp silently
    disarmed whichever one did not write last."""
    _stamp(
        tmp_path,
        {
            "session_id": "second",
            "sessions": [
                {"id": "first", "stamped_at": "2026-09-12T10:00:00"},
                {"id": "second", "stamped_at": "2026-09-12T11:00:00"},
            ],
        },
    )
    for sid in ("first", "second"):
        payload = {
            "tool_name": "Write",
            "session_id": sid,
            "tool_input": {"file_path": ".claude/settings.json", "content": "{}"},
        }
        assert _run(payload, tmp_path) == BLOCK, sid


def test_the_legacy_stamp_format_still_arms(tmp_path):
    _stamp(tmp_path, {"session": _SID, "stamped": "2026-08-30"})
    payload = {
        "tool_name": "Write",
        "session_id": _SID,
        "tool_input": {"file_path": ".claude/settings.json", "content": "{}"},
    }
    assert _run(payload, tmp_path) == BLOCK


def test_an_unlisted_session_is_dormant(tmp_path):
    _stamp(tmp_path, {"session_id": "second", "sessions": [{"id": "second"}]})
    payload = {
        "tool_name": "Write",
        "session_id": "not-listed",
        "tool_input": {"file_path": ".claude/settings.json", "content": "{}"},
    }
    assert _run(payload, tmp_path) == ALLOW
