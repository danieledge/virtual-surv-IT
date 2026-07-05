"""Prevention tests: keep documentation claims consistent with the code on disk.

Born from the 2026-07-05 truth audit, which found the false/stale documentation
claims cluster in a handful of duplicated facts (guard count, tier table, version
badges, roster location, CI matrix description). Each test pins one of those facts
so a regression fails CI instead of waiting for the next audit.

Pure file reads - no repo code is imported or executed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


# --- (a) tier drift: agent frontmatter vs the agent-design.md section 2 table ---
# agent-design.md claims "the tests and this matrix are the guard against drift";
# this test makes that claim true.


def _frontmatter_models() -> dict[str, str]:
    models: dict[str, str] = {}
    for path in sorted((_ROOT / ".claude" / "agents").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{path.name}: no frontmatter"
        block = text.split("---", 2)[1]
        m = re.search(r"^model:\s*(\S+)\s*$", block, re.M)
        assert m, f"{path.name}: no model: in frontmatter"
        models[path.stem] = m.group(1)
    return models


def _tier_table() -> dict[str, str]:
    text = _read("docs/agent-design.md")
    section = text.split("## 2.", 1)[1].split("\n## ", 1)[0]
    tiers: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("|") or set(line.strip("| ")) <= {"-", " "}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("Agent",):
            continue
        names = re.findall(r"`([a-z0-9-]+)`", cells[0])
        tier = re.search(r"\b(opus|sonnet|haiku)\b", cells[1])
        if not names or not tier:
            continue
        for name in names:
            tiers[name] = tier.group(1)
    return tiers


def test_agent_model_tiers_match_agent_design_table():
    frontmatter = _frontmatter_models()
    table = _tier_table()
    assert set(frontmatter) == set(table), (
        f"agents on disk vs agent-design.md section 2 table: "
        f"only-on-disk={sorted(set(frontmatter) - set(table))}, "
        f"only-in-table={sorted(set(table) - set(frontmatter))}"
    )
    mismatches = {
        name: (frontmatter[name], table[name])
        for name in frontmatter
        if frontmatter[name] != table[name]
    }
    assert not mismatches, f"model: frontmatter vs tier table (disk, table): {mismatches}"


# --- (b) README version badge == plugin.json version ---------------------------


def test_readme_version_badge_matches_plugin_json():
    plugin = json.loads(_read(".claude-plugin/plugin.json"))
    m = re.search(r"badge/version-([\d.]+)-", _read("README.md"))
    assert m, "README.md: no shields.io version badge found"
    assert m.group(1) == plugin["version"], (
        f"README badge says {m.group(1)}, plugin.json says {plugin['version']}"
    )


# --- (c) ADR-002 header version == last revision-table row ---------------------


def test_adr002_header_version_matches_revision_table():
    text = _read("docs/adr/ADR-002-safety-hook-threat-model.md")
    header = re.search(r"Version `([\d.]+)`", text)
    assert header, "ADR-002: no header version"
    rows = re.findall(r"^> \| ([\d.]+) \| \d{4}-\d{2}-\d{2} \|", text, re.M)
    assert rows, "ADR-002: no revision-table rows"
    assert header.group(1) == rows[-1], (
        f"ADR-002 header version {header.group(1)} != last revision row {rows[-1]}"
    )


# --- (d) guard-count wording: three hooks, everywhere it is claimed ------------
# The 19:25 audit found "two safety hooks" surviving in prose after the third
# guard landed. Tolerant of phrasing, but a regression to "two" fails.

_THREE = re.compile(r"\bthree\b[^.\n]{0,80}\b(?:hooks?|guards?)\b", re.I)
_TWO = re.compile(r"\btwo\b[^.\n]{0,30}\b(?:hooks?|guards?)\b", re.I)


def test_guard_count_says_three_everywhere():
    for rel in ("README.md", "SECURITY.md", "CLAUDE.md"):
        text = _read(rel)
        assert _THREE.search(text), f"{rel}: no 'three ... hooks/guards' claim found"
        two = _TWO.search(text)
        assert not two, f"{rel}: stale guard count: {two.group(0)!r}"


# --- (e) roster location: engage must not point at CLAUDE.md -------------------


def test_engage_does_not_claim_roster_in_claude_md():
    text = _read(".claude/skills/engage/SKILL.md")
    stale = re.search(r"roster (?:is|lives) in[\s`*]*CLAUDE\.md", text, re.I)
    assert not stale, f"engage/SKILL.md still says the roster is in CLAUDE.md: {stale.group(0)!r}"
    current = re.search(r"roster is in[\s`*\n]{0,10}[^\n]*team-operating-guide\.md", text)
    assert current, "engage/SKILL.md: roster pointer to docs/team-operating-guide.md not found"


# --- (f) spot-check doctrine: Morgan spot-checks, never re-scores --------------
# 0.8.0 removed the double-scoring posture; the router doc drifted back once.


def test_agent_router_does_not_reintroduce_rescoring():
    text = _read("docs/review/agent-router.md")
    assert "independently re-scores" not in text, (
        "agent-router.md reintroduces the removed 're-scores' doctrine"
    )
    for m in re.finditer(r"re-scores", text):
        preceding = text[max(0, m.start() - 20) : m.start()]
        assert re.search(r"\bnot\b[^\n]*$", preceding), (
            f"agent-router.md: non-negated 're-scores' at offset {m.start()}: "
            f"{text[max(0, m.start() - 40) : m.end() + 20]!r}"
        )


# --- (g) CONTRIBUTING CI description vs the actual workflow --------------------
# Compared both ways so either file drifting fails the test.


def test_contributing_ci_description_matches_workflow():
    contributing = _read("CONTRIBUTING.md")
    ci = _read(".github/workflows/ci.yml")
    for token in ("windows-latest", "3.10"):
        assert token in ci, f"ci.yml no longer contains {token!r} - update CONTRIBUTING.md too"
        assert token in contributing, (
            f"CONTRIBUTING.md does not mention {token!r} though ci.yml runs it"
        )
