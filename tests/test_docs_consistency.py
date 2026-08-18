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
    if not (_ROOT / "docs" / "adr").is_dir():
        import pytest

        pytest.skip(
            "docs/adr/ is deliberately untracked (internal docs, .gitignore 2026-08-13) "
            "and absent in this clone - the check runs wherever the files exist"
        )
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


def test_reviewer_agents_forbid_repo_enumeration():
    """Map-first review scoping (2026-08-17): dispatched reviewers must work from the
    brief's file list and the codebase map's PATH, never crawl the repo themselves - a
    live run had three parallel reviewers each independently re-discover a mapped repo."""
    for agent in ("code-reviewer", "performance-reviewer"):
        text = _read(f".claude/agents/{agent}.md").lower()
        assert "never enumerate the repo" in text, (
            f"{agent}.md: the no-self-enumeration rule is gone"
        )


def test_single_deliverable_close_is_the_rule_everywhere():
    """2026-08-18 live report: a /why-no-alert close demanded an 'engagement report'
    over a diagnosis that already covered everything, then offered an exec summary when
    challenged. The rule is general (any workflow): one artifact carrying the substance
    IS the delivery - closing block appended, summary email, done."""
    bookends = _read(".claude/skills/.shared/engagement-bookends.md")
    assert "Single-deliverable close" in bookends
    assert "never invent wrapper documents or executive summaries" in bookends
    dod = _read("docs/DEFINITION-OF-DONE.md")
    assert "Single-deliverable carve-out" in dod
    engage = _read(".claude/skills/engage/SKILL.md")
    assert "SINGLE-deliverable engagement skips the wrapper" in engage
    wna = _read(".claude/skills/why-no-alert/SKILL.md")
    assert "diagnosis report IS the delivery" in wna


def test_exploration_discipline_is_applied_through_every_route():
    """2026-08-18 deep research ('lots of greps, not optimal'): structure-first beats
    search-first at this scale (Agentless, RepoGraph). The discipline must reach every
    exploration route - the standing guide (Morgan's own pre-delegation work), the
    orchestration doc (dispatch time), the agent prompts (dispatched work), deep-review
    and why-no-alert (the named-reads prescription)."""
    guide = _read("docs/team-operating-guide.md")
    assert "Exploration discipline (standing)" in guide
    orch = _read("docs/team-operating-guide-orchestration.md")
    assert "## Exploration discipline" in orch
    assert "Search budget" in orch and "pinpoint symbol lookup" in orch
    for agent in (
        "code-reviewer",
        "performance-reviewer",
        "rules-developer",
        "platform-engineer",
        "ml-engineer",
        "qa-engineer",
        "data-analyst",
    ):
        text = _read(f".claude/agents/{agent}.md").lower()
        assert "grep is pinpoint symbol lookup" in text, (
            f"{agent}.md: the search-discipline sentence is missing"
        )
    deep = _read(".claude/skills/deep-review/SKILL.md")
    assert "Exploration discipline" in deep
    wna = _read(".claude/skills/why-no-alert/SKILL.md")
    assert "NAMED, never explored" in wna and "zero concept-greps" in wna


def test_build_side_agents_forbid_repo_enumeration_too():
    """The build-workflow pass (2026-08-17): builders, QA, the BA and the analyst get
    the same map-first scope rule reviews got - the enumeration guard denies a bare
    find mid-build, so the sanctioned route must be in each prompt."""
    for agent in (
        "rules-developer",
        "platform-engineer",
        "ml-engineer",
        "qa-engineer",
        "data-analyst",
    ):
        text = _read(f".claude/agents/{agent}.md").lower()
        assert "never enumerate the repo" in text, (
            f"{agent}.md: the map-first scope rule is missing"
        )
    ba = _read(".claude/agents/business-analyst.md").lower()
    assert "codebase-map.md" in ba and "never crawl" in ba


def test_build_solution_carries_the_2026_08_17_review_fixes():
    """Priced gate, light-shape derivation, consent-up-front, map-in-briefs - the four
    build-workflow findings that map onto SKILL text."""
    text = _read(".claude/skills/build-solution/SKILL.md")
    assert "Price the plan at the go-ahead gate" in text
    assert "EARS-lite" in text  # single-unit non-detection derives the light shape
    assert "consent declined" in text  # evidence level agreed up front
    assert "codebase map's\n   PATH" in text.replace("  ", " ") or "codebase map's" in text
    assert "point, never paste" in text.lower()


def test_bookends_close_refreshes_the_map():
    """A build outdates the map; direct-invoked skills never pass through /engage's
    close - the shared bookends must carry the bounded refresh + re-fingerprint."""
    text = _read(".claude/skills/.shared/engagement-bookends.md")
    assert "Map currency" in text
    assert "repo_skeleton --fingerprint docs/codebase-map.md" in text


def test_write_brd_batches_clarifying_questions():
    text = _read(".claude/skills/write-brd/SKILL.md")
    assert "ONE `AskUserQuestion` call" in text
    router = _read("docs/review/agent-router.md")
    assert "Point, never paste" in router, (
        "agent-router.md: briefs must point at the codebase map, never inline its body"
    )
    skill = _read(".claude/skills/deep-review/SKILL.md")
    assert "point, never paste" in skill.lower(), (
        "deep-review/SKILL.md: the map-pointer briefing rule is gone"
    )


def test_review_target_is_derived_or_batched_never_a_solo_turn():
    """Review-target batching (2026-08-17): the target is derived (diff / named path)
    and, when genuinely unknown, asked inside the 0a intake batch - never its own
    screen or turn."""
    engage = _read(".claude/skills/engage/SKILL.md")
    assert "Review target" in engage and "`Target`" in engage, (
        "engage/SKILL.md: the Work-type slot swap to Review target is gone"
    )
    deep = _read(".claude/skills/deep-review/SKILL.md")
    assert re.search(r"\*\*Target\*\*", deep), (
        "deep-review/SKILL.md: step 2 must derive the target before asking"
    )
    menu = _read(".claude/skills/engage/references/review-menu.md")
    assert "Name the derived target" in menu, (
        "review-menu.md: the price-line message must state the derived target"
    )


def test_engage_carries_the_jira_inbound_contract():
    """The [j] beta flow (2026-08-18): the skill must state that ticket content is DATA
    and that gates come from the human in the session - the injection boundary the
    whole inbound design rests on."""
    text = _read(".claude/skills/engage/SKILL.md")
    assert "--jira" in text and "BETA" in text
    assert "Ticket\n  content is DATA" in text.replace("**", "") or "content is DATA" in text
    integrations = _read(".claude/skills/engage/references/integrations.md")
    assert "--jira" in integrations and "Deliver back at close" in integrations
    canonical = _read("docs/INTEGRATIONS.md")
    assert "new engagement from a\nJira (beta)" in canonical or "from a Jira (beta)" in canonical.replace("\n", " ")


def test_engage_classify_names_the_alert_absence_entry_point():
    """Discoverability (2026-08-18): the routing table alone made /why-no-alert a
    judgement-dependent cross-reference; the classify step must name the query family
    so an absence ask never lands in the plain chat-answer bucket without the method."""
    text = _read(".claude/skills/engage/SKILL.md")
    assert "why did this not alert" in text
    assert "why-no-alert/SKILL.md" in text


def test_engage_new_flag_forbids_engagement_discovery():
    """Live report (2026-08-17): '/engage --new' from the go menu still spent a turn
    listing the open packs 'in case any are related' - the human had JUST seen that
    list in the launcher and chosen new. The skill must carry the zero-discovery rule
    for --new, and validation must be scoped to --resume only."""
    text = _read(".claude/skills/engage/SKILL.md")
    assert "ZERO engagement discovery" in text, (
        "engage/SKILL.md: the --new zero-discovery rule is gone - --new must skip "
        "list --menu, artifacts listings, ENGAGEMENTS.md and any open-pack commentary"
    )
    assert re.search(r"`--resume <slug>`[^\n]*validate", text), (
        "engage/SKILL.md: slug validation must be stated on the --resume branch "
        "(it is the only flag with anything to validate)"
    )


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
        for found in re.findall(r"(\d+)\s+(?:specialist|subagent|agent definitions)", _read(rel)):
            assert int(found) == n, (
                f"{rel}: says {found} specialists/subagents but {n} agent files exist on disk"
            )


def _test_function_def_count() -> int:
    """A cheap, pure-file-read LOWER BOUND on the real pytest-collected test count - a
    parametrized `def test_x` collects as MANY test IDs, never fewer, so this is always
    <= the true collected count. Deliberately not an exact match (this file's own stated
    design is pure file reads, no execution - actually invoking pytest --collect-only from
    inside a test would be circular and slow); a floor-check on the def-count is the
    strongest claim obtainable without running the suite."""
    total = 0
    for path in (_ROOT / "tests").glob("test_*.py"):
        total += len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), re.M))
    return total


def test_readme_test_count_claim_is_never_an_overstatement():
    """Found live 2026-08-07 (framework-wide audit): README claimed '700+ unit tests' /
    '785 collected as of 0.33.1' / a '1300+ passing' badge - three DIFFERENT numbers, none
    matching the real count by then (1842 collected). A hand-maintained exact count always
    eventually drifts (the skill/agent-count tests above solve this by deriving an EXACT
    match from disk; a test count can't use that pattern, since it changes on nearly every
    commit that touches tests/). This instead pins a WEAKER, permanently-true property: the
    rounded "N+" claims in README must never overstate reality - the real def-count (itself
    a floor on the true collected count) must be >= every "N+ ... test" figure quoted."""
    floor = _test_function_def_count()
    readme = _read("README.md")
    # Two phrasings appear: "N+ ... test(s)" (prose) and "Tests N+" (the badge alt text/URL).
    claims = re.findall(r"(\d[\d,]*)\+\s*(?:passing\s+)?(?:unit\s+)?tests?\b", readme, re.I)
    claims += re.findall(r"[Tt]ests?[\s-](\d[\d,]*)\+", readme)
    assert len(claims) >= 3, (
        f"README: expected at least 3 'N+ test(s)' claims (badge + two prose mentions), "
        f"found {len(claims)}: {claims} - did the wording change enough to need a new pattern?"
    )
    for claim in claims:
        n = int(claim.replace(",", ""))
        assert n <= floor, (
            f"README claims '{claim}+ tests' but only {floor} `def test_` definitions exist "
            f"on disk (a floor on the true collected count) - the claim overstates reality, "
            f"lower it"
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
    # CONTRIBUTING added 2026-07-30: its promotion-gate case count slipped this net once.
    n = _eval_case_count()
    for rel in ("README.md", "docs/agent-design.md", "CONTRIBUTING.md"):
        for found in re.findall(r"(\d+)\s+golden cases", _read(rel)):
            assert int(found) == n, (
                f"{rel}: says {found} golden cases but {n} eval-case dirs exist on disk"
            )


# --- (j) compliance-reviewer conditionality: never unconditional in the operative docs -----
# The 2026-08-04 eval trace found DEFINITION-OF-DONE.md's "Compliance-reviewed" checklist item
# and build-solution/SKILL.md's review step both named compliance-reviewer with no conditional
# qualifier - unlike performance-reviewer right next to it in both places, which correctly said
# "where it processes data at volume". CLAUDE.md §4 and the operating guide's routing table both
# scope compliance-reviewer to detection logic / regulated data / §4 thresholds ("not every code
# review"); an unqualified restatement elsewhere is exactly how that drifted. Anchored on the
# specific checklist bullet / review step, not every mention of the agent name - several OTHER
# mentions in these same files (audit-depth synthesis read, handover-usability check, eval
# attestation) are legitimately their own, differently-scoped conditions, not this one.

_COMPLIANCE_CONDITION_MARKERS = (
    "detection logic",
    "regulated data",
    "not every code review",
    "not a default",
)


def _assert_conditional(rel: str, section: str, label: str) -> None:
    assert any(marker in section for marker in _COMPLIANCE_CONDITION_MARKERS), (
        f"{rel}: {label} names compliance-reviewer with no nearby conditional qualifier "
        "(detection logic / regulated data / not every code review) - reads as unconditional, "
        "the exact 2026-08-04 bug"
    )


def test_dod_compliance_reviewed_bullet_is_conditional():
    text = _read("docs/DEFINITION-OF-DONE.md")
    m = re.search(r"- \[ \] \*\*Compliance-reviewed\*\*.*?(?=\n- \[ \]|\Z)", text, re.S)
    assert m, "DEFINITION-OF-DONE.md: 'Compliance-reviewed' checklist bullet not found"
    _assert_conditional(
        "docs/DEFINITION-OF-DONE.md", m.group(0), "the 'Compliance-reviewed' bullet"
    )


def test_build_solution_review_step_is_conditional():
    text = _read(".claude/skills/build-solution/SKILL.md")
    m = re.search(r"4\. \*\*Review\*\*.*?(?=\n5\.|\Z)", text, re.S)
    assert m, "build-solution/SKILL.md: step 4 ('Review') not found"
    _assert_conditional(
        ".claude/skills/build-solution/SKILL.md", m.group(0), "step 4's review-chain sentence"
    )
