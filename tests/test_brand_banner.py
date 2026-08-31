"""Tests for the shared VSIT brand banner (scripts/brand_banner.py).

The banner prints on every `virt-surv go` and every `virt-surv` menu, on machines this
repo cannot see - a corp Windows console that decodes stderr as cp1252, a piped capture, a
mosh session 40 columns wide. So the four things that would make it worse than no banner
at all are pinned here: non-ASCII bytes, colour that cannot be turned off, a line that
overflows the terminal, and drift between the two entry points that render it.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import brand_banner  # noqa: E402


def _paint(role, text):
    """A painter that marks every role, so a role the module emits but a caller does not
    map would show up as a KeyError rather than as silently unpainted text."""
    return f"<{role}>{text}</{role}>"


def _strip(line: str) -> str:
    for role in brand_banner.ROLES:
        line = line.replace(f"<{role}>", "").replace(f"</{role}>", "")
    return line


# --- the hard constraints -----------------------------------------------------------


class _Cp1252:
    """A console that cannot encode box-drawing glyphs, like a corp Windows one."""

    encoding = "cp1252"


@pytest.mark.parametrize("width", [40, 44, 45, 60, 64, 65, 80, 120, 200])
def test_every_line_is_pure_ascii_where_it_has_to_be(width, monkeypatch):
    """CLAUDE.md's cp1252 lesson (engage_probe._ascii_safe): a UTF-8 sequence this banner
    emitted could make a corp Windows console raise on decode, and box-drawing glyphs
    arrive as mojibake.

    The rule is now conditional rather than absolute, and the condition is the console's
    own encoding. A terminal draws '-' at mid-cell and '|' full-height, so an ASCII box
    never closes - `.-----.` over `|o o|` renders as strokes floating apart, which is what
    a photo of the real console showed. Box-drawing glyphs ARE designed to join, so they
    are correct wherever they can be encoded. Where they cannot, the banner must fall back
    to something with nothing to join up, and stay pure ASCII doing it."""
    monkeypatch.setattr(brand_banner.sys, "stderr", _Cp1252, raising=False)
    for line in brand_banner.render(width):
        assert line.isascii(), repr(line)


@pytest.mark.parametrize("width", [40, 44, 45, 60, 64, 65, 80, 120, 200])
def test_no_box_drawing_characters(width, monkeypatch):
    """On a console that cannot encode them. Where it CAN, box-drawing is the right
    choice - it is the only thing that closes a shape at terminal aspect ratio."""
    monkeypatch.setattr(brand_banner.sys, "stderr", _Cp1252, raising=False)
    text = "".join(brand_banner.render(width))
    assert not any(0x2500 <= ord(ch) <= 0x257F for ch in text)


@pytest.mark.parametrize("width", [40, 44, 45, 60, 64, 65, 80, 120, 200])
def test_the_banner_is_plain_text_on_every_console(width, monkeypatch):
    """It used to draw a mascot in box-drawing glyphs where they would render, and fall
    back to an ASCII face where they would not. There is no mascot here now (owner,
    2026-08-31: "theres another mascot shown on the fall back screens lets not have that
    displayed anywhere") - the Textual frame draws the only one, and two mascots for one
    product meant whichever you saw second read as a fault in the first.

    So the console's encoding no longer changes what this prints, which is a simplification
    worth asserting rather than merely allowing: it is now impossible for the banner to
    look different on the corporate box than it does here."""

    class _Utf8:
        encoding = "utf-8"

    monkeypatch.setattr(brand_banner.sys, "stderr", _Utf8, raising=False)
    rich = brand_banner.render(width)
    monkeypatch.setattr(brand_banner.sys, "stderr", _Cp1252, raising=False)
    plain = brand_banner.render(width)
    assert rich == plain, "the banner must not depend on what the console can encode"
    assert all(line.isascii() for line in rich), rich


@pytest.mark.parametrize("width", [40, 50, 65, 72, 80, 100])
def test_never_wider_than_the_terminal(width):
    """A banner that wraps reads as debris (the 2026-08-19 mobile/mosh lesson). Every
    tier must fit the width it was asked for."""
    for line in brand_banner.render(width):
        assert len(line) <= width, (width, len(line), line)


def test_fits_eighty_columns_at_the_documented_floor():
    """80 columns is the stated floor for the full banner."""
    assert brand_banner.FULL_WIDTH <= 80
    assert all(len(line) <= 80 for line in brand_banner.render(80))


# --- colour is the caller's, and always optional ------------------------------------


def test_renders_without_colour_by_default():
    """No paint callable means no escape sequences at all - the NO_COLOR / piped /
    dumb-terminal render."""
    lines = brand_banner.render(80)
    assert lines
    assert not any("\033" in line for line in lines)


def test_colour_is_purely_additive():
    """Painted and unpainted renders must be the same text: colour may not move a single
    column, or the boxed rows stop lining up once it is stripped."""
    plain = brand_banner.render(80)
    painted = brand_banner.render(80, _paint)
    assert [_strip(line) for line in painted] == plain


def test_every_role_emitted_is_declared():
    for width in (40, 45, 80):
        for row in brand_banner.banner(width):
            for role, _text in row:
                assert role in brand_banner.ROLES


def test_the_brand_palette_reaches_the_right_words():
    painted = "\n".join(brand_banner.render(80, _paint))
    # The subtitle's words take their colour from the wordmark letters they expand -
    # V cyan, S violet, T green - so the expansion reads as an expansion.
    assert "<cyan>Virtual </cyan>" in painted
    assert "<violet>Surveillance</violet>" in painted
    assert "<green> IT</green>" in painted
    assert "<amber>human controlled</amber>" in painted  # the one amber item, as supplied
    assert "<violet>" in painted  # the wordmark gradient's middle stop


# --- content and tiers ---------------------------------------------------------------


def test_full_tier_carries_every_element_of_the_supplied_brand():
    """Three rows: the wordmark, what it stands for, and what the team is.

    Was nine rows in a dashed box with five-row letterforms, until a photo of a real
    PowerShell console showed the letters do not read at terminal aspect ratio: a five-row
    V's diagonals never visually connect. The box went with them - noise around content
    that reads perfectly well without it, at four of the nine lines.

    The mascot went last (2026-08-31), and for a different reason: there were two of them.
    The Textual frame draws its own, and this drew a second, differently-built one directly
    above it."""
    lines = brand_banner.render(80)
    text = "\n".join(lines)
    assert len(lines) == 3
    assert brand_banner.TAGLINE in text
    assert brand_banner.FOOTER in text
    assert "V S I T" in text  # spaced caps, legible at any width in any font
    assert "+-" not in text, "the dashed box is gone; it read as debris on a real console"
    # THE SECOND MASCOT MUST NOT COME BACK. Named eyes rather than a glyph range, because
    # the ASCII fallback face was the form the corporate console actually showed.
    for face in ("o o", "o_o", "[o", "\u25cf \u25cf"):
        assert face not in text, f"a second mascot is back in the banner: {face!r}"


def test_narrow_terminals_get_the_compact_mark_not_a_wrapped_box():
    compact = brand_banner.render(brand_banner.FULL_WIDTH - 1)
    assert len(compact) == 2
    assert "+-" not in "".join(compact)
    assert brand_banner.TAGLINE in compact[1]


def test_the_narrowest_terminal_still_says_what_VSIT_stands_for():
    """_term_cols() floors at 40, so 40 has to render something legible.

    It used to drop the tagline there, because "AI TEAM FOR COMPLIANCE & SURVEILLANCE IT"
    could not fit. "Virtual Surveillance IT" does, so the narrowest terminal now keeps the
    one line that explains the four letters above it - which is the whole reason the
    subtitle exists (owner, 2026-08-28)."""
    minimal = brand_banner.render(40)
    assert len(minimal) == 2
    assert all(len(line) <= 40 for line in minimal)
    assert "V S I T" in minimal[0]
    assert brand_banner.TAGLINE in "".join(minimal)


def test_a_terminal_too_narrow_even_for_the_tagline_still_renders():
    """Below COMPACT_WIDTH the tagline gives way to the minimal mark. render() is called
    with an explicit width by install_helper, so this tier is reachable by a caller even
    though _term_cols() itself floors at 40."""
    tiny = brand_banner.render(brand_banner.COMPACT_WIDTH - 1)
    assert len(tiny) == 2
    assert brand_banner.TAGLINE not in "".join(tiny)
    assert "V S I T" in tiny[0]


# --- both entry points render the same art -------------------------------------------


def _launcher():
    spec = importlib.util.spec_from_file_location(
        "brandbanner_launcher", REPO_ROOT / "scripts" / "virt_team_launcher.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_launcher_banner_matches_the_shared_module(monkeypatch, capsys):
    mod = _launcher()
    monkeypatch.setattr(mod, "_term_cols", lambda: 80)
    monkeypatch.setattr(mod, "_rich_ui", lambda: None)
    monkeypatch.setattr(mod, "_color_enabled", lambda: False)
    mod._print_banner(Path("."))
    err = capsys.readouterr().err
    for line in brand_banner.render(80):
        assert line in err


def test_installer_banner_matches_the_shared_module():
    import install_helper

    rows = install_helper.brand_banner_rows(install_helper.Style(False), width=80)
    assert rows == brand_banner.render(80)


def test_installer_falls_back_to_its_boxed_banner_without_the_shared_module(monkeypatch, capsys):
    """install_helper is also shipped as a lone curl-bootstrapped file with no scripts/
    sibling. Losing the art must cost looks only - the menu still has to introduce itself."""
    import install_helper

    monkeypatch.setattr(install_helper, "brand_banner_rows", lambda *a, **k: [])
    install_helper.print_banner(install_helper.Style(False), stream=io.StringIO())
    out = capsys.readouterr().out
    assert install_helper.BANNER_TITLE in out
    assert "Morgan (PM)" in out


def test_installer_strips_colour_when_the_style_is_disabled():
    import install_helper

    rows = install_helper.brand_banner_rows(install_helper.Style(False), width=80)
    assert rows and not any("\033" in row for row in rows)
    lit = install_helper.brand_banner_rows(install_helper.Style(True), width=80)
    assert any("\033" in row for row in lit)


def test_launcher_strips_colour_under_no_color(monkeypatch, capsys):
    """The NO_COLOR contract, end to end through the launcher's own detector."""
    mod = _launcher()
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(mod, "_term_cols", lambda: 80)
    monkeypatch.setattr(mod, "_rich_ui", lambda: None)
    mod._print_banner(Path("."))
    err = capsys.readouterr().err
    assert "\033" not in err
    assert brand_banner.TAGLINE in err
