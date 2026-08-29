"""The installer's full-screen tier.

Driven headlessly (VIRT_SURV_FORCE_PTK + a pipe input + PlainTextOutput), the same way
tests/test_launcher_app.py drives the launcher's screens. That is not a convenience: the
launcher's two menu tiers drifted apart precisely because one of them could not be
exercised, and this file exists so the installer's two do not repeat it.
"""

from __future__ import annotations

import ast
import io
import subprocess
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


def test_the_screens_work_with_only_the_VENDORED_prompt_toolkit():
    """Why the new menus did not appear on a real machine.

    installer_app never put vendor/ on sys.path, so `import prompt_toolkit` failed on any
    box without a pip-installed copy - which is the normal case, since vendoring it exists
    precisely because a locked-down machine cannot pip-install. The `except Exception`
    turned that into "this console cannot host an app" and the numbered menu returned,
    looking like a graceful fallback.

    Invisible from a dev machine twice over: this one HAS prompt_toolkit installed, and
    the fixture in this very file puts vendor/ on the path by hand - so every other test
    here exercises a path production never takes. Reported from a container with neither
    (2026-08-28: "I don't see the better interface").

    A SUBPROCESS with -S, therefore: no site-packages, no test-fixture path edits, nothing
    but what the installer itself arranges."""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
        "import installer_app\n"
        "installer_app._vendor_on_path()\n"
        "import prompt_toolkit\n"
        "from prompt_toolkit.key_binding import KeyBindings\n"
        "print(prompt_toolkit.__file__)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"the screens cannot import prompt_toolkit:\n{proc.stderr}"
    assert "vendor" in proc.stdout, f"resolved a non-vendored copy: {proc.stdout.strip()}"


def test_scripts_resolve_when_the_installer_runs_from_its_TEMP_COPY(tmp_path, monkeypatch):
    """The reason the new screens never appeared on a real installation.

    _relocate_if_running_inside_target_repo copies install_helper.py to a bare temp
    directory and re-execs from there for the REST of the session, so a git checkout can
    safely overwrite the original. From that moment `Path(__file__).parent` is
    /tmp/virt-surv-it-installer-XXXX - one .py file, no scripts/ sibling. Every candidate
    missed, _import_from_scripts returned None, and the caller read that as "this console
    cannot host an app".

    So it worked in a checkout being developed in place and nowhere else. Two remote
    guesses failed to find it; instrumenting the actual container did, by printing
    __file__ and watching it point at a temp directory.

    _resolve_repo_root documents this hazard in its own docstring and already solves it -
    the re-exec passes the real clone through as --repo. This test pins that it is asked."""
    import install_helper as ih

    clone = tmp_path / "clone"
    (clone / "scripts").mkdir(parents=True)
    (clone / "scripts" / "fakemod.py").write_text("VALUE = 'from the clone'\n", encoding="utf-8")
    relocated = tmp_path / "virt-surv-it-installer-abc123"
    relocated.mkdir()

    monkeypatch.setattr(ih, "__file__", str(relocated / "install_helper.py"))
    monkeypatch.setattr(ih, "_resolve_repo_root", lambda hint=None: clone)
    module = ih._import_from_scripts("fakemod")
    assert module is not None, "a relocated installer must still find its own scripts/"
    assert module.VALUE == "from the clone"


def test_it_still_resolves_when_there_is_no_configured_clone(tmp_path, monkeypatch):
    """The __file__ candidates remain the fallback - a checkout run in place, or a machine
    whose installer.json has not been written yet, must keep working."""
    import install_helper as ih

    here = tmp_path / "inplace"
    (here / "scripts").mkdir(parents=True)
    (here / "scripts" / "fakemod2.py").write_text("VALUE = 'in place'\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(here / "install_helper.py"))
    monkeypatch.setattr(ih, "_resolve_repo_root", lambda hint=None: None)
    module = ih._import_from_scripts("fakemod2")
    assert module is not None and module.VALUE == "in place"


def test_the_banner_is_drawn_once_and_where_it_can_be_seen(monkeypatch, capsys):
    """The app runs in the alternate screen, so anything printed before it is invisible
    for as long as someone is actually using the menu, and only reappears when they leave.
    Identity belongs in the frame (owner decision, 2026-08-28).

    Both halves matter: the terminal print is skipped when the frame will carry it, AND
    the numbered tier still prints it - otherwise a box that cannot run the app would get
    no banner at all."""
    for extra in (REPO_ROOT / "scripts", REPO_ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import install_helper as ih

    monkeypatch.setattr(ih, "_BANNER_SHOWN", False, raising=False)
    monkeypatch.setattr(ih, "_submenu_screen", lambda *a, **k: None)  # app tier declines
    monkeypatch.setattr("builtins.input", lambda prompt="": "q")
    ih.choose_action(ih.Style(False))
    assert "Virtual Surveillance IT" in capsys.readouterr().out, (
        "the numbered tier has no frame, so it must print the banner itself"
    )

    # ...and having printed it, it must not print it a second time.
    monkeypatch.setattr("builtins.input", lambda prompt="": "q")
    ih.choose_action(ih.Style(False))
    assert capsys.readouterr().out.count("Virtual Surveillance IT") == 0


def test_the_frame_header_carries_the_brand(ptk):
    """The banner as frame-header rows. Its absence must cost the art and nothing else -
    brand_header returns None, not [], so the caller keeps tui_chrome's identity line
    rather than rendering a blank strip."""
    import install_helper as ih
    import installer_app

    rows = installer_app.brand_header(ih)
    assert rows, "the brand must resolve through the host's own importer"
    flat = "".join(text for row in rows for _style, text in row)
    assert "V S I T" in flat and "Virtual Surveillance IT" in flat

    # Forced through _import_brand rather than through a host with no resolver: that host
    # still finds brand_banner by plain import when scripts/ happens to be importable,
    # which is the deliberate curl-bootstrap fallback and not the case under test.
    original = installer_app._import_brand
    try:
        installer_app._import_brand = lambda mod: None
        assert installer_app.brand_header(ih) is None
    finally:
        installer_app._import_brand = original


def test_the_banner_and_the_menu_agree_about_the_app_tier(monkeypatch):
    """One question, asked once. If the banner decided "the frame will show it" and the
    menu then drew the numbered tier, a run would end up with no banner at all - so both
    consult app_tier_available rather than each testing conditions of their own."""
    for extra in (REPO_ROOT / "scripts", REPO_ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import install_helper as ih

    monkeypatch.setenv("VIRT_SURV_NO_APP", "1")
    assert ih.app_tier_available() is False
    monkeypatch.delenv("VIRT_SURV_NO_APP", raising=False)
    monkeypatch.setattr(ih, "_import_from_scripts", lambda name: None)
    assert ih.app_tier_available() is False


def test_no_new_clone_asset_is_resolved_from___file__():
    """A ratchet on a defect that has shipped three times and hid every time.

    _relocate_if_running_inside_target_repo copies install_helper.py into a bare temp
    directory and re-execs from there for the rest of the session. From that moment
    Path(__file__).parent holds one .py file and none of its siblings - so a path built
    that way is wrong AT RUNTIME, and wrong quietly: the new installer screens never ran,
    the brand banner fell back to a plain box, and scripts/ imports returned None which
    callers read as "unavailable" (all 2026-08-28, all found only by instrumenting a real
    container, none by any test).

    A NAMED ALLOW-LIST rather than a cleverer heuristic. Every legitimate use here is
    legitimate for its own specific reason - it is about the running file, or __file__ is
    a documented last resort after the configured clone has been tried - and no pattern
    match distinguishes those from the broken ones reliably. Naming them means a new use
    has to be argued for, which is the entire point: the three that shipped were all
    written without anyone asking the question."""
    src = (REPO_ROOT / "install_helper.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    allowed = {
        # About the RUNNING file, which is exactly what __file__ means.
        "_reexec_if_self_updated": "reads its own bytes to detect a self-update",
        "_relocate_if_running_inside_target_repo": "is the relocation itself",
        # __file__ as a documented LAST resort, after args.repo / installer.json.
        "_resolve_repo_root": "its docstring names __file__ as the final fallback",
        "clone_asset": "asks the resolver first, falls back for an in-place checkout",
        "_import_from_scripts": "same, and the reason clone_asset exists",
        # Candidates that are only accepted if looks_like_repo() agrees, which a bare
        # temp directory never does - and each checks the configured clone first.
        "resolve_repo": "script_root is a guarded candidate after args.repo/config",
        "locate_clone_asis": "same guarded-candidate shape",
        "check_updates_step": "same guarded-candidate shape",
        "check_for_update_upfront": "same guarded-candidate shape",
        # `(resolved / x) if resolved else Path(__file__) / x` - resolver first.
        "heal_stale_aliases": "resolver first, __file__ only when it returns nothing",
        "run_setup_alias": "resolver first, __file__ only when it returns nothing",
        "_run_evidence_room": "(repo / scripts) if repo else __file__ - resolver first",
        "_run_launcher_settings": "same",
        "_run_go": "same",
        # `_resolve_repo_root(hint) or Path(__file__)...` - resolver first, by construction.
        "run_env_check": "_resolve_repo_root(hint) or __file__",
        "run_hook_latency_diagnostic": "_resolve_repo_root(hint) or __file__",
        "run_adr014_smoke_test": "_resolve_repo_root(hint) or __file__",
        "run_daemon_start_diagnostic": "_resolve_repo_root(hint) or __file__",
        "run_selftest": "_resolve_repo_root(hint) or __file__",
    }

    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner.setdefault(line, node.name)

    # Only real __file__ EXPRESSIONS - not the prose in docstrings and comments, which
    # mentions it constantly and should.
    offenders = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__file__":
            function = owner.get(node.lineno, "<module>")
            if function not in allowed:
                offenders.setdefault(function, node.lineno)

    assert not offenders, (
        "these build a path from __file__, which at runtime is a temp copy of this file "
        "holding no siblings - use clone_asset() instead, or add the function to the "
        "allow-list with the reason it is safe:\n"
        + "\n".join(f"  {name} (line {line})" for name, line in sorted(offenders.items()))
    )
