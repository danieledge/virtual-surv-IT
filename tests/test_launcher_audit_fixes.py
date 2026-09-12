"""Regressions for the 2026-09-12 launcher/installer audit (lane-launcher.md).

One test per behavioural finding, named by what the fix protects rather than by the finding
id - the ids are in the docstrings so the report and the test can be matched up, but a test
called test_L_14 tells a future reader nothing.

Everything here drives the real functions. Where a finding is about a shape rather than a
behaviour (a glyph table, a subprocess keyword) that is said so in the test itself.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _extra in (REPO_ROOT, REPO_ROOT / "scripts", REPO_ROOT / "vendor"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _launcher():
    return _load("virt_team_launcher", REPO_ROOT / "scripts" / "virt_team_launcher.py")


def _installer():
    import install_helper

    return install_helper


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    return tmp_path


# --------------------------------------------------------------- the consent gate (L-1)


def test_a_failed_provenance_write_leaves_the_gate_SHUT(tmp_path, monkeypatch):
    """L-1. The marker used to be written first, so a sidecar that failed returned
    (False, reason) - the caller printing "the run continues WITHOUT execution" - while the
    marker it had already written sat on disk authorising everything, with no provenance,
    no expiry and no scope."""
    mod = _launcher()
    project = _project(tmp_path)
    fs = mod._fsutil()
    real = fs.atomic_write_json

    def _fail_sidecar(path, obj, **kw):
        if str(path).endswith(mod._AUTO_PROVENANCE):
            raise OSError("read-only")
        return real(path, obj, **kw)

    monkeypatch.setattr(fs, "atomic_write_json", _fail_sidecar)
    ok, reason = mod.grant_execution_consent(project, "alpha")
    assert ok is False and reason
    assert not mod._consent_marker_path(project).exists(), "the gate must be SHUT"


def test_a_failed_marker_write_leaves_no_orphan_sidecar(tmp_path, monkeypatch):
    """L-1, the other direction. A sidecar with no marker would make the NEXT hand-made
    marker look like one this launcher granted, and therefore its to expire."""
    mod = _launcher()
    project = _project(tmp_path)
    fs = mod._fsutil()

    def _fail_marker(path, text, **kw):
        raise OSError("locked")

    monkeypatch.setattr(fs, "atomic_write_text", _fail_marker)
    ok, reason = mod.grant_execution_consent(project, "alpha")
    assert ok is False and reason
    assert not mod._consent_marker_path(project).exists()
    assert not mod._auto_provenance_path(project).exists()


def test_a_granted_gate_carries_provenance_expiry_and_scope(tmp_path):
    """The success path still has all three properties the docstring calls non-optional."""
    mod = _launcher()
    project = _project(tmp_path)
    ok, reason = mod.grant_execution_consent(project, "spoofing-review")
    assert (ok, reason) == (True, "")
    body = mod._consent_marker_path(project).read_text(encoding="utf-8")
    assert mod._GRANT_SIGNATURE in body
    side = json.loads(mod._auto_provenance_path(project).read_text(encoding="utf-8"))
    assert side["engagement"] == "spoofing-review"
    assert side["expires_at"] > side["granted_at"]


# ------------------------------------------------- a hand-made gate nobody closes (H-6)


def _handmade_marker(mod, project: Path, age_days: int) -> Path:
    import time

    marker = mod._consent_marker_path(project)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    old = time.time() - age_days * 86400
    os.utime(marker, (old, old))
    return marker


def test_a_long_open_handmade_gate_is_reported(tmp_path, capsys):
    """H-6/G-4. The marker in the audited checkout had been open since 2026-07-06 - two
    months of standing authorisation for every session, with nothing saying so."""
    mod = _launcher()
    project = _project(tmp_path)
    _handmade_marker(mod, project, 40)
    assert mod.stale_handmade_consent(project) >= 40
    assert mod.report_stale_handmade_consent(project) is False  # no tty: warn, never act
    err = capsys.readouterr().err
    assert "CODE EXECUTION HAS BEEN AUTHORISED" in err
    assert mod._consent_marker_path(project).exists(), "never removed without being asked"


def test_a_young_or_launcher_granted_gate_is_not_reported(tmp_path):
    """Only the unexpiring hand-made kind. A young marker is ordinary, and one this
    launcher granted has its own expiry path."""
    mod = _launcher()
    project = _project(tmp_path)
    _handmade_marker(mod, project, 1)
    assert mod.stale_handmade_consent(project) == 0
    mod.grant_execution_consent(project, "alpha")
    assert mod.stale_handmade_consent(project) == 0


def test_the_offer_to_close_it_is_answered_by_the_human(tmp_path, monkeypatch, capsys):
    """Offered, never done silently: deleting someone else's marker without asking is the
    same class of surprise as leaving it open, in the other direction."""
    mod = _launcher()
    project = _project(tmp_path)
    _handmade_marker(mod, project, 30)

    class _Tty:
        @staticmethod
        def isatty():
            return True

    monkeypatch.setattr(mod.sys, "stdin", _Tty)
    monkeypatch.setattr(mod.sys, "stderr", sys.stderr)
    monkeypatch.setattr(mod.sys.stderr, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert mod.report_stale_handmade_consent(project) is False
    assert mod._consent_marker_path(project).exists()

    monkeypatch.setattr("builtins.input", lambda: "y")
    assert mod.report_stale_handmade_consent(project) is True
    assert not mod._consent_marker_path(project).exists()
    assert "closed" in capsys.readouterr().err


# ------------------------------------------------------ crashes that used to be silent


def test_every_prompt_toolkit_screen_reports_its_own_crash(monkeypatch):
    """L-2. _report_screen_crash reached one of the thirteen screens; the rest returned
    their sentinel with nothing written to the crash log and nothing printed."""
    app = _load("launcher_app", REPO_ROOT / "scripts" / "launcher_app.py")
    seen = []
    monkeypatch.setattr(app, "_report_screen_crash", lambda mod, where, exc: seen.append(where))

    def _boom(*a, **k):
        raise RuntimeError("the driver fell over")

    monkeypatch.setattr(app, "screen", _boom)
    assert app._draw(object(), "a screen", title="t") is False
    assert seen == ["a screen"], "a crashed screen must name itself"


def test_the_settings_screen_does_not_report_a_crash_as_a_finished_edit(monkeypatch):
    """L-3. Its exception handler returned the partial `changed` flag - the same value the
    success path returns - so a crash mid-edit was indistinguishable from someone finishing
    one, and the session recorded the project as configured."""
    app = _load("launcher_app", REPO_ROOT / "scripts" / "launcher_app.py")
    source = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")
    body = source.split("def settings_screen", 1)[1].split("\ndef ", 1)[0]
    assert "return changed[0]" in body, "the success path still answers with it"
    assert body.count("return changed[0]") == 1, "the crash path must not answer with it too"
    assert "_draw(" in body
    assert callable(app.settings_screen)


def test_the_tier_dispatcher_records_what_it_swallows(monkeypatch):
    """L-8. _auto_run_decision tells the human to see "the crash log above" when the
    dispatcher returns None, and the dispatcher wrote nothing to it."""
    mod = _launcher()
    seen = []
    monkeypatch.setattr(mod, "_report_crash", lambda where, exc=None: seen.append(where))

    class _Boom:
        APPS_RUN = 0

        @staticmethod
        def some_screen(*a, **k):
            raise RuntimeError("no driver")

    monkeypatch.setitem(sys.modules, "launcher_textual", _Boom)
    monkeypatch.setitem(sys.modules, "launcher_app", _Boom)
    assert mod._tiered_screen("some_screen") is None
    assert seen, "a tier that raises must be recorded"
    assert all("some_screen" in where for where in seen)


def test_a_missing_window_module_is_never_a_silent_in_place_launch(tmp_path, monkeypatch, capsys):
    """L-12. The docstring rules out a silent no-op - "the human has already committed to a
    run by this point" - and every other `return False` prints. The import guard did not."""
    mod = _launcher()
    monkeypatch.setattr(mod, "_report_crash", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "launch_terminal", None)
    assert mod._launch_in_window(tmp_path, "/engage --new") is False
    assert "windowed-launch module could not load" in capsys.readouterr().err


def test_a_failed_session_id_is_not_swallowed(tmp_path, monkeypatch, capsys):
    """L-13. An empty id means the pack and the transcript can only be correlated by hand -
    the audit trail the whole unattended flow exists to produce, quietly incomplete."""
    mod = _launcher()
    project = _project(tmp_path)
    seen = []
    monkeypatch.setattr(mod, "_report_crash", lambda where, exc=None: seen.append(where))
    monkeypatch.setattr(mod, "_hold_for_reader", lambda: None)
    monkeypatch.setattr(
        mod,
        "_tiered_screen",
        lambda *a, **k: {"run_mode": "headless", "data_attested": True, "on_budget": "park"},
    )

    class _NoId:
        @staticmethod
        def new_session_id():
            raise RuntimeError("no uuid here")

    monkeypatch.setitem(sys.modules, "headless_run", _NoId)
    mod._auto_run_decision(project, "SURV-1")
    assert any("session id" in where for where in seen)
    assert "correlated by hand" in capsys.readouterr().err


def test_a_headless_start_that_raises_anything_falls_back(tmp_path, monkeypatch, capsys):
    """L-14. It caught OSError and ValueError only, so a TypeError or KeyError from a
    malformed .auto-pending.json escaped into the fail-open crash path - and the wrapper
    then started a plain ATTENDED session."""
    mod = _launcher()
    project = _project(tmp_path)
    monkeypatch.setattr(mod, "_report_crash", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_configured_launch_command", lambda: "claude")

    class _Boom:
        @staticmethod
        def start(*a, **k):
            raise TypeError("malformed handoff")

    monkeypatch.setitem(sys.modules, "headless_run", _Boom)
    pending = {"hard_cap_usd": 10, "slug": "alpha", "session_id": "s"}
    assert mod._start_headless(project, "/engage --new --auto", pending) is False
    assert "could not start headless" in capsys.readouterr().err


# -------------------------------------------------------------- state files (L-15/L-16)


def test_the_file_that_arms_an_unattended_run_is_written_atomically(tmp_path, monkeypatch):
    """L-15. Truncated JSON here means engagement_state cannot consume it, `auto` stays
    unset and every AUTO-* DoD gate skips - the 2026-08-21 C1 failure this file exists to
    prevent."""
    mod = _launcher()
    project = _project(tmp_path)
    written = []
    fs = mod._fsutil()
    real = fs.atomic_write_json
    monkeypatch.setattr(
        fs, "atomic_write_json", lambda p, o, **k: written.append(Path(p).name) or real(p, o, **k)
    )
    monkeypatch.setattr(mod, "_hold_for_reader", lambda: None)
    monkeypatch.setattr(
        mod,
        "_tiered_screen",
        lambda *a, **k: {"run_mode": "window", "data_attested": True, "on_budget": "park"},
    )
    mod._auto_run_decision(project, "SURV-2")
    assert ".auto-pending.json" in written
    payload = json.loads((project / ".claude" / ".auto-pending.json").read_text(encoding="utf-8"))
    assert payload["auto"] is True and payload["slug"] == "SURV-2"


def test_the_machine_config_survives_a_byte_order_mark(tmp_path, monkeypatch):
    """L-16. The launcher read it as utf-8 while install_helper.load_config and the heal
    both read it as utf-8-sig, so a BOM'd config silently reset recent_projects on every
    go while the other two readers were perfectly happy with it."""
    mod = _launcher()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    path = mod._installer_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\ufeff" + json.dumps({"recent_projects": ["/keep/me"], "repo_path": "/x"}),
        encoding="utf-8",
    )
    mod._remember_project(tmp_path)
    after = json.loads(path.read_text(encoding="utf-8-sig"))
    assert "/keep/me" in after["recent_projects"], "the existing list must survive"
    assert after["repo_path"] == "/x", "and so must the key that finds scripts/"


def test_the_machine_config_is_replaced_whole(tmp_path, monkeypatch):
    """L-16. install_helper.save_config has always been temp-file-plus-replace; the
    launcher did a plain write_text on the same file from two places."""
    mod = _launcher()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    staged = []
    fs = mod._fsutil()
    real = fs.atomic_write_json
    monkeypatch.setattr(
        fs, "atomic_write_json", lambda p, o, **k: staged.append(Path(p).name) or real(p, o, **k)
    )
    mod._remember_project(tmp_path)
    assert staged == ["installer.json"]


# ------------------------------------------------------ the process boundary (L-4, L-5)


def test_a_crash_after_arming_disarms_and_launches_nothing(tmp_path):
    """L-4. The wrapper launches on anything but 97, so exiting 1 from a crash started a
    plain attended session - with .auto-pending.json written and the execution gate open.
    An attended session inheriting an unattended run's consent is the worst combination
    this launcher can produce."""
    mod = _launcher()
    project = _project(tmp_path)
    (project / ".claude" / ".auto-pending.json").write_text("{}", encoding="utf-8")
    mod._consent_marker_path(project).write_text("x", encoding="utf-8")
    assert mod._crash_exit_code(project) == mod._ABORT_EXIT_CODE
    assert not (project / ".claude" / ".auto-pending.json").exists()
    assert not mod._consent_marker_path(project).exists()


def test_a_crash_with_nothing_armed_still_fails_open(tmp_path):
    """The other half: a crash in the menu must not cost someone a session. Exit 1, not 0 -
    0 said "this succeeded", which was a lie to any caller checking the status."""
    mod = _launcher()
    assert mod._crash_exit_code(_project(tmp_path)) == 1


def test_ctrl_c_at_the_process_boundary_launches_nothing(tmp_path, monkeypatch):
    """L-5. KeyboardInterrupt was handled at nine input() sites and not at __main__, so an
    interrupt during any pre-launch probe exited 130 - and 130 is not 97, so the wrapper
    started the session the human had just interrupted."""
    import runpy
    import types

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    config = tmp_path / "cfg" / "virt-surv-it" / "installer.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    # Pre-stamped so the alias heal returns immediately rather than exec'ing the installer.
    mod = _launcher()
    config.write_text(
        json.dumps({"alias_heal_checked": mod._EXPECTED_ALIAS_VERSION}), encoding="utf-8"
    )

    def _interrupted(_project_dir):
        raise KeyboardInterrupt

    fake = types.ModuleType("preflight")
    fake.preflight = _interrupted
    monkeypatch.setitem(sys.modules, "preflight", fake)
    monkeypatch.chdir(_project(tmp_path))
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(REPO_ROOT / "scripts" / "virt_team_launcher.py"), run_name="__main__")
    assert caught.value.code == mod._ABORT_EXIT_CODE


# ------------------------------------------------- the plain tier's [n] parity (L-6/L-7)


def test_the_plain_tier_asks_for_a_request_and_offers_unattended(tmp_path, monkeypatch, capsys):
    """L-7. [n] returned a bare `--new` and said nothing, so a human on a console where no
    full-screen tier can draw - the locked-down box this subsystem exists for - never saw
    the request composer and was never offered an unattended run."""
    mod = _launcher()
    project = _project(tmp_path)
    monkeypatch.setattr(mod, "_engage_command", lambda p: "/engage")
    monkeypatch.setattr(mod, "_auto_offered", lambda p: True)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True, raising=False)
    answers = iter(["tune the spoofing thresholds", "n"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    decision = mod._new_decision_plain(project)
    assert decision.startswith("/engage --new")
    assert "--request-pending" in decision, "what was typed must reach the session"
    assert "Run this unattended" in capsys.readouterr().err


def test_the_plain_tier_routes_an_unattended_yes_to_the_pre_flight(tmp_path, monkeypatch):
    """The gate itself has no plain rendering by design, so [n] hands off to the same
    _auto_run_decision [j] does rather than collecting consent at a bare prompt."""
    mod = _launcher()
    project = _project(tmp_path)
    seen = []
    monkeypatch.setattr(mod, "_auto_offered", lambda p: True)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(
        mod,
        "_auto_run_decision",
        lambda p, ref, request_text="": seen.append(request_text) or "/engage --new --auto",
    )
    answers = iter(["review the comms lexicon", "y"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert mod._new_decision_plain(project) == "/engage --new --auto"
    assert seen == ["review the comms lexicon"]


def test_a_pipe_still_gets_the_plain_new_command(tmp_path, monkeypatch):
    """No tty means no prompt: automation that never sees a menu keeps behaving as it
    always has."""
    mod = _launcher()
    monkeypatch.setattr(mod, "_engage_command", lambda p: "/engage")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False, raising=False)
    assert mod._new_decision_plain(_project(tmp_path)) == "/engage --new"


def test_the_request_composer_goes_through_the_one_dispatcher(tmp_path, monkeypatch):
    """L-6. _new_decision hand-rolled its own two-tier fall-through and was one of the two
    copies missing the APPS_RUN fix, so a Textual composer that RAN and returned None put
    the prompt_toolkit composer on top of the screen just dismissed."""
    mod = _launcher()
    calls = []
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(mod, "_engage_command", lambda p: "/engage")
    monkeypatch.setattr(
        mod, "_tiered_screen", lambda name, *a, **k: calls.append(name) or "__request_skipped__"
    )
    mod._new_decision(_project(tmp_path))
    assert calls == ["request_screen"]


# ---------------------------------------------------------------- subprocess decoding


def test_no_capture_in_the_launcher_decodes_with_the_console_codepage():
    """L-9. A bare text=True decodes with the Windows console code page, and cp1252 has
    undefined bytes - git output carrying one raises inside subprocess's reader thread.
    install_helper.run_cmd was fixed for exactly that; these nine calls were not."""
    for name in ("scripts/virt_team_launcher.py", "scripts/preflight.py"):
        source = (REPO_ROOT / name).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert stripped != "text=True,", f"{name}: a bare text=True is back"


# ----------------------------------------------------------------- windows handles (L-17)


def test_the_console_rebind_can_be_undone(monkeypatch):
    """L-17. SetStdHandle(STD_OUTPUT_HANDLE, CONOUT$) was permanent for the life of the
    process and the handle was never closed, so every child spawned afterwards inherited
    the console rather than the alias capture pipe."""
    mod = _launcher()
    monkeypatch.setattr(mod, "_WIN_CONOUT_BOUND", True)
    monkeypatch.setattr(mod, "_WIN_CONOUT_PREVIOUS", 1234)
    monkeypatch.setattr(mod, "_WIN_CONOUT_HANDLE", 5678)
    mod._win_release_conout()  # no ctypes.windll off Windows: it must still reset the cache
    assert mod._WIN_CONOUT_BOUND is None
    assert mod._WIN_CONOUT_PREVIOUS is None and mod._WIN_CONOUT_HANDLE is None


def test_nothing_is_spawned_while_the_console_is_still_rebound():
    """The release has to happen BEFORE the spawn, or the child inherits the wrong
    handles - which is the half of L-17 that a restore alone would not fix."""
    source = (REPO_ROOT / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    for spawner in ("launch_terminal.open_in_new_window(", "headless_run.start("):
        before = source.split(spawner, 1)[0]
        assert "_win_release_conout()" in before[-1200:], f"{spawner} spawns while rebound"


# -------------------------------------------------------------------- window quoting


def test_tmux_is_handed_a_posix_path():
    """The tmux argv test failed on the Windows CI leg because str(Path("/tmp/proj"))
    renders backslashes there, which tmux cannot open. as_posix is identical on POSIX."""
    lt = _load("launch_terminal", REPO_ROOT / "scripts" / "launch_terminal.py")
    argv = lt._posix_argv("tmux", ["claude", "/engage"], Path("/tmp/proj"))
    assert "/tmp/proj" in argv and "\\" not in "".join(argv)


def test_applescript_quoting_cannot_end_the_literal_early():
    """L-18. _quote is POSIX single-quoting and the result was interpolated into an
    AppleScript DOUBLE-quoted literal, so a quote or backslash in a path ended it early -
    at best a confusing osascript error, at worst arbitrary AppleScript after it."""
    lt = _load("launch_terminal", REPO_ROOT / "scripts" / "launch_terminal.py")
    hostile = 'a"b\\c'
    escaped = lt._applescript_quote(hostile)
    assert '\\"' in escaped and "\\\\" in escaped
    # Rebuilt as AppleScript would read it: nothing terminates the literal.
    assert escaped.count('"') == escaped.count('\\"')


def test_cmd_start_escapes_its_own_metacharacters():
    """L-19. The cmd.exe tier concatenated the argv raw after `start`, so cmd re-parsed the
    tail under its own rules. The two tiers above it each got escaping work after a live
    failure; this one - the most locked-down target - got none."""
    lt = _load("launch_terminal", REPO_ROOT / "scripts" / "launch_terminal.py")
    assert lt._cmd_escape(["a&b", "c|d", "e>f"]) == ["a^&b", "c^|d", "e^>f"]
    argv = lt._windows_argv("cmd.exe", ["claude", "/engage & whoami"], Path("C:/proj"))
    assert "start" in argv
    assert any("^&" in part for part in argv), "the metacharacter must be escaped"


# ---------------------------------------------------------------- installer findings


def test_settings_backups_do_not_accumulate_without_bound(tmp_path):
    """L-20. The same dated-backup block was pasted at three writers and nothing ever
    pruned; .gitignore records what that cost - "a clone went dirty from files the USER
    never wrote and the next update refused to run"."""
    ih = _installer()
    target = tmp_path / "settings.json"
    target.write_text("{}", encoding="utf-8")
    for _ in range(ih._SETTINGS_BACKUPS_KEPT + 4):
        assert ih._backup_settings(target) is not None
    kept = list(tmp_path.glob("settings.json.bak-*"))
    assert len(kept) == ih._SETTINGS_BACKUPS_KEPT


def test_a_backup_carries_the_source_files_mode(tmp_path):
    """The backups hold the project's full settings.json, env block included. They were
    written under the ambient umask rather than with the mode the original had."""
    ih = _installer()
    if os.name == "nt":
        pytest.skip("POSIX modes only")
    target = tmp_path / "settings.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o600)
    backup = ih._backup_settings(target)
    assert backup is not None
    assert backup.stat().st_mode & 0o777 == 0o600


def test_two_processes_do_not_share_one_staging_file(tmp_path, monkeypatch):
    """L-30. _atomic_write_text used a fixed `<name>.tmp` sibling while save_config twenty
    lines above already used a pid-suffixed one, so a menu session and a `virt-surv
    configure` in another terminal could interleave writes to the same staging file."""
    ih = _installer()
    target = tmp_path / "settings.json"
    staged = []
    real_replace = os.replace

    def _watch(src, dst):
        staged.append(Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(ih.os, "replace", _watch)
    ih._atomic_write_text(target, "{}\n")
    assert staged and str(os.getpid()) in staged[0]
    assert target.read_text(encoding="utf-8") == "{}\n"


def test_the_banner_gate_counts_either_tier(monkeypatch):
    """L-22. It probed installer_app and prompt_toolkit alone while the menus try Textual
    first, so on a box with Textual and no prompt_toolkit the banner printed and was then
    covered by a Textual alternate screen - the artefact the gate exists to prevent."""
    ih = _installer()
    monkeypatch.delenv("VIRT_SURV_NO_APP", raising=False)
    monkeypatch.setenv("VIRT_SURV_FORCE_PTK", "1")
    monkeypatch.setattr(ih, "_textual_tier_available", lambda: True)
    monkeypatch.setattr(ih, "_ptk_tier_available", lambda: False)
    assert ih.app_tier_available() is True
    monkeypatch.setattr(ih, "_textual_tier_available", lambda: False)
    monkeypatch.setattr(ih, "_ptk_tier_available", lambda: True)
    assert ih.app_tier_available() is True
    monkeypatch.setattr(ih, "_ptk_tier_available", lambda: False)
    assert ih.app_tier_available() is False


def test_a_relocated_installer_cleans_up_after_itself():
    """L-11. Nothing removed the temp directory - not the parent, which exits, and not the
    child, which does not know the path - so every interactive run from inside a clone left
    another ~537 KB copy behind."""
    source = (REPO_ROOT / "install_helper.py").read_text(encoding="utf-8")
    body = source.split("def _relocate_if_running_inside_target_repo", 1)[1].split("\ndef ", 1)[0]
    assert "atexit.register(shutil.rmtree" in body
    assert body.index("atexit.register") < body.index("sys.exit(proc.returncode)")


def test_a_failed_launch_is_explained_rather_than_traced(capsys):
    """L-34. shutil.which was checked and os.execvp was then called unguarded: between the
    two the binary can be removed or lose its executable bit, and the result was an OSError
    traceback out of a menu command that had already printed "Launching:"."""
    ih = _installer()
    rc = ih._launch_failed(ih.Style(False), ["claude", "/engage"], OSError("gone"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "could not start 'claude'" in out and "claude /engage" in out


# ------------------------------------------------------------------ glyphs and chrome


def test_the_textual_widgets_degrade_on_a_cp1252_console(monkeypatch):
    """L-23. This file called _can_encode twice and emitted the mark, the bars, the rules,
    the radio buttons and every footer arrow unguarded - against a stated constraint that
    STRUCTURE stays pure ASCII because corporate consoles decode as cp1252."""
    import launcher_tiers

    assert launcher_tiers._console_can_encode("\u2588") in (True, False)

    class _Cp1252:
        encoding = "cp1252"

    monkeypatch.setattr(launcher_tiers.sys, "stderr", _Cp1252)
    monkeypatch.setattr(launcher_tiers.sys, "__stdout__", _Cp1252)
    assert launcher_tiers._console_can_encode("\u2588\u2502\u2191") is False

    class _Utf8:
        encoding = "utf-8"

    monkeypatch.setattr(launcher_tiers.sys, "stderr", _Utf8)
    assert launcher_tiers._console_can_encode("\u2588\u2502\u2191") is True


def test_the_glyph_table_is_resolved_once_not_per_screen():
    """One table, the way tui_chrome.glyphs does it - so a new screen cannot forget to
    ask."""
    import launcher_tiers

    for name in ("_BLOCK", "_HLINE", "_VLINE", "_ON", "_OFF", "_UPDOWN", "_DOT", "_TICK"):
        assert isinstance(getattr(launcher_tiers, name), str)
    assert len(launcher_tiers.EIGHTHS) == 9


def test_the_chrome_falls_back_to_plain_text_when_stderr_is_not_a_console():
    """The Windows CI failure. prompt_toolkit's create_output only tests isatty() on the
    POSIX branch; on win32 it goes straight to Win32Output, which raises when the stream is
    captured - and every screen's `except` read that as "this tier cannot draw"."""
    pytest.importorskip("prompt_toolkit")
    import io

    import tui_chrome
    from prompt_toolkit.output.plain_text import PlainTextOutput

    saved = sys.stderr
    sys.stderr = io.StringIO()
    try:
        assert isinstance(tui_chrome.default_output(), PlainTextOutput)
    finally:
        sys.stderr = saved


def test_one_pause_helper_serves_both_front_doors(monkeypatch, capsys):
    """L-28. Two implementations of the same 2026-09-11 fix, disagreeing about which stream
    to test and neither saying why. The stream is the caller's decision now, and it is the
    only thing that differed."""
    import tui_chrome

    class _NotTty:
        @staticmethod
        def isatty():
            return False

    monkeypatch.setattr(tui_chrome.sys, "stdin", _NotTty)
    called = []
    monkeypatch.setattr("builtins.input", lambda *a: called.append(1))
    tui_chrome.hold_for_reader(_NotTty)
    assert called == [], "silent when nobody is at the keyboard"


# ------------------------------------------------------------ the sign-off marker (W-2)


def _pack(mod, tmp_path: Path, slug: str = "alpha") -> Path:
    pack = mod._pack_dir(tmp_path, slug)
    pack.mkdir(parents=True, exist_ok=True)
    return pack


def test_the_human_marker_is_written_before_sign_off_runs(tmp_path, monkeypatch):
    """W-2. `engagement_state sign-off` refuses unless <pack>/.human-sign-off exists and
    prints a touch command instead - so the launcher, which is where a person actually
    presses the key, has to write it. Telling someone who just confirmed a sign-off to go
    and type a shell command would make the gate read as broken rather than protective.

    The ORDER is the assertion: the marker must be on disk by the time the command that
    reads it starts."""
    mod = _launcher()
    project = _project(tmp_path)
    pack = _pack(mod, project)
    seen = {}
    monkeypatch.setattr(mod, "_signer_name", lambda: "Dana Ruiz")

    class _Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(argv, **kw):
        seen["marker_present"] = (pack / ".human-sign-off").is_file()
        seen["argv"] = argv
        return _Ok()

    monkeypatch.setattr(mod.subprocess, "run", _run, raising=False)
    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", _run)
    note = mod._record_sign_off(project, "alpha")
    assert note == "signed off by Dana Ruiz"
    assert seen["marker_present"] is True, "the command reads the marker - it must exist first"
    assert "sign-off" in seen["argv"]
    body = (pack / ".human-sign-off").read_text(encoding="utf-8")
    assert "Dana Ruiz" in body and "alpha" in body
    assert "never by a session" in body


def test_a_refused_sign_off_leaves_no_marker_behind(tmp_path, monkeypatch):
    """Nothing was signed, so nothing may be left claiming a human asked for it - a marker
    outliving a refused sign-off would authorise the NEXT attempt, including one nobody
    pressed a key for."""
    mod = _launcher()
    project = _project(tmp_path)
    pack = _pack(mod, project)
    monkeypatch.setattr(mod, "_signer_name", lambda: "Dana Ruiz")

    class _Refused:
        returncode = 1
        stdout = ""
        stderr = "refusing: this pack is already signed"

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", lambda argv, **kw: _Refused())
    note = mod._record_sign_off(project, "alpha")
    assert "already signed" in note
    assert not (pack / ".human-sign-off").exists()


def test_a_sign_off_that_could_not_run_leaves_no_marker(tmp_path, monkeypatch):
    """Same rule when the command cannot be started at all."""
    mod = _launcher()
    project = _project(tmp_path)
    pack = _pack(mod, project)
    monkeypatch.setattr(mod, "_signer_name", lambda: "Dana Ruiz")

    def _boom(argv, **kw):
        raise OSError("no interpreter")

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", _boom)
    assert "could not sign off" in mod._record_sign_off(project, "alpha")
    assert not (pack / ".human-sign-off").exists()


def test_nothing_is_written_without_a_slug_or_a_signer(tmp_path, monkeypatch):
    """An unattributed signature is worse than none, and so is a marker with nothing to
    attribute it to. Neither early return may write anything."""
    mod = _launcher()
    project = _project(tmp_path)
    pack = _pack(mod, project)
    monkeypatch.setattr(mod, "_signer_name", lambda: "")
    assert mod._record_sign_off(project, "") == "nothing selected"
    assert "no signer identity" in mod._record_sign_off(project, "alpha")
    assert not (pack / ".human-sign-off").exists()


def test_a_marker_someone_else_made_is_never_deleted(tmp_path, monkeypatch):
    """A file this launcher did not write is not a file it may remove - the same rule
    _expire_stale_auto_consent keeps about a hand-made consent marker."""
    mod = _launcher()
    project = _project(tmp_path)
    pack = _pack(mod, project)
    (pack / ".human-sign-off").write_text("made by hand\n", encoding="utf-8")
    monkeypatch.setattr(mod, "_signer_name", lambda: "Dana Ruiz")

    class _Refused:
        returncode = 1
        stdout = ""
        stderr = "refusing"

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", lambda argv, **kw: _Refused())
    mod._record_sign_off(project, "alpha")
    assert (pack / ".human-sign-off").read_text(encoding="utf-8") == "made by hand\n"


def test_the_marker_name_matches_the_command_that_reads_it():
    """Two spellings of one filename is a gate that silently never fires. The launcher
    names it locally on purpose - so it still writes a harmless file beside an older
    engagement_state - but the two must agree today."""
    mod = _launcher()
    import scripts.engagement_state as es

    assert mod._HUMAN_SIGN_OFF_MARKER == es.SIGN_OFF_MARKER


def test_both_tiers_reach_the_same_sign_off_function():
    """A marker written on one renderer and not the other is exactly the drift this
    codebase has paid for more than once."""
    app = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")
    textual = (REPO_ROOT / "scripts" / "launcher_textual.py").read_text(encoding="utf-8")
    assert "mod._record_sign_off(project_dir, slug)" in app
    assert "lambda slug: mod._record_sign_off(project_dir, slug)" in textual
    # And both ask twice before they call it, so the marker is only ever written after a
    # confirmed keypress.
    assert "SIGN_OFF_CONFIRM" in app
    assert "_sign_off_confirm()" in (REPO_ROOT / "scripts" / "launcher_tiers.py").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------- project identity (W-21)


def test_a_moved_checkout_is_noticed(tmp_path, monkeypatch):
    """W-21. Repo-vs-plugin mode was a single is_file() test against Path.cwd() at
    invocation time, with a prose instruction as the only mitigation and a named live
    incident proving prose is not enough."""
    fpr = _load("find_plugin_root", REPO_ROOT / "scripts" / "find_plugin_root.py")
    project = _project(tmp_path / "before")
    monkeypatch.setattr(fpr, "_git_fact", lambda cwd, args: "")
    fpr.remember_identity(project, "repo-as-project")
    assert fpr.identity_warning(project, "repo-as-project") == ""
    moved = tmp_path / "after"
    (tmp_path / "before").rename(moved)
    warning = fpr.identity_warning(moved, "repo-as-project")
    assert "first resolved at" in warning and str(moved) in warning


def test_a_changed_remote_is_noticed(tmp_path, monkeypatch):
    """Path alone is not an identity and neither is a remote: two clones of one repo are
    two projects, so all three facts are recorded."""
    fpr = _load("find_plugin_root", REPO_ROOT / "scripts" / "find_plugin_root.py")
    project = _project(tmp_path)
    monkeypatch.setattr(fpr, "_git_fact", lambda cwd, args: "git@example.com:one.git")
    fpr.remember_identity(project, "plugin")
    monkeypatch.setattr(fpr, "_git_fact", lambda cwd, args: "git@example.com:two.git")
    assert "git remote changed" in fpr.identity_warning(project, "plugin")


def test_a_mid_session_mode_flip_is_noticed(tmp_path, monkeypatch):
    """Incident #19 itself: a `cd` lands in a different directory, which has its own (or
    no) record, so only a machine-level breadcrumb can see it."""
    fpr = _load("find_plugin_root", REPO_ROOT / "scripts" / "find_plugin_root.py")
    home = tmp_path / "home"
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    first = _project(tmp_path / "a")
    second = _project(tmp_path / "b")
    assert fpr.mode_flip_warning(home, first, "plugin") == ""
    warning = fpr.mode_flip_warning(home, second, "repo-as-project")
    assert "previous resolution on this machine was plugin" in warning
    # Same mode in a new directory is ordinary project-switching, not a flip.
    assert fpr.mode_flip_warning(home, first, "repo-as-project") == ""


def test_the_identity_is_recorded_once_not_rewritten(tmp_path, monkeypatch):
    """A record rewritten on every call can never disagree with anything."""
    fpr = _load("find_plugin_root", REPO_ROOT / "scripts" / "find_plugin_root.py")
    project = _project(tmp_path)
    monkeypatch.setattr(fpr, "_git_fact", lambda cwd, args: "")
    fpr.remember_identity(project, "plugin")
    first = (project / ".claude" / "project-identity.json").read_text(encoding="utf-8")
    fpr.remember_identity(project, "repo-as-project")
    assert (project / ".claude" / "project-identity.json").read_text(encoding="utf-8") == first


def test_warnings_never_reach_the_decision_channel(tmp_path, monkeypatch, capsys):
    """stdout carries PLUGIN_ROOT= and nothing else: the skill reads it with a shell
    capture, so a warning there would be consumed as part of the path."""
    fpr = _load("find_plugin_root", REPO_ROOT / "scripts" / "find_plugin_root.py")
    project = _project(tmp_path / "proj")
    monkeypatch.setattr(fpr, "_git_fact", lambda cwd, args: "")
    monkeypatch.setattr(fpr, "find_plugin_root", lambda home, cwd: "")
    fpr.remember_identity(project, "repo-as-project")
    (tmp_path / "proj").rename(tmp_path / "moved")
    monkeypatch.setattr(sys, "argv", ["find_plugin_root.py", "--cwd", str(tmp_path / "moved")])
    fpr.main()
    out = capsys.readouterr()
    assert out.out.strip() == "PLUGIN_ROOT="
    assert "first resolved at" in out.err
