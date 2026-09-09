"""The 2026-09-09 Jira hardening: the defects an attended engagement hits today.

Each test here pins one thing that was wrong before automation was ever considered. The
integration itself is prose the model executes, so these cover the parts that ARE code:
config resolution, the key round-trip, and the ticket link on the pack.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _write_prefs(root: Path, payload: dict, *, layout: str = "old") -> Path:
    """Write team-preferences.json where THIS layout keeps it."""
    if layout == "old":
        path = root / ".claude" / "team-preferences.json"
    else:
        # VSIT/config/preferences.json - the name loses its "team-" prefix in the new
        # layout, because the folder already says whose settings these are.
        path = root / "VSIT" / "config" / "preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --------------------------------------------------------------- transitions, default off


def test_done_transition_defaults_to_never(tmp_path):
    """Unset means the team does not touch workflow state. The docs used to say both
    "transitions remain human-only" and "transition to done at close"."""
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    _write_prefs(tmp_path, {"integrations": {"jira": {"enabled": True, "project_key": "SURV"}}})
    jira = resolve_integrations(tmp_path)["jira"]
    assert jira["done_transition"] == ""
    assert "transition=NONE" in integrations_report_line(resolve_integrations(tmp_path))


def test_done_transition_is_carried_verbatim(tmp_path):
    """Exactly the state named, never one guessed from what the board offers."""
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    _write_prefs(
        tmp_path,
        {
            "integrations": {
                "jira": {"enabled": True, "project_key": "SURV", "done_transition": "Ready for QA"}
            }
        },
    )
    resolved = resolve_integrations(tmp_path)
    assert resolved["jira"]["done_transition"] == "Ready for QA"
    assert "transition=Ready for QA" in integrations_report_line(resolved)


# ------------------------------------------------------------------------------- dry run


def test_dry_run_defaults_off_and_is_reported_when_on(tmp_path):
    """`mirror` chooses WHEN to post; there was no switch for WHETHER."""
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    _write_prefs(tmp_path, {"integrations": {"jira": {"enabled": True}}})
    assert resolve_integrations(tmp_path)["jira"]["dry_run"] is False
    assert "DRY-RUN" not in integrations_report_line(resolve_integrations(tmp_path))

    _write_prefs(tmp_path, {"integrations": {"jira": {"enabled": True, "dry_run": True}}})
    resolved = resolve_integrations(tmp_path)
    assert resolved["jira"]["dry_run"] is True
    assert "DRY-RUN" in integrations_report_line(resolved)


def test_dry_run_only_on_exact_true(tmp_path):
    """Same opt-in discipline as `enabled`: a truthy string must not arm it."""
    from scripts.engage_probe import resolve_integrations

    for bad in ("true", 1, "yes"):
        _write_prefs(tmp_path, {"integrations": {"jira": {"enabled": True, "dry_run": bad}}})
        assert resolve_integrations(tmp_path)["jira"]["dry_run"] is False, bad


# ------------------------------------------------------- the key round-trips on both layouts


def test_project_key_round_trips_where_the_probe_reads_it(tmp_path):
    """The setter wrote .claude/team-preferences.json while the probe resolved the path
    through vsit_paths. On a new-layout project the key saved, reported success, and was
    never read by anything."""
    import virt_team_launcher as vtl
    from scripts.engage_probe import resolve_integrations

    _write_prefs(tmp_path, {"integrations": {"jira": {"enabled": True}}}, layout="new")

    note = vtl.set_jira_project_key(tmp_path, "surv")
    assert "not a Jira project key" not in note
    assert vtl.jira_project_key(tmp_path) == "SURV"
    # the point of the test: the PROBE sees it, not just the launcher that wrote it
    assert resolve_integrations(tmp_path)["jira"]["project_key"] == "SURV"


def test_needs_key_agrees_with_the_reader(tmp_path):
    import virt_team_launcher as vtl

    _write_prefs(tmp_path, {"integrations": {"jira": {"enabled": True}}}, layout="new")
    assert vtl._jira_needs_key(tmp_path) is True
    vtl.set_jira_project_key(tmp_path, "SURV")
    assert vtl._jira_needs_key(tmp_path) is False


# ------------------------------------------------- a key that saves is a key that parses


def test_rejects_keys_whose_tickets_could_never_be_recognised(tmp_path):
    """The setter accepted anything alnum once underscores were stripped, so these three
    saved happily and then no ticket for that project could ever match _JIRA_KEY_RE."""
    import virt_team_launcher as vtl

    for bad in ("A_B", "1PROJ", "X"):
        note = vtl.set_jira_project_key(tmp_path, bad)
        assert "not a Jira project key" in note, bad
        assert vtl.jira_project_key(tmp_path) == "", bad


def test_every_accepted_key_parses_a_ticket_ref(tmp_path):
    """The property that matters, stated directly."""
    import virt_team_launcher as vtl

    for good in ("SURV", "ab", "Proj9", "X1"):
        note = vtl.set_jira_project_key(tmp_path, good)
        assert "not a Jira project key" not in note, good
        stored = vtl.jira_project_key(tmp_path)
        assert vtl._JIRA_KEY_RE.search(f"{stored}-123"), stored


# --------------------------------------------------------- the pack records its ticket


def test_handoff_ref_reaches_the_pack(tmp_path, monkeypatch):
    """The handoff always carried `ref` and init consumed everything except it, so the
    only ticket link was a decision key the model had to remember to write."""
    import engagement_state as es

    handoff = tmp_path / ".claude" / es.AUTO_HANDOFF
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(json.dumps({"auto": True, "ref": "SURV-412"}), encoding="utf-8")

    consumed = es._consume_auto_handoff(tmp_path)
    assert consumed["ref"] == "SURV-412"
    assert not handoff.exists()  # one-shot, unchanged
