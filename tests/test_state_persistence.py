"""Phase 2 of the 2026-07-29 workflow-robustness remediation: resume must not lose the
decisions (register R1/R2/R3/R7/R8).

R1 - the ACTIVE slug (ADR-008: one engagement ACTIVE per session) existed only in
conversation; with two open packs a resumed session that guessed wrong silently mutated
the wrong workspace. It now lives in `artifacts/.active-engagement.json`: written by the
workspaced init / `set-active`, honoured by pack resolution, cleared at close.

R3 - an execution-consent "No" left disk identical to never-asked, and the schema forbade
recording it. A single sanctioned field (`execution_consent_outcome`) now records the
NON-GRANTING outcomes only ("asked"/"declined"); anything grant-shaped still fails
validation, and every other consent/exec-shaped key stays forbidden (ADR-002: the grant is
the human-created marker, nothing else).

R7 - the run-mode probe (mode / plugin root / interpreter) was conversation state; after
compaction every scripts invocation was wrong in plugin mode. `set-runtime` persists it.

R8 - `add-artifact` never verified the file exists; after a crash "remove the row or
restore the artifact" was undecidable from disk. Rows added before their file exists are
now flagged.
"""

from __future__ import annotations

import json

from scripts.engagement_state import (
    load_state,
    main,
    read_active,
    state_path,
    validate_state,
)

import scripts.vsit_paths as _vsit


def _run(art, *argv) -> int:
    return main(["--dir", str(art), *argv])


def _run_env(monkeypatch, project, *argv) -> int:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    return main(list(argv))


# --- R1: the ACTIVE marker ----------------------------------------------------------------


def test_workspaced_init_sets_active_marker(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = _vsit.engagements_dir(tmp_path)
    assert read_active(art) == "audit"
    _run_env(monkeypatch, tmp_path, "init", "--title", "B", "--slug", "scoping")
    assert read_active(art) == "scoping"  # the newest engagement becomes ACTIVE


def test_resolution_targets_active_when_ambiguous(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    _run_env(monkeypatch, tmp_path, "init", "--title", "B", "--slug", "scoping")
    _run_env(monkeypatch, tmp_path, "set-active", "audit")
    # No --slug, two open workspaces: pre-R1 this was a hard error; now the marker decides.
    assert _run_env(monkeypatch, tmp_path, "add-outstanding", "waiting on spec") == 0
    audit = load_state(_vsit.engagements_dir(tmp_path) / "audit")
    scoping = load_state(_vsit.engagements_dir(tmp_path) / "scoping")
    assert any("waiting on spec" in i for i in audit["outstanding"])
    assert not any("waiting on spec" in i for i in scoping["outstanding"])


def test_set_active_unknown_slug_is_an_error(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    assert _run_env(monkeypatch, tmp_path, "set-active", "nope") == 2


def test_close_clears_the_active_marker(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = _vsit.engagements_dir(tmp_path)
    ws = art / "audit"
    (ws / "engagement-summary-audit.txt").write_text(
        "Done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
    _run(ws, "add-artifact", "engagement-summary-audit.txt", "--title", "Email", "--final")
    _run(ws, "set-team", "Ana (analysis)")
    assert _run(ws, "set-status", "closed", "--verdict", "done") == 0
    assert read_active(art) is None


def test_refused_close_keeps_the_active_marker(tmp_path, monkeypatch):
    _run_env(monkeypatch, tmp_path, "init", "--title", "A", "--slug", "audit")
    art = _vsit.engagements_dir(tmp_path)
    ws = art / "audit"
    _run(ws, "set-team", "Ana (analysis)")
    assert _run(ws, "set-status", "closed", "--verdict", "done") == 1  # no email -> refused
    assert read_active(art) == "audit"


# --- R3: consent outcome, non-granting only -----------------------------------------------


def test_record_consent_outcome_declined(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    assert _run(tmp_path, "record-consent-outcome", "declined") == 0
    state = load_state(tmp_path)
    rec = state["execution_consent_outcome"]
    assert rec["outcome"] == "declined" and rec["date"]
    assert validate_state(state) == []
    # Visible on the rendered index, so a cold resume sees it without parsing JSON.
    assert "declined" in (tmp_path / "START-HERE.md").read_text(encoding="utf-8")


def test_consent_outcome_grant_shaped_values_fail_validation(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    state = load_state(tmp_path)
    for bad in ("granted", "yes", True, {"outcome": "granted"}):
        state["execution_consent_outcome"] = bad
        problems = " ".join(validate_state(state))
        assert "asked" in problems or "declined" in problems, bad


def test_other_consent_shaped_keys_stay_forbidden(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    state = load_state(tmp_path)
    state["execution_consent"] = "false"
    assert any("forbidden key" in p for p in validate_state(state))
    state = load_state(tmp_path)
    state["decisions"]["exec_consent"] = "yes"
    assert any("forbidden key" in p for p in validate_state(state))


# --- R7: run-mode probe persisted ---------------------------------------------------------


def test_set_runtime_round_trip(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    assert (
        _run(
            tmp_path,
            "set-runtime",
            "--mode",
            "plugin",
            "--plugin-root",
            "/home/x/.claude/plugins/cst",
            "--interpreter",
            "python3",
        )
        == 0
    )
    state = load_state(tmp_path)
    assert state["runtime"] == {
        "mode": "plugin",
        "plugin_root": "/home/x/.claude/plugins/cst",
        "interpreter": "python3",
    }
    assert validate_state(state) == []


def test_runtime_bad_mode_fails_validation(tmp_path):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    state = load_state(tmp_path)
    state["runtime"] = {"mode": "container"}
    assert any("runtime" in p for p in validate_state(state))


# --- R8: artifact rows verified against disk ----------------------------------------------


def test_add_artifact_missing_file_flagged(tmp_path, capsys):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    _run(tmp_path, "add-artifact", "ghost.md", "--title", "Not yet written")
    assert "does not exist" in capsys.readouterr().err
    row = next(a for a in load_state(tmp_path)["artifacts"] if a["path"] == "ghost.md")
    assert row["added_before_file_existed"] is True


def test_add_artifact_existing_file_not_flagged(tmp_path, capsys):
    _run(tmp_path, "init", "--title", "T", "--slug", "t")
    (tmp_path / "brief.md").write_text("# b\n", encoding="utf-8")
    _run(tmp_path, "add-artifact", "brief.md", "--title", "Brief")
    row = next(a for a in load_state(tmp_path)["artifacts"] if a["path"] == "brief.md")
    assert "added_before_file_existed" not in row


# --- Exit criterion: cold resume from disk alone ------------------------------------------


def test_cold_resume_recovers_everything_from_disk(tmp_path, monkeypatch):
    """The phase 2 exit criterion: a fresh session against a mid-flight workspace recovers
    the ACTIVE slug, phase, run mode and the gate answers WITHOUT any conversation state."""
    _run_env(monkeypatch, tmp_path, "init", "--title", "Spoofing review", "--slug", "spoof")
    art = _vsit.engagements_dir(tmp_path)
    ws = art / "spoof"
    _run(ws, "set-phase", "delivery")
    _run(ws, "set-runtime", "--mode", "repo", "--interpreter", "python3")
    _run(ws, "set-decision", "go-ahead", "Proceed as briefed (user, 2026-07-29)")
    _run(ws, "set-decision", "fix-cycle", "report only - no fixes without approval")
    _run(ws, "set-decision", "data-attestation", "no data involved")
    _run(ws, "record-consent-outcome", "declined", "--note", "user said No at intake")

    # ---- cold resume: disk only from here on ----
    slug = read_active(art)
    assert slug == "spoof"
    state = json.loads(state_path(art / slug).read_text(encoding="utf-8"))
    assert state["phase"] == "delivery"
    assert state["runtime"]["mode"] == "repo"
    assert state["decisions"]["go-ahead"].startswith("Proceed as briefed")
    assert state["decisions"]["fix-cycle"].startswith("report only")
    assert state["decisions"]["data-attestation"] == "no data involved"
    assert state["execution_consent_outcome"]["outcome"] == "declined"


# ------------------------------------------------ nested-pack prevention (2026-07-30)


def test_default_artifacts_dir_resolves_outermost_from_inside_workspace(monkeypatch, tmp_path):
    """Live defect: a session cd'd into artifacts/<old>/ ran init and created
    artifacts/<old>/artifacts/<new>/. The default must resolve to the OUTERMOST
    artifacts root, not append another level."""
    from scripts.engagement_state import _default_artifacts_dir

    inside = tmp_path / "proj" / "artifacts" / "old-engagement"
    inside.mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(inside)
    assert _default_artifacts_dir() == (tmp_path / "proj" / "artifacts").resolve()
    # and from the project root the classic default still applies
    monkeypatch.chdir(tmp_path / "proj")
    assert _default_artifacts_dir() == tmp_path / "proj" / "artifacts"


def test_init_from_inside_workspace_lands_at_root(monkeypatch, tmp_path):
    from scripts.engagement_state import main as es_main

    root = tmp_path / "proj" / "artifacts"
    old = root / "old"
    old.mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(old)
    assert es_main(["init", "--title", "New", "--slug", "new-work"]) == 0
    assert (root / "new-work" / "engagement-state.json").is_file()
    assert not (old / "artifacts").exists()


def test_init_refuses_explicit_nested_dir(tmp_path, capsys):
    from scripts.engagement_state import main as es_main

    root = _vsit.engagements_dir(tmp_path)
    assert es_main(["--dir", str(root / "old"), "init", "--title", "Old", "--slug", "old"]) == 0
    nested = root / "old" / "artifacts" / "new"
    rc = es_main(["--dir", str(nested), "init", "--title", "New", "--slug", "new"])
    assert rc == 2
    assert "refusing to init inside another engagement pack" in capsys.readouterr().err
    # nested directly in a pack without a second artifacts level - also refused
    rc = es_main(["--dir", str(root / "old" / "sub"), "init", "--title", "S", "--slug", "s"])
    assert rc == 2


def test_checker_flags_existing_nested_pack(tmp_path):
    from scripts.check_artifacts import check_registry
    from scripts.engagement_state import main as es_main, render_registry

    root = _vsit.engagements_dir(tmp_path)
    assert es_main(["--dir", str(root / "old"), "init", "--title", "Old", "--slug", "old"]) == 0
    # simulate pre-fix damage: a pack nested inside old
    nested = root / "old" / "artifacts" / "new"
    nested.mkdir(parents=True)
    (nested / "engagement-state.json").write_text("{}", encoding="utf-8")
    render_registry(root)
    findings = check_registry(root)
    assert any("NESTED-PACK" in f and str(nested) in f for f in findings)
