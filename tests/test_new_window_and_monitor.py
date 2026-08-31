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
    (tmp_path / ".claude" / "team-preferences.json").write_text(json.dumps(prefs), encoding="utf-8")
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
    # TMUX too, since tmux became a legitimate answer that needs no display (2026-08-25).
    # Without this the test inherits the developer's own tmux session and fails - which is
    # itself the point of the feature, so it is cleared rather than worked around.
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(lt, "_which", lambda name: "/usr/bin/xterm")
    assert lt.available() == ""
    assert lt.open_in_new_window(["claude"], Path(".")) is False


def test_the_first_installed_terminal_wins(monkeypatch):
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(
        lt, "_which", lambda name: "/usr/bin/konsole" if name == "konsole" else None
    )
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
    assert mod._launch_in_window(project, "/engage --new --auto", "slug") is False
    assert "opening in this one instead" in capsys.readouterr().err


def test_a_terminal_that_exists_but_will_not_start_also_falls_back(tmp_path, monkeypatch, capsys):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "xterm")
    monkeypatch.setattr(lt, "open_in_new_window", lambda *a, **k: False)
    assert mod._launch_in_window(project, "/engage --new --auto", "slug") is False
    err = capsys.readouterr().err
    # The message names the terminal AND the command it could not start, because "could not
    # open a new window" told the reader nothing they could act on.
    assert "xterm could not start" in err and "claude" in err
    assert "launch_terminal --open" in err, "and points at the way to test it directly"


def test_the_wrapper_is_told_to_stand_down_only_when_a_window_opened(tmp_path, monkeypatch):
    """Exit 97 here means "already started", not "aborted". Getting it wrong in either
    direction is bad: too eager and the session starts twice, too shy and it starts in a
    window the human cannot see AND in this shell."""
    mod = _load("virt_team_launcher")
    # Explicit, because new_window is OFF by default since the Windows no-show (2026-08-25).
    # A test that relied on the default would have gone green for the wrong reason the day
    # the default changed - it went red instead, which is the behaviour worth keeping.
    project = _project(tmp_path, new_window=True)
    monkeypatch.chdir(project)
    (project / ".claude" / ".auto-pending.json").write_text(
        json.dumps({"slug": "alpha", "auto": True}), encoding="utf-8"
    )
    for name in (
        "_print_banner",
        "_check_plugin_cache_lag",
        "_print_project_defaults",
        "_prewarm_guard_interpreter",
        "_write_probe_cache",
        "_refresh_tool_cache",
        "_heal_stale_alias_once",
        "_clear_request_handoff",
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: "/engage --new --auto")

    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: True)
    assert mod.main() == mod._ABORT_EXIT_CODE

    # Both routes unavailable. Since 2026-08-25 an unattended run whose window fails
    # degrades to HEADLESS rather than in place, so this pins the property it always meant:
    # the wrapper stands down only when something actually started - not merely when a
    # launch was attempted.
    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: False)
    monkeypatch.setattr(mod, "_start_headless", lambda *a: False)
    assert mod.main() == 0, "nothing started, so the wrapper must launch in place"


def test_an_attended_run_gets_a_window_too(tmp_path, monkeypatch):
    """2026-08-25: it was unattended-only, on the reasoning that an attended run already has
    a human in the session. That ignored what the launcher had become - with the monitor and
    the workflow view living here, the TUI is worth keeping alive during ANY run, and it can
    only stay alive if the session did not replace it."""
    mod = _load("virt_team_launcher")
    # Explicit: the feature is opt-in now, so a test relying on the default would go green
    # for the wrong reason the day the default moves again - and it has moved three times.
    project = _project(tmp_path, new_window=True)
    monkeypatch.chdir(project)
    for name in (
        "_print_banner",
        "_check_plugin_cache_lag",
        "_print_project_defaults",
        "_prewarm_guard_interpreter",
        "_write_probe_cache",
        "_refresh_tool_cache",
        "_heal_stale_alias_once",
        "_clear_request_handoff",
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: "/engage --new --request-pending")
    called = []
    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: called.append(a) or True)
    assert mod.main() == mod._ABORT_EXIT_CODE, "a launched window means the wrapper stands down"
    assert called, "an attended run must also open in its own window"
    assert called[0][1] == "/engage --new --request-pending"


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
        json.dumps(
            {
                "status": "in_progress",
                "phase": "build",
                "auto": True,
                "auto_on_budget": "continue",
                "budget": {"engagement_usd": 35},
                "outstanding": [{"text": "QA pass"}],
                "engagement": {"slug": "alpha", "title": "Alpha work"},
            }
        ),
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


# --- the Windows failure that started nothing (live report 2026-08-25) ----------------------
#
# "the claude code session didnt start; on windows it was launched in powershell (virt-surv
# go) and with the workflow feature turned on it ran for several min with no new powershell
# launched or claude". Three separate defects, each tested below, and the third is the one
# that made the other two catastrophic instead of merely annoying.


def test_powershell_is_given_a_command_not_a_string(monkeypatch):
    """Without the call operator, "'claude' '/engage ...'" is a STRING EXPRESSION: PowerShell
    evaluates it, prints it, and runs nothing. Same invocation shape the virt-surv alias
    itself uses, because that is the one known to work."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "win32")
    monkeypatch.setattr(lt, "_which", lambda n: f"C:/{n}")
    argv = lt._windows_argv("powershell.exe", ["claude", "/engage --new --auto"], Path("C:/proj"))
    script = argv[-1]
    assert "& " in script, f"no call operator - PowerShell would print, not run: {script}"
    assert script.index("&") > script.index("Set-Location"), "cd first, then run"
    assert "'/engage --new --auto'" in script, "the decision must survive as one argument"
    assert "-NoExit" in argv, "a failing session must leave its error on screen, not flash shut"


def test_windows_gets_a_new_console_never_a_detached_process(monkeypatch, tmp_path):
    """DETACHED_PROCESS gives the child NO console, so powershell.exe starts with nowhere to
    draw and the user sees nothing at all. That is the invisible half of the live report."""
    source = (REPO_ROOT / "scripts" / "launch_terminal.py").read_text(encoding="utf-8")
    # Check what is USED, not what is mentioned - the reasoning above the code names the
    # flag it rejects, and a naive substring test flags its own explanation.
    used = [
        line
        for line in source.splitlines()
        if "creationflags" in line or "getattr(subprocess" in line
    ]
    assert any("CREATE_NEW_CONSOLE" in line for line in used), used
    assert not any("DETACHED_PROCESS" in line for line in used), (
        "a detached child has no window; that is not what 'another window' means on Windows"
    )


def test_a_spawner_that_dies_on_its_argv_is_not_reported_as_launched(monkeypatch, tmp_path):
    """The defect that made the others catastrophic. Popen succeeding proves only that the
    SPAWNER was found - not that a session started. Reporting success let the launcher tell
    the shell to stand down while nothing ran, so the user got neither window nor session."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "xterm")
    # The command must RESOLVE, or _shell_knows runs subprocess.run - which uses Popen as a
    # context manager and trips over the fake below. Found by running the suite in a clean
    # container, where `claude` is not on PATH; it passed here only because this box has it.
    monkeypatch.setattr(lt, "_resolvable", lambda program, terminal="": True)

    class _Dead:
        returncode = 1

        def wait(self, timeout=None):
            return 1

    monkeypatch.setattr(lt.subprocess, "Popen", lambda *a, **k: _Dead())
    assert lt.open_in_new_window(["claude", "/engage --new"], tmp_path) is False


def test_a_terminal_that_forks_and_exits_zero_still_counts_as_launched(monkeypatch, tmp_path):
    """wt.exe and `cmd start` hand off to their own window and exit 0 immediately. Treating
    that as failure would double-launch every session on Windows."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "wt.exe")
    monkeypatch.setattr(lt, "_resolvable", lambda program, terminal="": True)

    class _Forked:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(lt.subprocess, "Popen", lambda *a, **k: _Forked())
    assert lt.open_in_new_window(["claude", "/engage --new"], tmp_path) is True


def test_a_session_still_running_counts_as_launched(monkeypatch, tmp_path):
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "xterm")
    monkeypatch.setattr(lt, "_resolvable", lambda program, terminal="": True)

    class _Alive:
        returncode = None

        def wait(self, timeout=None):
            raise lt.subprocess.TimeoutExpired("x", timeout)

    monkeypatch.setattr(lt.subprocess, "Popen", lambda *a, **k: _Alive())
    assert lt.open_in_new_window(["claude", "/engage --new"], tmp_path) is True


def test_the_windowed_launch_uses_the_same_command_the_wrapper_would(tmp_path, monkeypatch):
    """Owner, 2026-08-25: "claude should be launched using the same method as virt surv go
    does". Anything else is a second way to start a session and a second way to get it
    wrong."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "xterm")
    seen = {}
    monkeypatch.setattr(
        lt, "open_in_new_window", lambda cmd, cwd: seen.update(cmd=cmd, cwd=cwd) or True
    )
    monkeypatch.setattr(mod, "_configured_launch_command", lambda: "cc --resume")
    try:
        import launcher_app

        monkeypatch.setattr(launcher_app, "monitor_screen", lambda *a, **k: None)
    except Exception:
        pass
    mod._launch_in_window(project, "/engage --new --auto", "alpha")
    assert seen["cmd"] == ["cc", "--resume", "/engage --new --auto"], (
        "the configured launch command must be word-split and used verbatim, as the wrapper "
        f"does - got {seen.get('cmd')}"
    )


def test_the_monitor_stops_saying_waiting_and_reports_a_no_show(tmp_path):
    """Several minutes of a patient "waiting" line while nothing ran is the report. A monitor
    that only ever reports patience is indistinguishable from one watching nothing."""
    source = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")
    body = source.split("def monitor_screen", 1)[1].split("\ndef ", 1)[0]
    assert "_PATIENCE" in body
    assert "Still no workspace after" in body, "it must eventually say so"
    assert "checking the other window" in body, "and offer the way out"


def test_the_monitor_waits_five_minutes_before_suggesting_a_fault(tmp_path):
    """2026-08-25, owner: "it can take a few mins for a workspace to be created in corp
    environment, don't prompt something may be wrong for 5 mins". On a locked-down corporate
    machine a cold start pays interpreter startup, a scanner on every file touched, and a
    network round trip before anything is written - 45 seconds is normal there.

    A warning that fires during normal operation is worse than none: the first false alarm
    teaches the reader to ignore the line, and the real one then goes unread."""
    source = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")
    body = source.split("def monitor_screen", 1)[1].split("\ndef ", 1)[0]
    patience = float(body.split("_PATIENCE = ", 1)[1].split("\n", 1)[0])
    assert patience >= 300.0, f"too impatient for a corporate machine: {patience}s"
    # And the interim must say the wait is expected rather than sitting mute.
    assert "normal" in body and "few minutes" in body


def test_an_unresolvable_command_is_never_reported_as_launched(tmp_path, monkeypatch):
    """Proven on WINTEST (PowerShell 5.1, 2026-08-25): waiting on the spawned process cannot
    answer this, because the terminal wrapper starts fine and -NoExit means it never exits -
    so a bogus executable reported success. The target is resolved BEFORE spawning now."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "xterm")
    # Patch the SHELL PROBE, not Popen: subprocess.run uses Popen as a context manager, so
    # replacing Popen wholesale breaks the very lookup under test.
    monkeypatch.setattr(lt, "_shell_knows", lambda program, terminal: False)
    called = []
    monkeypatch.setattr(lt.subprocess, "Popen", lambda *a, **k: called.append(a) or None)
    assert lt.open_in_new_window(["definitely-not-a-real-program-xyz"], tmp_path) is False
    assert called == [], "nothing should even be spawned for an unresolvable command"


def test_a_shell_alias_is_launchable_even_though_it_is_on_no_path(tmp_path, monkeypatch):
    """The live cause of "it opens in the same window" (2026-08-25). The user's launch
    command is `cc`, a PowerShell profile function - it is how they always start Claude, it
    is on no PATH, and a which()-based pre-check rejected it, so every run fell back to the
    same window. Verified on WINTEST: which('cc') is None while the shell resolves it."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "_which", lambda name: None)
    monkeypatch.setattr(lt, "_shell_knows", lambda program, terminal: program == "cc")
    assert lt._resolvable("cc", "powershell.exe") is True
    assert lt._resolvable("not-an-alias", "powershell.exe") is False


def test_a_probe_that_cannot_run_does_not_block_a_launch(tmp_path, monkeypatch):
    """A pre-flight that blocks a launch it merely could not VERIFY would recreate the bug
    it exists to prevent."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "_which", lambda name: None)

    def _boom(*a, **k):
        raise OSError("no shell here")

    monkeypatch.setattr(lt.subprocess, "run", _boom)
    assert lt._resolvable("cc", "powershell.exe") is True


def test_the_new_window_is_opt_in(tmp_path):
    """OFF by default (owner, 2026-08-25). The faults were each fixed and verified, but they
    were each invisible from Linux and each broke the one thing that must never break: a
    session actually starting. Opt-in until it has a boring week."""
    mod = _load("virt_team_launcher")
    assert mod._new_window_wanted(_project(tmp_path)) is False
    assert mod._new_window_wanted(_project(tmp_path, new_window=True)) is True


def _drive_main(mod, monkeypatch, project, decision):
    monkeypatch.chdir(project)
    for name in (
        "_print_banner",
        "_check_plugin_cache_lag",
        "_print_project_defaults",
        "_prewarm_guard_interpreter",
        "_write_probe_cache",
        "_refresh_tool_cache",
        "_heal_stale_alias_once",
        "_clear_request_handoff",
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: decision)
    return mod.main()


def test_every_reason_not_to_open_a_window_is_said_out_loud(tmp_path, monkeypatch, capsys):
    """2026-08-25: "it opens in the same window", and there was no way to tell which of three
    silent conditions declined. A control that quietly does nothing is the defect class this
    repo keeps meeting; the fix each time is to make it speak."""
    mod = _load("virt_team_launcher")

    # 1. the preference is off
    off = _project(tmp_path / "a", new_window=False)
    (off / ".claude" / ".auto-pending.json").write_text(json.dumps({"slug": "x"}), encoding="utf-8")
    assert _drive_main(mod, monkeypatch, off, "/engage --new --auto") == 0
    assert "new window off" in capsys.readouterr().err

    # 2. no terminal available
    ok = _project(tmp_path / "c", new_window=True)
    (ok / ".claude" / ".auto-pending.json").write_text(json.dumps({"slug": "x"}), encoding="utf-8")
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "")
    assert _drive_main(mod, monkeypatch, ok, "/engage --new --auto") == 0
    assert "no windowed terminal found" in capsys.readouterr().err


def test_the_running_engagement_is_found_from_the_active_marker(tmp_path):
    mod = _load("virt_team_launcher")
    state = _load("engagement_state")
    project = _project(tmp_path)
    assert mod._running_slug(project) == ""
    state.write_active(project, "alpha-run")
    assert mod._running_slug(project) == "alpha-run"


def test_an_unreadable_marker_is_treated_as_nothing_running(tmp_path):
    """Fail-open: the option simply is not offered, rather than the menu erroring."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    (project / ".active-engagement.json").write_text("{not json", encoding="utf-8")
    assert mod._running_slug(project) == ""


def test_watching_launches_nothing(tmp_path, monkeypatch):
    """The property that makes this safe to offer while work is in flight. A second session
    in one workspace is exactly what the resume path would have caused."""
    mod = _load("virt_team_launcher")
    state = _load("engagement_state")
    project = _project(tmp_path)
    state.write_active(project, "alpha-run")
    watched = []
    monkeypatch.setattr(mod, "_watch_after_launch", lambda p, s: watched.append(s))
    launched = []
    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: launched.append(a) or True)
    mod._watch_running_engagement(project)
    assert watched == ["alpha-run"]
    assert launched == [], "watching must never start a session"


def test_watching_with_nothing_running_does_nothing(tmp_path, monkeypatch):
    mod = _load("virt_team_launcher")
    project = _project(tmp_path)
    watched = []
    monkeypatch.setattr(mod, "_watch_after_launch", lambda p, s: watched.append(s))
    mod._watch_running_engagement(project)
    assert watched == []


def test_the_watch_option_returns_to_the_menu_rather_than_launching(tmp_path, monkeypatch):
    """Returning "__again__" is the whole point: the human came to look, not to start work."""
    mod = _load("virt_team_launcher")
    state = _load("engagement_state")
    project = _project(tmp_path)
    state.write_active(project, "alpha-run")
    monkeypatch.setattr(mod, "_watch_running_engagement", lambda p: None)
    decision = mod._decision_from_pick(("watch",), project, None, {}, [])
    assert decision == "__again__"


def test_every_tier_offers_the_watch_option():
    """The launcher's menu renderers drifted apart once before; a key that works in one tier
    and silently does nothing in another is how that started - and it happened AGAIN here.
    This was first written checking only virt_team_launcher.py, passed, and missed that the
    full-screen tier builds its own action list in launcher_app.py. A pty render caught it;
    the test could not, because it was looking in one file for a thing that lives in two.
    So: check BOTH files, and check the key bindings too, not just the labels."""
    launcher = (REPO_ROOT / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    app = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")

    # THREE TIERS, NOT FOUR (2026-08-31). The second prompt_toolkit picker was deleted:
    # it could only run when the prompt_toolkit full-screen menu had already failed while
    # prompt_toolkit was still usable, and it had begun to drift from the tiers either
    # side of it. Its watch row went with it, so this no longer looks for it.
    #
    # The plain tier's label and key still have to be here, and the Textual tier is
    # checked below through launcher_textual's shared action list.
    assert "[t]')} watch the running engagement" in launcher
    assert 'choice.lower() == "t"' in launcher
    # The DEFINITION, not the name: a comment stands where it was, explaining why, and a
    # check that trips over its own tombstone teaches the next person to delete the note.
    assert "def _pt_menu_round" not in launcher, "the deleted middle picker must not come back"
    # And no trace of the removed workflow screen anywhere in the menus.
    assert '(("workflow",)' not in launcher and '(("workflow",)' not in app

    # full-screen tiers: the action AND the keypress that reaches it. The Textual tier
    # builds its rows in launcher_textual._actions, which is a THIRD place this label
    # lives - the whole reason this test checks files rather than one file.
    textual = (REPO_ROOT / "scripts" / "launcher_textual.py").read_text(encoding="utf-8")
    assert '("watch",)' in textual, "the Textual tier must offer watch"
    assert '(("watch",)' in app, "the app tier must offer watch"
    keys = app.split("for key, ret in (", 1)[1].split("):", 1)[0]
    assert '("t", ("watch",))' in keys, "t must be bound in the app tier"


def test_the_transcript_reader_is_gone_not_dormant():
    """2026-08-25: "no transcript reader for unattended at all - the user can read the
    transcript themselves". It read Claude Code's INTERNAL file, which has no recorded cost,
    no engagement boundary, no view into a subagent's turns and no stability guarantee -
    every one of which showed in use.

    Deleted rather than left dormant: code kept in case it is useful rots into something
    nobody dares remove, and a disabled feature still ships, still needs maintaining, and
    still gets found by the next person. What replaces it is a supported source
    (docs/internal/plan-supported-monitoring-2026-08-25.md)."""
    scripts = REPO_ROOT / "scripts"
    for gone in ("workflow_trace.py", "render_workflow.py"):
        assert not (scripts / gone).exists(), f"{gone} came back"
    assert not (REPO_ROOT / "config" / "model-pricing.json").exists()
    app = (scripts / "launcher_app.py").read_text(encoding="utf-8")
    assert "def workflow_screen" not in app
    assert "import workflow_trace" not in app


# --- tmux is a window manager too (2026-08-25) ----------------------------------------------
#
# "If running tmux why not open in a tmux window" - asked after seeing "no windowed terminal
# found" on a box that was running tmux at the time. Exactly right: tmux needs no X display,
# works over ssh and mosh, and works in a container, which is every place the graphical tiers
# cannot go. Someone already in tmux wants the session in their tmux, not in a separate
# desktop window they then have to go and find.


def test_tmux_is_preferred_and_needs_no_display(monkeypatch):
    """It is checked BEFORE the display test, or a headless box inside tmux reports "no
    windowed terminal" while a perfectly good window manager runs in the same terminal."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,123,0")
    monkeypatch.setattr(lt, "_which", lambda name: f"/usr/bin/{name}")
    assert lt.available() == "tmux"


def test_tmux_wins_over_a_graphical_terminal(monkeypatch):
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,123,0")
    monkeypatch.setattr(lt, "_which", lambda name: f"/usr/bin/{name}")
    assert lt.available() == "tmux", "already in tmux: put it where they are looking"


def test_outside_tmux_the_variable_is_absent_so_the_tier_is_skipped(monkeypatch):
    """$TMUX is set by tmux in every pane and by nothing else, so its presence IS the test.
    Having the binary installed is not the same as running inside it."""
    lt = _load("launch_terminal")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(lt, "_which", lambda name: f"/usr/bin/{name}")
    assert lt._in_tmux() is False


def test_tmux_opens_a_window_in_the_existing_session(monkeypatch):
    """A new WINDOW, not a new session: the point is that it appears alongside what they are
    already looking at. The command follows as separate arguments, which tmux runs directly
    rather than through a shell - so nothing needs quoting."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "_which", lambda name: f"/usr/bin/{name}")
    argv = lt._posix_argv("tmux", ["claude", "/engage --new --auto"], Path("/tmp/proj"))
    assert argv[1] == "new-window"
    assert "-c" in argv and "/tmp/proj" in argv
    assert argv[-2:] == ["claude", "/engage --new --auto"], "one argument, unquoted, intact"
    assert "new-session" not in argv


def test_a_failing_tmux_call_is_reported_as_not_launched(monkeypatch, tmp_path):
    """tmux talks to its own server; if it cannot reach the session it must not be reported
    as a launch, or the caller stands down while nothing runs."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "tmux")
    monkeypatch.setattr(lt, "_resolvable", lambda program, terminal="": True)

    class _Failed:
        returncode = 1

    monkeypatch.setattr(lt.subprocess, "run", lambda *a, **k: _Failed())
    assert lt.open_in_new_window(["claude", "/engage"], tmp_path) is False


# --- an unattended run must never become unwatchable (2026-08-25) ---------------------------
#
# "It launched claude code in unattended mode and because no window manager it sat there in
# claude code - how can I monitor it if I can't go to the TUI, control it?" The window could
# not open, so it fell back IN PLACE: Claude Code took the terminal and the launcher went with
# it, taking the monitor. For an unattended run the monitor is the entire point.


def test_an_unattended_run_with_no_window_goes_headless_not_in_place(tmp_path, monkeypatch, capsys):
    """Headless is CLOSER to what was asked for than in-place. The human chose a separate
    window so the launcher would survive to show them the run; with no window, keeping the
    launcher is the part worth keeping. Nothing is lost - an unattended run answers no
    questions by definition, which is the only thing in-place would have offered."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path, new_window=True)
    (project / ".claude" / ".auto-pending.json").write_text(
        json.dumps({"slug": "alpha", "auto": True, "run_mode": "window"}), encoding="utf-8"
    )
    monkeypatch.chdir(project)
    for name in (
        "_print_banner",
        "_check_plugin_cache_lag",
        "_print_project_defaults",
        "_prewarm_guard_interpreter",
        "_write_probe_cache",
        "_refresh_tool_cache",
        "_heal_stale_alias_once",
        "_clear_request_handoff",
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: "/engage --new --auto")
    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: False)  # no window anywhere
    started = []
    monkeypatch.setattr(mod, "_start_headless", lambda p, d, pend: started.append(d) or True)

    assert mod.main() == mod._ABORT_EXIT_CODE
    assert started == ["/engage --new --auto"], "it must start headless rather than in place"
    assert "watch it here" in capsys.readouterr().err


def test_an_attended_run_with_no_window_still_falls_back_in_place(tmp_path, monkeypatch):
    """The degrade is for UNATTENDED runs only. An attended session in place is exactly
    right - there is a human in it, and nothing to monitor from outside."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path, new_window=True)
    monkeypatch.chdir(project)
    for name in (
        "_print_banner",
        "_check_plugin_cache_lag",
        "_print_project_defaults",
        "_prewarm_guard_interpreter",
        "_write_probe_cache",
        "_refresh_tool_cache",
        "_heal_stale_alias_once",
        "_clear_request_handoff",
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: "/engage --new --request-pending")
    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: False)
    started = []
    monkeypatch.setattr(mod, "_start_headless", lambda p, d, pend: started.append(d) or True)

    assert mod.main() == 0, "the wrapper launches it in place"
    assert started == [], "an attended run must not be forced headless"


# --- Windows Terminal hosts a shell; it does not replace one (2026-08-26) ---------------


def test_wt_runs_the_command_through_a_shell_not_as_a_bare_process(monkeypatch):
    """The corp-box failure. `wt.exe -d <dir> claude /engage` asks Windows Terminal to spawn
    `claude` itself: no profile loaded, no alias resolved, and whatever PATH wt inherited.
    On a machine where the launch command is a PowerShell alias - or an npm shim that group
    policy keeps off the bare PATH - the window opens and instantly fails, while the
    launcher has already stood down. The command must reach a SHELL."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "win32")
    monkeypatch.setattr(lt, "_which", lambda n: f"C:/{n}")
    monkeypatch.setattr(lt, "_invoking_shell", lambda: "pwsh.exe")
    argv = lt._windows_argv("wt.exe", ["claude", "/engage --new"], Path("C:/proj"))
    assert argv[0].endswith("wt.exe")
    assert "-d" in argv and "C:/proj" in argv, "the window still opens in the project"
    joined = " ".join(argv)
    assert "pwsh.exe" in joined, "a shell must sit between wt and the command"
    assert "-Command" in argv, "the shell must be told to RUN something"
    assert "& " in joined, "PowerShell needs the call operator or it prints the string"
    assert argv.index("-d") < argv.index("-Command"), "wt's own flags come first"


def test_wt_hosts_the_shell_the_launcher_was_started_from(monkeypatch):
    """Given a choice, spawn a window of the shell already resolving the user's command -
    not the first one on the box. Detection failing falls back to preference order, which
    is the pre-existing behaviour and never worse than it."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "win32")
    monkeypatch.setattr(lt, "_which", lambda n: f"C:/{n}")
    monkeypatch.setattr(lt, "_invoking_shell", lambda: "powershell.exe")
    assert lt._windows_shell() == "powershell.exe", "detected shell wins"
    monkeypatch.setattr(lt, "_invoking_shell", lambda: "")
    assert lt._windows_shell() == "pwsh.exe", "undetected falls back to preference order"


def test_nothing_hands_wt_an_unescaped_semicolon(monkeypatch):
    """`;` delimits subcommands on wt.exe's OWN command line, so an unescaped one would
    split the launch into two wt commands and run half of it."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "win32")
    monkeypatch.setattr(lt, "_which", lambda n: f"C:/{n}")
    monkeypatch.setattr(lt, "_invoking_shell", lambda: "pwsh.exe")
    argv = lt._windows_argv("wt.exe", ["claude", "/engage; whoami"], Path("C:/proj"))
    for part in argv:
        for hit in range(len(part)):
            if part[hit] == ";":
                assert hit and part[hit - 1] == "\\", f"bare ; reaches wt: {part!r}"


def test_the_alias_check_is_not_skipped_under_wt(monkeypatch):
    """Both safety nets missed this path: the pre-check answered True unconditionally when
    the terminal was wt.exe, and wt forks its own window and exits 0, so the post-spawn
    check could not tell either. The pre-check must ask the shell wt will host."""
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt.sys, "platform", "win32")
    monkeypatch.setattr(lt, "_which", lambda n: None)  # not on PATH: only the shell knows
    monkeypatch.setattr(lt, "_windows_shell", lambda: "pwsh.exe")
    asked = {}

    class _Probe:
        returncode = 1

    def _run(argv, **kwargs):
        asked["argv"] = argv
        return _Probe()

    monkeypatch.setattr(lt.subprocess, "run", _run)
    assert lt._shell_knows("cc", "wt.exe") is False, "an unresolvable command must be caught"
    assert "pwsh.exe" in " ".join(asked["argv"]), "it asked the shell wt would host"
