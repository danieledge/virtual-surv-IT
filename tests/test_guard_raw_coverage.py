"""
Tests for the STAGED raw-data guard coverage fixes
(scripts/staged_hooks/guard-raw-data.py; installed by the human via
scripts/apply-guard-raw-coverage.sh, ADR-002 rec 5 / house rule "don't edit the guards").

Audit finding 2026-08-01. Three coverage gaps and one false positive:

  1. ADR-002 rec 22 - _extract_path_candidates returned [] for any tool outside
     {Read,Grep,Glob,Bash}, so a read tool outside that set reached data/raw with NOTHING
     checking it. The rec rated this "architectural, not live" on the grounds that no
     local-filesystem tool was installed. WebFetch resolves `file://` against the local
     filesystem and is a live tool, so the gap was live.
  2. ADR-002 recs 7 and 15 - `Grep(path="data")` and path-less Grep descend INTO data/raw
     while naming a path that does not resolve under it, so both the path check and the
     literal deny globs missed them.
  3. Live false positive - `grep -n "data/raw" .claude/settings.json` (reading the DENY-LIST
     CONFIG) was blocked because the search PATTERN contained the marker.

Note this guard has never had a staged copy before, so it has never had a live-vs-staged
sync test. It does now, and it FAILS rather than skips until applied.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STAGED_PATH = REPO / "scripts" / "staged_hooks" / "guard-raw-data.py"
LIVE_PATH = REPO / ".claude" / "hooks" / "guard-raw-data.py"


def _run(payload: dict, project_dir: Path) -> int:
    proc = subprocess.run(
        [sys.executable, str(STAGED_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project_dir)},
    )
    return proc.returncode


def _blocks(project_dir: Path, tool: str, tool_input: dict) -> bool:
    return _run({"tool_name": tool, "tool_input": tool_input}, project_dir) == 2


@pytest.fixture
def project_with_raw(tmp_path):
    """A project that actually holds a raw record."""
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "trades.csv").write_text("account,amount\nACC1,100\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"deny": ["data/raw/**"]}', encoding="utf-8")
    return tmp_path


@pytest.fixture
def project_without_raw(tmp_path):
    """A project with no raw data - a fresh clone, or a synthetic-only project."""
    (tmp_path / "data" / "masked").mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    return tmp_path


# ------------------------------------------------ gap 1: non-enumerated read tools


@pytest.mark.parametrize(
    "url_template",
    [
        "file://{root}/data/raw/trades.csv",
        "file:///{rel}",
        "file://localhost{root}/data/raw/trades.csv",
    ],
)
def test_webfetch_file_url_to_raw_blocks(project_with_raw, url_template):
    """WebFetch addresses the local filesystem via file://, so it is a read tool for raw data
    whatever its name suggests. Previously returned [] candidates and sailed straight through."""
    url = url_template.format(
        root=project_with_raw, rel=str(project_with_raw / "data" / "raw" / "trades.csv").lstrip("/")
    )
    assert _blocks(project_with_raw, "WebFetch", {"url": url})


def test_webfetch_ordinary_url_allowed(project_with_raw):
    assert not _blocks(project_with_raw, "WebFetch", {"url": "https://example.com/docs"})


def test_notebookread_of_raw_blocks(project_with_raw):
    nb = str(project_with_raw / "data" / "raw" / "analysis.ipynb")
    assert _blocks(project_with_raw, "NotebookRead", {"notebook_path": nb})


def test_unknown_tool_gets_defence_in_depth_scan(project_with_raw):
    """A future local-filesystem MCP reader must not get the old free pass."""
    assert _blocks(
        project_with_raw,
        "mcp__somefs__read_file",
        {"path": "data/raw/trades.csv"},
    )


def test_unknown_tool_unrelated_input_allowed(project_with_raw):
    assert not _blocks(
        project_with_raw, "mcp__jira__create_issue", {"summary": "fix the parser"}
    )


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_write_tools_stay_out_of_scope(project_with_raw, tool):
    """The unknown-tool fallback must not sweep up the WRITE tools.

    This guard exists to stop raw records reaching the model's context (egress to the
    provider). Writing to data/raw egresses nothing, and is covered separately by the
    data/raw write-protect in .claude/settings.json and by guard-consent-writes.py.
    Caught live: the first cut of the fallback blocked `Write data/raw/x` and broke
    tests/test_guards.py::test_raw_guard_ignores_out_of_scope_tool, changing a documented
    behaviour as a side effect of closing a READ gap.
    """
    assert not _blocks(project_with_raw, tool, {"file_path": "data/raw/x"})


# ------------------------------------------------ gap 2: ancestor-rooted / path-less search


def test_parent_rooted_grep_blocks_when_raw_present(project_with_raw):
    """`Grep(path="data")` walks into data/raw while naming a path that is not under it."""
    assert _blocks(project_with_raw, "Grep", {"pattern": "account", "path": "data"})


def test_pathless_grep_blocks_when_raw_present(project_with_raw):
    """A path-less search is rooted at the working directory, which contains data/raw."""
    assert _blocks(project_with_raw, "Grep", {"pattern": "account"})


def test_parent_rooted_glob_blocks_when_raw_present(project_with_raw):
    assert _blocks(project_with_raw, "Glob", {"pattern": "**/*.csv", "path": "data"})


def test_ancestor_search_allowed_when_no_raw_data(project_without_raw):
    """The guard protects DATA, not a directory name. With no raw records present an
    ancestor-rooted search egresses nothing, and blocking every repo-root grep would be a
    pure false positive that makes the guard hated rather than respected."""
    assert not _blocks(project_without_raw, "Grep", {"pattern": "account", "path": "data"})
    assert not _blocks(project_without_raw, "Grep", {"pattern": "account"})


def test_sibling_scoped_search_still_allowed(project_with_raw):
    """Searching the masked lane must keep working even with raw data present."""
    assert not _blocks(
        project_with_raw, "Grep", {"pattern": "account", "path": "data/masked"}
    )


def test_direct_raw_path_still_blocks(project_with_raw):
    assert _blocks(project_with_raw, "Read", {"file_path": "data/raw/trades.csv"})
    assert _blocks(project_with_raw, "Grep", {"pattern": "x", "path": "data/raw"})


# ------------------------------------------------ fix 3: search-pattern false positive


def test_grep_for_the_marker_in_a_config_file_allowed(project_with_raw):
    """The live false positive observed during the audit: reading the deny-list config,
    whose CONTENT mentions data/raw, is a read ABOUT raw data, not a read OF it."""
    assert not _blocks(
        project_with_raw,
        "Bash",
        {"command": 'grep -n "data/raw" .claude/settings.json'},
    )


@pytest.mark.parametrize(
    "command",
    [
        'grep -n "data/raw" .claude/settings.json',
        "grep -rn data/raw docs/",
        'rg "data/raw" README.md',
        'grep -e "data/raw" .gitignore',
        'grep --include="*.md" -rn "data/raw" docs',
    ],
)
def test_search_pattern_mentioning_marker_allowed(project_with_raw, command):
    assert not _blocks(project_with_raw, "Bash", {"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "grep -n account data/raw/trades.csv",
        'grep -rn "account" data/raw/',
        "rg pattern data/raw/trades.csv",
        'grep -e "account" data/raw/trades.csv',
    ],
)
def test_search_with_raw_file_operand_still_blocks(project_with_raw, command):
    """The exemption covers the PATTERN only. A file operand under data/raw still blocks."""
    assert _blocks(project_with_raw, "Bash", {"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "cat data/raw/trades.csv",
        "cp -r data/raw /tmp/exfil",
        "cd data/raw && cat *",
        "tar cf out.tar data/raw",
    ],
)
def test_non_search_bash_commands_unchanged(project_with_raw, command):
    """Only search verbs get the pattern exemption; everything else keeps the old behaviour."""
    assert _blocks(project_with_raw, "Bash", {"command": command})


# ------------------------------------------------ compound-command segment splitting
# (2026-08-03 fable audit): a multi-statement command used to be shlex-split and judged as
# ONE invocation, so words from a LATER, unrelated statement became "file operands" of an
# EARLIER search verb - a live false positive during the audit's own session.


def test_compound_command_segments_judged_independently(project_with_raw):
    """A clean search in statement 1 must not be contaminated by statement 2's tokens."""
    assert not _blocks(
        project_with_raw, "Bash", {"command": 'grep -rn "commit" tests/test_guards.py; echo done'}
    )
    assert not _blocks(
        project_with_raw,
        "Bash",
        {"command": 'grep -rn "commit" tests/test_guards.py && ls artifacts/'},
    )


def test_compound_command_first_segments_raw_operand_still_blocks(project_with_raw):
    """The fix must not weaken detection - a REAL raw file operand in an early segment
    still blocks, whatever comes after it."""
    assert _blocks(
        project_with_raw, "Bash", {"command": "grep -rn account data/raw/trades.csv; echo done"}
    )


def test_compound_command_second_segments_raw_operand_still_blocks(project_with_raw):
    """A raw file operand in a LATER segment (not the first) must still block - segmenting
    must not accidentally only check the first statement."""
    assert _blocks(
        project_with_raw, "Bash", {"command": "echo start; grep -rn account data/raw/trades.csv"}
    )


# ------------------------------------------------ quote-aware segment splitting
# (2026-08-03, second fix): the naive split above chops INSIDE a quoted argument too - a
# log message using ';' or '&&' as ordinary punctuation got sliced into a bogus fragment.
# Live in an eval run: `engagement_state log-note "...close as-is; no real source data
# exists..." && next-command` was split mid-sentence, right after the semicolon inside the
# quotes, producing a garbage "segment" that spuriously matched an unrelated pattern.


def test_semicolon_inside_quoted_argument_is_not_a_segment_boundary():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "graw", REPO / "scripts" / "staged_hooks" / "guard-raw-data.py"
    )
    graw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graw)
    cmd = 'echo "close as-is; no real source data exists" && echo done'
    segs = graw._segments(cmd)
    assert segs == ['echo "close as-is; no real source data exists"', "echo done"]


def test_ampersand_and_pipe_inside_quotes_are_not_boundaries():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "graw", REPO / "scripts" / "staged_hooks" / "guard-raw-data.py"
    )
    graw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graw)
    assert graw._segments('echo "a && b | c"') == ['echo "a && b | c"']
    assert graw._segments("echo 'a && b | c'") == ["echo 'a && b | c'"]


def test_quoted_text_does_not_shield_a_genuine_later_boundary():
    """The fix must not over-correct into treating the WHOLE command as unsplittable - a
    real boundary after the closing quote still splits."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "graw", REPO / "scripts" / "staged_hooks" / "guard-raw-data.py"
    )
    graw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graw)
    segs = graw._segments('echo "a; b" && echo "c; d"')
    assert segs == ['echo "a; b"', 'echo "c; d"']


# ------------------------------------------------ git commit/tag message exemption
# (2026-08-03): `git commit -m "..."` is prose the user wrote, not a file read - it must not
# trip the marker scan just for MENTIONING the guard's own marker string.


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "fix: reads of data/raw/ were unsafe, closed the gap"',
        'git commit --message="mentions data/raw in passing"',
        'git tag -m "release notes mention data/raw handling"',
        "git commit --message=data/raw/mentioned/inline",  # same exemption, inline `=` form
    ],
)
def test_git_commit_or_tag_message_mentioning_marker_allowed(project_with_raw, command):
    assert not _blocks(project_with_raw, "Bash", {"command": command})


def test_git_commit_message_file_argument_still_blocks(project_with_raw):
    """The exemption covers the -m/--message VALUE only. `-F <file>` names an actual FILE to
    read (the message comes FROM that file), so it stays covered."""
    assert _blocks(project_with_raw, "Bash", {"command": "git commit -F data/raw/message.txt"})


def test_git_subcommand_other_than_commit_or_tag_gets_no_message_exemption(project_with_raw):
    """`-m` is used by several git subcommands for unrelated purposes (e.g. `git show -m`,
    `git log -m`) - only `commit`/`tag` are message-authoring subcommands, so only those get
    the exemption. A marker-shaped -m value elsewhere still trips the ordinary scan."""
    assert _blocks(project_with_raw, "Bash", {"command": "git log -m data/raw/trades.csv"})


# ------------------------------------------------ crash / payload semantics preserved


def test_malformed_payload_still_fails_open(project_with_raw):
    proc = subprocess.run(
        [sys.executable, str(STAGED_PATH)],
        input="not json at all",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project_with_raw)},
    )
    assert proc.returncode == 0


def test_non_dict_payload_fails_closed(project_with_raw):
    proc = subprocess.run(
        [sys.executable, str(STAGED_PATH)],
        input='"a bare string"',
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project_with_raw)},
    )
    assert proc.returncode == 2


# ------------------------------------------------ live/staged sync (fails until applied)


def test_live_guard_matches_staged_once_applied():
    """Hard failure, not a skip.

    guard-raw-data.py had NO staged copy before today, so this sync path never existed. The
    audit found guard-code-execution.py drifted from its staged copy while the suite reported
    green, because its sync test called pytest.skip(). A regression net that goes quiet when
    the thing it guards is unapplied is the exact failure mode this repo exists to warn about.
    """
    live = LIVE_PATH.read_text(encoding="utf-8")
    staged = STAGED_PATH.read_text(encoding="utf-8")
    assert live == staged, (
        "live guard-raw-data.py differs from its staged copy - "
        "run: bash scripts/apply-guard-raw-coverage.sh"
    )
