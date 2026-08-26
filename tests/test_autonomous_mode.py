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


# --- the spend ceiling and the pre-answered ladder (2026-08-24) --------------------------------


def test_the_handoff_carries_the_ceiling_and_the_chosen_rung(tmp_path):
    """Unattended work is the one case where nobody is watching the spend, and the attended
    degrade ladder is a QUESTION - which this run has nobody to ask, and which
    `--permission-mode dontAsk` denies outright. So the rung is chosen once at the pre-flight
    and travels with the flag."""
    import subprocess

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / ".auto-pending.json").write_text(
        json.dumps({"auto": True, "engagement_usd": 25, "on_budget": "light"}), encoding="utf-8"
    )
    workspace = tmp_path / "artifacts" / "demo"
    subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", "init",
         "--dir", str(workspace), "--slug", "demo", "--title", "Demo"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    state = json.loads((workspace / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["auto"] is True
    assert state["budget"]["engagement_usd"] == 25
    assert state["auto_on_budget"] == "light"


def test_an_unattended_run_defaults_to_parking_at_the_ceiling(tmp_path):
    """Park is the default because a parked run is recoverable and a truncated one is not -
    and because parking is already this mode's answer to every other cannot-proceed."""
    import subprocess

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / ".auto-pending.json").write_text(
        json.dumps({"auto": True}), encoding="utf-8"
    )
    workspace = tmp_path / "artifacts" / "demo"
    subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", "init",
         "--dir", str(workspace), "--slug", "demo", "--title", "Demo"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    state = json.loads((workspace / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["auto_on_budget"] == "park"


def test_an_attended_engagement_keeps_the_ladder(tmp_path):
    """No pre-answer for an attended run: it still gets asked, which is correct - there is
    somebody there."""
    import subprocess

    workspace = tmp_path / "artifacts" / "demo"
    subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", "init",
         "--dir", str(workspace), "--slug", "demo", "--title", "Demo"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    state = json.loads((workspace / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["auto_on_budget"] is None
    assert state["budget"] == {}


def test_a_corrupt_handoff_still_marks_the_run_unattended(tmp_path):
    """Losing the budget is a smaller error than losing the flag that makes the AUTO-* gates
    fire, so an unreadable handoff is consumed as auto rather than treated as absent."""
    import subprocess

    (tmp_path / ".claude").mkdir(parents=True)
    handoff = tmp_path / ".claude" / ".auto-pending.json"
    handoff.write_text("{ not json", encoding="utf-8")
    workspace = tmp_path / "artifacts" / "demo"
    subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", "init",
         "--dir", str(workspace), "--slug", "demo", "--title", "Demo"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    state = json.loads((workspace / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["auto"] is True
    assert not handoff.exists(), "a corrupt handoff must still be consumed, not left to recur"


def test_the_reference_tells_the_run_not_to_ask_at_the_ceiling():
    text = (
        REPO_ROOT / ".claude" / "skills" / "engage" / "references" / "auto-mode.md"
    ).read_text(encoding="utf-8")
    assert "do not offer the degrade ladder" in text
    assert "auto_on_budget" in text
    for rung in ("`park`", "`light`", "`continue`"):
        assert rung in text
    assert "advisory pacing, not a hard stop" in text


def test_the_light_rung_cannot_be_reached_on_the_models_own_judgement():
    """`engage-light` says the profile is chosen by invoking that command and is never
    inferred, nor suggested as a way around a gate - and the light rung IS a way around a
    spend gate. It is legitimate only because a human pre-authorised it at the pre-flight,
    and the reference has to say so or the two documents contradict each other.

    Fragments, not sentences: the source is hard-wrapped, so asserting a full phrase tests
    the line breaks rather than the meaning (which it did, on the first attempt)."""
    text = (
        REPO_ROOT / ".claude" / "skills" / "engage" / "references" / "auto-mode.md"
    ).read_text(encoding="utf-8")
    light = text[text.index("- **`light`**") :][:900]
    assert "pre-authorised" in light, "nothing distinguishes this from inferring the profile"
    assert "own judgement" in light
    assert "never checks or" in light, "must say what light does NOT remove"
    assert "set-profile light" in light, "the rung must name the mechanism it uses"


def test_a_light_downgrade_still_cannot_close_as_complete(tmp_path):
    """The backstop that makes the light rung safe at all. Reduced ceremony bought mid-flight
    must never read as a full close - and because AUTO-NOT-PARTIAL applies to EVERY auto run
    regardless of the rung taken, an engagement that dropped to light and then claimed
    DoD: MET is caught."""
    ca = _load("check_artifacts")
    findings = ca._auto_mode_findings(
        _closed_auto_pack(
            tmp_path,
            {"assumed-1": "dropped to light at the $25 ceiling"},
            "DoD: MET",
        )
    )
    assert any("AUTO-NOT-PARTIAL" in f for f in findings)


# --- [n] takes the request at the launcher (2026-08-24 user report) ---------------------------


def test_typing_is_an_offer_not_a_toll_gate(tmp_path):
    """User report: "I clicked new engagement but no option to pre-seed a prompt, it just
    opened cc". The fix must not swing the other way - an empty field gives exactly the plain
    launch it replaced, so nobody is forced to compose a brief at a prompt."""
    mod = _load("virt_team_launcher")
    assert mod._new_command(tmp_path) == mod._new_command(tmp_path, "")
    assert mod._new_command(tmp_path).endswith("--new")
    assert "--request" not in mod._new_command(tmp_path, "   ")


def test_a_typed_request_reaches_the_session(tmp_path):
    mod = _load("virt_team_launcher")
    command = mod._new_command(tmp_path, "review the spoofing rule")
    assert "--request-pending" in command
    assert (tmp_path / ".claude" / ".request-pending.txt").read_text(
        encoding="utf-8"
    ).strip() == "review the spoofing rule"


def test_the_request_is_sanitised_for_the_decision_channel(tmp_path):
    """The text is still sanitised even though it no longer rides in the command: it becomes
    one line with no quote characters, so a session reading it back gets something
    predictable, and so does anything that later echoes it into a prompt."""
    mod = _load("virt_team_launcher")
    command = mod._new_command(tmp_path, 'check "the" rule\nand   the other')
    assert "\n" not in command
    # No quotes left to balance: the decision carries a bare token and the text lives in a
    # file (2026-08-25). Unbalanced quoting cannot split what has no quotes in it.
    assert '"' not in command
    body = (tmp_path / ".claude" / ".request-pending.txt").read_text(encoding="utf-8").strip()
    assert body == "check 'the' rule and the other"


def test_unattended_is_reachable_from_a_typed_request_not_only_a_ticket(tmp_path):
    """Autonomy being Jira-only was an accident of where it was built. Everything downstream
    - the pre-flight, the ledger, park-don't-guess, the always-PARTIAL close - never cared
    where the work came from."""
    mod = _load("virt_team_launcher")
    command = mod._new_command(tmp_path, "review the spoofing rule", auto=True)
    assert command.endswith("--auto")
    assert "--jira" not in command


def test_auto_needs_an_actual_request(tmp_path):
    """An unattended run with no statement of the work is the one thing this mode must never
    start: it would have nothing to park against and nothing to assume from."""
    mod = _load("virt_team_launcher")
    assert "--auto" not in mod._new_command(tmp_path, "", auto=True)


def test_the_skill_treats_the_typed_request_as_the_request():
    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    assert "--request" in skill
    assert "do not re-ask what the work is" in skill


# --- the launcher and the skill must agree on what --auto can ride with ---------------------
#
# 2026-08-25 live report: auto mode on, [n] pressed, the request typed at the TUI - and the
# session still asked what to run. The launcher was right (it emitted
# `--new --request "..." --auto`) and the shell was right (one argument, quotes intact). The
# skill's flag contract was stale: it still said `--auto` rides with `--jira`, from when
# autonomy was Jira-only, so the model had no documented reason to treat `--auto` beside
# `--request` as authorisation. A capability grew on one side of an interface and the other
# side was never told - so pin the agreement rather than the wording.


def _auto_bullet(text: str) -> str:
    """The `--auto` bullet from SKILL.md, up to the next top-level bullet."""
    start = text.index("- **`--auto`")
    rest = text[start + 1 :]
    end = rest.find("\n- **`")
    return rest[: end if end != -1 else len(rest)]


def test_the_skill_documents_every_source_the_launcher_can_start_an_auto_run_from(tmp_path):
    """Both sources, checked against what the launcher actually emits - not against a list
    of flag names someone remembered to keep current."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    from_ticket = mod._jira_command(project, "SURV-9", auto=True)
    from_request = mod._new_command(project, "tune the Q3 thresholds", auto=True)
    assert from_ticket.endswith("--auto") and "--jira" in from_ticket
    assert from_request.endswith("--auto") and "--request" in from_request

    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    bullet = _auto_bullet(skill)
    assert "--jira" in bullet, "the ticket source must stay documented"
    assert "--request" in bullet, (
        "the launcher can start an unattended run from a typed request "
        f"({from_request!r}), but the --auto bullet does not mention --request - the exact "
        "drift that made a live auto run ask what the work was"
    )


def test_an_auto_run_is_told_not_to_ask_what_the_work_is():
    """The reported symptom, pinned directly: the brief arrived with the flags."""
    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    bullet = _auto_bullet(skill)
    assert "ask nothing at all" in bullet
    lowered = bullet.lower()
    assert "source-agnostic" in lowered or "either" in lowered, (
        "the bullet must say autonomy is not tied to one source, or it reads as Jira-only again"
    )


def test_the_decision_hands_a_shell_nothing_to_reinterpret(tmp_path):
    """The reported bug, from the other end. In bash the old quoted form survived - verified
    - but PowerShell 5.1 hands embedded quotes to a native .exe unescaped, so claude.exe
    re-split the line and kept the first token. Two users, same day, same symptom; the tell
    was that `--jira SURV-9` worked while a typed request did not, the difference being
    spaces and quotes rather than anything about Jira.

    So the property to hold is not "quoted correctly" but "nothing to quote": every token in
    the decision is bare, and the text travels in a file where no shell touches it."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    messy = 'run the "Q3"\n tuning   analysis'
    command = mod._new_command(project, messy, auto=True)
    assert "\n" not in command
    assert '"' not in command and "'" not in command
    assert command.split() == [
        mod._engage_command(project), "--new", "--request-pending", "--auto"
    ]
    body = (project / ".claude" / ".request-pending.txt").read_text(encoding="utf-8").strip()
    assert body == "run the 'Q3' tuning analysis", "the text itself keeps its spaces"


# --- what a typed request may safely contain (2026-08-25) ----------------------------------
#
# The request is delivered inside `--request "<text>"`. Anything that closes that span early
# hands the rest of the sentence to the skill as flags, which is silent corruption rather than
# an error - so the characters people actually type are pinned here.

BACKSLASH = chr(92)


def _request_body(command: str, project=None) -> str:
    """What the SESSION will actually read. The decision carries a bare `--request-pending`
    token; the text lives in a file, verbatim, spaces and all."""
    assert "--request-pending" in command, command
    assert '"' not in command, f"the decision must carry no quotes at all: {command}"
    assert not any(" " in tok for tok in command.split()), "every token must be space-free"
    return (project / ".claude" / ".request-pending.txt").read_text(encoding="utf-8").rstrip("\n")


def test_speech_marks_of_every_shape_cannot_close_the_span(tmp_path):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    for text in (
        'check the "Q3" figures',
        "check the “Q3” figures",     # curly
        "check the «Q3» figures",     # guillemets
        "check the ″Q3″ figures",     # double prime
    ):
        body = _request_body(mod._new_command(project, text), project)
        assert '"' not in body, f"{text!r} left a terminator in {body!r}"
        assert "Q3" in body and "figures" in body, "folding a quote must not lose words"


def test_an_interior_backslash_is_kept_because_a_windows_path_is_a_real_request(tmp_path):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    text = f"profile C:{BACKSLASH}extracts{BACKSLASH}q3 for gaps"
    body = _request_body(mod._new_command(project, text), project)
    assert body == text, "mangling a path would be its own bug"


def test_a_trailing_backslash_never_escapes_the_closing_quote(tmp_path):
    """The subtle one: a path typed with a trailing separator puts a backslash immediately
    before the closing quote, which an escape-aware reader takes as an escaped quote - so the
    request appears to swallow the rest of the line rather than ending."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    command = mod._new_command(project, f"read C:{BACKSLASH}data{BACKSLASH}alerts{BACKSLASH}")
    body = _request_body(command, project)
    assert not body.endswith(BACKSLASH)
    assert f"C:{BACKSLASH}data{BACKSLASH}alerts" in body, "the path itself must survive"


def test_control_characters_do_not_reach_the_prompt(tmp_path):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    body = _request_body(mod._new_command(project, "review\x07 the\x1b extract\x00 now"), project)
    assert all(ch.isprintable() for ch in body)
    assert "review" in body and "extract" in body


def test_a_long_request_is_never_truncated(tmp_path):
    """Losing the end of a brief is the failure this path was fixed for. Long is just long."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    text = " ".join(f"sentence number {i} about the extract." for i in range(60))
    body = _request_body(mod._new_command(project, text), project)
    assert body == text
    assert "sentence number 59" in body


# --- arming vs offering (2026-08-25, owner: "i dont understand why we wouldnt have an auto
# --- param then") ---------------------------------------------------------------------------
#
# autonomous_mode is a KILL SWITCH that already defaults to on, so "turning auto mode on"
# changed nothing observable - a setting that reads as an enabler but only ever removes an
# option. autonomous_default is the enabler it implied: it arms the unattended toggle for new
# work. The line these tests defend is that arming changes the default ANSWER to one question
# and never removes a question - the pre-flight still runs.


def _prefs(project, **kv):
    (project / ".claude" / "team-preferences.json").write_text(json.dumps(kv), encoding="utf-8")
    return project


def test_arming_is_off_unless_asked_for(tmp_path):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    assert mod._auto_offered(project) is True, "the option is offered by default"
    assert mod._auto_armed(project) is False, "but nothing is armed by default"


def test_a_project_can_arm_unattended_for_new_work(tmp_path):
    mod = _load("virt_team_launcher")
    project = _prefs(_project(tmp_path), autonomous_default=True)
    assert mod._auto_armed(project) is True


def test_the_kill_switch_still_wins_over_arming(tmp_path):
    """Otherwise a project that removed the option could still start armed runs - the two
    settings would contradict each other and the more permissive one would win, which is the
    wrong way round for anything to do with autonomy."""
    mod = _load("virt_team_launcher")
    project = _prefs(_project(tmp_path), autonomous_mode=False, autonomous_default=True)
    assert mod._auto_offered(project) is False
    assert mod._auto_armed(project) is False


def test_arming_never_skips_the_preflight(tmp_path):
    """The property that makes arming safe. The pre-flight is where data attestation,
    execution consent and the spend ceiling are answered; an armed run that bypassed it would
    be standing autonomy, which is exactly what the per-ticket rule exists to prevent."""
    mod = _load("virt_team_launcher")
    project = _prefs(_project(tmp_path), autonomous_default=True)
    calls = []

    class _Cancelled:
        pass

    import types
    fake = types.SimpleNamespace(
        AUTO_CANCELLED=_Cancelled,
        auto_preflight_screen=lambda p, m, ref: calls.append(ref) or None,
    )
    sys.modules["launcher_app"] = fake
    try:
        decision = mod._auto_run_decision(project, "tune thresholds", request_text="tune thresholds")
    finally:
        sys.modules.pop("launcher_app", None)
    assert calls == ["tune thresholds"], "the pre-flight must be consulted every time"
    assert decision == "", "a pre-flight that cannot run must NOT start an unattended run"


# --- pre-flight defaults and the commit key (owner, 2026-08-25) -----------------------------


def _preflight_source():
    return (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")


def test_the_spend_ceiling_defaults_to_35():
    src = _preflight_source()
    assert "CAPS = (0, 10, 25, 35, 50, 100)" in src, "$35 must be an offered rung"
    body = src.split("def auto_preflight_screen", 1)[1]
    state = body.split('state = {', 1)[1].split("}", 1)[0]
    assert '"cap": 3' in state, "index 3 of CAPS is $35"


def test_at_the_ceiling_it_defaults_to_parking():
    """Changed to park on 2026-08-26 after watching a live run hit a hard cap MID-CLOSE. It
    had written a delivery report, an engagement brief, two interim analyses and the summary
    email, then was stopped before recording its verdict - leaving the pack at status
    "closing" with no verdict at all. Parking happens AT A GATE, which is a resumable place;
    a cap that fires wherever the run happens to be is not."""
    src = _preflight_source()
    body = src.split("def auto_preflight_screen", 1)[1]
    assert 'ON_BUDGET = ("park", "light", "continue", "stop")' in body, (
        "four rungs: three advisory, one enforced"
    )
    state = body.split('state = {', 1)[1].split("}", 1)[0]
    assert '"on_budget": 0' in state, "index 0 of ON_BUDGET is park"
    assert '"park": "park at next gate"' in body


def test_enter_cannot_start_an_unattended_run():
    """2026-08-25: "enter is too easy to press ... user may press enter thinking it toggles
    options". On the single authorisation gate for an unattended run, the most reflexive key
    on the keyboard must not be the one that arms it."""
    body = _preflight_source().split("def auto_preflight_screen", 1)[1]
    commit = body.split("def _start(event):", 1)[0]
    tail = commit.rsplit("@kb.add(", 1)[1]
    assert tail.startswith('"c-d"'), f"the commit key must be Ctrl-D, found {tail[:20]!r}"
    toggle = body.split("def _toggle(event):", 1)[0]
    assert '@kb.add("enter")' in toggle, "Enter must be bound to the harmless toggle"
    # The keys are rendered from ONE constant now: the body used to repeat them, went stale
    # when Enter stopped starting the run, and then clipped when corrected. Assert the
    # constant and that the footer uses it, rather than a literal that can drift again.
    src = _preflight_source()
    assert 'Ctrl-D START unattended' in src.split("_PREFLIGHT_KEYS = ", 1)[1].split("\n", 1)[0]
    assert "_PREFLIGHT_KEYS" in body, "the footer must render the shared constant"
    assert body.count("Ctrl-D START unattended") == 0, "and must not repeat it as a literal"


def test_the_two_screens_in_the_flow_agree_on_their_send_key():
    """The composer sends on Ctrl-D; the pre-flight now commits on Ctrl-D. One flow, one key -
    a different commit key per screen is how a reflex lands on the wrong one."""
    src = _preflight_source()
    for func in ("def request_screen", "def auto_preflight_screen"):
        body = src.split(func, 1)[1].split("\ndef ", 1)[0]
        assert '@kb.add("c-d")' in body, f"{func} does not commit on Ctrl-D"


# --- the request handoff must never outlive the engagement it was typed for -----------------
#
# 2026-08-25, owner: "will it delete the file on read so something stale not lying around".
# The skill IS told to delete it, and "told to" is not a control that engages - the AUTO-*
# gates were dead code for exactly that reason. So two mechanical nets, neither relying on
# the session doing anything.


def test_creating_the_workspace_consumes_the_request(tmp_path):
    """Net one: whatever the session did or forgot, init deletes it."""
    state = _load("engagement_state")
    handoff = tmp_path / ".claude" / state.REQUEST_HANDOFF
    handoff.parent.mkdir(parents=True)
    handoff.write_text("review the spoofing rule\n", encoding="utf-8")
    assert state.consume_request_handoff(tmp_path) == "review the spoofing rule"
    assert not handoff.exists(), "the handoff must not survive being read"
    assert state.consume_request_handoff(tmp_path) == "", "and a second read finds nothing"


def test_consuming_a_missing_or_unreadable_handoff_is_quiet(tmp_path):
    state = _load("engagement_state")
    assert state.consume_request_handoff(tmp_path) == ""
    (tmp_path / ".claude").mkdir(parents=True)
    directory = tmp_path / ".claude" / state.REQUEST_HANDOFF
    directory.mkdir()  # a directory where a file is expected: must not raise
    assert state.consume_request_handoff(tmp_path) == ""


def test_every_go_clears_a_request_stranded_by_a_previous_one(tmp_path):
    """Net two, and the one that covers the case init cannot: a request typed and then
    ABANDONED with Esc leaves a file behind, and no workspace is ever created to consume it.
    Clearing at the start of every go means the file is this run's request or nothing."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    stranded = project / ".claude" / mod._REQUEST_HANDOFF
    stranded.write_text("a request nobody went through with\n", encoding="utf-8")
    mod._clear_request_handoff(project)
    assert not stranded.exists()
    mod._clear_request_handoff(project)  # idempotent - absent is the normal case


def test_a_plain_new_engagement_leaves_no_request_behind(tmp_path):
    """The precise stale-pickup risk: type a request, back out, start a plain [n]. The
    second engagement must not inherit the first one's instruction."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    mod._new_command(project, "tune the Q3 thresholds")
    assert (project / ".claude" / mod._REQUEST_HANDOFF).is_file()
    mod._clear_request_handoff(project)
    command = mod._new_command(project)  # plain [n], nothing typed
    assert command.endswith("--new") and "--request-pending" not in command
    assert not (project / ".claude" / mod._REQUEST_HANDOFF).exists()


# --- advisory ceiling vs enforced cap (owner, 2026-08-25) -----------------------------------
#
# "We can either say continue and notify or choose a hard cap - why don't we keep
# flexibility." Right: those are two different promises, and collapsing them loses one. The
# ceiling stays a threshold the run reports against; "stop" makes it a wall the CLI enforces
# with --max-budget-usd, which no run can talk past because it is the process that refuses.


def _preflight_answers(**over):
    """The dict the pre-flight returns, as the launcher consumes it."""
    base = {"data_attested": True, "allow_exec": False, "engagement_usd": 35,
            "on_budget": "continue", "run_mode": "window", "hard_cap_usd": None}
    base.update(over)
    return base


def test_the_enforced_cap_is_separate_from_the_advisory_ceiling():
    """Two fields, because they are two different promises and a caller must never have to
    infer which one was made."""
    src = _preflight_source()
    body = src.split("def auto_preflight_screen", 1)[1]
    assert '"engagement_usd": ceiling' in body
    assert '"hard_cap_usd"' in body


def test_a_hard_cap_is_only_produced_when_it_can_actually_be_enforced():
    """--max-budget-usd exists in print mode only. Handing a caller a cap that nothing will
    honour is the worst kind of setting: it reads as a guarantee and is a preference."""
    src = _preflight_source()
    body = src.split("def auto_preflight_screen", 1)[1]
    condition = body.split('"hard_cap_usd":', 1)[1].split("\n", 1)[0]
    assert 'rung == "stop"' in condition
    assert 'mode == "headless"' in condition
    assert "ceiling" in condition, "and only when a ceiling was actually set"


def test_choosing_a_hard_cap_on_a_windowed_run_says_why_it_cannot_apply():
    """Silently not enforcing it would be the failure. The screen names the fix."""
    body = _preflight_source().split("def auto_preflight_screen", 1)[1]
    assert "A hard cap needs a headless run" in body
    assert "Switch 'How it runs' to headless" in body


def test_the_run_mode_reaches_the_workspace(tmp_path):
    """The handoff carries it, so the session and every gate downstream know which kind of
    run this is without being told twice."""
    mod = _load("virt_team_launcher")
    src = (REPO_ROOT / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    assert '"run_mode": answers.get("run_mode") or "window"' in src
    assert '"hard_cap_usd": answers.get("hard_cap_usd")' in src
    assert mod is not None


def test_the_state_layer_accepts_the_enforced_rung():
    state = _load("engagement_state")
    assert "stop" in state.AUTO_ON_BUDGET
    assert state.AUTO_ON_BUDGET[:3] == ("park", "light", "continue"), (
        "the advisory rungs keep their order and meaning"
    )


# --- web access is a question, not a default (owner, 2026-08-26) -----------------------------


def test_web_search_is_off_unless_the_human_says_otherwise():
    """An unattended run reaching the internet is a decision. Nobody is watching what it
    fetches, or what a fetched page tells it to do - and reviewed content is DATA, never
    instruction (CLAUDE.md §7). So it is a pre-flight question with the cautious default."""
    src = _preflight_source()
    body = src.split("def auto_preflight_screen", 1)[1]
    state = body.split('state = {', 1)[1].split("}", 1)[0]
    assert '"web": False' in state, "off by default"
    assert '("web", "toggle", "Allow web search"' in body, "and asked, not assumed"


def test_granting_web_access_adds_both_search_and_fetch():
    """Search without fetch would be half a permission: the model finds a page it cannot
    read, which is worse than not searching."""
    mod = _load("virt_team_launcher")
    off = mod._headless_allow_rules(False)
    on = mod._headless_allow_rules(True)
    assert "WebSearch" not in off and "WebFetch" not in off
    assert "WebSearch" in on and "WebFetch" in on
    assert set(off).issubset(set(on)), "granting web must not remove anything else"


def test_the_answer_travels_to_the_run(tmp_path):
    """It has to reach the handoff, or the toggle is decoration."""
    src = (REPO_ROOT / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    assert '"allow_web": bool(answers.get("allow_web"))' in src
    assert '_headless_allow_rules(bool(pending.get("allow_web")))' in src


def test_a_report_written_without_the_web_is_not_silently_presented_as_researched():
    """The live case: a vendor report was produced with WebSearch refused and nothing said
    so. The pre-flight row states the consequence rather than only the setting."""
    body = _preflight_source().split("def auto_preflight_screen", 1)[1]
    assert "writes from what it knows" in body
