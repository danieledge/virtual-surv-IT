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
# The mascot: antenna dot, rounded head, two eyes, side ears, a smile, and the
# shield-with-a-tick as (v) on the chin. Five rows so it sits level with the wordmark.
_ROBOT = (
    "    .o.    ",
    "  .-----.  ",
    " -|o   o|- ",
    "  | \\_/ |  ",
    "  '-(v)-'  ",
)
_ROBOT_INK = ("cyan", "cyan", "cyan", "violet", "violet")

# The wordmark. V is drawn as two dotted diagonals; S, I and T are segment strokes - the
# same construction as the source image's segmented letterforms. Widths vary per letter
# (a narrow I, a wide V) because uniform cells read as a grid, not as type.
_GLYPHS = {
    "V": ("'.       .'", " '.     .' ", "  '.   .'  ", "   '. .'   ", "    '-'    "),
    "S": (".-------.", "|        ", "'-------.", "        |", "'-------'"),
    "I": (".---.", "  |  ", "  |  ", "  |  ", "'---'"),
    "T": (".-------.", "    |    ", "    |    ", "    |    ", "    |    "),
}
# cyan -> violet -> green across the wordmark, matching the source gradient.
_WORDMARK = (("V", "cyan"), ("S", "violet"), ("I", "violet"), ("T", "green"))
_LETTER_GAP = "  "
_ART_ROWS = 5

TAGLINE = "AI TEAM FOR COMPLIANCE & SURVEILLANCE IT"
FOOTER = "SPECIALIST AI TEAM | INDEPENDENT REVIEW | HUMAN CONTROLLED"

# Inner width of the box, sized to the footer (the widest element) plus one column of
# slack so the dashed rule can start AND end on a dash (it needs an odd span).
CONTENT_WIDTH = 59
BOX_WIDTH = CONTENT_WIDTH + 4  # ':' + ' ' + content + ' ' + ':'
INDENT = "  "
FULL_WIDTH = BOX_WIDTH + len(INDENT)
# Width below which the box is dropped, then below which the tagline is dropped.
COMPACT_WIDTH = len(INDENT) + 3 + len(TAGLINE)

# ':' rather than '|' for the box sides: it reads as the dashed vertical the source image
# has, and it does not collide with the '|' separators inside the footer text.
_SIDE = ":"
_CORNER = "+"
_MINIMAL_TAG = "compliance surveillance IT"


def _rule() -> str:
    """The dashed horizontal: a dash on every even column so both ends land on a dash."""
    span = CONTENT_WIDTH + 2
    return "".join("-" if i % 2 == 0 else " " for i in range(span))


def _plain(segments) -> str:
    return "".join(text for _role, text in segments)


def _centre(segments, width: int) -> list:
    """Pad `segments` to `width`, centred, using unpainted spaces."""
    slack = width - len(_plain(segments))
    if slack <= 0:
        return list(segments)
    left = slack // 2
    return [("plain", " " * left), *segments, ("plain", " " * (slack - left))]


def _art_row(index: int) -> list:
    """One row of mascot + wordmark, as coloured segments."""
    segments = [(_ROBOT_INK[index], _ROBOT[index]), ("plain", " ")]
    for position, (letter, role) in enumerate(_WORDMARK):
        if position:
            segments.append(("plain", _LETTER_GAP))
        segments.append((role, _GLYPHS[letter][index]))
    return segments


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
    """The strapline; "HUMAN CONTROLLED" is the amber one, as in the source image."""
    return [
        ("plain", "SPECIALIST AI TEAM"),
        ("dim", " | "),
        ("plain", "INDEPENDENT REVIEW"),
        ("dim", " | "),
        ("amber", "HUMAN CONTROLLED"),
    ]


def _boxed_line(segments) -> list:
    side = [("dim", _SIDE)]
    return [*side, ("plain", " "), *_centre(segments, CONTENT_WIDTH), ("plain", " "), *side]


def _full_banner() -> list:
    rule = [("dim", _CORNER + _rule() + _CORNER)]
    rows = [rule]
    rows += [_boxed_line(_art_row(i)) for i in range(_ART_ROWS)]
    rows.append(_boxed_line(_tagline_segments()))
    rows.append(_boxed_line(_footer_segments()))
    rows.append(rule)
    return [[("plain", INDENT), *row] for row in rows]


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
