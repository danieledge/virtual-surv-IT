"""Exploration discipline, mechanised (2026-08-26).

The rules were already written - `docs/team-operating-guide-orchestration.md` Exploration
discipline, copied verbatim into `.claude/agents/code-reviewer.md` - and a real review still
burned ~25k tokens doing exactly what they forbid: two full-file reads of 500-line sources
and two unbounded greps returning 80 and 50 near-identical lines. The owner's verdict was
that a written policy which is not followed does not help.

So these tests pin the properties that make it a control rather than another rule:
it fires only in engaged sessions, it fires on the shapes that actually cost money, and -
the one that decides whether it survives contact with real work - it redirects each target
exactly ONCE, so a deliberate full read costs a turn and never becomes impossible.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REDIRECT = REPO / "scripts" / "exploration_redirect.py"


@pytest.fixture()
def armed(tmp_path):
    """A project whose session stamp matches the payload - i.e. the team was invoked."""
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / ".team-session.json").write_text(
        json.dumps({"session": "S1"}), encoding="utf-8"
    )
    big = tmp_path / "big.py"
    big.write_text("\n".join(f"line {i}" for i in range(900)), encoding="utf-8")
    small = tmp_path / "small.py"
    small.write_text("one\ntwo\nthree\n", encoding="utf-8")
    return tmp_path


def _run(payload: dict, project: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(REDIRECT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stderr


def _read(path: Path, session: str = "S1", **extra) -> dict:
    return {
        "session_id": session,
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(path), **extra},
    }


def _grep(pattern: str, session: str = "S1", **extra) -> dict:
    return {
        "session_id": session,
        "hook_event_name": "PreToolUse",
        "tool_name": "Grep",
        "tool_input": {"pattern": pattern, **extra},
    }


# ------------------------------------------------------------------ dormancy


def test_a_dormant_session_is_untouched(armed):
    """Advisory polarity: a session that did not invoke the team is plain Claude Code, and
    an unknown or missing stamp stays SILENT. This is a cost rule, not a safety wall."""
    code, err = _run(_read(armed / "big.py", session="not-the-stamped-one"), armed)
    assert code == 0 and err == ""


def test_no_stamp_at_all_is_silent(tmp_path):
    big = tmp_path / "big.py"
    big.write_text("\n".join(str(i) for i in range(900)), encoding="utf-8")
    code, err = _run(_read(big), tmp_path)
    assert code == 0 and err == ""


# ------------------------------------------------------------------ the Read rule


def test_a_whole_file_read_of_a_large_file_is_redirected(armed):
    code, err = _run(_read(armed / "big.py"), armed)
    assert code == 2
    assert "repo_skeleton --slice" in err, "the cheap path must be NAMED, not just implied"
    assert "900 lines" in err, "say how big it is, or the redirect is unarguable noise"


def test_the_second_identical_read_goes_through(armed):
    """The property that decides whether this survives. That review's own retrospective
    says the RuleC scorer 'genuinely needed a full read - that one was well spent'. A rule
    that makes correct work impossible gets switched off, and then protects nothing."""
    first, _ = _run(_read(armed / "big.py"), armed)
    second, err = _run(_read(armed / "big.py"), armed)
    assert first == 2
    assert second == 0 and err == "", "a deliberate repeat must cost one turn, not the work"


def test_a_windowed_read_is_never_redirected(armed):
    """offset/limit IS the disciplined form - redirecting it would be nagging someone who
    already complied."""
    for extra in ({"offset": 100, "limit": 40}, {"limit": 50}):
        code, err = _run(_read(armed / "big.py", **extra), armed)
        assert code == 0 and err == ""


def test_a_small_file_is_never_redirected(armed):
    """Rule 3 in the operating guide says to read small files whole - one Read beats three
    greps plus their per-turn context tax. This must not contradict it."""
    code, err = _run(_read(armed / "small.py"), armed)
    assert code == 0 and err == ""


def test_a_missing_or_binary_file_fails_open(armed):
    code, _ = _run(_read(armed / "does-not-exist.py"), armed)
    assert code == 0
    binary = armed / "blob.bin"
    binary.write_bytes(b"\x00\x01" * 500_000)
    code, _ = _run(_read(binary), armed)
    assert code == 0, "unmeasurable means silent, never blocked"


def test_a_project_can_opt_out(armed):
    (armed / ".claude").mkdir()
    (armed / ".claude" / "team-preferences.json").write_text(
        json.dumps({"read_nudge_lines": 0}), encoding="utf-8"
    )
    code, err = _run(_read(armed / "big.py"), armed)
    assert code == 0 and err == ""


# ------------------------------------------------------------------ the Grep rule


def test_an_unbounded_content_grep_is_redirected(armed):
    code, err = _run(_grep("threshold"), armed)
    assert code == 2
    assert "count" in err, "count-before-content is the whole point"


@pytest.mark.parametrize(
    "extra",
    [{"output_mode": "count"}, {"output_mode": "files_with_matches"}, {"head_limit": 20}],
)
def test_a_bounded_grep_is_never_redirected(armed, extra):
    code, err = _run(_grep("threshold", **extra), armed)
    assert code == 0 and err == ""


def test_grep_redirect_is_also_once_per_pattern(armed):
    assert _run(_grep("same-pattern"), armed)[0] == 2
    assert _run(_grep("same-pattern"), armed)[0] == 0
    assert _run(_grep("a-different-pattern"), armed)[0] == 2, "per pattern, not per session"


# ------------------------------------------------------------------ wiring


def test_it_is_dispatched_for_read_and_grep_and_fails_open():
    """A guard nobody calls is not a guard. Pins the dispatcher entry, including the
    fail_open flag - this is advisory infra, and must never block on its own crash."""
    staged = REPO / "scripts" / "staged_hooks" / "bash_hook_dispatcher.py"
    spec = importlib.util.spec_from_file_location("staged_dispatcher", staged)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = [c for c in module._CHECKS if c[0] == "exploration_redirect"]
    assert entry, "exploration_redirect is not wired into the dispatcher"
    _name, path, tools, fail_closed = entry[0]
    assert tools == {"Read", "Grep"}
    assert fail_closed is False, "advisory tier: a cost rule must never fail closed"
    assert path.name == "exploration_redirect.py"
