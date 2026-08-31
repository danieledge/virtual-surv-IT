"""The VSIT brand banner, rendered as terminal art for both front doors.

One implementation, two callers: `virt-surv go` (scripts/virt_team_launcher.py's
`_print_banner`) and `virt-surv` with no args (install_helper.py's `print_banner`).
Neither owns the art, so a brand change is a single edit here.

Three constraints shaped every decision below:

* **Pure ASCII, no box-drawing glyphs.** Same lesson `scripts/engage_probe.py::_ascii_safe`
  and `virt_team_launcher._print_project_defaults` already carry: corp Windows consoles
  decode this output as cp1252, and box-drawing glyphs arrive as mojibake - some UTF-8
  sequences make such a console raise outright. The source brand image is a dotted/dashed
  outline design, which is lucky: the aesthetic is reproducible in `- . ' | + ( )` alone,
  so the ASCII rendition is a deliberate style rather than a degraded one. A test asserts
  every emitted byte is ASCII.
* **Colour is optional and supplied by the caller.** This module never emits an escape
  sequence itself. It hands out `(role, text)` segments and the caller's `paint` callable
  decides - so `_Ink`'s tty/NO_COLOR/Windows-VT detection and `Style`'s NO_COLOR/tty
  detection each stay the single authority in their own file, and the uncoloured render is
  the same text with the same alignment.
* **It has to fit.** 80 columns is the floor, but `_term_cols()` floors at 40 for a
  mobile/mosh screen, so there are three tiers (`render` picks by width): the full box at
  >= 65, a two-line compact mark at >= 45, and a minimal mark below that. Nothing wraps.

Cost: the full tier is 9 lines, which is what a banner with a mascot, a wordmark, a tagline
and a strapline costs. The compact tiers are 2.
"""

from __future__ import annotations

import sys

# ------------------------------------------------------------------ palette roles
# Role names, not colours: the caller maps them onto whatever painter it already has.
# "plain" must always render unchanged - it is the alignment-safe default.
ROLES = ("plain", "dim", "cyan", "violet", "green", "amber", "bold")

# ------------------------------------------------------------------ the art
#
# WHY THIS IS NOT BLOCK-GLYPH LETTERING (2026-08-28). The first version drew VSIT as
# five-row segmented letterforms in `- . ' |`, matching the source image's dotted style.
# A live photo of a corporate PowerShell console settled it: the letters do not read. A
# terminal cell is roughly twice as tall as it is wide, so a five-row V's diagonals never
# visually connect - they land as scattered apostrophes - and the S, I and T become
# columns of punctuation. Owner's verdict on the screenshot: "looks a bit ugly."
#
# That vindicates a 2026-08-19 comment the first version overrode, which said in terms:
# "NOT block-glyph ASCII art - hand-drawn art at this width reads as amateur and
# illegible." It was right. The wordmark is spaced caps again, which is legible at any
# width, in any font, on any console.
#
# What survives from the source image: the mascot (antenna, eyes, ears, smile, and the
# shield-with-tick as `(v)`), the gradient across the letters, and the two coloured domain
# words. What went: five-row letterforms, and the dashed box - the box was pure noise
# around content that reads perfectly well without it, and it cost four of the nine lines.
# TWO MASCOTS, and which one appears is decided by the console, not by preference.
#
# A terminal draws '-' at mid-cell height and '|' over the full cell, so an ASCII box never
# closes: `.-----.` above `|o   o|` renders as strokes floating apart, which is exactly what
# a photo of the corporate PowerShell console showed ("robot looks rubbish", 2026-08-28,
# and the same verdict on the letterforms the day before). Box-drawing glyphs are designed
# to join, so the box form is correct wherever it can be encoded - and cp1252, which is
# what that console decodes as, cannot encode it.
#
# So: the drawn robot where it will look drawn, and a one-line face where it will not.
# `[o_o]` needs nothing to join up - brackets are full-height glyphs and the face reads
# instantly - which is the whole reason it is the fallback rather than a smaller box.
_ROBOT_UNICODE = (
    " \u256d\u2500\u2500\u2500\u2500\u2500\u256e ",
    "\u2500\u2524 o o \u251c\u2500",
    " \u2570\u2500\u2500\u2500\u2500\u2500\u256f ",
)
_ROBOT_ASCII = ("[o_o]", "     ", "     ")
_ROBOT_INK = ("cyan", "cyan", "violet")
_ART_ROWS = 3

# The wordmark: spaced caps, cyan -> violet -> green, as in the source gradient.
_WORDMARK = (("V", "cyan"), ("S", "violet"), ("I", "violet"), ("T", "green"))


def _can_encode(text: str) -> bool:
    """Can stderr actually render these glyphs?

    The same question _can_encode in virt_team_launcher answers, asked here so this module
    stays importable on its own - install_helper loads it from a bare clone where the
    launcher may not be on sys.path.

    `sys` is imported at module level rather than here so a test can substitute a console
    with a different encoding; a function-local import is invisible to monkeypatch."""
    try:
        text.encode(getattr(sys.stderr, "encoding", None) or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _robot() -> tuple:
    """The mascot rows for THIS console."""
    return _ROBOT_UNICODE if _can_encode("".join(_ROBOT_UNICODE)) else _ROBOT_ASCII


# The acronym expanded, because that is what a subtitle under a wordmark is for
# (owner, 2026-08-28). The previous line described the team; it did not say what the
# four letters above it stood for, which is the one job the position had.
TAGLINE = "Virtual Surveillance IT"
FOOTER = "specialist | independent review | human controlled"

INDENT = "  "
# The widest row, computed rather than estimated: every row is indent + a mascot row + one
# space + its text, and the longest text is the footer, not the tagline. Getting this wrong
# by one column let the full tier render at 64 columns while needing 65 - which is the exact
# class of bug the width tiers exist to prevent.
# No mascot column any more, so the widest row is just the indent and the longest text -
# which is the footer, not the tagline. Computed rather than estimated: getting this wrong
# by one column let the full tier render at a width it did not fit, which is the exact
# class of bug the width tiers exist to prevent.
FULL_WIDTH = len(INDENT) + max(len(TAGLINE), len(FOOTER))
# Below this the mascot is dropped and only the two text lines remain.
COMPACT_WIDTH = len(INDENT) + 3 + len(TAGLINE)
_MINIMAL_TAG = "compliance surveillance IT"


def _plain(segments) -> str:
    return "".join(text for _role, text in segments)


def _wordmark_segments() -> list:
    """V S I T, spaced, each letter carrying its own colour."""
    out: list = []
    for position, (letter, role) in enumerate(_WORDMARK):
        if position:
            out.append(("plain", " "))
        out.append((role, letter))
    return out


def _tagline_segments() -> list:
    """The tagline: each word takes its colour from the letter it stands for in the
    wordmark above it (V cyan, S violet, T green), so the expansion reads as an
    expansion rather than as a second, unrelated line of text."""
    return [
        ("cyan", "Virtual "),
        ("violet", "Surveillance"),
        ("green", " IT"),
    ]


def _footer_segments() -> list:
    """The strapline; "human controlled" is the amber one, as in the source image."""
    return [
        ("dim", "specialist"),
        ("dim", " | "),
        ("dim", "independent review"),
        ("dim", " | "),
        ("amber", "human controlled"),
    ]


def _full_banner() -> list:
    """Three rows: the wordmark, what it stands for, and what the team is.

    NO MASCOT HERE (owner, 2026-08-31). There were two of them: the Textual mark draws its
    own robot inside the frame, and this printed a different one - different construction,
    different eyes, a cp1252 fallback face the other has no equivalent of - directly above
    it. Two mascots for one product is worse than either alone, because whichever a person
    meets second reads as a rendering fault in the first. The one in the frame stays; it is
    the one on screen while the thing is being used.

    _ROBOT_UNICODE, _ROBOT_ASCII and _robot() are kept below rather than deleted. They
    carry the reason an ASCII box never closes in a terminal, which is exactly the
    reasoning someone needs before drawing one here again."""
    return [
        [("plain", INDENT)] + _wordmark_segments(),
        [("plain", INDENT)] + _tagline_segments(),
        [("plain", INDENT)] + _footer_segments(),
    ]


def _compact_banner(with_tagline: bool) -> list:
    """Two lines for terminals the box cannot fit: a spaced-caps mark behind a bar, then
    either the full tagline or a short one. Same shape the pre-2026-08-27 wordmark used,
    which is known to survive narrow screens."""
    mark = [("plain", INDENT), ("cyan", "|"), ("plain", "  ")]
    mark += [
        ("cyan", "V"),
        ("plain", " "),
        ("violet", "S"),
        ("plain", " "),
        ("violet", "I"),
        ("plain", " "),
        ("green", "T"),
    ]
    second = [("plain", INDENT), ("cyan", "|"), ("plain", "  ")]
    second += _tagline_segments() if with_tagline else [("dim", _MINIMAL_TAG)]
    return [mark, second]


def banner(width: int = 80) -> list:
    """The banner for a terminal `width` columns wide, as rows of (role, text) segments."""
    if width >= FULL_WIDTH:
        return _full_banner()
    return _compact_banner(with_tagline=width >= COMPACT_WIDTH)


def render(width: int = 80, paint=None) -> list:
    """The banner as printable strings. `paint(role, text)` supplies colour; the default
    returns the text unchanged, which is exactly what a NO_COLOR / piped / dumb terminal
    must see."""
    if paint is None:

        def paint(_role, text):
            return text

    return ["".join(paint(role, text) for role, text in row) for row in banner(width)]
