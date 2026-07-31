"""The 'closing' transitional status and the close gate (2026-07-29 register, R5/G4/R6).

R5: the documented close order (email + report BEFORE `set-status closed`) transiently
tripped the close-only checks, and the stop-gate nudge told a resumed session to delete
the just-written close pack. `closing` makes the window recognisable on disk.

R6: `set-status closed` validated only closed-state completeness, so a resumed session
could mint a fully valid ✅ pack that passed no gate. The close now runs the full
mechanical checker and refuses (rolling back) on findings.

G4: `set-status closed` wiped `outstanding` with no trace, making a mistaken close
irreversible from disk. The wiped items are now snapshotted into the log.
"""

from __future__ import annotations

import json

from scripts.engagement_state import load_state, main as es_main, state_path


def _run(art, *argv) -> int:
    return es_main(["--dir", str(art), *argv])


def _closeable(tmp_path):
    """A pack the full DoD checker accepts at close: summary email present and listed."""
    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "T", "--slug", "t")
    (art / "engagement-summary-t.txt").write_text(
        "Done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
    _run(art, "add-artifact", "engagement-summary-t.txt", "--title", "Summary email", "--final")
    _run(art, "set-team", "Ana (analysis)")
    return art


def test_closing_is_a_valid_status(tmp_path):
    art = _closeable(tmp_path)
    assert _run(art, "set-status", "closing") == 0
    state = load_state(art)
    assert state["status"] == "closing"
    assert state["engagement"]["closed"] is None
    index = (art / "START-HERE.md").read_text(encoding="utf-8")
    assert "🔒" in index and "CLOSING" in index


def test_close_refused_on_gate_findings_rolls_back(tmp_path, capsys):
    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "T", "--slug", "t")
    _run(art, "set-team", "Ana (analysis)")
    # No summary email: the checker must refuse the close and restore the prior state.
    rc = _run(art, "set-status", "closed", "--verdict", "done")
    assert rc == 1
    err = capsys.readouterr().err
    assert "CLOSE-REFUSED" in err and "MISSING-SUMMARY-EMAIL" in err
    state = load_state(art)
    assert state["status"] == "in_progress"
    assert state["engagement"]["closed"] is None
    assert state["outstanding"]  # the init defaults survived the rollback
    assert "✅ CLOSED" not in (art / "START-HERE.md").read_text(encoding="utf-8")


def test_close_refused_on_stale_index_link(tmp_path, capsys):
    art = _closeable(tmp_path)
    _run(art, "add-artifact", "ghost.md", "--title", "Never written", "--final")
    rc = _run(art, "set-status", "closed", "--verdict", "done")
    assert rc == 1
    assert "STALE-INDEX" in capsys.readouterr().err
    assert load_state(art)["status"] == "in_progress"


def test_close_succeeds_and_logs_cleared_outstanding(tmp_path):
    art = _closeable(tmp_path)
    before = load_state(art)["outstanding"]
    assert before  # init seeds the gates ahead
    assert _run(art, "set-status", "closed", "--verdict", "done") == 0
    state = load_state(art)
    assert state["status"] == "closed" and state["outstanding"] == []
    joined = " ".join(state["log"])
    assert "close" in joined and str(len(before)) in joined
    assert before[0].split(" - ")[0] in joined  # the wiped items are recoverable from the log


def test_close_from_closing_succeeds(tmp_path):
    art = _closeable(tmp_path)
    assert _run(art, "set-status", "closing") == 0
    assert _run(art, "set-status", "closed", "--verdict", "done") == 0
    assert load_state(art)["status"] == "closed"


def test_hand_minted_closed_state_still_judged_by_checker(tmp_path):
    """The R6 mint (writing the JSON by hand) remains possible on disk - but the checker
    still judges the pack, so the mint no longer passes silently."""
    from scripts.check_artifacts import check

    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "T", "--slug", "t")
    state = load_state(art)
    state["status"] = "closed"
    state["engagement"]["closed"] = "2026-07-29"
    state["outstanding"] = []
    state["team"] = ["Ana (analysis)"]
    state_path(art).write_text(json.dumps(state), encoding="utf-8")
    _run(art, "render")
    assert any("MISSING-SUMMARY-EMAIL" in f for f in check(art))
