"""The installer's full-screen tier.

Driven headlessly (VIRT_SURV_FORCE_PTK + a pipe input + PlainTextOutput), the same way
tests/test_launcher_app.py drives the launcher's screens. That is not a convenience: the
launcher's two menu tiers drifted apart precisely because one of them could not be
exercised, and this file exists so the installer's two do not repeat it.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor"


@pytest.fixture
def ptk(monkeypatch):
    for extra in (VENDOR, REPO_ROOT / "scripts", REPO_ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    pytest.importorskip("prompt_toolkit.application")
    monkeypatch.setenv("VIRT_SURV_FORCE_PTK", "1")
    monkeypatch.setenv("VIRT_SURV_DEBUG_APP", "1")  # never let a real bug read as a fallback
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output.plain_text import PlainTextOutput

    return create_app_session, create_pipe_input, PlainTextOutput


_OPTIONS = (
    ("1", "Environment setup only (deps + status line, no clone sync)"),
    ("6", "Machine defaults (docx, citations, review tools, map skeleton, model)"),
    ("9", "Clean plugin cache (remove stale cached copies of the plugin from ~/.claude)"),
    ("", "-- internal / prototype --"),
    ("13", "Org extensions (review/edit the standard workflow this machine applies)"),
    ("b", "Back"),
)


def _run(ptk, keys, options=_OPTIONS):
    """Drive the picker with `keys` and return (chosen, rendered_frames)."""
    create_app_session, create_pipe_input, PlainTextOutput = ptk
    import install_helper as ih
    import installer_app

    buf = io.StringIO()
    out = PlainTextOutput(buf)
    with create_pipe_input() as inp:
        inp.send_text(keys)
        # `output=` passed to the SCREEN, not only to the app session: screen() falls back
        # to create_output(stdout=sys.stderr) when it is not given one, so a session-level
        # output alone is ignored and the frames go to the real stderr. That is exactly how
        # a first attempt at this file appeared to capture renders while asserting on an
        # empty buffer.
        with create_app_session(input=inp, output=out):
            chosen = installer_app.chooser_screen(options, ih, title="Advanced", output=out)
    return chosen, buf.getvalue()


def test_arrowing_and_enter_picks_the_row_you_are_looking_at(ptk):
    """The bug this shape keeps producing, asserted directly: the row highlighted is the
    row returned. Positional dispatch has broken that twice in this repo (the launcher's
    settings screen on 2026-08-28, and an Advanced-menu renumbering before it)."""
    chosen, _ = _run(ptk, "\x1b[B\r")  # down once: row 1 -> row 6
    assert chosen == "6"
    chosen, _ = _run(ptk, "\x1b[B\x1b[B\r")  # down twice
    assert chosen == "9"


def test_typing_a_key_still_works_for_people_who_know_the_number(ptk):
    """A picker that punishes muscle memory from the numbered menu is a downgrade, not an
    upgrade. Single-character keys jump to their row."""
    chosen, _ = _run(ptk, "9\r")
    assert chosen == "9"


def test_escape_is_a_decision_not_an_unavailability(ptk):
    """ "" (backed out) and None (could not run) must stay distinct. The launcher conflated
    them once and cancelling its settings screen dumped the user into the old numbered
    editor (2026-08-20)."""
    chosen, _ = _run(ptk, "\x1b")
    assert chosen == "", "Esc means the user chose to leave"
    assert chosen is not None


def test_divider_rows_are_not_selectable(ptk):
    """The submenu tables carry ("", "-- label --") rows for grouping. They are printed by
    the numbered tier and must never become a choice here."""
    import installer_app

    keys = [key for key, _label, _blurb, _writes in installer_app._rows(_OPTIONS, None)]
    assert "" not in keys
    assert keys == ["1", "6", "9", "13", "b"]


def test_the_explanation_leaves_the_label_and_goes_to_the_pane(ptk):
    """The actual gap this screen closes.

    Six Advanced items carry a parenthetical longer than the option itself - one is 136
    characters. Printed as `12) label (explanation...)` they soft-wrap to column 0 with no
    hanging indent, so the continuation sits under the number gutter and reads as a
    separate, unnumbered option. No rewording fixes that; the text needs somewhere to go."""
    _chosen, rendered = _run(ptk, "\r")
    assert "Environment setup only" in rendered
    assert "deps + status line" in rendered  # the blurb rendered, in the pane
    # And the label column itself is short - the parenthetical is not in it.
    import installer_app

    for _key, label, _blurb, _writes in installer_app._rows(_OPTIONS, None):
        assert len(label) <= 34, f"{label!r} is too long for a column"


def test_a_destructive_option_says_so_before_the_keypress(ptk):
    """Ten of the twenty-one options write outside the repo - shell rc files,
    ~/.claude/settings.json, one rmtree - and the numbered menu marked none of them. The
    marker is on the ROW, not only in the pane: someone arrowing quickly past should not
    have to read to notice."""
    _chosen, rendered = _run(ptk, "\x1b[B\x1b[B\r")
    assert "Deletes cached plugin copies" in rendered
    assert "writes outside this project" in rendered  # the legend explains the marker


def test_the_write_marker_is_not_the_off_marker(ptk):
    """One symbol, one meaning. glyphs()["off"] is "·" on every launcher row; reusing it
    for "writes outside the repo" would give it two meanings in one product."""
    import installer_app

    source = (REPO_ROOT / "scripts" / "installer_app.py").read_text(encoding="utf-8")
    # Scoped to the CHOOSER. glyphs()["off"] is correct on a settings grid row, where it
    # means what it says; the point is that the chooser must not borrow it for a different
    # meaning. An unscoped assertion started failing the moment the grid landed and would
    # have been "fixed" by deleting it.
    chooser = source[source.index("def chooser_screen(") : source.index("def grid_screen(")]
    assert "g['off']" not in chooser and 'g["off"]' not in chooser
    assert installer_app._marker_kind(installer_app._WRITES["cleanplugincache"]) == "deletes"
    # And a read-only row carries no write marker at all - otherwise the marker means
    # nothing on a screen where most rows have one.
    assert installer_app._marker_kind("reads only - explains the plugin") == ""
    assert installer_app._marker_kind("opens a submenu; each item states its own") == ""


def test_it_returns_None_rather_than_starting_an_app_without_a_terminal(monkeypatch):
    """A tier, never a replacement. Under --yes, over a pipe, or on a box where
    prompt_toolkit will not start, the caller must get None and print its numbered menu."""
    for extra in (REPO_ROOT / "scripts", REPO_ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import install_helper as ih
    import installer_app

    monkeypatch.delenv("VIRT_SURV_FORCE_PTK", raising=False)
    assert installer_app.chooser_screen(_OPTIONS, ih, title="Advanced") is None


def test_the_host_probes_the_stream_the_chrome_actually_draws_on():
    """The one trap in the shared-chrome extraction, and it fails silently.

    install_helper._can_encode defaults its stream to sys.stdout; tui_chrome renders to
    sys.stderr. Handing the module straight over would probe one console and draw on
    another, so the ASCII fallbacks would fire on the wrong condition - and on any machine
    where a developer would notice, the two streams are the same console."""
    for extra in (REPO_ROOT / "scripts", REPO_ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import install_helper as ih
    import installer_app

    asked = []

    def _spy(text, stream=None):
        asked.append(stream)
        return True

    original = ih._can_encode
    try:
        ih._can_encode = _spy
        installer_app.InstallerHost(ih)._can_encode("x")
    finally:
        ih._can_encode = original
    assert asked == [sys.stderr], f"probed {asked}, but the chrome draws on stderr"


def test_a_rows_consequence_comes_from_ITS_menus_table_not_a_guess(ptk):
    """Key "1" is a full install at the top level, environment-setup-only under Advanced,
    and check-for-updates under Diagnostics. _writes used to scan the three tables in a
    fixed order and take the first hit, so the most prominent option on the most-seen
    screen showed the consequence of a different action entirely (seen on screen,
    2026-08-28)."""
    import install_helper as ih
    import installer_app

    top = installer_app._writes("1", ih, ih.MENU_ACTIONS)
    advanced = installer_app._writes("1", ih, ih._ADVANCED_ACTIONS)
    assert top != advanced, "the same key in two menus must not share one consequence"
    assert "registers the plugin" in top
    assert "installs requirements" in advanced


def test_the_top_level_menu_goes_through_the_picker_too(monkeypatch, tmp_path):
    """The submenus were wired first, which left the one screen everybody sees on every
    run exactly as it was - so the change was invisible unless you went three levels deep
    (owner report: "the menu system still feels ugly")."""
    for extra in (REPO_ROOT / "scripts", REPO_ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import install_helper as ih

    seen = {}

    def _fake(style, title, options, actions):
        seen["title"] = title
        seen["actions"] = actions
        return "q"

    monkeypatch.setattr(ih, "_submenu_screen", _fake)
    assert ih.choose_action(ih.Style(False)) == "quit"
    assert seen["title"] == "What can I do for you?"
    assert seen["actions"] is ih.MENU_ACTIONS, "the top menu must pass its OWN table"


def test_escape_at_the_top_level_quits_rather_than_installing(monkeypatch):
    """Blank-is-a-full-install is a fine default for a typed prompt, where the keypress is
    deliberate. It is a bad one for a full-screen app, where Esc is how people leave - and
    would start a thirteen-step install for someone trying to back out of one."""
    for extra in (REPO_ROOT / "scripts", REPO_ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import install_helper as ih

    monkeypatch.setattr(ih, "_submenu_screen", lambda *a, **k: "")  # Esc
    assert ih.choose_action(ih.Style(False)) == "quit"
