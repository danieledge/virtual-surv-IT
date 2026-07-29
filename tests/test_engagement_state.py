"""
Tests for the machine-readable engagement state (scripts/engagement_state.py, ADR-006).

The state file is the authoritative lifecycle record; START-HERE.md is a rendered view.
These tests pin the contract: schema validation (including the hard exclusion of any
consent-like key), single-emoji status rendering the emoji-sniffing consumers rely on,
the embedded state-hash that STATE-STALE-RENDER checks, mutator round-trips, and the
render-on-every-mutation guarantee that keeps the human view on disk at all times.
"""

from __future__ import annotations

import copy
import json

from scripts.engagement_state import (
    embedded_hash,
    load_state,
    main,
    render_markdown,
    state_hash,
    state_path,
    validate_state,
)

_STATE = {
    "schema": 1,
    "engagement": {
        "title": "Test engagement",
        "slug": "test-eng",
        "requested_by": None,
        "opened": "2026-07-26",
        "closed": None,
    },
    "status": "in_progress",
    "phase": "delivery",
    "team": ["Amara (BA)", "Linh (QA)"],
    "verdict": None,
    "footprint": {"agents": 3, "approx_tokens": "40k"},
    "outstanding": ["independent QA - not yet run"],
    "artifacts": [
        {
            "path": "engagement-brief.md",
            "title": "Scope and plan",
            "status": "interim",
            "added": "2026-07-26",
        }
    ],
    "decisions": {"review_depth": "deep"},
    "team_version": "v0.28.0",
}


def _valid() -> dict:
    return copy.deepcopy(_STATE)


# ------------------------------------------------------------------ validation


def test_valid_state_passes():
    assert validate_state(_valid()) == []


def test_bad_status_and_phase_flagged():
    state = _valid()
    state["status"] = "done"
    state["phase"] = "wrapping-up"
    problems = " ".join(validate_state(state))
    assert "status" in problems and "phase" in problems


def test_closed_requires_date_and_empty_outstanding():
    state = _valid()
    state["status"] = "closed"
    problems = " ".join(validate_state(state))
    assert "closed" in problems  # no closed date
    state["engagement"]["closed"] = "2026-07-26"
    problems = " ".join(validate_state(state))
    assert "outstanding" in problems  # still has open items


def test_consent_like_keys_are_forbidden():
    """ADR-002: consent has exactly one home (the human-made marker file). Any consent- or
    exec-shaped key in the model-writable state file must fail validation, at any depth."""
    for bad_key in ("execution_consent", "exec_mode", "consent_granted"):
        state = _valid()
        state[bad_key] = "false"
        assert any("forbidden key" in p for p in validate_state(state)), bad_key
    nested = _valid()
    nested["decisions"]["exec_consent"] = "yes"
    assert any("forbidden key" in p for p in validate_state(nested))


def test_duplicate_artifact_paths_flagged():
    state = _valid()
    state["artifacts"].append(dict(state["artifacts"][0]))
    assert any("duplicates" in p for p in validate_state(state))


# ------------------------------------------------------------------ rendering


def test_render_has_single_status_emoji_line():
    """The legacy consumers (_index_status, hook fallback) sniff status emoji; the rendered
    status line must carry exactly one so it can never be mistaken for a legend."""
    md = render_markdown(_valid())
    status_lines = [ln for ln in md.splitlines() if ln.startswith("| **Status** |")]
    assert len(status_lines) == 1
    line = status_lines[0]
    assert sum(e in line for e in ("⏳", "⛔", "✅")) == 1
    assert "⏳" in line


def test_render_closed_shows_date_and_nothing_outstanding():
    state = _valid()
    state["status"] = "closed"
    state["engagement"]["closed"] = "2026-07-27"
    state["outstanding"] = []
    md = render_markdown(state)
    assert "✅ CLOSED 2026-07-27" in md
    assert "Nothing - closed 2026-07-27." in md


def test_render_embeds_matching_state_hash():
    state = _valid()
    md = render_markdown(state)
    assert embedded_hash(md) == state_hash(state)
    state["outstanding"].append("new item")
    assert embedded_hash(md) != state_hash(state)  # stale render detectable


def test_render_lists_every_artifact():
    state = _valid()
    state["artifacts"].append(
        {
            "path": "review-pass-1.md",
            "title": "First review",
            "status": "interim",
            "added": "2026-07-26",
        }
    )
    md = render_markdown(state)
    assert "review-pass-1.md" in md and "engagement-brief.md" in md


# ------------------------------------------------------------------ CLI round-trip


def _run(tmp_path, *argv) -> int:
    return main(["--dir", str(tmp_path), *argv])


def test_init_creates_state_and_rendered_view(tmp_path):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert state_path(tmp_path).is_file()
    assert (tmp_path / "START-HERE.md").is_file()  # human view exists from the first moment
    state = load_state(tmp_path)
    assert state["status"] == "in_progress"
    assert validate_state(state) == []


def test_init_refuses_to_overwrite(tmp_path):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert _run(tmp_path, "init", "--title", "T2", "--slug", "t2") == 2


def test_every_mutator_rerenders_the_view(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    index = tmp_path / "START-HERE.md"

    _run(tmp_path, "add-artifact", "review-pass-1.md", "--title", "First review")
    assert "review-pass-1.md" in index.read_text(encoding="utf-8")

    _run(tmp_path, "set-status", "blocked", "--verdict", "waiting on input")
    text = index.read_text(encoding="utf-8")
    assert "⛔" in text and "waiting on input" in text

    _run(tmp_path, "add-outstanding", "jurisdiction unanswered - waiting on user")
    assert "jurisdiction unanswered" in index.read_text(encoding="utf-8")

    _run(tmp_path, "resolve-outstanding", "jurisdiction")
    assert "jurisdiction" not in index.read_text(encoding="utf-8")

    _run(tmp_path, "set-decision", "review_depth", "deep")
    assert "review_depth" in index.read_text(encoding="utf-8")

    # After every mutation the embedded hash matches the state - never stale.
    assert embedded_hash(index.read_text(encoding="utf-8")) == state_hash(load_state(tmp_path))


def test_set_status_closed_sets_date_clears_outstanding(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    _run(tmp_path, "set-team", "Amara (BA)", "Linh (QA)")
    # The close now runs the full DoD checker (R6 gate) - give it the closing email.
    (tmp_path / "engagement-summary-t.txt").write_text("Done. - Morgan\n", encoding="utf-8")
    _run(tmp_path, "add-artifact", "engagement-summary-t.txt", "--title", "Email", "--final")
    assert _run(tmp_path, "set-status", "closed", "--verdict", "ready") == 0
    state = load_state(tmp_path)
    assert state["engagement"]["closed"] and state["outstanding"] == []
    assert "✅" in (tmp_path / "START-HERE.md").read_text(encoding="utf-8")
    assert "Amara (BA)" in (tmp_path / "START-HERE.md").read_text(encoding="utf-8")


def test_close_requires_team_and_finalised_artifacts(tmp_path):
    """2026-07-26 live-run finding: the pack closed with team [] and every artifact interim
    because nothing enforced the close. Now the close refuses until both are done."""
    import pytest

    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    (tmp_path / "review-pass-1.md").write_text("# review\n", encoding="utf-8")
    (tmp_path / "review-pass-1.html").write_text("<p>x</p>", encoding="utf-8")
    _run(tmp_path, "add-artifact", "review-pass-1.md", "--title", "First review")
    with pytest.raises(SystemExit):
        _run(tmp_path, "set-status", "closed")  # no team yet
    _run(tmp_path, "set-team", "Mateo (rules)")
    with pytest.raises(SystemExit):
        _run(tmp_path, "set-status", "closed")  # artifact still interim
    _run(tmp_path, "finalise-artifacts")
    (tmp_path / "engagement-summary-t.txt").write_text("Done. - Morgan\n", encoding="utf-8")
    _run(tmp_path, "add-artifact", "engagement-summary-t.txt", "--title", "Email", "--final")
    assert _run(tmp_path, "set-status", "closed", "--verdict", "ready") == 0
    state = load_state(tmp_path)
    assert all(a["status"] == "final" for a in state["artifacts"])


def test_resolve_outstanding_unmatched_is_an_error(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    assert _run(tmp_path, "resolve-outstanding", "no-such-item") == 2


def test_add_artifact_updates_in_place(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    _run(tmp_path, "add-artifact", "fsd.md", "--title", "Draft spec")
    _run(tmp_path, "add-artifact", "fsd.md", "--title", "Functional spec", "--final")
    arts = [a for a in load_state(tmp_path)["artifacts"] if a["path"] == "fsd.md"]
    assert len(arts) == 1
    assert arts[0]["title"] == "Functional spec" and arts[0]["status"] == "final"


def test_validate_cli_flags_hand_edited_consent_key(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    state = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))
    state["execution_consent"] = False
    state_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    assert _run(tmp_path, "validate") == 1


# ------------------------------------------------------------ schema v2 (log/ratifications)


def test_v1_state_upgrades_in_place_on_first_mutation(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    state = load_state(tmp_path)
    state["schema"] = 1
    state.pop("log", None)
    state.pop("ratifications", None)
    state_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    assert (
        validate_state(json.loads(state_path(tmp_path).read_text(encoding="utf-8"))) == []
    )  # v1 valid
    _run(tmp_path, "log-note", "fix cycle 3 complete")
    upgraded = load_state(tmp_path)
    assert upgraded["schema"] == 2
    assert any("fix cycle 3 complete" in e for e in upgraded["log"])


def test_log_note_is_dated_and_not_in_outstanding(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    _run(tmp_path, "log-note", "QA cycle 2 verified the fixes")
    state = load_state(tmp_path)
    assert any(
        e.endswith("QA cycle 2 verified the fixes") and e[:4].isdigit() for e in state["log"]
    )
    assert not any("QA cycle 2" in o for o in state["outstanding"])
    assert "Engagement log" in (tmp_path / "START-HERE.md").read_text(encoding="utf-8")


def test_blocked_requires_outstanding(tmp_path):
    import pytest

    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    _run(tmp_path, "resolve-outstanding", "independent QA")
    _run(tmp_path, "resolve-outstanding", "DoD")
    with pytest.raises(SystemExit):
        _run(tmp_path, "set-status", "blocked")  # nothing recorded to wait on


def test_ratification_lifecycle(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    _run(tmp_path, "add-ratification", "WINDOW_SECONDS change-control approver")
    state = load_state(tmp_path)
    assert state["ratifications"][0]["status"] == "pending"
    index = (tmp_path / "START-HERE.md").read_text(encoding="utf-8")
    assert "PENDING" in index and "WINDOW_SECONDS" in index
    assert _run(tmp_path, "ratify", "window_seconds", "--by", "ops lead") == 0
    state = load_state(tmp_path)
    assert state["ratifications"][0]["status"] == "ratified"
    assert state["ratifications"][0]["by"] == "ops lead"
    assert _run(tmp_path, "ratify", "window_seconds") == 2  # nothing pending any more


# ------------------------------------------------------------------ profiles (0.30)


def test_profile_defaults_standard_and_validates(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    state = load_state(tmp_path)
    assert state["profile"] == "standard"
    state["profile"] = "heavy"
    assert any("profile" in p for p in validate_state(state))


def test_light_profile_init_and_upgrade(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t", "--profile", "light")
    assert load_state(tmp_path)["profile"] == "light"
    assert "| **Profile** | light |" in (tmp_path / "START-HERE.md").read_text(encoding="utf-8")
    assert _run(tmp_path, "set-profile", "standard") == 0
    assert load_state(tmp_path)["profile"] == "standard"


# ------------------------------------------------------- workspaces + registry (0.31)


def _run_env(monkeypatch, root, *argv) -> int:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return main(list(argv))


def test_init_default_creates_workspace_and_registry(tmp_path, monkeypatch):
    assert _run_env(monkeypatch, tmp_path, "init", "--title", "Audit", "--slug", "audit") == 0
    ws = tmp_path / "artifacts" / "audit"
    assert (ws / "engagement-state.json").is_file()
    assert (ws / "START-HERE.md").is_file()
    reg = tmp_path / "artifacts" / "engagements.json"
    assert reg.is_file()
    rows = json.loads(reg.read_text(encoding="utf-8"))["engagements"]
    assert rows[0]["slug"] == "audit" and rows[0]["status"] == "in_progress"
    assert "audit/START-HERE.md" in (tmp_path / "artifacts" / "ENGAGEMENTS.md").read_text(
        encoding="utf-8"
    )


def test_single_workspace_auto_resolves_without_slug(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "Audit", "--slug", "audit")
    assert _run_env(monkeypatch, tmp_path, "set-status", "blocked") == 0
    assert load_state(tmp_path / "artifacts" / "audit")["status"] == "blocked"


def test_multiple_workspaces_require_slug_without_active_marker(tmp_path, monkeypatch):
    """R1 update (2026-07-29): ambiguity is resolved by the on-disk ACTIVE marker when one
    exists; with the marker cleared it stays the hard error it always was."""
    import pytest

    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    _run_env(monkeypatch, tmp_path, "init", "--title", "B", "--slug", "scoping")
    _run_env(monkeypatch, tmp_path, "clear-active")
    with pytest.raises(SystemExit):
        _run_env(monkeypatch, tmp_path, "set-status", "blocked")  # ambiguous, no marker
    assert _run_env(monkeypatch, tmp_path, "--slug", "audit", "set-status", "blocked") == 0
    assert load_state(tmp_path / "artifacts" / "audit")["status"] == "blocked"
    assert load_state(tmp_path / "artifacts" / "scoping")["status"] == "in_progress"


def test_registry_tracks_independent_states(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    _run_env(monkeypatch, tmp_path, "init", "--title", "B", "--slug", "scoping")
    _run_env(monkeypatch, tmp_path, "--slug", "audit", "set-status", "blocked")
    rows = {
        r["slug"]: r["status"]
        for r in json.loads(
            (tmp_path / "artifacts" / "engagements.json").read_text(encoding="utf-8")
        )["engagements"]
    }
    assert rows == {"audit": "blocked", "scoping": "in_progress"}


def test_migrate_moves_flat_pack_into_workspace(tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "Legacy", "--slug", "legacy-job")  # flat via --dir
    (art / "report.md").write_text("x", encoding="utf-8")
    assert _run_env(monkeypatch, tmp_path, "migrate") == 0
    ws = art / "legacy-job"
    assert (ws / "engagement-state.json").is_file()
    assert (ws / "report.md").is_file()
    assert not (art / "engagement-state.json").exists()
    rows = json.loads((art / "engagements.json").read_text(encoding="utf-8"))["engagements"]
    assert rows[0]["slug"] == "legacy-job"


def test_old_flat_engagement_then_new_workspace_and_migrate(tmp_path, monkeypatch):
    """User scenario: an old (closed, pre-workspaces) flat engagement exists; a new session
    starts a new engagement beside it, then tidies via migrate. Nothing of the old pack is
    lost and both end up as registered workspaces."""
    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "Old review", "--slug", "old-review")  # flat (pre-0.31)
    _run(art, "set-team", "Ravi (review)")
    # A pre-workspaces legacy close: hand-mint the closed state (the R6 close gate would
    # demand the full pack; this test is about migration, not the close).
    state = load_state(art)
    state["status"] = "closed"
    state["engagement"]["closed"] = "2026-07-01"
    state["outstanding"] = []
    state["verdict"] = "done"
    state_path(art).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    _run(art, "render")
    old_state = state_path(art).read_text(encoding="utf-8")

    assert _run_env(monkeypatch, tmp_path, "init", "--title", "New job", "--slug", "new-job") == 0
    rows = {
        r["slug"]: r["status"]
        for r in json.loads((art / "engagements.json").read_text(encoding="utf-8"))["engagements"]
    }
    assert rows == {"old-review": "closed", "new-job": "in_progress"}

    assert _run_env(monkeypatch, tmp_path, "migrate") == 0
    assert (art / "old-review" / "engagement-state.json").read_text(encoding="utf-8") == old_state
    assert not (art / "engagement-state.json").exists()
    rows = {
        r["slug"]: r["status"]
        for r in json.loads((art / "engagements.json").read_text(encoding="utf-8"))["engagements"]
    }
    assert rows == {"old-review": "closed", "new-job": "in_progress"}


def test_no_limit_on_engagement_count(tmp_path, monkeypatch):
    """User ruling: no cap on engagements per project. Five at mixed states, all
    registered, all individually addressable."""
    statuses = {}
    for i in range(5):
        slug = f"eng-{i}"
        _run_env(monkeypatch, tmp_path, "init", "--title", f"E{i}", "--slug", slug)
        if i % 2:
            _run_env(monkeypatch, tmp_path, "--slug", slug, "set-status", "blocked")
            statuses[slug] = "blocked"
        else:
            statuses[slug] = "in_progress"
    rows = {
        r["slug"]: r["status"]
        for r in json.loads(
            (tmp_path / "artifacts" / "engagements.json").read_text(encoding="utf-8")
        )["engagements"]
    }
    assert rows == statuses
    assert _run_env(monkeypatch, tmp_path, "--slug", "eng-3", "set-status", "in_progress") == 0
