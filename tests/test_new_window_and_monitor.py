"""Opening an unattended run beside the launcher, and watching it (2026-08-25).

Asked for as "the new terminal window launch for virt-surv go, and crucially when in
autonomous mode show the status of the engagement in the TUI - this is a precursor to
running headless".

The two halves are one feature. `go` used to REPLACE itself with the session, so the TUI
that had just taken the decision was gone the moment the work began. For an attended run
that costs a pane; for an unattended one it costs the only place progress could ever be
shown, because nobody is being asked anything. The window makes the monitor possible; the
monitor is what the window is for.

What these tests defend, in order of how much it would hurt to lose:

1. a run the human authorised ALWAYS starts - every failure falls back to launching in
   place, and none of them is a silent no-op;
2. the session is never started TWICE - the wrapper is told to stand down only when a
   window actually opened;
3. the monitor never writes anything, so closing it cannot disturb the run;
4. the one-shot auto handoff is READ, never consumed, here - consuming it would take the
   unattended flag off the run and re-create the dead-gate bug of 2026-08-21.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    for extra in (REPO_ROOT / "vendor", REPO_ROOT / "scripts"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _project(tmp_path: Path, **prefs) -> Path:
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text(
        json.dumps(prefs), encoding="utf-8"
    )
    return tmp_path


# --- choosing a terminal ---------------------------------------------------------------


def test_no_graphical_session_means_no_window(monkeypatch):
    """A headless Linux box has xterm installed and no display to open it into. Claiming a
    window is available there is the worst answer: the caller stops falling back and the
    session never starts at all."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(lt, "_which", lambda name: "/usr/bin/xterm")
    assert lt.available() == ""
    assert lt.open_in_new_window(["claude"], Path(".")) is False


def test_the_first_installed_terminal_wins(monkeypatch):
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(lt, "_which", lambda name: "/usr/bin/konsole" if name == "konsole" else None)
    assert lt.available() == "konsole"


def test_every_tier_builds_an_argv_that_keeps_the_command_together(monkeypatch):
    """The command carries a decision string with spaces in it. Whatever the emulator's
    flag spelling, that must arrive as ONE argument - the failure mode this repo has
    already met once, on PowerShell, at a cost of two users losing their request."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "_which", lambda name: f"/usr/bin/{name}")
    decision = "/engage --new --request-pending --auto"
    for terminal in lt._POSIX_TIERS:
        argv = lt._posix_argv(terminal, ["claude", decision], Path("/tmp/proj"))
        assert isinstance(argv, list) and argv
        joined = " ".join(argv)
        assert "--request-pending" in joined
        if "sh" not in argv:  # the sh -c tiers quote it instead of passing it whole
            assert decision in argv, f"{terminal} split the decision: {argv}"


def test_windows_tiers_are_tried_in_order(monkeypatch):
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "win32")
    present = {"powershell.exe"}
    monkeypatch.setattr(lt, "_which", lambda n: f"C:/{n}" if n in present else None)
    assert lt.available() == "powershell.exe"
    present.add("wt.exe")
    assert lt.available() == "wt.exe", "Windows Terminal is preferred when present"


# --- launching, and never launching twice ----------------------------------------------


def test_a_failed_window_falls_back_and_says_so(tmp_path, monkeypatch, capsys):
    """The property that matters most: the human has already authorised this run."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "")
    assert mod._launch_unattended_in_window(project, "/engage --new --auto", "slug") is False
    assert "opening in this one instead" in capsys.readouterr().err


def test_a_terminal_that_exists_but_will_not_start_also_falls_back(tmp_path, monkeypatch, capsys):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "xterm")
    monkeypatch.setattr(lt, "open_in_new_window", lambda *a, **k: False)
    assert mod._launch_unattended_in_window(project, "/engage --new --auto", "slug") is False
    assert "could not open a new window" in capsys.readouterr().err


def test_the_wrapper_is_told_to_stand_down_only_when_a_window_opened(tmp_path, monkeypatch):
    """Exit 97 here means "already started", not "aborted". Getting it wrong in either
    direction is bad: too eager and the session starts twice, too shy and it starts in a
    window the human cannot see AND in this shell."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    (project / ".claude" / ".auto-pending.json").write_text(
        json.dumps({"slug": "alpha", "auto": True}), encoding="utf-8"
    )
    for name in ("_print_banner", "_check_plugin_cache_lag", "_print_project_defaults",
                 "_prewarm_guard_interpreter", "_write_probe_cache", "_refresh_tool_cache",
                 "_heal_stale_alias_once", "_clear_request_handoff"):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: "/engage --new --auto")

    monkeypatch.setattr(mod, "_launch_unattended_in_window", lambda *a: True)
    assert mod.main() == mod._ABORT_EXIT_CODE

    monkeypatch.setattr(mod, "_launch_unattended_in_window", lambda *a: False)
    assert mod.main() == 0, "a failed window must let the wrapper launch in place"


def test_an_attended_run_is_never_moved_to_another_window(tmp_path, monkeypatch):
    """You are already in that session; a second window would just be a second window."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    for name in ("_print_banner", "_check_plugin_cache_lag", "_print_project_defaults",
                 "_prewarm_guard_interpreter", "_write_probe_cache", "_refresh_tool_cache",
                 "_heal_stale_alias_once", "_clear_request_handoff"):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: "/engage --new --request-pending")
    called = []
    monkeypatch.setattr(mod, "_launch_unattended_in_window", lambda *a: called.append(a) or True)
    assert mod.main() == 0
    assert called == [], "no --auto, no new window"


def test_the_auto_handoff_is_read_not_consumed(tmp_path):
    """Consuming it here would take the unattended flag off the run before it started -
    exactly the 2026-08-21 bug that left the AUTO-* gates dead."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    handoff = project / ".claude" / ".auto-pending.json"
    handoff.write_text(json.dumps({"slug": "alpha", "auto": True}), encoding="utf-8")
    assert mod._pending_auto_slug(project) == "alpha"
    assert handoff.is_file(), "the handoff must survive for engagement_state to consume"
    assert mod._pending_auto_slug(project) == "alpha", "and stay readable"


def test_a_missing_or_corrupt_handoff_yields_no_slug(tmp_path):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    assert mod._pending_auto_slug(project) == ""
    (project / ".claude" / ".auto-pending.json").write_text("{not json", encoding="utf-8")
    assert mod._pending_auto_slug(project) == ""


# --- the monitor -----------------------------------------------------------------------


def test_the_monitor_reads_a_live_state_file(tmp_path):
    app = _load("launcher_app")
    pack = tmp_path / "artifacts" / "alpha"
    pack.mkdir(parents=True)
    (pack / "engagement-state.json").write_text(
        json.dumps({
            "status": "in_progress", "phase": "build", "auto": True,
            "auto_on_budget": "continue", "budget": {"engagement_usd": 35},
            "outstanding": [{"text": "QA pass"}],
            "engagement": {"slug": "alpha", "title": "Alpha work"},
        }),
        encoding="utf-8",
    )
    snap = app._monitor_read(tmp_path, "alpha")
    assert snap["state"]["phase"] == "build"
    assert snap["artifacts"] == 1
    assert snap["error"] == ""


def test_the_monitor_survives_every_normal_failure(tmp_path):
    """All three are ordinary, not exceptional: the pack does not exist until the session
    makes it, and a read can land mid-write."""
    app = _load("launcher_app")
    missing = app._monitor_read(tmp_path, "nope")
    assert missing["state"] is None and "waiting" in missing["error"]

    pack = tmp_path / "artifacts" / "alpha"
    pack.mkdir(parents=True)
    assert "waiting" in app._monitor_read(tmp_path, "alpha")["error"]

    (pack / "engagement-state.json").write_text('{"status": "in_pr', encoding="utf-8")
    partial = app._monitor_read(tmp_path, "alpha")
    assert partial["state"] is None
    assert "being written" in partial["error"], "a race must not read as a broken engagement"


def test_the_monitor_opens_nothing_for_writing(tmp_path):
    """Closing the view must never be able to disturb the run it is watching."""
    app = _load("launcher_app")
    source = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")
    body = source.split("def monitor_screen", 1)[1].split("\ndef ", 1)[0]
    for forbidden in ("write_text(", "unlink(", "mkdir(", "open(", "rename("):
        assert forbidden not in body, f"the monitor must not {forbidden} anything"
    assert "_monitor_read" in body

    pack = tmp_path / "artifacts" / "alpha"
    pack.mkdir(parents=True)
    state = pack / "engagement-state.json"
    state.write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")
    before = state.stat().st_mtime_ns
    app._monitor_read(tmp_path, "alpha")
    assert state.stat().st_mtime_ns == before, "reading must not touch the file"


def test_elapsed_reads_as_time_not_a_number():
    app = _load("launcher_app")
    now = app._clock()
    assert app._elapsed(now).endswith("s")
    assert app._elapsed(now - 75) == "1m 15s"
    assert app._elapsed(now - 3725) == "1h 02m"
    assert app._elapsed(now + 10) == "0s", "a clock change must not show negative time"
