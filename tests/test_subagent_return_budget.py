"""scripts/subagent_return_budget.py: PostToolUse feedback on Task completion when a
subagent's return clearly exceeds the operating guide's condensed-return budget (audit
finding #4, 2026-07-30 - "a hard budget, not a nicety" was previously enforced only by
wording in the delegation brief, nothing measured the actual return).

The exact Task-tool tool_response schema is not documented anywhere in this repo and this
hook was written without a live sample to verify against - these tests pin the DEFENSIVE
extraction across several plausible shapes and the fail-silent behaviour on anything else,
which is the honest, verifiable contract regardless of which shape turns out to be real."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "staged_hooks" / "subagent_return_budget.py"
LIVE_HOOK = REPO_ROOT / "scripts" / "subagent_return_budget.py"


def _run(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    payload = {"cwd": str(cwd), **payload}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _live_project(tmp_path: Path) -> Path:
    art = tmp_path / "artifacts" / "eng"
    art.mkdir(parents=True)
    (art / "engagement-state.json").write_text(
        json.dumps({"status": "in_progress"}), encoding="utf-8"
    )
    return tmp_path


def test_non_task_tool_is_silent(tmp_path):
    proj = _live_project(tmp_path)
    proc = _run({"tool_name": "Bash", "tool_response": "x" * 100000}, proj)
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_dormant_project_is_silent_even_with_a_huge_return(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    proc = _run({"tool_name": "Task", "tool_response": "word " * 5000, "tool_input": {}}, tmp_path)
    assert proc.returncode == 0


def test_short_return_within_budget_is_silent(tmp_path):
    proj = _live_project(tmp_path)
    proc = _run({"tool_name": "Task", "tool_response": "A short summary.", "tool_input": {}}, proj)
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_bare_string_response_over_budget_flags(tmp_path):
    proj = _live_project(tmp_path)
    huge = "word " * 3000  # ~15000 chars => ~3750 estimated tokens, over the 3000 trigger
    proc = _run({"tool_name": "Task", "tool_response": huge, "tool_input": {}}, proj)
    assert proc.returncode == 2
    assert "condensed-return budget" in proc.stderr


def test_content_dict_shape_over_budget_flags(tmp_path):
    proj = _live_project(tmp_path)
    huge = "word " * 3000
    proc = _run({"tool_name": "Task", "tool_response": {"content": huge}, "tool_input": {}}, proj)
    assert proc.returncode == 2


def test_content_block_list_shape_over_budget_flags(tmp_path):
    proj = _live_project(tmp_path)
    huge = "word " * 3000
    proc = _run(
        {
            "tool_name": "Task",
            "tool_response": {"content": [{"type": "text", "text": huge}]},
            "tool_input": {},
        },
        proj,
    )
    assert proc.returncode == 2


def test_output_key_shape_over_budget_flags(tmp_path):
    proj = _live_project(tmp_path)
    huge = "word " * 3000
    proc = _run({"tool_name": "Task", "tool_response": {"output": huge}, "tool_input": {}}, proj)
    assert proc.returncode == 2


def test_over_line_budget_alone_also_flags(tmp_path):
    """Long but sparse text (many short lines) should trip the line trigger even if the
    char/4 token estimate alone would not."""
    proj = _live_project(tmp_path)
    text = "\n".join(f"line {i}" for i in range(70))  # > 60-line trigger
    proc = _run({"tool_name": "Task", "tool_response": text, "tool_input": {}}, proj)
    assert proc.returncode == 2


def test_unrecognized_response_shape_is_silent_not_a_crash(tmp_path):
    proj = _live_project(tmp_path)
    proc = _run({"tool_name": "Task", "tool_response": [1, 2, 3], "tool_input": {}}, proj)
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_garbage_stdin_never_crashes():
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input="{not json", capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0


def test_message_names_the_subagent_when_description_given(tmp_path):
    proj = _live_project(tmp_path)
    huge = "word " * 3000
    proc = _run(
        {
            "tool_name": "Task",
            "tool_response": huge,
            "tool_input": {"description": "Audit LLM-vs-mechanical reliance"},
        },
        proj,
    )
    assert "Audit LLM-vs-mechanical reliance" in proc.stderr


def test_staged_and_live_launchers_match_when_installed():
    if not LIVE_HOOK.is_file():
        pytest_skip_missing()
    assert LIVE_HOOK.read_bytes() == HOOK.read_bytes()


def pytest_skip_missing():
    import pytest

    pytest.skip("live hook not installed in this checkout")
