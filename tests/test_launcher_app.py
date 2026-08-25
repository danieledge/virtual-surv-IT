"""The full-screen launcher tier (scripts/launcher_app.py, prototype 2026-08-20).

Driven HEADLESSLY on purpose. An untestable tier is exactly how the launcher's two
renderers drifted apart on 2026-08-19 - the picker kept old rows while the numbered tier
was redesigned, and only a screenshot caught it. So this tier is testable from the day it
exists, and one test below pins the shared-content rule that prevents a repeat.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ptk(monkeypatch):
    # BOTH paths: vendor/ for prompt_toolkit, and scripts/ because the launcher's
    # helpers do bare `import engage_probe` / `import engagement_state` - which resolve
    # in production (it runs from scripts/) but not under pytest's rootdir path.
    for extra in (VENDOR, REPO_ROOT / "scripts"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    pytest.importorskip("prompt_toolkit.application")
    monkeypatch.setenv("VIRT_SURV_FORCE_PTK", "1")
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output.plain_text import PlainTextOutput

    return create_app_session, create_pipe_input, PlainTextOutput


def _menu(rows):
    return {
        "open": [r["dir"] for r in rows],
        "shown": rows,
        "more": 0,
        "archived": 0,
        "default": rows[0]["dir"] if rows else None,
    }


def _row(slug="alpha", title="Alpha work", status="in_progress", **extra):
    row = {
        "dir": slug,
        "slug": slug,
        "title": title,
        "status": status,
        "opened": "2026-08-19",
        "phase": "plan",
        "outstanding": 2,
    }
    row.update(extra)
    return row


def _drive(ptk, keys: str, rows, jira_on=False, project=None):
    """Render the app, send `keys`, return (pick, rendered_text)."""
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=out):
            pick = app.run_app(
                project or REPO_ROOT, launcher, _menu(rows), rows, jira_on=jira_on, output=out
            )
    return pick, buf.getvalue()


def test_app_renders_a_framed_two_pane_layout(ptk):
    pick, text = _drive(ptk, "\x1b", [_row()])
    assert pick is None  # Esc
    assert "Resume an engagement" in text
    assert "Start something new" in text
    assert "Alpha work" in text
    assert "│" in text or "|" in text, "no pane divider rendered"


def test_detail_pane_shows_the_selected_engagement(ptk):
    _pick, text = _drive(ptk, "\x1b", [_row(title="Threshold tuning")])
    # The pane's labelled fields are the whole point of the split layout.
    for label in ("slug", "status", "opened", "phase"):
        assert label in text, f"detail pane missing {label!r}"


def test_blocked_engagement_names_what_it_waits_on(ptk):
    rows = [_row(status="blocked", outstanding=3, outstanding_first="independent QA - not run")]
    _pick, text = _drive(ptk, "\x1b", rows)
    assert "independent QA" in text


def test_enter_picks_the_highlighted_engagement(ptk):
    pick, _text = _drive(ptk, "\r", [_row(), _row(slug="beta", title="Beta")])
    assert pick == ("resume", 0)


def test_down_then_enter_moves_the_selection(ptk):
    pick, _text = _drive(ptk, "\x1b[B\r", [_row(), _row(slug="beta", title="Beta")])
    assert pick == ("resume", 1)


def test_hotkeys_return_actions(ptk):
    assert _drive(ptk, "n", [_row()])[0] == ("new",)
    assert _drive(ptk, "c", [_row()])[0] == ("settings",)
    assert _drive(ptk, "a", [_row()])[0] == ("archive",)


def test_jira_action_only_when_enabled(ptk):
    assert _drive(ptk, "j", [_row()], jira_on=True)[0] == ("jira",)
    # With Jira off, 'j' is not bound - Esc still exits cleanly rather than hanging.
    assert _drive(ptk, "j\x1b", [_row()], jira_on=False)[0] is None


def test_empty_menu_still_offers_actions(ptk):
    pick, text = _drive(ptk, "n", [])
    assert pick == ("new",)
    assert "no open engagements" in text


def test_app_writes_nothing_to_stdout(ptk, capsys):
    """THE load-bearing contract: the shell captures stdout as the decision string, so a
    full-screen renderer must never touch it (an input() prompt leaking there was a real
    bug, 2026-08-15)."""
    capsys.readouterr()
    _drive(ptk, "\x1b", [_row()])
    assert capsys.readouterr().out == ""


def test_unusable_console_falls_back_instead_of_failing(monkeypatch):
    """No tty and no force flag: the tier declines so the picker/numbered flow runs."""
    monkeypatch.delenv("VIRT_SURV_FORCE_PTK", raising=False)
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    monkeypatch.setattr(launcher, "_ptk_ui", lambda: None)
    result = app.run_app(REPO_ROOT, launcher, _menu([]), [], jira_on=False)
    assert result == app.APP_FALLBACK


def test_both_tiers_render_the_same_row_content():
    """The drift guard. Content comes from row_view(); a tier that hand-rolls its own row
    is how the picker and numbered flows diverged in the first place."""
    launcher = _load("virt_team_launcher")
    source = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")
    assert "row_view(" in source, "the app must build rows from the shared view"
    view = launcher.row_view(
        _row(status="blocked", outstanding_first="QA not run"), default_slug="alpha", of_many=True
    )
    assert view["title"] == "Alpha work" and view["mark"] == "!"
    assert view["recommended"] is True
    assert any(label == "next" for label, _v in view["lines"])


def test_row_view_is_plain_data_not_styled_strings():
    """Tiers decorate differently (ANSI, pt fragments, app styles), so the shared view
    must stay style-free or one tier's escape codes leak into another."""
    launcher = _load("virt_team_launcher")
    view = launcher.row_view(_row())
    blob = json.dumps(view)
    assert "\x1b[" not in blob and "class:" not in blob


# --- the other screens (2026-08-20): settings and archive on the same shell ----------


def test_settings_screen_lists_rows_and_toggles_in_place(ptk, tmp_path):
    """Same _editor_rows/_editor_apply the plain tier drives, so behaviour cannot
    diverge - only presentation. Enter toggles the highlighted row for real."""
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text("\r\x1b")  # toggle the first row, then leave
        with create_app_session(input=pipe, output=out):
            changed = app.settings_screen(tmp_path, launcher, output=out)
    text = buf.getvalue()
    assert "Project settings" in text
    assert "docx export" in text, "settings rows not rendered"
    assert changed is True, "Enter did not toggle anything"
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs, "the toggle never reached team-preferences.json"


def test_settings_screen_escape_changes_nothing(ptk, tmp_path):
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    out = PlainTextOutput(io.StringIO())
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")
        with create_app_session(input=pipe, output=out):
            changed = app.settings_screen(tmp_path, launcher, output=out)
    # False, NOT None: the screen RAN and the user cancelled. None means "could not run"
    # and is the only thing that may fall back to the numbered editor - conflating them
    # is what dropped users into the old interface on Esc (live report, 2026-08-20).
    assert changed is False
    assert changed is not None
    assert json.loads((tmp_path / ".claude" / "team-preferences.json").read_text()) == {}


def test_archive_screen_states_the_open_pack_consequence(ptk):
    """ARCHIVED-OPEN is on screen BEFORE the key is pressed - it is what a person needs
    in order to decide, not an after-the-fact note."""
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    rows = [_row()]
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")
        with create_app_session(input=pipe, output=out):
            app.archive_screen(Path("."), launcher, None, _menu(rows), output=out)
    text = buf.getvalue()
    assert "Archive engagements" in text
    assert "ARCHIVED-OPEN" in text
    assert "archive ALL open engagements" in text


def test_every_screen_shares_one_shell():
    """menu, settings and archive all render through screen() - three hand-rolled
    layouts would drift exactly as the two menu tiers did."""
    source = (REPO_ROOT / "scripts" / "launcher_app.py").read_text(encoding="utf-8")
    assert source.count("        screen(") >= 3, "a screen is not using the shared shell"


def test_glyphs_degrade_on_a_cp1252_console(monkeypatch):
    """Emoji only where the console can encode them - the same gate the wordmark uses."""
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    monkeypatch.setattr(launcher, "_can_encode", lambda text: False)
    plain = app.glyphs(launcher)
    assert plain["point"] == ">" and plain["settings"] == ""
    # Brackets, never the WORDS on/off: on a real cp1252 console those sat next to the
    # value and produced "docx export  off off", and on a choice row "qa depth  off auto"
    # - which states the opposite of the truth. Found on Windows 2026-08-20.
    assert plain["on"] == "[x]" and plain["off"] == "[ ]"
    assert "on" not in (plain["on"] + plain["off"]).replace("[", "").replace("]", "").strip()
    monkeypatch.setattr(launcher, "_can_encode", lambda text: True)
    rich = app.glyphs(launcher)
    assert rich["point"] == "▸" and "⚙" in rich["settings"]


def test_no_ascii_mark_can_be_mistaken_for_a_setting_value(monkeypatch):
    """A guard against reintroducing the collision in any glyph: no ASCII fallback may be
    a word that also appears as a VALUE in the settings table."""
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    monkeypatch.setattr(launcher, "_can_encode", lambda text: False)
    plain = app.glyphs(launcher)
    values = {"on", "off", "auto", "quick", "deep", "audit", "applied", "live", "close-only"}
    clashes = [k for k, v in plain.items() if v.strip().lower() in values]
    assert not clashes, f"glyph(s) collide with a settings value: {clashes}"


def test_escape_does_not_fall_back_to_the_old_interface(ptk, tmp_path):
    """The live report: pressing Esc in the app dropped back to the numbered editor.
    Cause was a conflated return - False (ran, cancelled) read the same as
    "unavailable". The caller falls back ONLY on None."""
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    out = PlainTextOutput(io.StringIO())
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")
        with create_app_session(input=pipe, output=out):
            result = app.settings_screen(tmp_path, launcher, output=out)
    assert result is False, "Esc must report 'ran, no change', never 'unavailable'"


def test_screens_report_none_only_when_they_cannot_run(monkeypatch, tmp_path):
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    monkeypatch.setattr(launcher, "_ptk_ui", lambda: None)
    assert app.settings_screen(tmp_path, launcher) is None
    assert app.archive_screen(tmp_path, launcher, None, _menu([_row()])) is None


def test_jira_is_offered_even_without_the_integration_configured(tmp_path):
    """2026-08-20: [j] is an affordance, not an outward action - the launcher never talks
    to Jira, it only pre-seeds a ticket ref - so it is offered everywhere. The OUTWARD
    half (issue creation, progress comments) stays behind integrations.jira.enabled."""
    launcher = _load("virt_team_launcher")
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    assert launcher._jira_offered(tmp_path) is True
    assert launcher._jira_enabled(tmp_path) is False, "outward actions must stay gated"


# --- the [j] ticket prompt as a real screen (2026-08-20 user report) -------------------------


def _drive_jira(ptk, keys: str, project):
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=out):
            ref = app.jira_screen(project, launcher, output=out)
    return ref, buf.getvalue()


def test_jira_screen_collects_a_key_without_leaving_the_interface(ptk, tmp_path):
    """The whole point: picking [j] used to tear the app down and drop to a bare input()
    on stderr. The ticket is now collected inside the same framed shell."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    ref, text = _drive_jira(ptk, "SURV-142\r", tmp_path)
    assert ref == "SURV-142"
    assert "From a Jira ticket" in text, "the framed screen never rendered"
    assert "will open from SURV-142" in text, "no live validation of what was typed"


def test_jira_screen_keeps_the_url_so_the_instance_host_survives(ptk, tmp_path):
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    url = "https://acme.atlassian.net/browse/SURV-9"
    ref, _text = _drive_jira(ptk, url + "\r", tmp_path)
    assert ref == url, "a pasted URL must pass through, not be reduced to the bare key"


def test_jira_screen_escape_is_a_cancel_not_an_unavailable_screen(ptk, tmp_path):
    """Same distinction the settings screen had to learn: a cancel returns to the menu,
    only None may fall back to the plain input() prompt."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    app = _load("launcher_app")
    ref, _text = _drive_jira(ptk, "\x1b", tmp_path)
    assert ref == app.JIRA_CANCELLED
    assert ref is not None


def test_jira_screen_enter_on_an_unparseable_ref_stays_put(ptk, tmp_path):
    """Enter with nothing valid must not bounce the user out of the screen; the old flow
    returned them to the menu and made them pick [j] again."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    # Enter on garbage is ignored, the text stays put to be corrected, and Ctrl-U clears
    # it. (Without the clear the two run together into one bogus key - which the live
    # "will open from ..." line shows before Enter, so it is visible, not silent.)
    ref, _text = _drive_jira(ptk, "nonsense\r\x15SURV-7\r", tmp_path)
    assert ref == "SURV-7", "the first Enter should have been ignored, not exited"
    # The "keep typing" warning is deliberately NOT asserted here: piped input is drained
    # before a frame is painted, so no intermediate state ever reaches the output buffer.
    # It is the returned ref that proves Enter was ignored.


def test_jira_screen_says_when_the_project_has_no_write_back_configured(ptk, tmp_path):
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    _ref, text = _drive_jira(ptk, "\x1b", tmp_path)
    assert "No Jira integration configured" in text
    assert "INTEGRATIONS.md" in text


# --- per-setting explanations in the right pane (2026-08-20 user request) ---------------------


def test_settings_screen_explains_the_highlighted_setting(ptk, tmp_path):
    """The pane used to describe the screen's own keys, which a user has worked out by the
    time they read it, while "what does this setting DO?" went unanswered - asked out loud
    about the jira row, which is what prompted this."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")  # first row highlighted, then leave
        with create_app_session(input=pipe, output=out):
            app.settings_screen(tmp_path, launcher, output=out)
    text = buf.getvalue()
    assert "docx export" in text
    assert "Word" in text, "the first row's explanation never rendered"
    assert "currently:" in text


def test_every_settings_row_has_an_explanation():
    """A new toggle with no entry renders "No description available" - true, but useless.
    This fails the moment a setting is added without one, which is the only reliable time
    to write it."""
    launcher = _load("virt_team_launcher")
    labels = [label for label, _key in launcher._TOGGLE_PREFS]
    labels += [launcher._ENV_ROW_LABEL, launcher._JIRA_ROW_LABEL]
    missing = [label for label in labels if not launcher.setting_help(label)]
    assert not missing, f"settings with no explanation: {missing}"


def test_setting_help_is_two_parts_and_stays_pane_sized():
    """(what it does, what off means). Long enough to be useful, short enough for a ~30
    column pane - a wall of text in there is as unread as no text."""
    launcher = _load("virt_team_launcher")
    for label, parts in launcher._SETTING_HELP.items():
        assert len(parts) == 2, label
        for part in parts:
            assert part and part[0].isupper(), f"{label}: not a sentence"
            assert len(part) < 220, f"{label}: too long for the pane ({len(part)})"
        # Both parts share ~19 lines of a ~30-column pane with the label and the current
        # value. Overrun does not scroll, it CLIPS - a first attempt at the jira wording
        # pushed "currently:" clean off the screen (caught by rendering under a pty).
        budget = sum(len(part) for part in parts)
        assert budget < 380, f"{label}: {budget} chars will not fit the pane together"


def test_the_jira_explanation_says_j_still_works_when_it_is_off():
    """The exact confusion that prompted all this: "off" on this row does not mean Jira is
    unavailable, and the pane has to say so or the label misleads again."""
    launcher = _load("virt_team_launcher")
    what, off = launcher.setting_help(launcher._JIRA_ROW_LABEL)
    assert "WRITE" in what
    assert "[j]" in off and "does NOT hide" in off


# --- the working directory on screen (2026-08-20 user request) -------------------------------


def test_the_menu_shows_the_full_project_directory(ptk, tmp_path):
    """The frame title carried the basename only, which does not distinguish two checkouts
    of the same repo - and running from the wrong directory is a documented cause of a
    silent plain launch on corp Windows."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    _pick, text = _drive(ptk, "\x1b", [_row()], project=tmp_path)
    assert str(tmp_path.resolve())[-30:] in text.replace("\r", "")


def test_a_long_path_keeps_its_tail_not_its_head():
    """An over-long path loses the head: the leaf is the part that identifies which
    project you are in, so truncating the other end would defeat the whole point."""
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    deep = Path("/" + "/".join(f"segment-{i}" for i in range(20)) + "/the-actual-project")
    line = app.project_line(deep, launcher, width=40)
    assert line.endswith("the-actual-project")
    assert len(line) <= 40
    assert line.startswith("..")


def test_the_settings_and_jira_screens_show_it_too(ptk, tmp_path):
    """It lives in the shared shell, so no screen can quietly lose it."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    tail = str(tmp_path.resolve())[-24:]
    for run in (
        lambda out: app.settings_screen(tmp_path, launcher, output=out),
        lambda out: app.jira_screen(tmp_path, launcher, output=out),
    ):
        buf = io.StringIO()
        out = PlainTextOutput(buf)
        with create_pipe_input() as pipe:
            pipe.send_text("\x1b")
            with create_app_session(input=pipe, output=out):
                run(out)
        assert tail in buf.getvalue().replace("\r", "")


# --- project explorer, setup screen, and backing out (2026-08-20 user requests) ---------------


def test_browse_screen_lists_folders_and_marks_team_projects(ptk, tmp_path):
    (tmp_path / "plain-folder").mkdir()
    proj = tmp_path / "a-team-project"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")
        with create_app_session(input=pipe, output=out):
            app.browse_screen(tmp_path, launcher, output=out)
    text = buf.getvalue()
    assert "a-team-project" in text and "plain-folder" in text
    assert "team project" in text, "configured projects are not distinguished"
    assert "use this folder" in text


def test_browse_screen_first_row_picks_the_current_folder(ptk, tmp_path):
    """Enter must never mean both "descend" and "choose" - that is how you open the wrong
    project. The first row is explicitly the current folder."""
    (tmp_path / "sub").mkdir()
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    out = PlainTextOutput(io.StringIO())
    with create_pipe_input() as pipe:
        pipe.send_text("\r")
        with create_app_session(input=pipe, output=out):
            chosen = app.browse_screen(tmp_path, launcher, output=out)
    assert chosen == tmp_path.resolve()


def test_browse_screen_escape_cancels(ptk, tmp_path):
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    out = PlainTextOutput(io.StringIO())
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")
        with create_app_session(input=pipe, output=out):
            chosen = app.browse_screen(tmp_path, launcher, output=out)
    assert chosen == app.BROWSE_CANCELLED


def test_setup_screen_offers_defaults_without_leaving_the_interface(ptk, tmp_path):
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text("\r")  # first option
        with create_app_session(input=pipe, output=out):
            choice = app.setup_screen(tmp_path, launcher, output=out)
    # Only the RETURN value is asserted here: piped keys are drained before a frame is
    # painted, so an immediately-accepted screen renders nothing. The wording is checked
    # in the Esc test below, which does paint.
    assert choice == app.SETUP_DEFAULTS


def test_setup_screen_escape_skips(ptk, tmp_path):
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")
        with create_app_session(input=pipe, output=out):
            choice = app.setup_screen(tmp_path, launcher, output=out)
    assert choice == app.SETUP_SKIP
    text = buf.getvalue()
    assert "First-time setup" in text
    assert "no questions asked" in text
    assert "leaves this screen" in text, "the guided pass must admit that it leaves"


def test_the_menu_offers_the_explorer(ptk):
    _pick, text = _drive(ptk, "\x1b", [_row()])
    assert "open a different project folder" in text


# --- artifacts, help, recents, and the scrolling engagement list ------------------------------


def _show(ptk, fn, keys="\x1b"):
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=out):
            fn(out)
    return buf.getvalue().replace("\r", "")


def test_artifacts_screen_lists_what_the_engagement_produced(ptk, tmp_path):
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    ws = tmp_path / "artifacts" / "demo"
    ws.mkdir(parents=True)
    (ws / "START-HERE.html").write_text("x", encoding="utf-8")
    (ws / "delivery-report.html").write_text("x", encoding="utf-8")
    text = _show(ptk, lambda o: app.artifacts_screen(tmp_path, launcher, "demo", output=o))
    assert "START-HERE.html" in text and "delivery-report.html" in text
    assert "Artifacts for demo" in text


def test_artifacts_screen_says_so_when_nothing_is_rendered_yet(ptk, tmp_path):
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    (tmp_path / "artifacts" / "empty").mkdir(parents=True)
    text = _show(ptk, lambda o: app.artifacts_screen(tmp_path, launcher, "empty", output=o))
    assert "nothing rendered yet" in text


def test_help_screen_explains_the_status_marks_and_the_keys(ptk, tmp_path):
    """The settings screen explains itself; the menu's glyphs did not - a row marked with
    the blocked mark told you something was wrong without saying what."""
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    text = _show(ptk, lambda o: app.help_screen(tmp_path, launcher, output=o))
    for word in ("in progress", "blocked", "closing", "most recent"):
        assert word in text
    assert "quit, no launch" in text, "Esc's real behaviour must be stated"
    assert "view artifacts" in text and "show all open" in text


def test_the_menu_advertises_help_and_that_escape_does_not_launch(ptk):
    _pick, text = _drive(ptk, "\x1b", [_row()])
    assert "? help" in text
    assert "Esc back to terminal" in text


def test_the_menu_offers_artifacts_when_something_is_open(ptk):
    _pick, text = _drive(ptk, "\x1b", [_row()])
    assert "view an engagement's artifacts" in text


def test_a_long_engagement_list_scrolls_instead_of_running_off_the_frame(ptk):
    """This tier now receives EVERY open engagement, so without a viewport the rows past
    the frame are simply invisible."""
    rows = [_row(slug=f"eng-{i}", title=f"Engagement {i}") for i in range(20)]
    _pick, text = _drive(ptk, "\x1b", rows)
    assert "more below" in text, "no scroll indicator on a 20-row list"
    assert "Engagement 0" in text


def test_the_explorer_offers_recent_projects(ptk, tmp_path, monkeypatch):
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    recent = tmp_path / "a-recent-project"
    recent.mkdir()
    launcher._remember_project(recent)
    start = tmp_path / "somewhere-else"
    start.mkdir()
    text = _show(ptk, lambda o: app.browse_screen(start, launcher, output=o))
    assert "a-recent-project" in text
    assert "recent" in text


# ------------------------------------------------------- browse done & archived


class _FakeES:
    """finished_engagements stub - the screen's only engagement_state touchpoint."""

    def __init__(self, rows):
        self._rows = rows

    def finished_engagements(self, root):
        return self._rows


def _finished_rows():
    return [
        _row("old-audit", "Old audit", "closed", closed="2026-08-01", archived=False),
        _row("parked", "Parked spike", "in_progress", archived=True),
    ]


def _drive_finished(ptk, keys: str, rows):
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    launcher = _load("virt_team_launcher")
    app = _load("launcher_app")
    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=out):
            token = app.finished_screen(Path("."), launcher, _FakeES(rows), output=out)
    return token, buf.getvalue()


def test_menu_key_b_returns_the_finished_pick(ptk):
    pick, text = _drive(ptk, "b", [_row()])
    assert pick == ("finished",)
    assert "browse done & archived" in text


def test_finished_screen_lists_closed_and_archived_with_provenance(ptk):
    token, text = _drive_finished(ptk, "\x1b", _finished_rows())
    assert token == ""  # Esc = backed out, NOT None (None would mean "could not run")
    assert "Done & archived engagements" in text
    assert "Old audit" in text and "closed" in text
    assert "Parked spike" in text and "archived" in text


def test_finished_screen_enter_returns_the_selected_token(ptk):
    token, _ = _drive_finished(ptk, "\r", _finished_rows())
    assert token == "old-audit"
    token, _ = _drive_finished(ptk, "\x1b[B\r", _finished_rows())  # Down, Enter
    assert token == "parked"


def test_finished_screen_returns_none_when_nothing_finished(ptk):
    token, _ = _drive_finished(ptk, "\x1b", [])
    assert token is None  # caller falls back, and the fallback owns the message


# --- Esc, end to end (2026-08-25) ----------------------------------------------------------
#
# The abort tests in test_virt_team_launcher.py stub _resume_decision, so they prove the
# mapping and never the chain. This drives a REAL Escape keypress through the real app, the
# real menu round and main(), and asserts the two things the shell wrapper depends on: exit
# code 97, and a stdout with nothing on it (a stray character there becomes the session's
# opening prompt). Written after a user reported Esc launching a session anyway - the cause
# was an out-of-date shell wrapper rather than this chain, but nothing had ever tested the
# chain itself, so the report could not be narrowed without adding this first.


def test_escape_drives_main_to_the_abort_exit_code(ptk, tmp_path, monkeypatch, capsys):
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    art = project / "artifacts" / "alpha"
    art.mkdir(parents=True)
    (art / "engagement-state.json").write_text(
        json.dumps(
            {"schema": 2, "status": "in_progress", "engagement": {"slug": "alpha", "title": "A"}}
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    # A v7 wrapper is present, so the abort is honoured and nothing is warned about.
    monkeypatch.setenv("VIRT_SURV_CD_FILE", str(tmp_path / "cd"))

    mod = _load("virt_team_launcher")
    for name in (
        "_print_banner", "_check_plugin_cache_lag", "_print_project_defaults",
        "_prewarm_guard_interpreter", "_write_probe_cache", "_refresh_tool_cache",
        "_heal_stale_alias_once",
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, lambda *a, **k: None)

    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b")  # Escape
        with create_app_session(input=pipe, output=out):
            rc = mod.main()
    assert rc == mod._ABORT_EXIT_CODE == 97, "Esc must abort, never fall through to a launch"
    assert capsys.readouterr().out == "", "stdout is the decision channel - it must be empty"
