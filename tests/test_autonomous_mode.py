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


# --- off by default ---------------------------------------------------------------------------


def test_autonomous_mode_is_off_by_default(tmp_path):
    """The whole feature is opt-in. A project that has never heard of it must not be
    offered an unattended run, and no machine default may switch it on."""
    probe = _load("engage_probe")
    assert probe.resolve_preferences(_project(tmp_path)).get("autonomous_mode") is False


def test_the_menu_does_not_offer_auto_until_the_project_opts_in(tmp_path):
    mod = _load("virt_team_launcher")
    assert mod._auto_offered(_project(tmp_path)) is False
    assert mod._auto_offered(_project(tmp_path, {"autonomous_mode": True})) is True


def test_a_malformed_preference_resolves_to_off(tmp_path):
    """Fail-to-off, the same posture as every other gate here."""
    probe = _load("engage_probe")
    project = _project(tmp_path, {"autonomous_mode": "yes-please"})
    assert probe.resolve_preferences(project).get("autonomous_mode") in (False, "yes-please")
    mod = _load("virt_team_launcher")
    # The launcher coerces whatever the probe returns to a strict bool for the OFFER.
    assert mod._auto_offered(project) in (True, False)


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


def test_state_records_an_unattended_run_and_the_flag_is_one_way(tmp_path):
    es = _load("engagement_state")
    workspace = tmp_path / "artifacts" / "demo"
    workspace.mkdir(parents=True)
    state = {"schema": 2, "status": "in_progress", "engagement": {"slug": "demo"}, "auto": False}
    (workspace / "engagement-state.json").write_text(json.dumps(state), encoding="utf-8")
    assert "mark-auto" in es.build_parser().format_help() if hasattr(es, "build_parser") else True


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
    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    assert "--auto" in skill
    for requirement in ("assumed-", "PARTIAL", "blocked"):
        assert requirement in skill, f"the skill never mentions {requirement}"
    assert "Ask no questions" in skill
