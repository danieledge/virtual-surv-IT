"""Regression tests for the 2026-07-05 guard-fix package (ADR-002 rec 14).

Written to FAIL against the pre-fix guards and PASS once the human applies
`apply-guard-fixes.sh`. Driven the way Claude Code drives the hooks: a PreToolUse
JSON payload on stdin, exit 2 = block, exit 0 = allow (same style as
tests/test_guards.py and tests/test_guard_hardening.py).

Covers the four defects:
  * multi-.py false positive - the trailing "py" of one filename parsing as the
    Windows `py` launcher "running" the next argument (third instance of the
    prose/argument FP class, after make-in-prose and `shellcheck a.sh b.sh`);
  * unanchored pwsh/powershell - the word inside a grep pattern or commit message
    blocked as if it were the command;
  * `pre-commit run` executing arbitrary hook entries with no exec pattern;
  * `.pre-commit-config.yaml` being model-writable (a consent-free execution path
    via `git commit`, since hook entries run with `language: system`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_EXEC = _ROOT / ".claude" / "hooks" / "guard-code-execution.py"
_CONSENT = _ROOT / ".claude" / "hooks" / "guard-consent-writes.py"

BLOCK, ALLOW = 2, 0


def _run(script: Path, payload: dict, drop: str, env_extra: dict | None = None) -> int:
    env = {k: v for k, v in os.environ.items() if k != drop}
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    return proc.returncode


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def _exec(cmd: str, tmp_path) -> int:
    return _run(_EXEC, _bash(cmd), "CST_ALLOW_EXEC", {"CLAUDE_PROJECT_DIR": str(tmp_path)})


def _consent(payload: dict) -> int:
    return _run(_CONSENT, payload, "CST_ALLOW_CONFIG_EDIT")


# --- (a) exec guard: multi-.py false positive (rec 14a) ------------------------
# The bare `py` alternative in _PY let the trailing "py" of one FILENAME parse as
# the Windows launcher "running" the next argument, blocking read-only commands
# over two .py files - static review's core job. Reproduced live 2026-07-05.


def test_git_diff_over_two_py_files_allowed(tmp_path):
    assert _exec("git diff -- rules/spoofing.py tests/test_spoofing.py", tmp_path) == ALLOW


def test_grep_over_two_py_files_allowed(tmp_path):
    cmd = "grep -n 'def test' tests/test_spoofing.py tests/test_masking.py"
    assert _exec(cmd, tmp_path) == ALLOW


def test_wc_over_two_py_files_allowed(tmp_path):
    assert _exec("wc -l a.py b.py", tmp_path) == ALLOW


def test_py_launcher_running_a_file_still_blocked(tmp_path):
    # True positives must survive the lookbehind fix.
    assert _exec("py script.py", tmp_path) == BLOCK


def test_python3_running_a_file_still_blocked(tmp_path):
    assert _exec("python3 foo.py", tmp_path) == BLOCK


def test_versioned_py_launcher_blocked(tmp_path):
    # `py -3 foo.py` is the versioned Windows-launcher form - the fixed file-run
    # pattern tolerates flag tokens between the launcher and the file.
    assert _exec("py -3 foo.py", tmp_path) == BLOCK


def test_py_launcher_team_script_still_allowed(tmp_path):
    # The Windows allow-list half of 0.4.1 must survive the lookbehind fix.
    assert _exec("py -m scripts.render_html x.md", tmp_path) == ALLOW


# --- (b) exec guard: pwsh/powershell anchored (rec 14b) ------------------------
# `\bpwsh\b` blocked the word inside a grep pattern or prose; now anchored to the
# segment start (with optional env-var prefixes), exactly like pytest.


def test_pwsh_in_grep_pattern_allowed(tmp_path):
    assert _exec('grep -rn "pwsh" docs/', tmp_path) == ALLOW


def test_pwsh_in_commit_message_allowed(tmp_path):
    assert _exec('git commit -m "docs: gate pwsh behind exec consent"', tmp_path) == ALLOW


def test_pwsh_as_command_still_blocked(tmp_path):
    assert _exec("pwsh -Command Invoke-ScriptAnalyzer -Path script.ps1", tmp_path) == BLOCK


def test_powershell_as_command_still_blocked(tmp_path):
    assert _exec("powershell -ExecutionPolicy Bypass -File deploy.ps1", tmp_path) == BLOCK


def test_env_prefixed_pwsh_still_blocked(tmp_path):
    assert _exec("FOO=1 pwsh -Command Get-Date", tmp_path) == BLOCK


# --- (c) exec guard: pre-commit is gated pre-consent (rec 14c) -----------------
# pre-commit executes arbitrary hook entries (`language: system` runs any command),
# so it is an execution path, not a linter invocation.


def test_pre_commit_run_blocked(tmp_path):
    assert _exec("pre-commit run", tmp_path) == BLOCK


def test_pre_commit_run_all_files_blocked(tmp_path):
    assert _exec("pre-commit run --all-files", tmp_path) == BLOCK


def test_pre_commit_in_prose_allowed(tmp_path):
    # Anchored like pytest: the word inside a commit message is not the command.
    assert _exec('git commit -m "ci: document the pre-commit gate"', tmp_path) == ALLOW


# --- (d) consent guard: .pre-commit-config.yaml write-protected (rec 14c) ------
# A model-writable pre-commit config plus a runnable `pre-commit run` was a
# consent-free execution path. Writes block; read-only inspection stays allowed.


def test_write_precommit_config_blocked():
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": ".pre-commit-config.yaml", "content": "repos: []"},
    }
    assert _consent(payload) == BLOCK


def test_edit_precommit_config_blocked():
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/home/user/project/.pre-commit-config.yaml",
            "old_string": "ruff",
            "new_string": "evil",
        },
    }
    assert _consent(payload) == BLOCK


def test_bash_redirect_into_precommit_config_blocked():
    assert _consent(_bash('echo "  - repo: local" >> .pre-commit-config.yaml')) == BLOCK


def test_bash_sed_i_on_precommit_config_blocked():
    assert _consent(_bash("sed -i 's/ruff/evil/' .pre-commit-config.yaml")) == BLOCK


def test_bash_readonly_inspection_of_precommit_config_allowed():
    assert _consent(_bash("cat .pre-commit-config.yaml")) == ALLOW
    assert _consent(_bash("grep -n language .pre-commit-config.yaml")) == ALLOW
