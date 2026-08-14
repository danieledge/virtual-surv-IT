"""Behaviour tests for the warn-first DoD Stop-hook backstop (scripts/dod_stop_gate.py, finding #6).

Pins the four branches so the hook stays low-noise and loop-safe:
  * `stop_hook_active` -> no-op (never loops the model);
  * no living index -> silent (never nags legacy/dormant artifacts folders);
  * ✅ closed index -> silent;
  * ⏳/⛔ open index with a DoD finding -> exactly one `block` nudge.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import scripts.dod_stop_gate as gate


def _run(monkeypatch, capsys, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main()
    return rc, capsys.readouterr().out


def test_stop_hook_active_is_noop(monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, {"stop_hook_active": True})
    assert rc == 0
    assert out == ""


def test_no_start_here_is_silent(tmp_path, monkeypatch, capsys):
    (tmp_path / "artifacts").mkdir()
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    assert out == ""


def test_closed_engagement_is_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ✅ closed\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    assert out == ""


def test_open_engagement_with_findings_nudges_once(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    # A deliverable .md with no rendered .html sibling -> a MISSING-HTML finding from check_artifacts.
    (art / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")

    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "DoD backstop" in decision["reason"]


def test_open_but_clean_does_not_nudge(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    # Open engagement, but the only artifact is START-HERE itself with its .html sibling and it
    # lists itself - check_artifacts should be satisfied, so no nudge.
    (art / "START-HERE.md").write_text(
        "Status: ⏳ in progress\n\n- [START-HERE](START-HERE.md)\n", encoding="utf-8"
    )
    (art / "START-HERE.html").write_text("<p>ok</p>\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    # May legitimately be silent (clean) - assert we did not hard-error and produced no block.
    assert out == "" or json.loads(out).get("decision") != "block"


def test_unscored_review_pack_surfaces_in_nudge(tmp_path, monkeypatch, capsys):
    """PACK-UNSCORED reaches the model through the existing Stop-hook path with no new
    wiring - an open engagement whose scored-kind pack records no review-scorer pass is
    nudged at turn end, while the scorer delegation can still run."""
    from scripts.findings_pack_io import write_pack

    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text(
        "Status: ⏳ in progress\n\n- `data/findings-t.jsonl`\n", encoding="utf-8"
    )
    (art / "START-HERE.html").write_text("<p>ok</p>\n", encoding="utf-8")
    write_pack(
        art / "data" / "findings-t.jsonl",
        {
            "slug": "t",
            "scope": "s",
            "mode": "audit",
            "verdict": "conditional",
            "findings": [
                {
                    "id": "F1",
                    "title": "t",
                    "severity": "warning",
                    "location": "a.py:1",
                    "basis": "coded",
                    "standard": "CWE-1",
                    "problem": "p",
                    "likely_cause": "c",
                    "impact": "i",
                    "fix": {"diff": "-x\n+y", "why": "w"},
                    "disposition": "open",
                }
            ],
        },
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "PACK-UNSCORED" in decision["reason"]


# --------------------------------------------- machine-readable state first (ADR-006)


def test_state_closed_wins_over_stale_open_render(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 1, "status": "closed"}), encoding="utf-8"
    )
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""  # the state is authoritative


def test_state_open_arms_gate_even_without_render(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 1, "status": "in_progress"}), encoding="utf-8"
    )
    # No START-HERE.md at all: legacy sniff finds nothing, the state still arms the gate,
    # and the checker reports the state findings (invalid-minimal state here).
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "STATE-" in decision["reason"]


def test_invalid_state_falls_back_to_emoji_sniff(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text("{broken", encoding="utf-8")
    (art / "START-HERE.md").write_text("Status: ✅ closed\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""  # unreadable state -> legacy sniff -> closed -> silent


def test_blocked_workspace_not_gated_but_in_progress_is(tmp_path, monkeypatch, capsys):
    """0.31 rule: a ⛔ parked workspace stays silent while a sibling ⏳ one is gated."""
    art = tmp_path / "artifacts"
    for slug, status in (("parked", "blocked"), ("active", "in_progress")):
        (art / slug).mkdir(parents=True)
        (art / slug / "engagement-state.json").write_text(
            json.dumps({"schema": 2, "status": status}), encoding="utf-8"
        )
    # the active workspace has a defect (invalid-minimal state -> STATE-INVALID)
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "[active]" in decision["reason"]
    assert "[parked]" not in decision["reason"]


def test_only_blocked_workspaces_stay_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    (art / "parked").mkdir(parents=True)
    (art / "parked" / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "blocked"}), encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


# --- deferral permission when the user's most recent ask is unrelated new work (2026-08-12) ---
#
# Live report: the nudge's own directive tone ("resume and FINISH it") led a session to divert
# into completing an old engagement's DoD work instead of a just-requested new engagement -
# the hook has no visibility into what the user actually asked for, only that a pack is gated.
# Fixed at the instruction level: an explicit, bounded permission to defer, with a hard
# constraint against silently suppressing the finding via the log-note marker while deferring
# (that marker means "acted on", and recording it without acting would be a real loophole -
# a way to make a gap disappear from the nudge without ever having addressed it).
#
# Loads scripts/staged_hooks/dod_stop_gate.py directly (importlib, by path) rather than
# importing scripts.dod_stop_gate - this fix is staged, not yet human-applied to the live
# copy (test_hooks_in_sync.py's test_staged_matches_live correctly flags that as pending,
# same posture as every other staged hook change), so testing the live import would test
# unfixed code.


def _load_staged_gate():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "staged_hooks" / "dod_stop_gate.py"
    spec = importlib.util.spec_from_file_location("staged_dod_stop_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reason_permits_deferring_for_unrelated_new_work():
    staged = _load_staged_gate()
    reason = staged._reason(
        ["PACK-UNSCORED: findings-t.jsonl carries 3 finding(s)..."], [], "slug", "abc123"
    )
    assert "clearly asked for" in reason and "something else" in reason
    assert "proceed with THAT first" in reason


def test_reason_forbids_recording_the_suppression_marker_while_deferring():
    """The deferral permission must not double as a silent-suppress loophole - recording
    the log-note marker means "acted on", not "saw and moved past"."""
    staged = _load_staged_gate()
    reason = staged._reason(
        ["PACK-UNSCORED: findings-t.jsonl carries 3 finding(s)..."], [], "slug", "abc123"
    )
    assert "do **NOT** record" in reason
    assert 'log-note "dod-nudged:abc123"' in reason


def test_load_checker_does_not_grow_sys_path_on_repeat_calls(tmp_path):
    """M3 (2026-08-14 daemon-safety audit): same bug class already fixed in
    persona_anchor.py's own _load_checker, missed here - this hook is re-exec'd fresh
    per Stop event INSIDE the daemon when daemon-served (stop_hook_dispatcher.py loads
    it via importlib on every call), so an unconditional sys.path.insert would grow
    the daemon's process-global sys.path without bound over its life. Calling
    _load_checker twice with the SAME project_root must not add a second entry."""
    import sys

    staged = _load_staged_gate()
    project_root = tmp_path
    before = list(sys.path)
    staged._load_checker(project_root)
    after_first = list(sys.path)
    staged._load_checker(project_root)
    after_second = list(sys.path)

    added_by_first = [p for p in after_first if p not in before]
    assert len(added_by_first) <= 1  # at most the one, deliberate insert
    assert after_second == after_first, (
        "a second call with the same project_root grew sys.path again - the dedup "
        "check did not hold"
    )
