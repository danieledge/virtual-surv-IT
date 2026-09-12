"""Code-execution gate hardening from the 2026-09-12 safety-hook audit.

Drives the STAGED guard (scripts/staged_hooks/guard-code-execution.py); the live copy is
identical until a human runs scripts/apply-guard-exec-allow.sh, and
tests/test_guard_exec_team_allow.py's sync test is what says so.

Findings covered: H-1 (a CST_ALLOW_EXEC that came from settings.json), H-2 (apply-*.sh),
H-3 (literal paths are judged by location), H-4 (the never-consent-free module set),
H-10 (wrapper prefixes, heredocs and stdin pipes), H-13 (the multi-session stamp).

Every case is a pair: the bypass the audit found now blocks, and the legitimate command
beside it still runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "staged_hooks" / "guard-code-execution.py"

ALLOW, BLOCK = 0, 2


def _run(cmd: str, project: Path, env_extra: dict | None = None, sid: str | None = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CST_")}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    if env_extra:
        env.update(env_extra)
    payload: dict = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if sid is not None:
        payload["session_id"] = sid
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _code(cmd: str, project: Path, **kw) -> int:
    return _run(cmd, project, **kw).returncode


# ------------------------------------------------------------------- H-2: the apply scripts


@pytest.mark.parametrize(
    "cmd",
    (
        "bash scripts/apply-all-staged.sh",
        "bash scripts/apply-guard-exec-allow.sh",
        "sh scripts/apply-guard-raw-coverage.sh",
        "./scripts/apply-guard-daemon.sh",
    ),
)
def test_an_apply_script_never_runs_from_a_model_turn(cmd, tmp_path):
    """The chain the audit rated Critical: edit scripts/staged_hooks/<guard>.py, run the
    apply script, every guard replaced - with no human in the loop and no consent prompt.
    _TEAM_ALLOW's `bash scripts/` branch matched it and _resolves_into_plugin_scripts
    accepted it, because in repo-as-project mode it really does live in the plugin's own
    scripts directory. The only control was a prose note in user memory."""
    proc = _run(cmd, tmp_path)
    assert proc.returncode == BLOCK
    assert "HUMAN act" in proc.stderr
    assert "NOT a consent question" in proc.stderr


def test_an_apply_script_is_refused_even_with_execution_consent(tmp_path):
    """Consent authorises running the code UNDER REVIEW in a sandbox. It was never a grant
    to replace the guards, and an execution-authorised session must not be able to rewrite
    the gate that authorised it."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".exec-consent").write_text("", encoding="utf-8")
    assert _code("bash scripts/apply-all-staged.sh", tmp_path) == BLOCK


def test_reading_an_apply_script_is_not_running_it(tmp_path):
    """The prose/argument false-positive class this guard family keeps hitting."""
    for cmd in (
        "cat scripts/apply-all-staged.sh",
        "grep -n cp scripts/apply-guard-daemon.sh",
        "ruff check scripts/guard_daemon.py",
    ):
        assert _code(cmd, tmp_path) == ALLOW, cmd


# -------------------------------------------------- H-4: shipped, but never consent-free


@pytest.mark.parametrize(
    "name",
    (
        "guard_daemon",
        "headless_run",
        "launch_terminal",
        "installer_app",
        "eval_engage",
        "virt_team_launcher",
        "release_gate",
    ),
)
def test_a_session_spawning_or_config_rewriting_script_is_refused(name, tmp_path):
    """These are shipped tooling, so `-m scripts.<name>` satisfied "does the plugin ship
    it" and ran with no prompt. None is a front-door script a skill invokes mid-turn, and
    each is a way to reach further execution, a new session, or the harness config."""
    assert _code(f"python -m scripts.{name}", tmp_path) == BLOCK
    assert _code(f"python scripts/{name}.py", tmp_path) == BLOCK


def test_the_real_front_door_scripts_still_run(tmp_path):
    """The allowance has to survive or every front-door script starts prompting, which
    CLAUDE.md §7 explicitly forbids."""
    for cmd in (
        "python -m scripts.engagement_state list",
        "python -m scripts.convert_file report.xlsx",
        "python -m scripts.render_html artifacts/x.md",
        "python -m scripts.check_artifacts",
    ):
        assert _code(cmd, tmp_path) == ALLOW, cmd


# ------------------------------------------------------- H-3: literal paths, judged by where


def test_a_whitelisted_basename_written_anywhere_is_not_team_tooling(tmp_path):
    """Write-then-run. The model holds an unrestricted Write tool, so a file named
    scripts/ingest.py in /tmp was arbitrary, consent-free code execution."""
    fake = tmp_path / "scripts"
    fake.mkdir()
    (fake / "ingest.py").write_text("print('hi')", encoding="utf-8")
    assert _code(f"python {fake}/ingest.py", tmp_path) == BLOCK
    assert _code(f'python "{fake}/render_html.py"', tmp_path) == BLOCK


def test_the_unresolvable_bundled_form_still_runs(tmp_path):
    """The one case the whitelist was added for, and now the only one it covers: a path
    carrying an unexpanded variable, which nothing can resolve."""
    for cmd in (
        'python3 "$CLAUDE_SKILL_DIR/../../../scripts/render_html.py" artifacts/x.md',
        "py %CLAUDE_PLUGIN_ROOT%\\scripts\\check_artifacts.py",
    ):
        assert _code(cmd, tmp_path) == ALLOW, cmd


# ------------------------------------------------ H-10: wrappers, heredocs and stdin pipes


@pytest.mark.parametrize(
    "cmd",
    (
        "sudo pytest",
        "nice -n 10 pytest",
        "timeout 60 pytest tests/",
        "env pytest",
        "command pytest tests/",
        "nohup pytest",
        "exec pytest",
        "sudo make test",
        "sudo pre-commit run --all-files",
        "python3 <<'EOF'\nimport os\nEOF",
        "python3 << EOF\nimport os\nEOF",
        "bash <<'EOF'\nid\nEOF",
        "python3 < evil.py",
        "bash < evil.sh",
        "cat evil.py | python3",
        "cat evil.sh | sh",
        "cat evil.sh | bash",
    ),
)
def test_a_wrapped_or_stdin_fed_execution_is_blocked(cmd, tmp_path):
    """Verified unblocked by the audit against the exact live pattern set. Five patterns are
    anchored with `^(?:\\w+=\\S+\\s+)*`, which permits a VAR=value prefix and nothing else, and
    the interpreter patterns only recognised `-c`, a trailing bare `-` and a `.py` filename."""
    assert _code(cmd, tmp_path) == BLOCK


@pytest.mark.parametrize(
    "cmd",
    (
        "python --version",
        "python3 -V",
        "git diff --stat",
        "ruff check scripts/",
        "command -v python3",
        "env | sort",
        'git commit -m "docs: make the domain case"',
        "shellcheck .claude/hooks/run-guard.sh scripts/install-git-hooks.sh",
        "PYTHONIOENCODING=utf-8 python -m scripts.engage_probe",
    ),
)
def test_the_read_only_and_team_commands_still_run(cmd, tmp_path):
    assert _code(cmd, tmp_path) == ALLOW


# ----------------------------------------------- H-1: where CST_ALLOW_EXEC came from


def test_a_settings_declared_cst_allow_exec_is_ignored(tmp_path):
    """settings.json's `env` block is exported into hook subprocesses, and settings.json is
    model-writable in a dormant session - so a CST_ALLOW_EXEC that came from there is not
    the human-only launch-environment grant this gate documents."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"env": {"CST_ALLOW_EXEC": "1"}}), encoding="utf-8"
    )
    proc = _run("pytest tests/", tmp_path, env_extra={"CST_ALLOW_EXEC": "1"})
    assert proc.returncode == BLOCK
    assert "Ignoring CST_ALLOW_EXEC" in proc.stderr


def test_a_launch_environment_cst_allow_exec_still_authorises(tmp_path):
    assert _code("pytest tests/", tmp_path, env_extra={"CST_ALLOW_EXEC": "1"}) == ALLOW


# --------------------------------------------------------------- H-13: the stamp format


def _stamp(project: Path, payload: dict) -> None:
    art = project / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / ".team-session.json").write_text(json.dumps(payload), encoding="utf-8")


def test_every_listed_session_is_armed(tmp_path):
    """Two engaged sessions in one project must both be armed; the single-id stamp silently
    disarmed whichever one did not write last."""
    _stamp(
        tmp_path,
        {
            "session_id": "second",
            "sessions": [{"id": "first", "stamped_at": "x"}, {"id": "second", "stamped_at": "y"}],
        },
    )
    assert _code("pytest tests/", tmp_path, sid="first") == BLOCK
    assert _code("pytest tests/", tmp_path, sid="second") == BLOCK


def test_a_session_that_is_not_listed_is_dormant(tmp_path):
    _stamp(tmp_path, {"session_id": "second", "sessions": [{"id": "second"}]})
    assert _code("pytest tests/", tmp_path, sid="somebody-else") == ALLOW


def test_the_legacy_single_id_stamp_still_arms(tmp_path):
    _stamp(tmp_path, {"session": "only-one", "stamped": "2026-08-30"})
    assert _code("pytest tests/", tmp_path, sid="only-one") == BLOCK


def test_the_stamp_list_is_read_only_to_its_cap(tmp_path):
    """An abandoned id must not arm the gate forever - the reader honours the same cap the
    writer applies."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gce_cap", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _stamp(
        tmp_path,
        {"sessions": [{"id": f"s{i}"} for i in range(mod._MAX_STAMPED_SESSIONS + 5)]},
    )
    assert _code("pytest tests/", tmp_path, sid="s0") == ALLOW  # aged out
    assert _code("pytest tests/", tmp_path, sid=f"s{mod._MAX_STAMPED_SESSIONS + 4}") == BLOCK
