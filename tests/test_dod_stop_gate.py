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


def _run_bare(monkeypatch, capsys, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main()
    return rc, capsys.readouterr().out


# Session scoping (2026-08-16): the STAGED hook arms only when the payload's session_id
# matches the acting-session stamp in artifacts/.team-session.json. The live copy under
# test here ignores both until the staged fix is applied, so adding them now is inert -
# and it keeps this whole suite green the moment the human runs the apply script.
_SID = "sess-live-suite"


def _stamped_run(run_fn, monkeypatch, capsys, payload: dict):
    payload.setdefault("session_id", _SID)
    cwd = payload.get("cwd")
    if cwd:
        art = Path(cwd) / "artifacts"
        if art.is_dir():
            (art / ".team-session.json").write_text(json.dumps({"session": _SID}), encoding="utf-8")
    return run_fn(monkeypatch, capsys, payload)


def _run(monkeypatch, capsys, payload: dict):
    return _stamped_run(_run_bare, monkeypatch, capsys, payload)


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

    from _staging import staged_or_live

    path = staged_or_live("dod_stop_gate.py")  # staged copy while pending, else live (step 3.6)
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


# --- session-owned ACTIVE marker + other-pack summarisation (2026-08-17 live report) ------


def _owned_setup(tmp_path, marker_session: str):
    """Two gated workspaces, ACTIVE marker on 'previous', arming stamp for THIS session."""
    art = tmp_path / "artifacts"
    for slug in ("previous", "sibling"):
        (art / slug).mkdir(parents=True)
        (art / slug / "engagement-state.json").write_text(
            json.dumps({"schema": 2, "status": "in_progress"}), encoding="utf-8"
        )
    (art / ".active-engagement.json").write_text(
        json.dumps({"slug": "previous", "session": marker_session}), encoding="utf-8"
    )
    (art / ".team-session.json").write_text(json.dumps({"session": "sess-mine"}), encoding="utf-8")
    return art


def _run_staged(monkeypatch, capsys, payload, project):
    staged = _load_staged_gate()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = staged.main()
    return rc, capsys.readouterr().out


def test_another_sessions_active_pack_gets_no_fix_list(tmp_path, monkeypatch, capsys):
    """The 7-minute live detour (2026-08-17): a fresh engagement's intake ended a turn
    while the ACTIVE marker still named the previous engagement - the fix-list sent the
    model off repairing it. A marker owned by ANOTHER session now yields surface-only
    output: no AUTO-FIX instruction, an explicit do-not-act, and summaries instead of
    finding bodies."""
    _owned_setup(tmp_path, marker_session="sess-somebody-else")
    rc, out = _run_staged(
        monkeypatch, capsys, {"session_id": "sess-mine", "cwd": str(tmp_path)}, tmp_path
    )
    assert rc == 0
    decision = json.loads(out)
    reason = decision["reason"]
    assert "do NOT fix" in reason
    assert "AUTO-FIX" not in reason
    # 2026-08-18 tightening: COUNT only - no per-pack lines, no finding codes
    assert "open engagement(s)/area(s)" in reason
    assert "finding(s):" not in reason  # no per-pack summaries either
    assert "expected" not in reason  # no finding BODIES (schema detail text)


def test_own_sessions_active_pack_keeps_the_fix_list(tmp_path, monkeypatch, capsys):
    _owned_setup(tmp_path, marker_session="sess-mine")
    rc, out = _run_staged(
        monkeypatch, capsys, {"session_id": "sess-mine", "cwd": str(tmp_path)}, tmp_path
    )
    assert rc == 0
    reason = json.loads(out)["reason"]
    assert "AUTO-FIX" in reason  # the fix-list applies - this session owns the pack
    assert "[previous]" in reason
    # ...and the SIBLING pack is a COUNT only (2026-08-18): never listed, never coded
    assert "[sibling]" not in reason
    assert "not this session's scope" in reason


def test_legacy_marker_without_session_keeps_old_behaviour(tmp_path, monkeypatch, capsys):
    art = _owned_setup(tmp_path, marker_session="ignored")
    (art / ".active-engagement.json").write_text(json.dumps({"slug": "previous"}), encoding="utf-8")
    rc, out = _run_staged(
        monkeypatch, capsys, {"session_id": "sess-mine", "cwd": str(tmp_path)}, tmp_path
    )
    assert rc == 0
    assert "AUTO-FIX" in json.loads(out)["reason"]


# --- W-6 (2026-09-12 audit): self-serve suppression, and the give-up ceiling -------------


_W6_SID = "sess-w6"


def _w6_project(tmp_path: Path) -> Path:
    """A REAL pack (built by engagement_state, so its own validator is satisfied) carrying
    one stable, unchanging DoD finding.

    A hand-written stub pack would do for the gate's read path, but not here: the W-6
    ceiling is counted in hook-written log notes, and `log-note` refuses to mutate a state
    file that does not validate - so a stub would silently never count."""
    from scripts import engagement_state as es

    pack = tmp_path / "artifacts" / "eng"
    assert es.main(["init", "--slug", "eng", "--title", "W-6", "--dir", str(pack)]) == 0
    (pack / "NOTES.md").write_text("# notes\n", encoding="utf-8")
    assert es.main(["add-artifact", "NOTES.md", "--title", "Notes", "--dir", str(pack)]) == 0
    (tmp_path / "artifacts" / ".team-session.json").write_text(
        json.dumps({"session": _W6_SID}), encoding="utf-8"
    )
    return pack


def _w6_run(monkeypatch, capsys, tmp_path: Path):
    # Drain first: the fixture's own engagement_state/render_html calls print "wrote ..."
    # to stdout, and this hook's whole contract is that stdout carries the block decision
    # and nothing else - leftover setup chatter would be read as part of it.
    capsys.readouterr()
    staged = _load_staged_gate()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"session_id": _W6_SID, "cwd": str(tmp_path)}))
    )
    rc = staged.main()
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _w6_log(pack: Path) -> str:
    return json.dumps(
        json.loads((pack / "engagement-state.json").read_text(encoding="utf-8")).get("log") or []
    )


def test_w6_a_claimed_suppression_does_not_silence_an_unresolved_finding(
    tmp_path, monkeypatch, capsys
):
    """The whole W-6 finding: `dod-nudged:<hash>` is a deterministic hash of the printed
    findings, so recording it needed none of the work it claimed. The findings reported
    here come from a check that just ran, so a marker on THIS hash means they are still
    open - the gate must block anyway and say the note did not match reality."""
    from scripts import engagement_state as es

    pack = _w6_project(tmp_path)
    staged = _load_staged_gate()
    from scripts import check_artifacts as ca

    findings = [f"[eng] {f}" for f in ca.check(pack)]
    digest = staged._findings_hash(findings)
    assert es.main(["log-note", f"dod-nudged:{digest}", "--dir", str(pack)]) == 0

    rc, out, _err = _w6_run(monkeypatch, capsys, tmp_path)
    assert rc == 0
    reason = json.loads(out)["reason"]
    assert "STILL reports the same findings" in reason
    assert "MISSING-HTML" in reason


def test_w6_the_gate_gives_up_after_three_blocks_and_records_it(tmp_path, monkeypatch, capsys):
    """A finding nobody can clear must not nudge forever. Three blocks, then a warning on
    stderr (no block decision, so the turn can end) and DOD-GATE-EXHAUSTED in the log, so
    a gate that went quiet is distinguishable from a gate that was satisfied."""
    pack = _w6_project(tmp_path)

    for expected_blocks in (1, 2, 3):
        rc, out, err = _w6_run(monkeypatch, capsys, tmp_path)
        assert rc == 0
        assert json.loads(out)["decision"] == "block"
        assert err == ""
        # The count is kept in the pack's own log by the hook, never by the model, and
        # never printed in the reason (the reason must stay identical between stops).
        assert _w6_log(pack).count("dod-gate-block:") == expected_blocks

    rc, out, err = _w6_run(monkeypatch, capsys, tmp_path)
    assert rc == 0
    assert out == "", "the gate must stop BLOCKING once exhausted, so the turn can end"
    assert "DOD-GATE-EXHAUSTED recorded" in err
    assert "DOD-GATE-EXHAUSTED" in _w6_log(pack)


def test_w6_exhausted_is_recorded_once_not_on_every_later_stop(tmp_path, monkeypatch, capsys):
    pack = _w6_project(tmp_path)
    for _ in range(6):
        _w6_run(monkeypatch, capsys, tmp_path)
    assert _w6_log(pack).count("DOD-GATE-EXHAUSTED") == 1


def test_w6_actually_clearing_the_finding_ends_the_nudges(tmp_path, monkeypatch, capsys):
    """The other direction, and the only one that should ever silence the gate: fix the
    finding and the next stop is silent - no block, no warning, nothing recorded."""
    pack = _w6_project(tmp_path)
    rc, out, _err = _w6_run(monkeypatch, capsys, tmp_path)
    assert json.loads(out)["decision"] == "block"

    # Render the missing sibling the same way the fix-list tells the model to.
    from scripts import render_html

    render_html.render_file(pack / "NOTES.md")
    rc, out, err = _w6_run(monkeypatch, capsys, tmp_path)
    assert rc == 0
    assert out == "" and err == ""


def test_w6_after_exhaustion_new_findings_still_surface_as_a_warning(tmp_path, monkeypatch, capsys):
    """The ceiling is per ENGAGEMENT, so a later finding does not re-arm the block - but it
    must still be SEEN. The degraded warning keeps printing the current findings at every
    stop, so drift after a give-up is surfaced rather than swallowed."""
    from scripts import engagement_state as es

    pack = _w6_project(tmp_path)
    for _ in range(4):
        _w6_run(monkeypatch, capsys, tmp_path)

    (pack / "SECOND.md").write_text("# second\n", encoding="utf-8")
    assert es.main(["add-artifact", "SECOND.md", "--title", "Second", "--dir", str(pack)]) == 0
    rc, out, err = _w6_run(monkeypatch, capsys, tmp_path)
    assert rc == 0
    assert out == "", "exhausted means no more blocking, whatever the findings are"
    assert "SECOND.md" in err, "the new finding must still be printed in the warning"


# ---- 2026-09-14 live report: the marker home is the pack the findings came from


def test_marker_home_is_the_contributing_pack_not_the_first_gated_one(tmp_path):
    staged = _load_staged_gate()
    first, second = tmp_path / "alpha", tmp_path / "vrtsrv-13"
    gated = [("alpha", first), ("vrtsrv-13", second)]
    # Only the second pack contributed findings: it is the home, whatever the order.
    assert staged.marker_home(gated, [("vrtsrv-13", second)], None) == ("vrtsrv-13", second)
    # Several contributed and one is ACTIVE: the active one.
    assert staged.marker_home(gated, gated, "vrtsrv-13") == ("vrtsrv-13", second)
    # Several contributed, none active: the first contributing (the old rule, narrowed).
    assert staged.marker_home(gated, gated, None) == ("alpha", first)
    # Nothing contributed (project-level findings only): the old rule, unchanged.
    assert staged.marker_home(gated, [], None) == ("alpha", first)
    assert staged.marker_home([("", tmp_path), *gated], [], None) == ("", tmp_path)


def test_two_open_engagements_the_remediation_names_the_pack_with_the_findings(
    tmp_path, monkeypatch, capsys
):
    """VRTSRV-13, 2026-09-14: findings belonged to one pack, the hook hardcoded the first
    gated slug in the command it printed, the block note landed in that other pack's log,
    and the next stop escalated against a pack a direct check found clean. Now the slug in
    the command, the note and the marker check all follow the findings."""
    from scripts import engagement_state as es

    art = tmp_path / "artifacts"
    clean = art / "alpha-clean"
    dirty = art / "vrtsrv-13"
    for slug, pack in (("alpha-clean", clean), ("vrtsrv-13", dirty)):
        assert es.main(["init", "--slug", slug, "--title", slug, "--dir", str(pack)]) == 0
    (dirty / "NOTES.md").write_text("# notes\n", encoding="utf-8")  # MISSING-HTML on this pack
    assert es.main(["add-artifact", "NOTES.md", "--title", "Notes", "--dir", str(dirty)]) == 0
    (art / ".team-session.json").write_text(json.dumps({"session": _W6_SID}), encoding="utf-8")
    # A stale suppression note on the CLEAN pack must not be read as a claim about the
    # dirty one.
    assert es.main(["log-note", "dod-nudged:0000000000000000", "--dir", str(clean)]) == 0
    capsys.readouterr()
    staged = _load_staged_gate()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"session_id": _W6_SID, "cwd": str(tmp_path)}))
    )
    assert staged.main() == 0
    out = capsys.readouterr().out
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "engagement_state --slug vrtsrv-13 log-note" in decision["reason"]
    assert "--slug alpha-clean" not in decision["reason"]
    assert "the note claims was done" not in decision["reason"]
    assert "dod-gate-block:" in _w6_log(dirty)
    assert "dod-gate-block:" not in _w6_log(clean)


# --- 2026-09-15 (ISRT): a CLOSED pack drifting after close must re-arm the gate for the
# session's own ACTIVE engagement, and the persisted block note must carry a human-readable
# excerpt, not just a hash + counter.

_CLOSED_DRIFT_SID = "sess-closed-drift"


def _close_cleanly(es, pack: Path, slug: str) -> None:
    """A REAL close with nothing outstanding, so it stores a legitimate scan_fingerprint -
    same recipe as test_engagement_state.py::test_set_status_closed_sets_date_clears_outstanding."""
    assert es.main(["init", "--slug", slug, "--title", slug, "--dir", str(pack)]) == 0
    assert es.main(["set-team", "Amara (BA)", "--dir", str(pack)]) == 0
    (pack / f"engagement-summary-{slug}.txt").write_text(
        f"Done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
    assert (
        es.main(
            [
                "add-artifact",
                f"engagement-summary-{slug}.txt",
                "--title",
                "Email",
                "--final",
                "--dir",
                str(pack),
            ]
        )
        == 0
    )
    assert es.main(["set-footprint", "--agents", "1", "--tokens", "10k", "--dir", str(pack)]) == 0
    assert es.main(["set-status", "closed", "--verdict", "ready", "--dir", str(pack)]) == 0


def test_closed_active_pack_reopens_gate_when_disk_moved_since_close(tmp_path, monkeypatch, capsys):
    from scripts import engagement_state as es

    art = tmp_path / "artifacts"
    pack = art / "z1"
    _close_cleanly(es, pack, "z1")
    state_before = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))
    assert state_before["status"] == "closed" and state_before.get("scan_fingerprint")

    # Post-close edit: add-artifact carries no closed-pack guard (that gap is real and
    # deliberately NOT closed here - see the fix note) - a new FINAL .md (closed-status
    # validation requires final, not interim) with no rendered .html sibling is registered
    # after the close gate already ran and passed.
    (pack / "NOTES.md").write_text("# late addition\n", encoding="utf-8")
    assert (
        es.main(
            ["add-artifact", "NOTES.md", "--title", "Late notes", "--final", "--dir", str(pack)]
        )
        == 0
    )

    (art / ".active-engagement.json").write_text(
        json.dumps({"slug": "z1", "session": _CLOSED_DRIFT_SID}), encoding="utf-8"
    )
    (art / ".team-session.json").write_text(
        json.dumps({"session": _CLOSED_DRIFT_SID}), encoding="utf-8"
    )
    capsys.readouterr()
    staged = _load_staged_gate()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"session_id": _CLOSED_DRIFT_SID, "cwd": str(tmp_path)})),
    )
    assert staged.main() == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "MISSING-HTML" in decision["reason"]

    # The persisted block note carries a readable excerpt, not just a hash + counter.
    log = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))["log"]
    block_entries = [e for e in log if "dod-gate-block:" in str(e)]
    assert block_entries, "no dod-gate-block: entry was persisted"
    assert "MISSING-HTML" in str(block_entries[-1]), (
        "the persisted marker is still just a hash + counter - the human-readable excerpt "
        "did not make it into the log"
    )


def test_closed_pack_untouched_since_close_stays_silent(tmp_path, monkeypatch, capsys):
    """The counterpart guard: a closed pack nobody touched since close must NOT re-arm -
    only actual drift (fingerprint mismatch) does."""
    from scripts import engagement_state as es

    art = tmp_path / "artifacts"
    pack = art / "z2"
    _close_cleanly(es, pack, "z2")
    (art / ".active-engagement.json").write_text(
        json.dumps({"slug": "z2", "session": _CLOSED_DRIFT_SID}), encoding="utf-8"
    )
    (art / ".team-session.json").write_text(
        json.dumps({"session": _CLOSED_DRIFT_SID}), encoding="utf-8"
    )
    capsys.readouterr()
    staged = _load_staged_gate()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"session_id": _CLOSED_DRIFT_SID, "cwd": str(tmp_path)})),
    )
    assert staged.main() == 0
    assert capsys.readouterr().out == ""
