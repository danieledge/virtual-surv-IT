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
_ROBOT = (
    "     .o.    ",
    "   .-----.  ",
    "  -|o   o|- ",
    "   '-(v)-'  ",
)
_ROBOT_INK = ("cyan", "cyan", "cyan", "violet")

# The wordmark: spaced caps, cyan -> violet -> green, as in the source gradient.
_WORDMARK = (("V", "cyan"), ("S", "violet"), ("I", "violet"), ("T", "green"))
_ART_ROWS = 4

TAGLINE = "AI TEAM FOR COMPLIANCE & SURVEILLANCE IT"
FOOTER = "specialist | independent review | human controlled"

INDENT = "  "
# The widest row, computed rather than estimated: every row is indent + a mascot row + one
# space + its text, and the longest text is the footer, not the tagline. Getting this wrong
# by one column let the full tier render at 64 columns while needing 65 - which is the exact
# class of bug the width tiers exist to prevent.
FULL_WIDTH = len(INDENT) + max(len(row) for row in _ROBOT) + 1 + max(len(TAGLINE), len(FOOTER))
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
    """The tagline; the two domain words carry the colour, as in the source image."""
    return [
        ("bold", "AI TEAM FOR "),
        ("cyan", "COMPLIANCE"),
        ("bold", " & "),
        ("green", "SURVEILLANCE"),
        ("bold", " IT"),
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
    """Four rows: the mascot on the left, the three text lines beside it.

    Blank text rows are deliberate - the mascot is four rows tall and the text is three, so
    the antenna row carries no text rather than the mascot being cropped to fit."""
    beside = [[], _wordmark_segments(), _tagline_segments(), _footer_segments()]
    rows = []
    for index in range(_ART_ROWS):
        row = [("plain", INDENT), (_ROBOT_INK[index], _ROBOT[index]), ("plain", " ")]
        row += beside[index]
        rows.append(row)
    return rows


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
