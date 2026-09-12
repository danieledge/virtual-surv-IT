"""The plain/numbered launcher tier - the one that runs where neither full-screen tier can.

WHY IT HAS A FILE OF ITS OWN (2026-09-12 audit, L-37). Textual has tests/test_launcher_tier.py,
prompt_toolkit has tests/test_launcher_app.py, the installer's picker has
tests/test_installer_app.py. The numbered tier - the one every locked-down corporate box
actually gets, and the reason this whole subsystem exists - had none: its 199-line `_menu_round`
was reached only incidentally from tests/test_virt_team_launcher.py. L-7 (the [n] key silently
skipping the request composer and the unattended offer) lived in exactly that function and no
test caught it.

So: drive `_menu_round` key by key with VIRT_SURV_NO_APP=1, and assert that every option the app
tiers offer is reachable here and produces the same decision.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _extra in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))


def _load():
    spec = importlib.util.spec_from_file_location(
        "virt_team_launcher", REPO_ROOT / "scripts" / "virt_team_launcher.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["virt_team_launcher"] = module
    spec.loader.exec_module(module)
    return module


def _row(slug="alpha", title="Alpha work", status="in_progress"):
    return {
        "dir": slug,
        "slug": slug,
        "title": title,
        "status": status,
        "opened": "2026-09-01",
        "phase": "plan",
        "outstanding": 0,
    }


def _menu(rows):
    return {
        "open": [r["dir"] for r in rows],
        "shown": rows,
        "more": 0,
        "archived": 0,
        "default": rows[0]["dir"] if rows else None,
    }


@pytest.fixture
def plain(monkeypatch, tmp_path):
    """A launcher pinned to the numbered tier, in a configured project."""
    monkeypatch.setenv("VIRT_SURV_NO_APP", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    mod = _load()
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "_engage_command", lambda p: "/engage")
    monkeypatch.setattr(mod, "_jira_offered", lambda p: True)
    monkeypatch.setattr(mod, "_running_slug", lambda p: "")
    monkeypatch.setattr(mod, "_suggestion_line", lambda p, m: "")
    monkeypatch.setattr(mod, "_hold_for_reader", lambda: None)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True, raising=False)
    return mod, project


def _press(mod, monkeypatch, keys, project, rows):
    """Feed `keys` to the numbered menu and return its decision."""
    typed = iter(keys)
    monkeypatch.setattr("builtins.input", lambda *a: next(typed))
    return mod._menu_round(project, None, _menu(rows), rows)


# --------------------------------------------------------------------- the resume rows


def test_a_numbered_pick_resumes_that_engagement(plain, monkeypatch):
    mod, project = plain
    rows = [_row(), _row(slug="beta", title="Beta work")]
    assert _press(mod, monkeypatch, ["2"], project, rows) == "/engage --resume beta"


def test_enter_decides_inside_the_session(plain, monkeypatch):
    """An empty answer is the documented plain launch, not an abort."""
    mod, project = plain
    assert _press(mod, monkeypatch, [""], project, [_row()]) == ""


def test_ctrl_c_backs_out_rather_than_launching(plain, monkeypatch):
    """Same as Esc in the app tiers: backing out returns you to the terminal."""
    mod, project = plain

    def _interrupt(*_a):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _interrupt)
    assert mod._menu_round(project, None, _menu([_row()]), [_row()]) == mod._ABORT


def test_a_pipe_takes_the_documented_plain_launch(plain, monkeypatch):
    """EOF is CI and `go < /dev/null`, and must keep behaving as it always has."""
    mod, project = plain

    def _eof(*_a):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert mod._menu_round(project, None, _menu([]), []) == ""


def test_an_unrecognised_key_explains_itself(plain, monkeypatch, capsys):
    mod, project = plain
    assert _press(mod, monkeypatch, ["zzz"], project, [_row()]) == ""
    assert "not recognised" in capsys.readouterr().err


def test_a_number_out_of_range_explains_itself(plain, monkeypatch, capsys):
    mod, project = plain
    assert _press(mod, monkeypatch, ["9"], project, [_row()]) == ""
    assert "out of range" in capsys.readouterr().err


# ------------------------------------------------------------ every hotkey is reachable


def test_n_asks_for_a_request_like_the_app_tiers_do(plain, monkeypatch, capsys):
    """L-7. This is the finding: [n] returned a bare `--new` and said nothing, so the
    request composer and the unattended offer were simply absent on this tier with no way
    to tell."""
    mod, project = plain
    monkeypatch.setattr(mod, "_auto_offered", lambda p: True)
    decision = _press(mod, monkeypatch, ["n", "tighten the wash-trade window", "n"], project, [])
    assert decision.startswith("/engage --new")
    assert "--request-pending" in decision
    err = capsys.readouterr().err
    assert "What would you like the team to do?" in err
    assert "Run this unattended" in err


def test_n_with_an_empty_request_is_exactly_the_old_plain_new(plain, monkeypatch):
    """Typing is an OFFER, never a toll gate."""
    mod, project = plain
    monkeypatch.setattr(mod, "_auto_offered", lambda p: False)
    assert _press(mod, monkeypatch, ["n", ""], project, []) == "/engage --new"


def test_j_collects_a_ticket_and_offers_unattended(plain, monkeypatch, capsys):
    """The path fixed on 2026-09-11, pinned here so the pair cannot drift apart again."""
    mod, project = plain
    monkeypatch.setattr(mod, "_auto_offered", lambda p: True)
    monkeypatch.setattr(mod, "_jira_enabled", lambda p: True)
    decision = _press(mod, monkeypatch, ["j", "SURV-42", "n"], project, [])
    assert decision == "/engage --new --jira SURV-42"
    assert "Run this unattended" in capsys.readouterr().err


def test_both_new_paths_route_an_unattended_yes_to_the_same_gate(plain, monkeypatch):
    """[n] and [j] must reach ONE pre-flight. Two ways to authorise an unattended run is
    two places for the authorisation to be wrong."""
    mod, project = plain
    seen = []
    monkeypatch.setattr(mod, "_auto_offered", lambda p: True)
    monkeypatch.setattr(mod, "_jira_enabled", lambda p: True)
    monkeypatch.setattr(
        mod,
        "_auto_run_decision",
        lambda p, ref, request_text="": seen.append((ref, request_text)) or "/engage --auto",
    )
    assert _press(mod, monkeypatch, ["n", "do the thing", "y"], project, []) == "/engage --auto"
    assert _press(mod, monkeypatch, ["j", "SURV-9", "y"], project, []) == "/engage --auto"
    assert seen == [("do the thing", "do the thing"), ("SURV-9", "")]


def test_c_opens_the_settings_editor_and_returns_to_the_menu(plain, monkeypatch):
    mod, project = plain
    opened = []
    monkeypatch.setattr(mod, "_run_settings_editor", lambda p: opened.append(p))
    assert _press(mod, monkeypatch, ["c"], project, [_row()]) == "__again__"
    assert opened == [project]


def test_a_archives_and_returns_to_the_menu(plain, monkeypatch):
    mod, project = plain
    ran = []
    monkeypatch.setattr(mod, "_archive_menu", lambda p, es, m: ran.append(1))
    assert _press(mod, monkeypatch, ["a"], project, [_row()]) == "__again__"
    assert ran == [1]


def test_question_mark_prints_the_plain_legend(plain, monkeypatch, capsys):
    """[?] needs prompt_toolkit for its screen, and this tier is shown PRECISELY when that
    cannot draw - so it fell through to nothing and looked broken."""
    mod, project = plain
    assert _press(mod, monkeypatch, ["?"], project, [_row()]) == "__again__"
    assert capsys.readouterr().err.strip(), "the legend must actually print"


def test_b_opens_the_done_and_archived_review(plain, monkeypatch):
    mod, project = plain
    monkeypatch.setattr(mod, "_tiered_screen", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_finished_menu", lambda p, es: "gamma")
    assert _press(mod, monkeypatch, ["b"], project, [_row()]) == "/engage --review gamma"


def test_o_hands_back_a_chdir_instruction(plain, monkeypatch, tmp_path):
    """The explorer's answer is a directory change, not a launch - the v7 wrapper reads it
    out of the handshake file."""
    mod, project = plain
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setattr(mod, "_browse_decision", lambda p: other)
    decision = _press(mod, monkeypatch, ["o"], project, [_row()])
    assert decision == mod._CHDIR_PREFIX + str(other)


def test_m_shows_the_rest_of_a_long_list(plain, monkeypatch):
    """The menu arrives uncapped, so this tier caps it - and the remainder must be
    reachable rather than merely counted."""
    mod, project = plain
    rows = [_row(slug=f"e{i}", title=f"Work {i}") for i in range(mod._PLAIN_TIER_ROWS + 3)]
    assert _press(mod, monkeypatch, ["m"], project, rows) == mod._SHOW_ALL


def test_v_opens_the_artifacts_of_the_only_engagement(plain, monkeypatch):
    mod, project = plain
    monkeypatch.setattr(mod, "_tiered_screen", lambda *a, **k: None)
    shown = []
    monkeypatch.setattr(mod, "_artifacts_plain", lambda p, slug: shown.append(slug))
    assert _press(mod, monkeypatch, ["v"], project, [_row()]) == "__again__"
    assert shown == ["alpha"]


# --------------------------------------------------- parity with the tiers above it


def test_every_app_tier_hotkey_is_offered_here_too(plain, monkeypatch, capsys):
    """The drift this whole effort exists to prevent: the app tiers build their own action
    lists, and a key present there and missing here is invisible until someone on a corp
    box goes looking for it."""
    mod, project = plain
    monkeypatch.setattr(mod, "_running_slug", lambda p: "alpha")
    try:
        _press(mod, monkeypatch, [""], project, [_row()])
    except StopIteration:  # pragma: no cover - the menu always reads exactly once
        pass
    rendered = capsys.readouterr().err
    for key in ("[n]", "[j]", "[c]", "[o]", "[v]", "[a]", "[b]", "[t]", "[?]", "[Enter]"):
        assert key in rendered, f"{key} is offered by the app tiers and not by this one"


def test_the_rows_come_from_the_shared_view_builder(plain, monkeypatch, capsys):
    """Row CONTENT comes from row_view() on every tier. Two renderers keeping a table in
    visual sync by hand is how they diverged for real on 2026-08-19."""
    mod, project = plain
    row = _row(title="Threshold tuning", status="blocked")
    view = mod.row_view(row, default_slug="alpha", of_many=False)
    _press(mod, monkeypatch, [""], project, [row])
    rendered = capsys.readouterr().err
    assert view["title"] in rendered
    assert view["slug"] in rendered


def test_the_decision_never_reaches_stdout(plain, monkeypatch, capsys):
    """The output contract: stdout carries the decision and main() prints it, so the menu
    itself must write nothing there at all."""
    mod, project = plain
    _press(mod, monkeypatch, ["1"], project, [_row()])
    assert capsys.readouterr().out == ""


# ------------------------------------------- the installer's own numbered fall-through


def test_the_installer_submenu_never_draws_a_second_screen_over_the_first(monkeypatch):
    """L-36/L-6. Every existing test monkeypatched _submenu_screen away, so the dispatcher's
    own logic - the copy that was missing the APPS_RUN fix - was never executed. This drives
    the real one with two stub tiers: the first draws and answers None, and the second must
    never be reached."""
    import install_helper as ih

    drawn = []

    class _Drew:
        APPS_RUN = 0

        @staticmethod
        def chooser_screen(*_a, **_k):
            _Drew.APPS_RUN += 1
            drawn.append("textual")
            return None  # it RAN and the human backed out

    class _Underneath:
        APPS_RUN = 0

        @staticmethod
        def chooser_screen(*_a, **_k):
            drawn.append("prompt_toolkit")
            return "install"

    monkeypatch.delenv("VIRT_SURV_NO_APP", raising=False)
    monkeypatch.setattr(
        ih,
        "_import_from_scripts",
        lambda name: {"launcher_textual": _Drew, "installer_app": _Underneath}.get(name),
    )
    picked = ih._submenu_screen(ih.Style(False), "Advanced", (("a", "one"),), {})
    assert picked is None, "a screen that ran answers for itself"
    assert drawn == ["textual"], "the older renderer must not be drawn over it"


def test_the_installer_submenu_still_falls_through_a_tier_that_cannot_draw(monkeypatch):
    """The other half. A tier that never drew must not stop the fall-through, or a box
    without Textual loses its menu entirely."""
    import install_helper as ih

    class _CannotDraw:
        APPS_RUN = 0

        @staticmethod
        def chooser_screen(*_a, **_k):
            return None  # never drew

    class _Drew:
        APPS_RUN = 0

        @staticmethod
        def chooser_screen(*_a, **_k):
            _Drew.APPS_RUN += 1
            return "install"

    monkeypatch.delenv("VIRT_SURV_NO_APP", raising=False)
    monkeypatch.setattr(
        ih,
        "_import_from_scripts",
        lambda name: {"launcher_textual": _CannotDraw, "installer_app": _Drew}.get(name),
    )
    assert ih._submenu_screen(ih.Style(False), "Advanced", (("a", "one"),), {}) == "install"


def test_no_hand_rolled_tier_loop_survives_anywhere():
    """The structural half of L-6: the fall-through exists ONCE per front door. A new copy
    is how the APPS_RUN fix went missing from two of four in the first place."""
    for name, dispatcher in (
        (
            "scripts/virt_team_launcher.py",
            'for module_name in ("launcher_textual", "launcher_app")',
        ),
        ("install_helper.py", 'for module_name in ("launcher_textual", "installer_app")'),
    ):
        source = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert source.count(dispatcher) == 1, f"{name}: the dispatcher is duplicated"
        assert 'for _tier in ("launcher_textual"' not in source, f"{name}: a hand-rolled copy"


def test_the_plain_tier_is_what_runs_with_no_app(plain, monkeypatch, capsys):
    """The gate itself: VIRT_SURV_NO_APP is the documented escape hatch and it must reach
    this tier, not a half-disabled version of one above it."""
    mod, project = plain
    tried = []
    monkeypatch.setattr(mod, "_tiered_screen", lambda *a, **k: tried.append(a) or None)
    _press(mod, monkeypatch, [""], project, [_row()])
    assert tried == [], "no full-screen tier may be reached with VIRT_SURV_NO_APP set"
    assert "How would you like to start?" in capsys.readouterr().err


def test_the_menu_survives_a_project_with_no_engagements(plain, monkeypatch, capsys):
    mod, project = plain
    assert _press(mod, monkeypatch, [""], project, []) == ""
    rendered = capsys.readouterr().err
    assert "no open engagements" in rendered
    assert "[n]" in rendered, "starting new must still be offered"


def test_the_engagement_state_module_is_never_required_by_this_tier(plain, monkeypatch):
    """It is passed in as None throughout this file on purpose: the numbered tier renders
    from the menu dict it is given, so a project whose state module will not import still
    gets a working menu."""
    mod, project = plain
    assert _press(mod, monkeypatch, ["1"], project, [_row()]) == "/engage --resume alpha"


def test_the_menu_dict_is_not_mutated_by_a_notice(plain, monkeypatch):
    """A pending notice is carried into the draw as a copy - the caller recomputes the menu
    between rounds and a mutated dict would carry a stale notice into the next one."""
    mod, project = plain
    mod._notice("nothing was archived")
    menu = _menu([_row()])
    typed = iter([""])
    monkeypatch.setattr("builtins.input", lambda *a: next(typed))
    mod._menu_round(project, None, menu, [_row()])
    assert "notice" not in menu
    assert json.dumps(menu)  # still a plain serialisable dict
