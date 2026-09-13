"""House style, mechanically (2026-09-13 framework review, step 6.3).

The owner's writing rule for everything the team ships: no em or en dashes, and none of the
framing words that read as machine-written. Plain hyphens with spaces are the house dash.
Prose files are held to the whole list; code comments are held to the filler words and the
dashes, because "honest" is a defined term in a few review-method comments. Transcripts,
internal notes, ADRs, release notes and the CHANGELOG are history and exempt; the live hook
files are exempt until the human applies the staged copies, which the sync tests pin."""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_PROSE = (
    "README.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/**/*.md",
    ".claude/skills/**/*.md",
    ".claude/agents/*.md",
)
_CODE = (
    "scripts/*.py",
    "scripts/staged_hooks/*.py",
    "scripts/*.sh",
    "install_helper.py",
    "tests/*.py",
)
_EXEMPT_PREFIXES = ("docs/demos/transcripts", "docs/internal", "docs/adr", "docs/releases")
_FILLER = re.compile(r"\b(?:genuinely|truly|robust|leverage|delve)\b", re.I)
_FRAMING = re.compile(r"\bhonest(?:ly)?\b", re.I)
_DASHES = re.compile(r"[—–]")


def _files(patterns) -> list[str]:
    out = []
    for pattern in patterns:
        out += glob.glob(str(REPO / pattern), recursive=True)
    rel = sorted({str(Path(f).relative_to(REPO)).replace("\\", "/") for f in out})
    return [
        f
        for f in rel
        if not f.startswith(_EXEMPT_PREFIXES)
        and f != Path(__file__).name
        and not f.endswith("tests/test_house_style.py")
    ]


def _offences(rel: str, patterns) -> list[str]:
    text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    if rel == "README.md":
        # The Why essay is the owner's locked text (test_readme_why_essay_unchanged); the
        # style rule does not reach into it.
        start, end = text.index("## 🤔 Why Virtual Surv-IT?"), text.index("## ✨ Features")
        text = text[:start] + "\n" * text[start:end].count("\n") + text[end:]
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for pat in patterns:
            if pat.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:80]}")
                break
    return hits


@pytest.mark.parametrize("rel", _files(_PROSE), ids=lambda r: r)
def test_prose_carries_no_dashes_or_framing_words(rel):
    hits = _offences(rel, (_FILLER, _FRAMING, _DASHES))
    assert not hits, "house style: " + "; ".join(hits)


@pytest.mark.parametrize("rel", _files(_CODE), ids=lambda r: r)
def test_code_carries_no_filler_words(rel):
    """Code is held to the filler words only: a dash character inside a string literal is
    output formatting or a normalisation table (scripts/engage_probe.py maps both dashes to
    a hyphen), not prose, and rewriting it changes behaviour."""
    hits = _offences(rel, (_FILLER,))
    assert not hits, "house style: " + "; ".join(hits)
