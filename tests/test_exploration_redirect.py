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
from _staging import staged_or_live  # staged copy while pending, else live (step 3.6)

REPO = Path(__file__).resolve().parents[1]
REDIRECT = staged_or_live("exploration_redirect.py")


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
    recorded one scorer that 'needed a full read - well spent'. A rule
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
    staged = staged_or_live("bash_hook_dispatcher.py")
    spec = importlib.util.spec_from_file_location("staged_dispatcher", staged)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = [c for c in module._CHECKS if c[0] == "exploration_redirect"]
    assert entry, "exploration_redirect is not wired into the dispatcher"
    _name, path, tools, fail_closed = entry[0]
    assert tools == {"Read", "Grep", "Bash"}
    assert fail_closed is False, "advisory tier: a cost rule must never fail closed"
    assert path.name == "exploration_redirect.py"


def test_advice_is_language_tailored():
    """2026-09-13: --slice is exact only for Python; on a SQL file it must not be offered as
    the cheap path, and the advice acknowledges reviewing/control-flow code is read whole."""
    import scripts.exploration_redirect as er

    py = er._read_advice("/x/foo.py", 500)
    assert "--slice" in py and "exact for Python" in py

    sql = er._read_advice("/x/proc.sql", 500)
    assert "Python-only" in sql  # --slice flagged as not the cheap path here
    assert "reviewing this code" in sql


# ------------------------------------------------------------------ Bash whole-file reads
# 2026-09-14: the Read rule had a silent hole - `cat big.scala` in Bash got no nudge where a
# Read of the same file would. These pin the closed hole and, as strictly, its bounds: a
# piped, redirected, chained or multi-file command is targeted work and must pass untouched.


def _bash(command: str, session: str = "S1") -> dict:
    return {
        "session_id": session,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def test_a_bash_cat_of_a_large_file_is_redirected(armed):
    code, err = _run(_bash("cat big.py"), armed)
    assert code == 2
    assert "big.py" in err and "reads" in err


def test_a_bash_cat_of_a_small_file_is_untouched(armed):
    code, _ = _run(_bash("cat small.py"), armed)
    assert code == 0


def test_a_piped_bash_read_is_untouched(armed):
    # `cat big.py | grep line` is already targeted work; never redirect it.
    code, _ = _run(_bash("cat big.py | grep line"), armed)
    assert code == 0


def test_a_redirected_bash_read_is_untouched(armed):
    code, _ = _run(_bash("cat big.py > out.txt"), armed)
    assert code == 0


def test_head_and_tail_are_not_redirected(armed):
    # head/tail are bounded by default - the targeted form already.
    assert _run(_bash("head big.py"), armed)[0] == 0
    assert _run(_bash("tail big.py"), armed)[0] == 0


def test_a_multi_file_cat_is_untouched(armed):
    code, _ = _run(_bash("cat big.py small.py"), armed)
    assert code == 0


def test_a_flagged_cat_is_untouched(armed):
    # `cat -n` changes the behaviour; be conservative and decline rather than guess.
    code, _ = _run(_bash("cat -n big.py"), armed)
    assert code == 0


def test_powershell_get_content_of_a_large_file_is_redirected(armed):
    # A second large file, because the -Path form resolves to the same target as the bare
    # form and the redirect fires once per file - reusing big.py would just prove the de-dup.
    big2 = armed / "big2.py"
    big2.write_text("\n".join(f"row {i}" for i in range(900)), encoding="utf-8")
    assert _run(_bash("Get-Content big.py"), armed)[0] == 2
    assert _run(_bash("Get-Content -Path big2.py"), armed)[0] == 2


def test_the_second_identical_bash_read_goes_through(armed):
    # Redirect ONCE, exactly like the Read rule: a deliberate re-run costs a turn, no more.
    assert _run(_bash("cat big.py"), armed)[0] == 2
    assert _run(_bash("cat big.py"), armed)[0] == 0


def test_a_bash_read_is_silent_in_a_dormant_session(armed):
    code, _ = _run(_bash("cat big.py", session="OTHER"), armed)
    assert code == 0


def test_a_project_can_opt_out_of_the_bash_read_nudge(armed):
    (armed / ".claude").mkdir()
    (armed / ".claude" / "team-preferences.json").write_text(
        json.dumps({"read_nudge_lines": 0}), encoding="utf-8"
    )
    code, _ = _run(_bash("cat big.py"), armed)
    assert code == 0


def _load_staged_redirect():
    spec = importlib.util.spec_from_file_location(
        "staged_exploration_redirect", staged_or_live("exploration_redirect.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bash_whole_file_target_parsing():
    er = _load_staged_redirect()
    t = er._bash_whole_file_target
    assert t("cat big.scala") == "big.scala"
    assert t("less src/App.java") == "src/App.java"
    assert t("more notes.txt") == "notes.txt"
    assert t("Get-Content -Path a.sql") == "a.sql"
    assert t("cat a.py | grep x") is None  # piped
    assert t("cat a.py > b") is None  # redirected
    assert t("cat a.py && echo done") is None  # chained
    assert t("cat $(ls)") is None  # substitution
    assert t("cat a b") is None  # multi-file
    assert t("head a.py") is None  # not a whole-file verb
    assert t("grep x a.py") is None  # a filter, not a whole read
    assert t("python -m scripts.convert_file a.xlsx") is None  # team tooling untouched
