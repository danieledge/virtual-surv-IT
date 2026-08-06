"""Tests for the STAGED findings-pack-write scope guard
(scripts/staged_hooks/guard-findings-pack-write.py; installed by the human via
scripts/apply-guard-findings-pack-write.sh, ADR-002 rec 5 / house rule "don't edit the
guards").

Token-usage audit (P4, 2026-08-03): `code-reviewer`, `compliance-reviewer`,
`model-validator` and `performance-reviewer` were granted `Write` so each can author its own
findings-pack JSON directly, instead of returning it through the orchestrator's context and
having the orchestrator re-emit it (halving that round-trip's token cost). A Write grant with
no path restriction is a much bigger blast radius than "author one JSON file", so this guard
mechanically scopes it: fires only when the calling `agent_type` is one of the four, and
blocks unless the target matches the findings-pack shape.

Live freedom-dashboard diagnostic (2026-08-06): the same four agents were also granted `Edit`,
scoped by this guard to the identical path pattern, so a scoped agent that hits the Write
size cap (below) can chunk its own pack incrementally instead of silently dropping findings -
the same option the orchestrator already had. The scoping half of the guard now fires for
both `Write` and `Edit`; the size-cap half stays `Write`-only (Edit is the intended way past
it, so it must stay exempt).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGED_PATH = REPO / "scripts" / "staged_hooks" / "guard-findings-pack-write.py"
LIVE_PATH = REPO / ".claude" / "hooks" / "guard-findings-pack-write.py"

_SCOPED_AGENTS = ("code-reviewer", "compliance-reviewer", "model-validator", "performance-reviewer")


def _run(payload: dict) -> int:
    proc = subprocess.run(
        [sys.executable, str(STAGED_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return proc.returncode


def _blocks(tool: str, tool_input: dict, agent_type: str | None) -> bool:
    payload = {"tool_name": tool, "tool_input": tool_input}
    if agent_type is not None:
        payload["agent_type"] = agent_type
    return _run(payload) == 2


# ------------------------------------------------ scope: which agents, which tool


def test_orchestrators_own_write_is_untouched():
    """No agent_type field at all (the orchestrator's own call) - this guard has no
    opinion, whatever the path."""
    assert not _blocks("Write", {"file_path": "src/anything.py"}, None)


def test_orchestrators_own_edit_is_untouched():
    assert not _blocks("Edit", {"file_path": "src/anything.py"}, None)


def test_unrelated_agent_type_is_untouched():
    """An agent this guard doesn't scope (e.g. a build agent that legitimately writes
    source code) is not this guard's concern."""
    assert not _blocks("Write", {"file_path": "src/anything.py"}, "rules-developer")


def test_unrelated_agent_type_edit_is_untouched():
    assert not _blocks("Edit", {"file_path": "src/anything.py"}, "rules-developer")


def test_non_write_edit_tool_is_untouched():
    assert not _blocks(
        "Read", {"file_path": "artifacts/x/data/findings-x.json"}, "compliance-reviewer"
    )


# ------------------------------------------------ the four scoped agents, allowed path

_TOOLS = ("Write", "Edit")


def _allowed_paths():
    for agent in _SCOPED_AGENTS:
        yield agent, f"artifacts/my-slug/data/findings-{agent}.json"
        yield agent, "artifacts/data/findings-flat.json"  # flat pack, no slug directory


def test_scoped_agents_can_write_their_own_findings_pack():
    for agent, path in _allowed_paths():
        assert not _blocks("Write", {"file_path": path}, agent), f"{agent} blocked on {path!r}"


def test_scoped_agents_can_edit_their_own_findings_pack():
    for agent, path in _allowed_paths():
        assert not _blocks("Edit", {"file_path": path}, agent), f"{agent} blocked on {path!r}"


def test_scoped_agents_can_write_an_absolute_findings_pack_path():
    assert not _blocks(
        "Write",
        {"file_path": "/home/user/project/artifacts/my-slug/data/findings-my-slug.json"},
        "compliance-reviewer",
    )


def test_scoped_agents_can_edit_an_absolute_findings_pack_path():
    assert not _blocks(
        "Edit",
        {"file_path": "/home/user/project/artifacts/my-slug/data/findings-my-slug.json"},
        "compliance-reviewer",
    )


def test_scoped_agents_can_write_windows_style_path():
    assert not _blocks(
        "Write",
        {"file_path": r"C:\project\artifacts\my-slug\data\findings-my-slug.json"},
        "model-validator",
    )


def test_scoped_agents_can_edit_windows_style_path():
    assert not _blocks(
        "Edit",
        {"file_path": r"C:\project\artifacts\my-slug\data\findings-my-slug.json"},
        "model-validator",
    )


# ------------------------------------------------ the four scoped agents, disallowed path


def test_scoped_agents_cannot_write_outside_the_findings_pack_shape():
    for agent in _SCOPED_AGENTS:
        assert _blocks("Write", {"file_path": "src/app.py"}, agent)
        assert _blocks("Write", {"file_path": "CLAUDE.md"}, agent)
        assert _blocks("Write", {"file_path": ".claude/settings.json"}, agent)


def test_scoped_agents_cannot_edit_outside_the_findings_pack_shape():
    for agent in _SCOPED_AGENTS:
        assert _blocks("Edit", {"file_path": "src/app.py"}, agent)
        assert _blocks("Edit", {"file_path": "CLAUDE.md"}, agent)
        assert _blocks("Edit", {"file_path": ".claude/settings.json"}, agent)


def test_scoped_agent_cannot_write_the_rendered_report_directly():
    """The rendered .md/.html is the RENDERER's output (check_artifacts --fix), never
    hand-authored - these agents author the JSON pack only."""
    assert _blocks(
        "Write", {"file_path": "artifacts/my-slug/REVIEW-my-slug.md"}, "code-reviewer"
    )


def test_scoped_agent_cannot_edit_the_rendered_report_directly():
    assert _blocks(
        "Edit", {"file_path": "artifacts/my-slug/REVIEW-my-slug.md"}, "code-reviewer"
    )


def test_scoped_agent_cannot_write_a_findings_looking_path_in_the_wrong_directory():
    """The shape must be genuinely under artifacts/.../data/, not just contain the
    filename pattern anywhere in a path."""
    assert _blocks("Write", {"file_path": "data/findings-x.json"}, "compliance-reviewer")
    assert _blocks(
        "Write", {"file_path": "artifacts/my-slug/findings-my-slug.json"}, "compliance-reviewer"
    )  # missing the /data/ segment


def test_empty_path_blocks_for_both_tools():
    for tool in _TOOLS:
        assert _blocks(tool, {"file_path": ""}, "performance-reviewer")


# ------------------------------------------------ crash / payload semantics


def test_malformed_payload_fails_open():
    proc = subprocess.run(
        [sys.executable, str(STAGED_PATH)],
        input="not json at all",
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0


def test_non_dict_tool_input_treated_as_empty():
    assert _blocks("Write", {}, "code-reviewer")  # missing tool_input -> empty path -> blocked
    assert _blocks("Edit", {}, "code-reviewer")


# ------------------------ size limit (2026-08-05, opt-in via large_context_review_split)


def _pack_content(n_findings: int) -> str:
    finding = {
        "id": "F1", "title": "t", "severity": "warning", "location": "a.py:1",
        "basis": "coded", "standard": "s", "problem": "p", "likely_cause": "c",
        "impact": "i", "fix": {"diff": "-x\n+y", "why": "w"}, "disposition": "open",
    }
    return json.dumps({"findings": [dict(finding, id=f"F{i}") for i in range(n_findings)]})


def _run_with_project(payload: dict, project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STAGED_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(project_dir)},
    )


def _write_prefs(project_dir: Path, split_on: bool | None) -> None:
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    if split_on is None:
        return  # no file at all - the common case
    (claude_dir / "team-preferences.json").write_text(
        json.dumps({"large_context_review_split": split_on}), encoding="utf-8"
    )


def test_size_limit_silent_when_split_off_by_default(tmp_path):
    _write_prefs(tmp_path, None)  # no team-preferences.json at all
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "artifacts/x/data/findings-x.json", "content": _pack_content(20)},
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 0


def test_size_limit_silent_when_split_explicitly_off(tmp_path):
    _write_prefs(tmp_path, False)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "artifacts/x/data/findings-x.json", "content": _pack_content(20)},
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 0


def test_size_limit_blocks_oversized_orchestrator_write_when_split_on(tmp_path):
    _write_prefs(tmp_path, True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "artifacts/x/data/findings-x.json", "content": _pack_content(9)},
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 2
    assert "findings-pack size limit" in proc.stderr
    assert "Edit" in proc.stderr


def test_size_limit_allows_write_at_the_threshold(tmp_path):
    _write_prefs(tmp_path, True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "artifacts/x/data/findings-x.json", "content": _pack_content(8)},
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 0


def test_size_limit_applies_to_scoped_agent_too_when_split_on(tmp_path):
    _write_prefs(tmp_path, True)
    payload = {
        "tool_name": "Write",
        "agent_type": "code-reviewer",
        "tool_input": {"file_path": "artifacts/x/data/findings-x.json", "content": _pack_content(9)},
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 2
    assert "findings-pack size limit" in proc.stderr


def test_size_limit_ignored_when_content_not_valid_json(tmp_path):
    _write_prefs(tmp_path, True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "artifacts/x/data/findings-x.json", "content": "not json"},
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 0


def test_size_limit_ignored_when_path_is_not_a_findings_pack(tmp_path):
    _write_prefs(tmp_path, True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "artifacts/notes.md", "content": _pack_content(50)},
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 0


def test_size_limit_never_applies_to_edit_even_when_split_on(tmp_path):
    """Edit is the sanctioned way past the cap (append in batches) - capping it too would
    defeat the point of granting it. Edit's tool_input has no `content` field anyway
    (old_string/new_string instead), but this locks in the behaviour explicitly rather than
    relying on that shape mismatch as an accident of implementation."""
    _write_prefs(tmp_path, True)
    payload = {
        "tool_name": "Edit",
        "agent_type": "performance-reviewer",
        "tool_input": {
            "file_path": "artifacts/x/data/findings-x.json",
            "old_string": "]",
            "new_string": _pack_content(50) + "]",
        },
    }
    proc = _run_with_project(payload, tmp_path)
    assert proc.returncode == 0


# ------------------------------------------------ live/staged sync (fails until applied)


def test_live_guard_matches_staged_once_applied():
    """Hard failure, not a skip - the 2026-08-01 audit found a guard drift while the suite
    reported green because its sync test called pytest.skip(); this guard never repeats
    that mistake even on day one."""
    if not LIVE_PATH.is_file():
        raise AssertionError(
            "guard-findings-pack-write.py not yet installed - "
            "run: bash scripts/apply-guard-findings-pack-write.sh"
        )
    live = LIVE_PATH.read_text(encoding="utf-8")
    staged = STAGED_PATH.read_text(encoding="utf-8")
    assert live == staged, (
        "live guard-findings-pack-write.py differs from its staged copy - "
        "run: bash scripts/apply-guard-findings-pack-write.sh"
    )
