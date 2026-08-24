"""Autonomous (unattended) Jira mode - the safety properties, not the pixels.

Auto mode removes the human from the loop DURING a run, so the tests that matter are the
ones asserting what it still cannot do: grant its own execution consent from inside a
session, leave standing authorisation behind, hide the judgement calls it made, or close
looking signed off.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

MARKER_NAME = "." + "exec" + "-" + "consent"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _project(tmp_path: Path, prefs: dict | None = None) -> Path:
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text(
        json.dumps(prefs or {}), encoding="utf-8"
    )
    return tmp_path


# --- per TICKET, not per project (2026-08-21) --------------------------------------------------
#
# Re-scoped on the owner's "auto should be per jira not entire project". The preference
# became a kill switch rather than an enabler, so what these tests must protect changed
# shape: not "is the project switched on?" but "can a run become unattended without a human
# choosing it for THAT ticket?". The answer must stay no.


def test_the_option_is_offered_without_any_project_opt_in(tmp_path):
    """Same reasoning as [j] itself: offering grants nothing. The affordance is present,
    the decision is per ticket."""
    mod = _load("virt_team_launcher")
    assert mod._auto_offered(_project(tmp_path)) is True


def test_a_project_can_remove_the_option_entirely(tmp_path):
    """The kill switch has to actually kill it - a governance decision to forbid unattended
    work in a project must hold."""
    mod = _load("virt_team_launcher")
    assert mod._auto_offered(_project(tmp_path, {"autonomous_mode": False})) is False
    probe = _load("engage_probe")
    resolved = probe.resolve_preferences(_project(tmp_path, {"autonomous_mode": False}))
    assert resolved.get("autonomous_mode") is False


def test_offering_is_not_choosing(tmp_path):
    """THE property. Offered everywhere, but a run only becomes unattended when the ticket
    screen returns the auto flag - the plain ref alone never carries it."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    assert mod._auto_offered(project) is True
    assert "--auto" not in mod._jira_command(project, "SURV-1")
    assert "--auto" in mod._jira_command(project, "SURV-1", auto=True)


def test_a_malformed_preference_still_leaves_the_option_available(tmp_path):
    """Only an explicit false removes it; a typo must not silently disable a feature, the
    way it must not silently enable a dangerous one."""
    probe = _load("engage_probe")
    project = _project(tmp_path, {"autonomous_mode": "yes-please"})
    assert probe.resolve_preferences(project).get("autonomous_mode") is True
    mod = _load("virt_team_launcher")
    assert mod._auto_offered(project) is True


# --- the consent boundary ---------------------------------------------------------------------


def test_the_launcher_grant_is_written_with_provenance_and_an_expiry(tmp_path):
    """ADR-002's rule is that the MODEL cannot manufacture a grant. The launcher is a
    different process, running before any session exists, driven by a keypress - so it may.
    What keeps that honest is provenance and an expiry, both asserted here."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    ok, problem = mod.grant_execution_consent(project, "SURV-1")
    assert ok, problem
    marker = project / ".claude" / MARKER_NAME
    assert marker.is_file(), "the gate the guard looks for was not created"
    body = marker.read_text(encoding="utf-8")
    assert "human" in body.lower() and "SURV-1" in body
    side = json.loads((project / ".claude" / ".auto-grant.json").read_text(encoding="utf-8"))
    assert side["engagement"] == "SURV-1"
    assert "keypress" in side["granted_by"]
    granted = datetime.datetime.fromisoformat(side["granted_at"])
    expires = datetime.datetime.fromisoformat(side["expires_at"])
    assert expires > granted, "a grant with no expiry is a standing grant"


def test_an_expired_grant_is_closed_at_the_next_go(tmp_path):
    """The failure this prevents: one unattended run quietly authorising execution in every
    later session in that project."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    mod.grant_execution_consent(project, "SURV-2")
    side = project / ".claude" / ".auto-grant.json"
    data = json.loads(side.read_text(encoding="utf-8"))
    data["expires_at"] = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat()
    side.write_text(json.dumps(data), encoding="utf-8")
    assert mod._expire_stale_auto_consent(project) is True
    assert not (project / ".claude" / MARKER_NAME).exists()
    assert not side.exists()


def test_a_live_grant_is_left_alone(tmp_path):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    mod.grant_execution_consent(project, "SURV-3")
    assert mod._expire_stale_auto_consent(project) is False
    assert (project / ".claude" / MARKER_NAME).is_file()


def test_a_hand_made_marker_is_never_touched(tmp_path):
    """Only a grant this launcher made (proved by the sidecar) may be expired. A marker the
    human created by hand is theirs."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    marker = project / ".claude" / MARKER_NAME
    marker.write_text("granted by hand\n", encoding="utf-8")
    assert mod._expire_stale_auto_consent(project) is False
    assert marker.is_file()


def test_the_session_side_still_cannot_create_the_marker():
    """The guard is the thing that must not have moved. Auto mode adds a launcher channel;
    it does not add a session one, and nothing in the skill surface may tell a session to
    create the gate itself."""
    guard = (REPO_ROOT / ".claude" / "hooks" / "guard-consent-writes.py").read_text(
        encoding="utf-8"
    )
    assert "exec-consent" in guard, "the guard no longer names the marker it protects"
    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()
    for phrase in ("create the marker", "touch .claude/." + "exec-consent"):
        assert phrase not in lowered, f"the skill tells a session to self-grant: {phrase!r}"


# --- the run itself ---------------------------------------------------------------------------


def test_the_auto_flag_rides_with_jira_and_only_when_asked(tmp_path):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    assert mod._jira_command(project, "SURV-9").endswith("--jira SURV-9")
    assert mod._jira_command(project, "SURV-9", auto=True).endswith("--jira SURV-9 --auto")


def test_the_launcher_hands_the_unattended_flag_to_the_workspace(tmp_path):
    """2026-08-21 audit finding C1 - the one that mattered.

    `auto` was set only by a `mark-auto` subcommand that NOTHING in any skill or document
    ever told a session to run, so it stayed False on every real unattended engagement and
    both AUTO-* gates skipped the pack. The enforcement existed only inside tests that
    hand-built packs with auto=True - the gate was checked, the path to it never was.

    The fix removes the model from the loop: the launcher, which already knows the run is
    unattended, drops a handoff file and `init` consumes it. This test drives that path
    rather than asserting the flag, so it fails if the wiring is ever broken again."""
    import subprocess

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / ".auto-pending.json").write_text(
        json.dumps({"ref": "SURV-9", "slug": "SURV-9"}), encoding="utf-8"
    )
    workspace = tmp_path / "artifacts" / "demo"
    subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", "init",
         "--dir", str(workspace), "--slug", "demo", "--title", "Demo"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    state = json.loads((workspace / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["auto"] is True, "the unattended flag never reached the pack"
    assert not (tmp_path / ".claude" / ".auto-pending.json").exists(), (
        "the handoff must be one-shot - a stale one would mark a later attended run autonomous"
    )


def test_an_ordinary_engagement_is_never_marked_autonomous(tmp_path):
    """The other half: no handoff, no auto. A false positive here would make every
    engagement close PARTIAL and demand a ledger it never needed."""
    import subprocess

    workspace = tmp_path / "artifacts" / "demo"
    subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", "init",
         "--dir", str(workspace), "--slug", "demo", "--title", "Demo"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    state = json.loads((workspace / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["auto"] is False


def test_a_launcher_grant_expires_even_if_its_sidecar_is_gone(tmp_path):
    """Audit C3: keying ownership on the sidecar meant deleting or corrupting it turned a
    4-hour grant into a permanent one. Ownership now comes from the marker's own body."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    mod.grant_execution_consent(project, "SURV-4")
    (project / ".claude" / ".auto-grant.json").unlink()
    assert mod._expire_stale_auto_consent(project) is True
    assert not (project / ".claude" / MARKER_NAME).exists()


def test_a_corrupt_expiry_closes_the_gate_rather_than_leaving_it_open(tmp_path):
    """Fail SAFE: an unreadable window costs one static-only run; an unbounded grant is a
    standing authorisation nobody gave."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    mod.grant_execution_consent(project, "SURV-5")
    (project / ".claude" / ".auto-grant.json").write_text("{ not json", encoding="utf-8")
    assert mod._expire_stale_auto_consent(project) is True
    assert not (project / ".claude" / MARKER_NAME).exists()


def test_a_hand_made_marker_survives_a_stale_sidecar(tmp_path):
    """Audit S1: with ownership keyed on the sidecar, a leftover one would have deleted a
    marker the human created themselves. The body check is what makes claim 3 hold."""
    import datetime

    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    (project / ".claude" / MARKER_NAME).write_text("granted by hand\n", encoding="utf-8")
    (project / ".claude" / ".auto-grant.json").write_text(
        json.dumps({"expires_at": (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()}),
        encoding="utf-8",
    )
    assert mod._expire_stale_auto_consent(project) is False
    assert (project / ".claude" / MARKER_NAME).is_file()


# --- the Definition-of-Done gates --------------------------------------------------------------


def _closed_auto_pack(tmp_path, decisions=None, verdict=""):
    workspace = tmp_path / "artifacts" / "demo"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "engagement-state.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "status": "closed",
                "auto": True,
                "engagement": {"slug": "demo"},
                "decisions": decisions or {},
                "verdict": verdict,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path / "artifacts"


def test_an_unattended_run_that_looks_signed_off_is_a_finding(tmp_path):
    """The dangerous failure is not a wrong answer, it is a complete-looking one."""
    ca = _load("check_artifacts")
    findings = ca._auto_mode_findings(_closed_auto_pack(tmp_path, {"assumed-1": "x"}, "DoD: MET"))
    assert any("AUTO-NOT-PARTIAL" in f for f in findings)


def test_an_unattended_run_with_no_assumption_ledger_is_a_finding(tmp_path):
    """It answered its own questions; hiding which ones defeats the point of the mode."""
    ca = _load("check_artifacts")
    findings = ca._auto_mode_findings(_closed_auto_pack(tmp_path, {}, "DoD: PARTIAL"))
    assert any("AUTO-LEDGER-MISSING" in f for f in findings)


def test_a_properly_closed_unattended_run_is_clean(tmp_path):
    ca = _load("check_artifacts")
    findings = ca._auto_mode_findings(
        _closed_auto_pack(
            tmp_path,
            {"assumed-1": "scope -> review because the ticket named no target"},
            "DoD: PARTIAL - unattended run, human sign-off outstanding",
        )
    )
    assert findings == []


def test_the_gates_ignore_an_ordinary_attended_engagement(tmp_path):
    ca = _load("check_artifacts")
    workspace = tmp_path / "artifacts" / "normal"
    workspace.mkdir(parents=True)
    (workspace / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "closed", "engagement": {"slug": "normal"}}),
        encoding="utf-8",
    )
    assert ca._auto_mode_findings(tmp_path / "artifacts") == []


def test_a_parked_unattended_run_is_not_nagged_about_a_verdict(tmp_path):
    """Parking is the CORRECT outcome when scope is unclear - it must not also produce
    findings for lacking a verdict it was right not to reach."""
    ca = _load("check_artifacts")
    workspace = tmp_path / "artifacts" / "parked"
    workspace.mkdir(parents=True)
    (workspace / "engagement-state.json").write_text(
        json.dumps(
            {"schema": 2, "status": "blocked", "auto": True, "engagement": {"slug": "parked"}}
        ),
        encoding="utf-8",
    )
    assert ca._auto_mode_findings(tmp_path / "artifacts") == []


# --- the flow is documented where the session will read it -------------------------------------


def test_the_skill_tells_an_auto_run_what_it_may_not_do():
    """The detail moved behind a read-trigger on 2026-08-21 - inline in SKILL.md it cost
    +532 tokens at EVERY engagement open for a mode that is off by default and rare. What
    must survive that move is the trigger itself (a rule nothing routes to is not a rule)
    and the two things a run needs before it reads anything: ask nothing, and where to
    look."""
    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    assert "--auto" in skill
    assert "ask nothing at all" in skill.lower()
    assert "references/auto-mode.md" in skill, "the deferred detail is unreachable"
    detail = (
        REPO_ROOT / ".claude" / "skills" / "engage" / "references" / "auto-mode.md"
    ).read_text(encoding="utf-8")
    for requirement in ("assumed-", "PARTIAL", "blocked"):
        assert requirement in detail, f"the reference never mentions {requirement}"


# --- the gate must be REACHED, not merely present (2026-08-24 enforcement inventory) ---------


def test_the_auto_gate_is_reached_through_the_real_entry_point(tmp_path):
    """The lesson of finding C1, applied to its own fix.

    Every other AUTO-* test here calls `_auto_mode_findings` directly - which proves the gate
    WORKS while proving nothing about whether anything reaches it. That is exactly the shape
    of the original defect: the gate was correct and unreachable, and a suite full of direct
    calls stayed green throughout.

    So this one drives `check_artifacts.main()`, the entry point the DoD close and CI
    actually invoke, over a realistic tree, and asserts the finding surfaces in its OUTPUT.
    If the gate is ever unregistered from the check list, this fails and the direct-call
    tests do not."""
    import subprocess

    workspace = tmp_path / "artifacts" / "demo"
    workspace.mkdir(parents=True)
    (workspace / "engagement-state.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "status": "closed",
                "auto": True,
                "engagement": {"slug": "demo"},
                "decisions": {},
                "verdict": "DoD: MET",
            }
        ),
        encoding="utf-8",
    )
    # Invoked as a SUBPROCESS, the way CI and the DoD close invoke it - an in-process
    # main() call resolved the artifacts dir against the test runner's cwd and silently
    # checked this repo instead of the fixture.
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_artifacts", str(tmp_path / "artifacts")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    printed = result.stdout + result.stderr
    assert "AUTO-NOT-PARTIAL" in printed, (
        "the gate is not reached from main() - it can be correct and still never run"
    )
    assert "AUTO-LEDGER-MISSING" in printed
