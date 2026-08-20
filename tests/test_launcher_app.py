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
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
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
