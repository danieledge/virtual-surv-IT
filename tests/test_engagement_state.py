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
    import scripts.engagement_state as es_module

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
