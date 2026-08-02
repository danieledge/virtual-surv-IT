"""
Tests for the STAGED consent-write guard fix closing the git-execution-config escape
(scripts/staged_hooks/guard-consent-writes.py; installed by the human via
scripts/apply-guard-git-config.sh, ADR-002 rec 5 / house rule "don't edit the guards").

Audit finding 2026-08-01. `guard-consent-writes.py` protected the consent marker,
`.claude/settings*.json` and `.pre-commit-config.yaml`, but NOT `.git/config`. Nothing in the
protected set stopped:

    git config core.hooksPath /tmp/attacker-hooks
    git config diff.evil.command /tmp/x.sh
    <Write> .git/config

None of these writes the consent marker, so the "the model cannot grant itself execution
consent" property stayed technically true while its PURPOSE was defeated: the next
`git commit` / `git diff` executes attacker-chosen code with no marker and no gate. ADR-002
rec 14c recorded the external diff/merge driver shape as "adjacent unfixed" and never named
`core.hooksPath`; `.git/config` itself was never write-protected.

Also pinned here: Bash MUTATION of a guard file (`sed -i`, `tee`, `cp`, `rm`, redirect) now
blocks, while reading and static-analysing a guard still works - that read/analyse case is the
false positive the original Write/Edit-only rule was protecting, so both directions are tested.

Written to FAIL until the human runs scripts/apply-guard-git-config.sh, per the standing
staged-hook workflow.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STAGED_PATH = REPO / "scripts" / "staged_hooks" / "guard-consent-writes.py"
LIVE_PATH = REPO / ".claude" / "hooks" / "guard-consent-writes.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAGED = _load(STAGED_PATH)


def _run(guard: Path, payload: dict, project_dir: Path) -> int:
    """Drive the guard as a real PreToolUse subprocess and return its exit code."""
    proc = subprocess.run(
        [sys.executable, str(guard)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project_dir)},
    )
    return proc.returncode


def _blocks(tmp_path: Path, command: str) -> bool:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return _run(STAGED_PATH, payload, tmp_path) == 2


def _blocks_write(tmp_path: Path, file_path: str) -> bool:
    payload = {"tool_name": "Write", "tool_input": {"file_path": file_path}}
    return _run(STAGED_PATH, payload, tmp_path) == 2


# --------------------------------------------------- the escape itself (must block)


@pytest.mark.parametrize(
    "command",
    [
        "git config core.hooksPath /tmp/attacker-hooks",
        "git config --local core.hooksPath .evil",
        "git -C /repo config core.hooksPath /tmp/h",
        "git config core.hookspath /tmp/h",  # git keys are case-insensitive
    ],
)
def test_core_hookspath_write_blocks(tmp_path, command):
    assert _blocks(tmp_path, command), f"core.hooksPath escape not blocked: {command}"


@pytest.mark.parametrize(
    "command",
    [
        "git config diff.evil.command /tmp/x.sh",
        "git config diff.evil.textconv /tmp/x.sh",
        "git config merge.evil.driver /tmp/x.sh",
        "git config filter.evil.smudge /tmp/x.sh",
        "git config filter.evil.clean /tmp/x.sh",
        "git config core.pager /tmp/x.sh",
        "git config core.editor /tmp/x.sh",
        "git config core.sshCommand /tmp/x.sh",
        'git config alias.st "!sh /tmp/x.sh"',
    ],
)
def test_git_executable_value_keys_block(tmp_path, command):
    """Every key whose VALUE git later executes is consent-equivalent."""
    assert _blocks(tmp_path, command), f"executable-value key not blocked: {command}"


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        "/proj/.git/config",
        ".git/hooks/pre-commit",
        "/proj/.git/hooks/post-checkout",
    ],
)
def test_write_edit_of_git_config_blocks(tmp_path, path):
    assert _blocks_write(tmp_path, path), f"Write of {path} not blocked"


@pytest.mark.parametrize(
    "command",
    [
        "cp /tmp/evil .git/config",
        "mv /tmp/evil /repo/.git/config",
        "echo x > .git/config",
        "tee .git/config",
        "sed -i s/a/b/ .git/config",
    ],
)
def test_bash_mutation_of_git_config_blocks(tmp_path, command):
    """The path can sit mid-command as a bare argument, so the boundary must not
    require a leading separator (regression: `cp /tmp/evil .git/config` was allowed)."""
    assert _blocks(tmp_path, command), f"Bash mutation not blocked: {command}"


# --------------------------------------------------- `config` must be the SUBCOMMAND


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "close the git config core.hooksPath escape"',
        'git commit -q -m "fix: core.hooksPath and diff.evil.command were unguarded"',
        'git log --grep "core.hooksPath"',
        'git show --stat -- "docs/adr: git config alias.st note"',
        "grep -rn 'core.hooksPath' docs/",
    ],
)
def test_prose_mentioning_the_attack_is_not_blocked(tmp_path, command):
    """The fourth instance of a false-positive class ADR-002 has fixed three times before
    (`make` in prose, `shellcheck a.sh b.sh`, the multi-.py launcher).

    Caught live on 2026-08-01: the first cut of this guard allowed any tokens between `git`
    and `config`, so the guard blocked the very commit that introduced it, because the commit
    MESSAGE quoted the attack it was fixing. `config` must be the subcommand, so only git's own
    global options may precede it.
    """
    assert not _blocks(tmp_path, command), f"false positive on prose: {command}"


@pytest.mark.parametrize(
    "command",
    [
        "git -c core.hooksPath=/tmp/h commit -m x",
        "git -c core.pager=/tmp/x.sh log",
        "git -c diff.evil.command=/tmp/x.sh diff",
        "git -c alias.st=!sh status",
    ],
)
def test_one_shot_inline_exec_config_blocks(tmp_path, command):
    """`git -c <key>=<value> <subcommand>` applies config for a single command, reaching the
    same execution keys without ever running `git config`."""
    assert _blocks(tmp_path, command), f"inline exec config not blocked: {command}"


@pytest.mark.parametrize(
    "command",
    [
        "git -c user.email=me@example.com commit -m x",
        "git -c color.ui=always log",
    ],
)
def test_one_shot_inline_benign_config_allowed(tmp_path, command):
    assert not _blocks(tmp_path, command), f"false positive on benign -c: {command}"


def test_global_options_before_the_subcommand_still_match(tmp_path):
    """Anchoring must not lose the real forms: git's own global options may precede `config`."""
    for command in (
        "git -C /repo config core.hooksPath /tmp/h",
        "git --git-dir=/x/.git config core.hooksPath /tmp/h",
        "git --no-pager config core.hooksPath /tmp/h",
    ):
        assert _blocks(tmp_path, command), f"real attack missed: {command}"


# --------------------------------------------------- guard-file mutation via Bash


@pytest.mark.parametrize(
    "command",
    [
        "sed -i 's/exit(2)/exit(0)/' .claude/hooks/guard-code-execution.py",
        "echo pass > .claude/hooks/guard-raw-data.py",
        "cp /tmp/neutered.py .claude/hooks/guard-consent-writes.py",
        "rm .claude/hooks/guard-raw-data.py",
        "chmod 000 .claude/hooks/run-guard.sh",
        "truncate -s 0 .claude/hooks/guard-raw-data.py",
    ],
)
def test_bash_mutation_of_guard_files_blocks(tmp_path, command):
    """Deleting a guard DISARMS it - unlike deleting the consent marker, which closes
    the gate and is therefore fail-safe and still allowed."""
    assert _blocks(tmp_path, command), f"guard mutation not blocked: {command}"


# --------------------------------------------------- must NOT regress (read-only)


@pytest.mark.parametrize(
    "command",
    [
        "git config --get core.hooksPath",
        "git config --get-all core.hooksPath",
        "git config --list",
        "git config -l",
        "cat .git/config",
        "grep -n hooksPath .git/config",
        "git config user.email me@example.com",
        "git config user.name Someone",
        "git config push.default simple",
    ],
)
def test_read_only_and_benign_git_config_allowed(tmp_path, command):
    """Reads and non-executable keys must keep working, or the guard becomes unusable."""
    assert not _blocks(tmp_path, command), f"false positive: {command}"


@pytest.mark.parametrize(
    "command",
    [
        "shellcheck .claude/hooks/run-guard.sh",
        "ruff check .claude/hooks/",
        "grep -n 'exit' .claude/hooks/guard-raw-data.py",
        "cat .claude/hooks/guard-code-execution.py",
        "wc -l .claude/hooks/guard-consent-writes.py",
        "python3 -m mypy .claude/hooks/guard-raw-data.py",
    ],
)
def test_reading_and_analysing_guards_still_allowed(tmp_path, command):
    """The exact false-positive class the original Write/Edit-only rule was protecting:
    static analysis of the hooks must not become collateral damage of the Bash rule."""
    assert not _blocks(tmp_path, command), f"false positive on hook read: {command}"


def test_deleting_the_consent_marker_still_allowed(tmp_path):
    """Closing the gate is always fail-safe and must never be blocked."""
    marker = ".claude/" + ".exec" + "-consent"
    assert not _blocks(tmp_path, f"rm {marker}")


# --------------------------------------------------- structural


def test_git_config_paths_are_in_the_protected_set():
    assert STAGED._protected(".git/config")
    assert STAGED._protected("/proj/.git/hooks/pre-commit")
    assert STAGED._protected("cp /tmp/evil .git/config")
    assert not STAGED._protected("src/config.py")
    assert not STAGED._protected("mygit/config")


def test_maintenance_override_still_bypasses(tmp_path, monkeypatch):
    """CST_ALLOW_CONFIG_EDIT stays the human-only maintenance escape hatch."""
    proc = subprocess.run(
        [sys.executable, str(STAGED_PATH)],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git config core.hooksPath /tmp/h"}}
        ),
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "CST_ALLOW_CONFIG_EDIT": "1",
        },
    )
    assert proc.returncode == 0


# --------------------------------------------------- live/staged sync (fails until applied)


def test_live_guard_matches_staged_once_applied():
    """Hard failure, not a skip.

    The 2026-08-01 audit found guard-code-execution.py drifted from its staged copy while the
    suite reported green, because its sync test called pytest.skip(). A regression net that
    goes quiet when the thing it guards is unapplied is the failure mode this repo exists to
    warn about, so this one fails.
    """
    live = LIVE_PATH.read_text(encoding="utf-8")
    staged = STAGED_PATH.read_text(encoding="utf-8")
    assert live == staged, (
        "live guard-consent-writes.py differs from its staged copy - "
        "run: bash scripts/apply-guard-git-config.sh"
    )
