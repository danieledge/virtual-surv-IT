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
    for name in ("_print_banner", "_check_plugin_cache_lag", "_print_project_defaults",
                 "_prewarm_guard_interpreter", "_write_probe_cache", "_refresh_tool_cache",
                 "_heal_stale_alias_once", "_clear_request_handoff"):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: "/engage --new --auto")

    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: True)
    assert mod.main() == mod._ABORT_EXIT_CODE

    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: False)
    assert mod.main() == 0, "a failed window must let the wrapper launch in place"


def test_an_attended_run_gets_a_window_too(tmp_path, monkeypatch):
    """2026-08-25: it was unattended-only, on the reasoning that an attended run already has
    a human in the session. That ignored what the launcher had become - with the monitor and
    the workflow view living here, the TUI is worth keeping alive during ANY run, and it can
    only stay alive if the session did not replace it."""
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
    used = [line for line in source.splitlines()
            if "creationflags" in line or "getattr(subprocess" in line]
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

    class _Forked:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(lt.subprocess, "Popen", lambda *a, **k: _Forked())
    assert lt.open_in_new_window(["claude", "/engage --new"], tmp_path) is True


def test_a_session_still_running_counts_as_launched(monkeypatch, tmp_path):
    lt = _load("launch_terminal")
    monkeypatch.setattr(lt, "available", lambda: "xterm")

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
    monkeypatch.setattr(lt, "open_in_new_window",
                        lambda cmd, cwd: seen.update(cmd=cmd, cwd=cwd) or True)
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
    assert "may not" in body and "started" in body, "it must name the likely cause"
    assert "launch" in body, "and offer the way out"


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


def test_the_new_window_default_is_on_now_it_is_verified(tmp_path):
    """On, off, and on again - the last move only after being proven on the platform that
    broke it: powershell.exe found, the spawned command executes, and `claude --version`
    runs inside the new console and exits 0."""
    mod = _load("virt_team_launcher")
    assert mod._new_window_wanted(_project(tmp_path)) is True
    assert mod._new_window_wanted(_project(tmp_path, new_window=False)) is False


def _drive_main(mod, monkeypatch, project, decision):
    monkeypatch.chdir(project)
    for name in ("_print_banner", "_check_plugin_cache_lag", "_print_project_defaults",
                 "_prewarm_guard_interpreter", "_write_probe_cache", "_refresh_tool_cache",
                 "_heal_stale_alias_once", "_clear_request_handoff"):
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


def test_a_plain_launch_also_opens_in_a_window(tmp_path, monkeypatch):
    """Pressing Enter with nothing pre-seeded is still a session, and still worth watching.
    Only the decision string differs - and it must stay OFF stdout when empty, because a
    bare newline on the decision channel is captured by the shell."""
    mod = _load("virt_team_launcher")
    project = _project(tmp_path, new_window=True)
    seen = []
    monkeypatch.setattr(mod, "_launch_in_window", lambda *a: seen.append(a) or True)
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _drive_main(mod, monkeypatch, project, "")
    assert rc == mod._ABORT_EXIT_CODE
    assert seen and seen[0][1] == ""
    assert out.getvalue() == "", "an empty decision must put nothing on stdout"
