"""Phase 4 of the 2026-07-29 remediation: the codebase map's provenance must be real
(register M1/M2/M3/M7).

M1 [reproduced] - the shipped template's own Anchor placeholder contains the words
`no-vcs`, which the gate accepted as a valid anchor: a map created from the template with
the placeholder untouched passed the whole gate while claiming "no VCS" in a git repo.
The no-vcs escape is now strict (the anchor VALUE must be the token, immediately after the
label), and an unfilled `<...>` placeholder is called out.

M2 - per-entry anchors and as-of dates were never validated (only the 📊/🧠 glyph was):
entry SHAs read as verified provenance on resume and were decorative.

M3 - no staleness bound existed at all: the header anchor is now compared against HEAD and
MAP-STALE fires when the anchored commit is more than the staleness budget behind
(default 50 commits, overridable in the map header with a rationale - CLAUDE.md §4).

M7 - the entries scan keyed on the literal section name "map entries" (a rename disabled
every row check) and the 250-line cap counted the Deprecated section ADR-003 mandates
keeping. Detection is now column-driven (a table with a Basis column) and the cap excludes
Deprecated.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_artifacts import check_map

REPO_ROOT = Path(__file__).resolve().parents[1]


def _touch(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _map_repo(tmp_path, commits=1):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    shas = []
    for i in range(commits):
        _git(
            repo,
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            f"c{i}",
        )
        shas.append(
            subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    return repo, shas


def _map(sha, entry_asof="2026-07-18", entry_anchor=None, header_extra=""):
    entry_anchor = entry_anchor if entry_anchor is not None else f"`{sha[:9]}`"
    return (
        "# Codebase Map - Proj\n\n"
        f"> **Document control** · Owner `Morgan (PM)` · As-of `2026-07-18` · Anchor `{sha}`"
        f"{header_extra}\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor |\n"
        "|---|------|-------|-------|-------|--------|\n"
        f"| 1 | rules | threshold rationale in x.py | 📊 seen | {entry_asof} | {entry_anchor} |\n"
    )


# --- M1: the raw template must not pass -----------------------------------------------------


def test_shipped_template_fails_the_gate_raw(tmp_path):
    """[reproduced] The template's own placeholder used to pass as a no-vcs anchor."""
    template = (REPO_ROOT / "docs" / "templates" / "codebase-map.md").read_text(encoding="utf-8")
    m = tmp_path / "docs" / "codebase-map.md"
    _touch(m, template)
    codes = "".join(check_map(m))
    assert "MAP-NO-ANCHOR" in codes
    assert "placeholder" in codes.lower()


def test_strict_novcs_value_still_accepted(tmp_path):
    m = tmp_path / "nogit" / "docs" / "codebase-map.md"
    _touch(
        m,
        "# Map - Proj\n\n"
        "> **Document control** · Owner `Morgan (PM)` · As-of `2026-07-22` · Anchor `no-vcs`\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor |\n"
        "|---|------|-------|-------|-------|--------|\n"
        "| 1 | rules | threshold in x.py | 📊 seen | 2026-07-22 | no-vcs |\n",
    )
    assert check_map(m) == []


def test_novcs_mentioned_in_prose_is_not_an_anchor(tmp_path):
    # The escape only counts as the anchor VALUE, not words later in the line.
    m = tmp_path / "docs" / "codebase-map.md"
    _touch(
        m,
        "# Map\n\n> As-of `2026-07-22` · Anchor `TBD - write no-vcs if there is no repo`\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor |\n"
        "|---|------|-------|-------|-------|--------|\n"
        "| 1 | rules | x | 📊 seen | 2026-07-22 | no-vcs |\n",
    )
    assert any("MAP-NO-ANCHOR" in f for f in check_map(m))


# --- M2: per-entry provenance validated -----------------------------------------------------


def test_entry_without_asof_flagged(tmp_path):
    repo, shas = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _map(shas[-1], entry_asof="<YYYY-MM-DD>"))
    assert any("MAP-ENTRY-NO-ASOF" in f for f in check_map(m))


def test_entry_without_anchor_flagged(tmp_path):
    repo, shas = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _map(shas[-1], entry_anchor="`<sha>`"))
    assert any("MAP-ENTRY-NO-ANCHOR" in f for f in check_map(m))


def test_entry_sha_that_does_not_resolve_flagged(tmp_path):
    repo, shas = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _map(shas[-1], entry_anchor="`deadbeefdead`"))
    assert any("MAP-STALE-ENTRY-ANCHOR" in f for f in check_map(m))


def test_good_entries_pass(tmp_path):
    repo, shas = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _map(shas[-1]))
    assert check_map(m) == []


# --- M3: staleness bound --------------------------------------------------------------------


def test_anchor_far_behind_head_is_stale(tmp_path):
    repo, shas = _map_repo(tmp_path, commits=6)
    m = repo / "docs" / "codebase-map.md"
    # Anchor the map at the first commit, 5 behind HEAD, with a budget of 3.
    _touch(
        m,
        _map(shas[0], entry_anchor=f"`{shas[0][:9]}`", header_extra=" · Staleness-budget `3`"),
    )
    codes = "".join(check_map(m))
    assert "MAP-STALE" in codes and "behind" in codes


def test_anchor_within_budget_not_stale(tmp_path):
    repo, shas = _map_repo(tmp_path, commits=3)
    m = repo / "docs" / "codebase-map.md"
    _touch(
        m,
        _map(shas[0], entry_anchor=f"`{shas[0][:9]}`", header_extra=" · Staleness-budget `10`"),
    )
    assert not any("MAP-STALE:" in f for f in check_map(m))


# --- M7: rename tolerance + Deprecated excluded from the cap --------------------------------


def test_renamed_entries_section_still_checked(tmp_path):
    repo, shas = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    text = _map(shas[-1]).replace("## 2. Map entries", "## 2. What we know")
    text += "| 2 | etl | untagged claim | none | 2026-07-18 | `" + shas[-1][:9] + "` |\n"
    _touch(m, text)
    assert any("MAP-NO-BASIS" in f for f in check_map(m))


def test_deprecated_section_excluded_from_line_cap(tmp_path):
    repo, shas = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    filler = "| 2026-01-01 | old entry | superseded |\n" * 300
    _touch(
        m,
        _map(shas[-1]) + "\n## 5. Deprecated\n\n"
        "| Date | Original entry | Why deprecated |\n|---|---|---|\n" + filler,
    )
    assert not any("MAP-TOO-LONG" in f for f in check_map(m))
