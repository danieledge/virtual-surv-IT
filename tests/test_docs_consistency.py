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


# --- (h) inventory derived from the filesystem, not hand-synced -----------------
# The recurring stale-count defect class (skill/agent/eval-case counts, the command
# index) drifted repeatedly because it was hand-maintained across README, the
# operating guide and plugin.json. These tests DERIVE the truth from disk so any
# drift fails CI proactively, instead of being pinned only after it burns.


def _skill_names() -> set[str]:
    root = _ROOT / ".claude" / "skills"
    return {d.name for d in root.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()}


def _agent_count() -> int:
    return len(list((_ROOT / ".claude" / "agents").glob("*.md")))


def _eval_case_count() -> int:
    root = _ROOT / "evals" / "cases"
    return len([d for d in root.iterdir() if d.is_dir()])


def test_command_index_lists_exactly_the_skills_on_disk():
    """The canonical command index in the operating guide must list every skill
    directory - no more, no less. Catches 'added a skill but forgot to register it'."""
    guide = _read("docs/team-operating-guide.md")
    m = re.search(r"## Command index.*?\n(.*?)(?:\n## |\Z)", guide, re.S)
    assert m, "operating guide: 'Command index' section not found"
    listed = set(re.findall(r"^- `/([a-z0-9-]+)`", m.group(1), re.M))
    on_disk = _skill_names()
    missing = on_disk - listed
    extra = listed - on_disk
    assert not missing, f"skills on disk missing from the command index: {sorted(missing)}"
    assert not extra, f"command index lists non-existent skills: {sorted(extra)}"


def test_skill_count_references_match_filesystem():
    n = len(_skill_names())
    for rel in ("README.md", "docs/team-operating-guide.md"):
        for found in re.findall(r"(\d+)\s+(?:skills|workflows)\b", _read(rel)):
            assert int(found) == n, (
                f"{rel}: says {found} skills/workflows but {n} skill dirs exist on disk"
            )


def test_agent_count_references_match_filesystem():
    n = _agent_count()
    for rel in ("README.md", ".claude-plugin/plugin.json"):
        for found in re.findall(r"(\d+)\s+(?:specialist|subagent)", _read(rel)):
            assert int(found) == n, (
                f"{rel}: says {found} specialists/subagents but {n} agent files exist on disk"
            )


def test_roster_gate_matches_operating_guide():
    """The roster hardcoded in check_artifacts (for ROSTER-UNKNOWN/ROSTER-ROLE-MISMATCH) must
    match the canonical roster line in the operating guide, so the name->role map can't drift."""
    from scripts.check_artifacts import _ROSTER

    guide = _read("docs/team-operating-guide.md")
    # Roster line form: "Amara (`business-analyst`), Mateo (`rules-developer`), ..."
    pairs = dict(re.findall(r"([A-Z][a-z]+)\s*\(`([a-z0-9-]+)`\)", guide))
    assert pairs, "operating guide: no `Name (`slug`)` roster pairs found"
    for name, slug in pairs.items():
        assert _ROSTER.get(name.lower()) == slug, (
            f"roster drift: guide says {name} is `{slug}`, check_artifacts._ROSTER says "
            f"`{_ROSTER.get(name.lower())}`"
        )
    # Every non-PM roster entry in the script must appear in the guide (Morgan is the PM, not a
    # subagent slug, so it is exempt from the guide's `Name (`slug`)` list).
    guide_names = {n.lower() for n in pairs}
    script_names = {n for n in _ROSTER if n != "morgan"}
    assert script_names == guide_names, (
        f"roster membership drift: only-in-script={sorted(script_names - guide_names)}, "
        f"only-in-guide={sorted(guide_names - script_names)}"
    )


def test_eval_case_count_references_match_filesystem():
    # The dated eval-baseline-*.md is a point-in-time record - excluded on purpose.
    n = _eval_case_count()
    for rel in ("README.md", "docs/agent-design.md"):
        for found in re.findall(r"(\d+)\s+golden cases", _read(rel)):
            assert int(found) == n, (
                f"{rel}: says {found} golden cases but {n} eval-case dirs exist on disk"
            )
