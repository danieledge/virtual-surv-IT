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

import pytest

from scripts.engagement_state import (
    ACTIVE_MARKER,
    compute_fingerprint,
    embedded_hash,
    load_state,
    main,
    read_active,
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


def test_dir_flag_also_works_after_the_subcommand_name(tmp_path):
    """Regression (2026-08-10, live Windows session where a Claude Code agent's shell cwd
    kept resetting away from the project root): --dir only worked typed BEFORE the
    subcommand for init/list/migrate/clear-active - their subparsers were missing
    parents=[common], unlike every other subcommand, so e.g. `list --menu --dir X` failed
    with argparse's "unrecognized arguments" even though `--dir X list --menu` worked fine.
    _run()/_run_env() elsewhere in this file always use the working (before) ordering, so
    this gap went uncaught until it hit a real machine."""
    assert main(["init", "--title", "T", "--slug", "t", "--dir", str(tmp_path)]) == 0
    assert state_path(tmp_path).is_file()
    assert main(["list", "--menu", "--dir", str(tmp_path)]) == 0
    assert main(["clear-active", "--dir", str(tmp_path)]) == 0


def test_migrate_dir_flag_also_works_after_the_subcommand_name(tmp_path):
    """Same regression as above, isolated to migrate: needs its own tmp_path so the flat
    pack it inits isn't nested inside another test's pack (init refuses that on purpose)."""
    assert main(["init", "--title", "F", "--slug", "flat-job", "--dir", str(tmp_path)]) == 0
    assert main(["migrate", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "flat-job" / "engagement-state.json").is_file()


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
    (tmp_path / "engagement-summary-t.txt").write_text(
        "Done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
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
    (tmp_path / "engagement-summary-t.txt").write_text(
        "Done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
    _run(tmp_path, "add-artifact", "engagement-summary-t.txt", "--title", "Email", "--final")
    assert _run(tmp_path, "set-status", "closed", "--verdict", "ready") == 0
    state = load_state(tmp_path)
    assert all(a["status"] == "final" for a in state["artifacts"])


# -------------------------------------------------------- close-gate strand (2026-08 audit, C4)


def test_close_refuses_upfront_when_pre_close_state_is_already_invalid(tmp_path):
    """C4a: the close path writes the CLOSED state to disk first, then rolls back to the
    pre-close snapshot if the gate refuses. If that snapshot is itself invalid, the
    rollback write would raise before the CLOSE-REFUSED explanation ever printed,
    stranding the pack CLOSED on disk despite no gate having passed it. The fix checks
    the snapshot up front, before any write, so an already-broken state file refuses the
    close cleanly with nothing written."""
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    state = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))
    state["engagement"]["title"] = ""  # now fails validate_state
    state_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")

    assert _run(tmp_path, "set-status", "closed", "--verdict", "ready") == 1

    on_disk = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))
    assert on_disk["status"] != "closed"  # never got the chance to strand as closed
    assert on_disk["engagement"]["title"] == ""  # untouched - no write happened at all


def test_close_rolls_back_when_the_gate_checker_itself_crashes(tmp_path, monkeypatch):
    """C4b: a checker crash used to fail OPEN (close kept, 'run the checker by hand') -
    a crash proves nothing about whether the pack meets the DoD. Now it fails closed,
    same as a real findings list: rolled back, close refused."""
    import scripts.engagement_state as es_module

    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    _run(tmp_path, "set-team", "Amara (BA)")
    (tmp_path / "engagement-summary-t.txt").write_text(
        "Done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
    _run(tmp_path, "add-artifact", "engagement-summary-t.txt", "--title", "Email", "--final")
    before_status = load_state(tmp_path)["status"]

    class _CrashingChecker:
        @staticmethod
        def check(_dir):
            raise RuntimeError("boom")

    monkeypatch.setattr(es_module, "_load_checker", lambda: _CrashingChecker)

    assert _run(tmp_path, "set-status", "closed", "--verdict", "ready") == 1

    state = load_state(tmp_path)
    assert state["status"] == before_status  # rolled back, not left closed
    assert not state["engagement"]["closed"]


def test_compute_fingerprint_changes_when_state_file_is_tampered(tmp_path):
    """M3 (2026-08 Fable audit): compute_fingerprint used to EXCLUDE engagement-state.json
    entirely from the closed-pack fingerprint (stat-only walk AND content) - a hand-edit
    to the state file after close (verdict flipped, status tampered) left every
    stat-only deliverable untouched, so the fingerprint still matched and a later scan
    silently skipped re-validating the very record that had changed."""
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    fp_before = compute_fingerprint(tmp_path)
    state = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))
    state["verdict"] = "tampered-by-hand"
    state_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    fp_after = compute_fingerprint(tmp_path)
    assert fp_before != fp_after, "fingerprint must move when the state file's own content changes"


def test_compute_fingerprint_is_stable_once_stored_in_the_state_it_was_computed_from(tmp_path):
    """The state-content hash must pop its OWN key before hashing, or storing the
    fingerprint back into the file it was computed from would invalidate itself on
    every subsequent comparison (self-reference), permanently defeating the fast-path
    skip the fingerprint exists to provide."""
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    fp = compute_fingerprint(tmp_path)
    state = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))
    state["scan_fingerprint"] = fp
    state_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    assert compute_fingerprint(tmp_path) == fp


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


# ------------------------------------------------------------- concurrent mutation (2026-08 audit, C5)


def test_concurrent_mutations_do_not_lose_updates(tmp_path):
    """C5: parallel Workflow-tool dispatch can run several mutating commands against the
    SAME pack concurrently. Without a lock around the read-modify-write cycle, this is a
    classic lost-update race - confirmed live (2026-08 audit repro): 12 concurrent
    add-outstanding calls with the lock disabled lost 7 of 12 items, plus two calls hit a
    transient 'no engagement-state.json - run init first' from reading mid-replace. Uses
    real threads against the on-disk pack so it exercises the actual OS-level file lock,
    not a mocked stand-in."""
    import threading

    _run(tmp_path, "init", "--title", "T", "--slug", "t")

    errors = []

    def _add(i):
        rc = _run(tmp_path, "add-outstanding", f"item-{i}")
        if rc != 0:
            errors.append((i, rc))

    threads = [threading.Thread(target=_add, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    outstanding = load_state(tmp_path)["outstanding"]
    for i in range(12):
        assert f"item-{i}" in outstanding


def test_stale_lock_is_reclaimed_not_left_jamming_the_pack(tmp_path):
    """A process that dies mid-mutation leaves the lock file behind forever otherwise.
    Staleness is age-based (not a live PID check - Windows has no clean signal-0
    equivalent) so a later command reclaims it instead of jamming against a lock nobody
    will ever release."""
    import os
    import time

    from scripts.engagement_state import _LOCK_STALE_SECONDS

    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    lock_path = tmp_path / ".engagement-state.lock"
    lock_path.write_text("", encoding="utf-8")
    old = time.time() - _LOCK_STALE_SECONDS - 5
    os.utime(lock_path, (old, old))

    assert _run(tmp_path, "add-outstanding", "still works") == 0
    assert "still works" in load_state(tmp_path)["outstanding"]


# --------------------------------------------------- artifacts-root resolution (2026-08-14 audit, C2)


def test_default_artifacts_dir_trusts_claude_project_dir_even_named_artifacts(
    tmp_path, monkeypatch
):
    """The actual fix: a project whose OWN path happens to contain a directory
    literally named "artifacts" somewhere ABOVE it (unrelated to any engagement
    pack - just directory naming) must not have its artifacts root resolve to that
    unrelated ancestor. CLAUDE_PROJECT_DIR being explicitly set is authoritative and
    must be trusted directly, never walked past."""
    from scripts.engagement_state import _default_artifacts_dir

    project = tmp_path / "artifacts" / "myproject"
    project.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    result = _default_artifacts_dir()
    assert result == project / "artifacts"
    assert result != tmp_path / "artifacts"  # the unrelated ancestor - must never be chosen


def test_default_artifacts_dir_cwd_fallback_finds_nearest_enclosing_workspace(
    tmp_path, monkeypatch
):
    """The ORIGINAL 2026-07-30 fix, still correct: with no CLAUDE_PROJECT_DIR, a
    session that has genuinely cd'd inside an existing artifacts/<slug>/ workspace
    must resolve to that same artifacts/ dir, not nest a new one underneath it."""
    from scripts.engagement_state import _default_artifacts_dir

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    pack = tmp_path / "artifacts" / "old-slug"
    pack.mkdir(parents=True)
    monkeypatch.chdir(pack)
    assert _default_artifacts_dir() == tmp_path / "artifacts"


def test_default_artifacts_dir_cwd_fallback_picks_nearest_not_outermost(tmp_path, monkeypatch):
    """If the cwd fallback path has TWO ancestors named "artifacts" (an unrelated
    outer one plus the real enclosing workspace), the nearest one - the workspace
    actually being cd'd into - must win, not the outermost."""
    from scripts.engagement_state import _default_artifacts_dir

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    outer_artifacts = tmp_path / "artifacts"
    real_project = outer_artifacts / "myproject"
    pack = real_project / "artifacts" / "old-slug"
    pack.mkdir(parents=True)
    monkeypatch.chdir(pack)
    assert _default_artifacts_dir() == real_project / "artifacts"
    assert _default_artifacts_dir() != outer_artifacts


def test_project_root_for_picks_nearest_artifacts_ancestor(tmp_path):
    """Mirrors _default_artifacts_dir's own fix in reverse - given a pack dir, the
    project root is the parent of the NEAREST artifacts/ ancestor, not the
    outermost, for the identical reason."""
    from scripts.engagement_state import _project_root_for

    outer_artifacts = tmp_path / "artifacts"
    real_project = outer_artifacts / "myproject"
    pack = real_project / "artifacts" / "my-slug"
    pack.mkdir(parents=True)
    assert _project_root_for(pack) == real_project


# --------------------------------------------------- settings snapshot (2026-08-08, dashboard v2)


def test_init_captures_settings_snapshot_from_team_preferences(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "team-preferences.json").write_text(
        json.dumps({"regulatory_citations": False, "large_context_review_split": True}),
        encoding="utf-8",
    )
    _run_env(monkeypatch, tmp_path, "init", "--title", "Audit", "--slug", "audit")
    state = load_state(tmp_path / "artifacts" / "audit")
    assert state["settings_snapshot"] == {
        "extra_formats": [],
        "regulatory_citations": False,
        "large_context_review_split": True,
        "parallel_dispatch_via_workflow": True,
        "standards_critique": False,
        "map_skeleton": False,
        "probe_cache": True,
    }
    assert validate_state(state) == []


def test_init_settings_snapshot_builtin_defaults_when_no_preferences_file(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "Audit", "--slug", "audit")
    state = load_state(tmp_path / "artifacts" / "audit")
    assert state["settings_snapshot"] == {
        "extra_formats": [],
        "regulatory_citations": True,
        "large_context_review_split": False,
        "parallel_dispatch_via_workflow": True,
        "standards_critique": False,
        "map_skeleton": False,
        "probe_cache": True,
    }


def test_settings_snapshot_is_a_point_in_time_record_not_relive_resolved(tmp_path, monkeypatch):
    """Changing team-preferences.json AFTER init must not retroactively change an already-
    recorded snapshot - it is a record of what was true when the engagement opened."""
    _run_env(monkeypatch, tmp_path, "init", "--title", "Audit", "--slug", "audit")
    before = load_state(tmp_path / "artifacts" / "audit")["settings_snapshot"]
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "team-preferences.json").write_text(
        json.dumps({"regulatory_citations": False}), encoding="utf-8"
    )
    _run_env(monkeypatch, tmp_path, "log-note", "unrelated mutation")
    after = load_state(tmp_path / "artifacts" / "audit")["settings_snapshot"]
    assert before == after
    assert after["regulatory_citations"] is True  # unchanged despite the later preference edit


def test_validate_state_rejects_non_dict_settings_snapshot():
    bad = copy.deepcopy(_STATE)
    bad["settings_snapshot"] = "not a dict"
    assert any("settings_snapshot" in p for p in validate_state(bad))


# --------------------------------------------------- log-note --tag (2026-08-08, dashboard v2)


def test_log_note_without_tag_is_unchanged(tmp_path):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert _run(tmp_path, "log-note", "plain note") == 0
    log = load_state(tmp_path)["log"]
    assert len(log) == 1
    assert log[0].endswith(": plain note")
    assert "[" not in log[0]


def test_log_note_tag_round_trip(tmp_path):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert (
        _run(
            tmp_path,
            "log-note",
            "Ravi -> Mateo: 3 findings, resubmit",
            "--tag",
            "review-loop",
        )
        == 0
    )
    log = load_state(tmp_path)["log"]
    assert len(log) == 1
    assert "[review-loop]: Ravi -> Mateo: 3 findings, resubmit" in log[0]
    assert validate_state(load_state(tmp_path)) == []


# --------------------------------------------------- set-decisions (batch, corp perf report 2026-08-10)


def test_set_decisions_records_all_pairs_in_one_call(tmp_path):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert (
        _run(
            tmp_path,
            "set-decisions",
            "--json",
            json.dumps({"data-attestation": "yes - masked", "fix-cycle": "report"}),
        )
        == 0
    )
    decisions = load_state(tmp_path)["decisions"]
    assert decisions == {"data-attestation": "yes - masked", "fix-cycle": "report"}
    assert validate_state(load_state(tmp_path)) == []


def test_set_decisions_matches_equivalent_set_decision_calls(tmp_path):
    """The batch and single forms must produce byte-identical state - this is a process-
    count optimization, not a behavior change."""
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert _run(tmp_path, "set-decision", "a", "1") == 0
    assert _run(tmp_path, "set-decision", "b", "2") == 0
    sequential = load_state(tmp_path)["decisions"]

    other = tmp_path.parent / (tmp_path.name + "-batch")
    assert _run(other, "init", "--title", "T", "--slug", "t") == 0
    assert _run(other, "set-decisions", "--json", json.dumps({"a": "1", "b": "2"})) == 0
    batched = load_state(other)["decisions"]

    assert sequential == batched == {"a": "1", "b": "2"}


def test_set_decisions_merges_with_existing_decisions(tmp_path):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert _run(tmp_path, "set-decision", "existing", "kept") == 0
    assert _run(tmp_path, "set-decisions", "--json", json.dumps({"new": "added"})) == 0
    assert load_state(tmp_path)["decisions"] == {"existing": "kept", "new": "added"}


def test_set_decisions_rejects_invalid_json(tmp_path):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert _run(tmp_path, "set-decisions", "--json", "not json") == 2
    assert load_state(tmp_path).get("decisions", {}) == {}


@pytest.mark.parametrize("bad_json", ["[]", "5", '"a string"', "{}"])
def test_set_decisions_rejects_non_object_or_empty_json(tmp_path, bad_json):
    assert _run(tmp_path, "init", "--title", "T", "--slug", "t") == 0
    assert _run(tmp_path, "set-decisions", "--json", bad_json) == 2
    assert load_state(tmp_path).get("decisions", {}) == {}


# --------------------------------------- slug path-traversal (found 2026-08-07, fixed) -------
#
# Every command that builds a workspace path from a --slug used to do `root / slug` with no
# validation. Two real escapes, verified by hand before fixing: (1) Path.__truediv__ DISCARDS
# the left side when the right is absolute, so a slug of an absolute path targets that path
# directly, not a subdirectory of it; (2) a `..`-bearing slug resolves outside the artifacts
# root on .resolve(), ordinary directory traversal. Both must be refused, not just the
# character that happens to be in one example.


def test_init_absolute_path_slug_is_refused(tmp_path, monkeypatch):
    outside = tmp_path / "outside-target"
    rc = _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", str(outside))
    assert rc == 2
    assert not outside.exists()  # never created at the escaped location


def test_init_dotdot_slug_is_refused(tmp_path, monkeypatch):
    rc = _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", "../../escaped")
    assert rc == 2
    assert not (tmp_path.parent.parent / "escaped").exists()


def test_init_legitimate_slug_with_dots_still_works(tmp_path, monkeypatch):
    """The fix checks CONTAINMENT after resolving, not a character blocklist - a slug that
    merely contains a single dot (not a traversal sequence) must still work fine."""
    rc = _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", "release-0.33")
    assert rc == 0
    assert (tmp_path / "artifacts" / "release-0.33" / "engagement-state.json").is_file()


def test_set_active_absolute_path_slug_is_refused(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", "real")
    outside = tmp_path / "outside-target"
    rc = _run_env(monkeypatch, tmp_path, "set-active", "--slug", str(outside))
    assert rc == 2
    assert not outside.exists()


def test_archive_dotdot_slug_is_refused(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", "real")
    rc = _run_env(monkeypatch, tmp_path, "archive", "--slug", "../../escaped")
    assert rc == 2
    assert not (tmp_path.parent.parent / "escaped").exists()


def test_unarchive_dotdot_slug_is_refused(tmp_path, monkeypatch):
    rc = _run_env(monkeypatch, tmp_path, "unarchive", "--slug", "../../escaped")
    assert rc == 2


def test_resolve_pack_dir_target_slug_dotdot_is_refused(tmp_path, monkeypatch):
    """Exercises resolve_pack_dir()'s own --slug branch (shared by most non-init/list
    commands) via `set-status`, which routes through it when --dir is omitted.
    resolve_pack_dir() already raises SystemExit(2) directly for its pre-existing
    ambiguity error (line ~465) rather than returning an error code - this fix follows
    that same established convention rather than inventing a new one."""
    import pytest

    _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", "real")
    with pytest.raises(SystemExit) as exc:
        _run_env(monkeypatch, tmp_path, "set-status", "blocked", "--slug", "../../escaped")
    assert exc.value.code == 2


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


def test_standalone_flat_pack_writes_no_registry_anywhere(tmp_path, monkeypatch):
    """2026-08-14 Fable-model audit finding (C3): a genuinely standalone flat pack (no
    sibling workspaces at all) used to have _registry_root_for misidentify the pack
    itself as a "sibling workspace" of the PROJECT ROOT (tmp_path here), writing
    engagements.json/ENGAGEMENTS.md/.html into the user's own git-tracked project
    directory. Fixed: no registry needed for a standalone flat pack at all - none
    should appear at the project root OR the artifacts dir."""
    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "Solo", "--slug", "solo-job")  # flat via --dir
    assert not (tmp_path / "engagements.json").is_file(), (
        "registry leaked into the project root - the exact regression this guards"
    )
    assert not (art / "engagements.json").is_file()  # no siblings yet, none needed either


def test_flat_pack_with_genuine_sibling_workspace_gets_a_registry(tmp_path, monkeypatch):
    """The OTHER half of the same fix: a flat pack that DOES have a real sibling
    workspace under the same artifacts root must still get a registry - at the
    artifacts root (the parent both share), not the project root above it. Proves
    the fix didn't just make registry creation never fire for flat packs."""
    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "Flat", "--slug", "flat-job")  # flat via --dir
    _run_env(monkeypatch, tmp_path, "init", "--title", "Workspace", "--slug", "ws-job")
    reg = art / "engagements.json"
    assert reg.is_file()
    assert not (tmp_path / "engagements.json").is_file()
    slugs = {r["slug"] for r in json.loads(reg.read_text(encoding="utf-8"))["engagements"]}
    assert slugs == {"flat-job", "ws-job"}


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


def test_migrate_leaves_root_active_marker_in_place(tmp_path, monkeypatch):
    """M2 (2026-08 Fable audit): a root that has BOTH a flat pack and a genuine sibling
    workspace (the C3-supported case) can carry the root-level ACTIVE_MARKER too - the
    workspaced init below writes it. migrate's keep-set used to list only the registry
    and existing workspace dirs, so the marker (not a dir, not the registry) got swept
    into the newly migrated pack's directory instead of staying at the root it describes -
    read_active(root) silently went back to None after a migrate that had nothing to do
    with the active engagement at all."""
    art = tmp_path / "artifacts"
    _run(art, "init", "--title", "Legacy", "--slug", "legacy-job")  # flat via --dir
    _run_env(monkeypatch, tmp_path, "init", "--title", "WS", "--slug", "ws-job")  # workspaced
    assert read_active(art) == "ws-job"  # workspaced init marks itself ACTIVE
    assert _run_env(monkeypatch, tmp_path, "--dir", str(art), "migrate") == 0
    assert (art / ACTIVE_MARKER).is_file(), "ACTIVE marker must stay at the artifacts root"
    assert not (art / "legacy-job" / ACTIVE_MARKER).exists(), (
        "ACTIVE marker must not be swept into the migrated pack's directory"
    )
    assert read_active(art) == "ws-job"  # unaffected by migrating an unrelated flat pack


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


def test_slug_flag_accepted_before_or_after_subcommand(tmp_path, monkeypatch):
    """Live corp report 2026-07-31: --slug is a top-level argparse flag, so typing it
    AFTER the subcommand used to exit 2 'unrecognized arguments' - only the pre-subcommand
    order worked. Both orders must now resolve to the same pack."""
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "eng-a")
    _run_env(monkeypatch, tmp_path, "init", "--title", "B", "--slug", "eng-b")
    assert _run_env(monkeypatch, tmp_path, "--slug", "eng-a", "log-note", "before") == 0
    assert _run_env(monkeypatch, tmp_path, "log-note", "--slug", "eng-a", "after") == 0
    state = load_state(tmp_path / "artifacts" / "eng-a")
    assert any("before" in entry for entry in state["log"])
    assert any("after" in entry for entry in state["log"])


def test_archive_force_excludes_stateless_directory(tmp_path, monkeypatch):
    """Live corp report 2026-07-31: `archive <name> --force` on a directory with no
    engagement-state.json (a legacy/non-workspace directory the DoD scan still walks)
    exited 2 with no way to exclude it - only a hand-written .archive marker worked."""
    art = tmp_path / "artifacts"
    (art / "legacy").mkdir(parents=True)
    (art / "legacy" / "notes.md").write_text("old", encoding="utf-8")
    assert _run_env(monkeypatch, tmp_path, "archive", "legacy") == 2
    assert not (art / "legacy" / ".archive").is_file()
    assert _run_env(monkeypatch, tmp_path, "archive", "legacy", "--force") == 0
    assert (art / "legacy" / ".archive").is_file()
    assert _run_env(monkeypatch, tmp_path, "archive", "nosuch", "--force") == 2


def test_show_prints_state_and_always_exits_0(tmp_path, monkeypatch, capsys):
    """Unlike validate (exits 1 on findings), show is for inspection only - it must
    always exit 0 once the state file was found, and a missing pack is a clean 2, not a
    traceback."""
    _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", "t")
    capsys.readouterr()
    assert _run_env(monkeypatch, tmp_path, "--slug", "t", "show") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown == load_state(tmp_path / "artifacts" / "t")
    assert _run_env(monkeypatch, tmp_path, "--slug", "nosuch", "show") == 2


def test_render_exits_nonzero_when_html_sibling_skipped(tmp_path, monkeypatch):
    """Live corp report 2026-07-31: render exited 0 even when the .html sibling was
    skipped, falsely signalling success - it must reflect a partial render in its exit
    code so a caller doesn't have to parse stderr to notice."""
    import scripts.engagement_state as es_module

    _run_env(monkeypatch, tmp_path, "init", "--title", "T", "--slug", "t")
    assert _run_env(monkeypatch, tmp_path, "--slug", "t", "render") == 0
    monkeypatch.setattr(es_module, "_load_render_html_module", lambda: None)
    assert _run_env(monkeypatch, tmp_path, "--slug", "t", "render") == 2
    assert (tmp_path / "artifacts" / "t" / "START-HERE.md").is_file()


# ------------------------------------------------ module-loader memoization (2026-08-03 perf audit)
#
# _load_render_html_module / _load_checker are each called from more than one place within
# ONE _write_state() / close flow (render_files() and render_registry() both load
# render_html; the close path loads check_artifacts). The fast `from scripts import X`
# branch is already cached by Python's own import machinery; the __file__-relative
# FALLBACK (taken in plugin mode) used to re-parse and re-exec the whole file on every
# call. These force the fallback via __import__ interception (poisoning sys.modules alone
# is unreliable once a genuine prior import has cached the submodule as an attribute of
# the `scripts` package) and prove the same module object comes back, exec_module invoked
# only once.


def _block_scripts_import(monkeypatch, blocked_name: str) -> None:
    import builtins

    real_import = builtins.__import__

    def _guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scripts" and fromlist and blocked_name in fromlist:
            raise ImportError(f"blocked for test: scripts.{blocked_name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded)


def _counting_spec_from_file_location(monkeypatch):
    import importlib.util

    exec_calls = []
    orig = importlib.util.spec_from_file_location

    def _counting(*a, **k):
        spec = orig(*a, **k)
        orig_exec = spec.loader.exec_module

        def _counted_exec(module):
            exec_calls.append(1)
            return orig_exec(module)

        spec.loader.exec_module = _counted_exec
        return spec

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _counting)
    return exec_calls


def test_render_html_loader_is_memoized_across_calls(monkeypatch):
    import scripts.engagement_state as es_module

    _block_scripts_import(monkeypatch, "render_html")
    monkeypatch.setattr(es_module, "_RENDER_HTML_MODULE_CACHE", None)
    exec_calls = _counting_spec_from_file_location(monkeypatch)

    first = es_module._load_render_html_module()
    second = es_module._load_render_html_module()

    assert first is not None
    assert first is second
    assert len(exec_calls) == 1


def test_check_artifacts_loader_is_memoized_across_calls(monkeypatch):
    import scripts.engagement_state as es_module

    _block_scripts_import(monkeypatch, "check_artifacts")
    monkeypatch.setattr(es_module, "_CHECK_ARTIFACTS_MODULE_CACHE", None)
    exec_calls = _counting_spec_from_file_location(monkeypatch)

    first = es_module._load_checker()
    second = es_module._load_checker()

    assert first is not None
    assert first is second
    assert len(exec_calls) == 1


# ------------------------------------------------ registry known-pack reuse (2026-08-03 perf audit)
#
# Every mutation (add-artifact, set-status, log-note, ...) re-renders the WHOLE project
# registry via render_registry() -> scan_engagements(), which re-reads and re-parses
# EVERY open pack's engagement-state.json from disk, including the one _write_state()
# just validated and wrote. scan_engagements()'s `known=(pack, state)` lets _write_state()
# hand back that in-memory state instead of re-reading the file it just wrote - a
# one-row substitution, not a cache: every OTHER row is still read fresh, unconditionally,
# on every single call, so the registry's documented "always regenerated, never drifts"
# guarantee (render_registry()'s own docstring/heading comment) is untouched. The
# archive/unarchive/migrate call sites change which packs even exist, so they deliberately
# do NOT pass `known` and keep the full rescan.


def test_write_state_does_not_reread_the_pack_it_just_wrote(tmp_path, monkeypatch):
    import scripts.engagement_state as es_module

    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = tmp_path / "artifacts"
    pack = art / "audit"

    orig_load_state = es_module.load_state
    read_packs = []

    def _counting_load_state(artifacts_dir):
        read_packs.append(artifacts_dir)
        return orig_load_state(artifacts_dir)

    monkeypatch.setattr(es_module, "load_state", _counting_load_state)

    assert _run_env(monkeypatch, tmp_path, "--slug", "audit", "set-status", "blocked") == 0

    # Read once to build the mutated state (every command's normal read-modify-write);
    # NOT a second time for the registry render that follows the write.
    assert read_packs.count(pack) == 1, "the just-written pack must not be re-read for the registry"


def test_write_state_still_reads_every_other_pack_fresh(tmp_path, monkeypatch):
    """No-drift guarantee: mutating one pack must not stop the registry from reflecting a
    sibling pack that changed between renders (e.g. edited by a different session)."""
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    _run_env(monkeypatch, tmp_path, "init", "--title", "B", "--slug", "scoping")
    art = tmp_path / "artifacts"

    # Simulate a sibling pack changing on disk without going through this process.
    sibling_state = json.loads(state_path(art / "scoping").read_text(encoding="utf-8"))
    sibling_state["status"] = "blocked"
    state_path(art / "scoping").write_text(
        json.dumps(sibling_state, indent=2) + "\n", encoding="utf-8"
    )

    assert _run_env(monkeypatch, tmp_path, "--slug", "audit", "log-note", "note") == 0

    rows = {
        r["slug"]: r["status"]
        for r in json.loads((art / "engagements.json").read_text(encoding="utf-8"))["engagements"]
    }
    assert rows["scoping"] == "blocked"  # the sibling's edit is reflected, not stale
    assert rows["audit"] == "in_progress"


def test_known_pack_substitution_matches_full_rescan_output(tmp_path, monkeypatch):
    """The substituted row must be byte-for-byte the same shape a full rescan would
    produce - scan_engagements(root) vs scan_engagements(root, known=...) agree."""
    import scripts.engagement_state as es_module

    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    _run_env(monkeypatch, tmp_path, "init", "--title", "B", "--slug", "scoping")
    art = tmp_path / "artifacts"
    pack = art / "audit"
    state = load_state(pack)

    full_rescan = es_module.scan_engagements(art)
    substituted = es_module.scan_engagements(art, known=(pack, state))

    assert substituted == full_rescan


def test_scan_engagements_known_ignored_when_pack_does_not_match(tmp_path, monkeypatch):
    """A `known` pack that isn't among the candidates (e.g. a stale/mismatched path) must
    never leak its state onto some other row - it's a no-op, not a silent substitution."""
    import scripts.engagement_state as es_module

    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = tmp_path / "artifacts"

    rows = es_module.scan_engagements(art, known=(tmp_path / "nowhere", {"status": "bogus"}))
    assert rows[0]["status"] == "in_progress"


def test_render_files_reuses_known_state_instead_of_rereading(tmp_path, monkeypatch):
    """render_files() had the identical redundant-read pattern one call up the chain -
    _write_state() re-reads the pack it just wrote to render START-HERE.md/.html. Found
    and fixed alongside the registry substitution (same file, same _write_state() call
    chain, same root cause)."""
    import scripts.engagement_state as es_module

    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = tmp_path / "artifacts"
    pack = art / "audit"

    orig_load_state = es_module.load_state
    read_packs = []

    def _counting_load_state(artifacts_dir):
        read_packs.append(artifacts_dir)
        return orig_load_state(artifacts_dir)

    monkeypatch.setattr(es_module, "load_state", _counting_load_state)

    assert _run_env(monkeypatch, tmp_path, "--slug", "audit", "log-note", "hi") == 0

    # log-note goes through _mutate(), which reads once to build the mutated state; that
    # is the only read that should happen for this pack across the whole call.
    assert read_packs.count(pack) == 1


def test_standalone_render_command_still_reads_from_disk(tmp_path, monkeypatch):
    """The `render` command has no in-memory state to reuse - it must keep reading fresh
    (its whole purpose is regenerating the view FROM disk, e.g. after a hand-edit)."""
    import scripts.engagement_state as es_module

    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = tmp_path / "artifacts"
    pack = art / "audit"

    orig_load_state = es_module.load_state
    read_packs = []

    def _counting_load_state(artifacts_dir):
        read_packs.append(artifacts_dir)
        return orig_load_state(artifacts_dir)

    monkeypatch.setattr(es_module, "load_state", _counting_load_state)

    assert _run_env(monkeypatch, tmp_path, "--slug", "audit", "render") == 0

    assert pack in read_packs


def test_render_registry_with_no_known_reads_every_pack_fresh(tmp_path, monkeypatch):
    """archive/unarchive/migrate change pack MEMBERSHIP itself, so they call
    render_registry() with no `known` - proving render_registry(root) (its default,
    known=None) unconditionally re-reads every candidate, exactly what those three call
    sites rely on for correctness after membership changes."""
    import scripts.engagement_state as es_module

    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = tmp_path / "artifacts"
    pack = art / "audit"

    orig_load_state = es_module.load_state
    read_packs = []

    def _counting_load_state(artifacts_dir):
        read_packs.append(artifacts_dir)
        return orig_load_state(artifacts_dir)

    monkeypatch.setattr(es_module, "load_state", _counting_load_state)

    es_module.render_registry(art)

    assert pack in read_packs


def test_resume_menu_json_slims_open_to_slugs_but_resume_menu_keeps_rows(tmp_path):
    """Token audit Track C (2026-08-18): the model-facing menu carries `open` as slugs
    only (its prompt consumers are emptiness + --resume membership checks; full rows
    duplicated `shown`), while the in-process resume_menu() keeps full rows - the
    launcher's archive-all iterates them (broke live in the first cut, same day)."""
    from scripts.engagement_state import main as es_main
    from scripts.engagement_state import resume_menu, resume_menu_json

    art = tmp_path / "artifacts"
    assert es_main(["--dir", str(art / "pack"), "init", "--title", "Pack", "--slug", "pack"]) == 0

    rows_menu = resume_menu(art)
    assert rows_menu["open"] and isinstance(rows_menu["open"][0], dict)

    json_menu = resume_menu_json(art)
    assert json_menu["open"] == ["pack"]
    assert json_menu["shown"] and isinstance(json_menu["shown"][0], dict)
    assert json_menu["default"] == "pack"
