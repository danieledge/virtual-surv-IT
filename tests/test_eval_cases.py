"""Contract tests over every golden eval case (evals/cases/*/expected.yaml).

These run token-free in CI and pin the *harness contract* between the ground-truth
manifests and the deterministic scorer (scripts.eval_score):

  * every manifest stays well-formed against the schema the scorer actually reads
    (planted/forbidden specs, keywords, locations, severity floors, pass rules);
  * the scorer keeps discriminating good runs from bad ones - a synthetic "perfect
    run" derived from each manifest PASSES, and an empty run FAILS wherever the
    manifest demands findings (and passes only for the cases whose ground truth is
    "there is nothing to find");
  * any schema drift between a manifest and the scorer fails the build.

What this deliberately does NOT do: it never runs the team, so it says nothing about
the live quality of the prompts. Scoring the *team's* output still requires running
`/run-evals` manually (each case spawns the team and spends tokens). This file is the
regression net for the harness itself, not for the team.
"""

from pathlib import Path

import pytest
import yaml

from scripts.eval_score import score

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = REPO_ROOT / "evals" / "cases"
CASE_DIRS = sorted(p for p in CASES_ROOT.iterdir() if p.is_dir())
RUBRICS_ROOT = REPO_ROOT / "evals" / "rubrics"
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"

# Ground-truth markers that must never appear in an agent-visible input: the blind run
# briefs the team-under-test with the case's input file, so an answer-key section or an
# "you are being evaluated" banner in it invalidates the case. That content belongs in
# the case's notes.md sidecar (see evals/README.md).
ANSWER_KEY_MARKERS = (
    "seeded issue",
    "for the harness",
    "not shown to the team",
    "expected.yaml",
    "behaviour eval",
)

# Canonical severity vocabulary the scorer ranks (scripts.eval_score._SEVERITY_RANK).
# Manifests must use it for min_severity floors: the scorer resolves synonyms ("high",
# "blocker", ...) for *findings*, but an out-of-vocab floor ranks as unsatisfiable (99),
# which would silently make a case unpassable.
CANONICAL_SEVERITIES = {"style", "medium", "warning", "critical"}

# Cases whose ground truth is "there is nothing to find": zero findings is the CORRECT
# answer (they test false-positive restraint - a clean file / fully-covered inventory
# must not get fabricated findings), so an empty run must PASS for these. The manifest
# consistency is asserted below - a case belongs here iff it has no must-find items.
ZERO_FINDING_CASES = {"coverage-complete", "review-clean-code"}


def _load_expected(case_dir: Path) -> dict:
    return yaml.safe_load((case_dir / "expected.yaml").read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    """Mirror the scorer's text normalisation (lowercase, collapsed whitespace)."""
    return " ".join((text or "").lower().split())


def _perfect_findings(expected: dict) -> list[dict]:
    """Build a synthetic 'perfect run': one finding per planted spec.

    Each finding is derived only from the manifest's own matching fields - a keyword as
    the title, the planted location, and 'critical' severity (top rank, satisfies any
    min_severity floor). The chosen keyword must not collide with any forbidden trap:
    the scorer matches traps on keyword-in-haystack, so a manifest where every keyword
    of a planted spec also triggers a trap could never be satisfied by a correct run -
    that is a manifest bug and this helper fails loudly on it.
    """
    forbidden_kws = [
        _norm(kw)
        for trap in expected.get("forbidden", []) or []
        for kw in trap.get("keywords", []) or []
    ]
    findings = []
    for spec in expected.get("planted", []) or []:
        location = spec.get("location", "") or ""
        title = None
        for kw in spec.get("keywords", []) or []:
            # The scorer's haystack is title + kind + location; check the trap keywords
            # against the same combined text this finding will present.
            hay = _norm(f"{kw} {location}")
            if not any(f_kw in hay for f_kw in forbidden_kws):
                title = kw
                break
        assert title is not None, (
            f"{expected.get('case')}: planted {spec.get('id')} has no keyword that avoids "
            "every forbidden trap - a correct finding could never score clean"
        )
        findings.append({"severity": "critical", "location": location, "title": title, "kind": ""})
    return findings


@pytest.fixture(params=CASE_DIRS, ids=lambda p: p.name)
def case_dir(request):
    return request.param


def test_cases_are_collected():
    """Path drift guard: the golden cases exist and each carries a manifest."""
    assert CASE_DIRS, f"no eval cases found under {CASES_ROOT}"
    missing = [d.name for d in CASE_DIRS if not (d / "expected.yaml").is_file()]
    assert not missing, f"case dirs without expected.yaml: {missing}"


def test_manifest_matches_scorer_schema(case_dir):
    """expected.yaml parses and carries the fields the scorer reads."""
    expected = _load_expected(case_dir)
    assert isinstance(expected, dict), f"{case_dir.name}: expected.yaml must be a mapping"
    assert expected.get("case") == case_dir.name, (
        f"{case_dir.name}: 'case' must name its directory (got {expected.get('case')!r})"
    )

    planted = expected.get("planted", []) or []
    forbidden = expected.get("forbidden", []) or []
    assert isinstance(planted, list), f"{case_dir.name}: 'planted' must be a list"
    assert isinstance(forbidden, list), f"{case_dir.name}: 'forbidden' must be a list"

    for spec in planted:
        assert isinstance(spec, dict), f"{case_dir.name}: planted items must be mappings"
        sid = spec.get("id")
        assert sid, f"{case_dir.name}: planted item without an id"
        keywords = spec.get("keywords") or []
        assert isinstance(keywords, list), f"{case_dir.name}/{sid}: keywords must be a list"
        assert all(isinstance(k, str) and k.strip() for k in keywords), (
            f"{case_dir.name}/{sid}: keywords must be non-empty strings"
        )
        # The scorer matches on location OR keywords - a spec with neither is unmatchable.
        assert keywords or spec.get("location"), (
            f"{case_dir.name}/{sid}: needs keywords or a location to be matchable"
        )
        if "min_severity" in spec:
            assert spec["min_severity"] in CANONICAL_SEVERITIES, (
                f"{case_dir.name}/{sid}: min_severity {spec['min_severity']!r} is outside "
                f"the scorer's canonical vocabulary {sorted(CANONICAL_SEVERITIES)}"
            )
        if "must_find" in spec:
            assert isinstance(spec["must_find"], bool), (
                f"{case_dir.name}/{sid}: must_find must be a boolean"
            )

    for trap in forbidden:
        assert isinstance(trap, dict), f"{case_dir.name}: forbidden items must be mappings"
        tid = trap.get("id")
        assert tid, f"{case_dir.name}: forbidden item without an id"
        kws = trap.get("keywords") or []
        assert kws and all(isinstance(k, str) and k.strip() for k in kws), (
            f"{case_dir.name}/{tid}: a trap with no keywords can never trigger"
        )

    rules = expected.get("pass", {}) or {}
    assert isinstance(rules, dict), f"{case_dir.name}: 'pass' must be a mapping"
    for key in ("require_all_must_find", "forbid_all"):
        if key in rules:
            assert isinstance(rules[key], bool), f"{case_dir.name}: pass.{key} must be boolean"


def test_manifest_references_resolve(case_dir):
    """The manifest's file pointers all resolve: the blind run depends on every one.

    `input:` is the (only) file the team-under-test is briefed with, `rubric:` is what the
    LLM judge scores against, and `workflow:` names the skill whose SKILL.md the runner
    inlines into the blind brief - a dangling pointer breaks /run-evals silently.
    """
    expected = _load_expected(case_dir)

    input_name = expected.get("input")
    assert input_name, f"{case_dir.name}: manifest has no 'input:' file"
    assert (case_dir / input_name).is_file(), (
        f"{case_dir.name}: input file {input_name!r} not found in the case directory"
    )

    rubric = expected.get("rubric")
    assert rubric, f"{case_dir.name}: manifest has no 'rubric:'"
    assert (RUBRICS_ROOT / f"{rubric}.md").is_file(), (
        f"{case_dir.name}: rubric {rubric!r} does not resolve to evals/rubrics/{rubric}.md"
    )

    workflow = expected.get("workflow")
    if workflow:
        skill_dir = SKILLS_ROOT / str(workflow).lstrip("/")
        assert skill_dir.is_dir(), (
            f"{case_dir.name}: workflow {workflow!r} does not resolve to a skill directory "
            f"under {SKILLS_ROOT}"
        )


def test_planted_line_anchors_within_input(case_dir):
    """Every numeric line anchor points inside the input file.

    The scorer matches planted locations within +/- 3 lines, so a stale anchor (input
    edited, manifest not re-anchored) silently kills the location channel - and
    test_perfect_run_passes cannot catch it because _perfect_findings copies the
    manifest's own location back. An anchor past end-of-file is proof of drift.
    """
    expected = _load_expected(case_dir)
    input_name = expected.get("input")
    if not input_name or not (case_dir / input_name).is_file():
        pytest.skip("no resolvable input file (covered by test_manifest_references_resolve)")
    line_count = len((case_dir / input_name).read_text(encoding="utf-8").splitlines())

    for spec in expected.get("planted", []) or []:
        loc = spec.get("location")
        if not loc:
            continue
        parts = str(loc).rsplit(":", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue  # symbolic anchors (e.g. feeds.yaml:TYP-WASH) carry no line number
        line = int(parts[1])
        assert 1 <= line <= line_count, (
            f"{case_dir.name}/{spec.get('id')}: location {loc!r} points at line {line} "
            f"but {input_name} has {line_count} lines - stale anchor, re-anchor it"
        )


def test_scenario_contains_no_answer_key(case_dir):
    """scenario.md files carry no ground truth or eval banner.

    scenario.md is agent-visible (for many cases it IS the input the blind subagent gets),
    so seeded-issue sections, pointers at expected.yaml, and "this is a behaviour eval"
    announcements invalidate the case. That content lives in notes.md.
    """
    scenario = case_dir / "scenario.md"
    if not scenario.is_file():
        pytest.skip("case has no scenario.md")
    text = _norm(scenario.read_text(encoding="utf-8"))
    leaked = [m for m in ANSWER_KEY_MARKERS if m in text]
    assert not leaked, (
        f"{case_dir.name}: scenario.md contains answer-key markers {leaked} - move the "
        "grading content to notes.md (see evals/README.md)"
    )


def test_perfect_run_passes(case_dir):
    """A run that surfaces every planted issue (and trips no trap) must PASS."""
    expected = _load_expected(case_dir)
    result = score(expected, _perfect_findings(expected))
    assert result["passed"] is True, (
        f"{case_dir.name}: a perfect run scored as FAIL - manifest/scorer contract broken: "
        f"missed={result['planted_missed']} traps={result['false_positive_traps_triggered']}"
    )
    assert result["recall"] == 1.0
    assert result["planted_missed"] == []
    assert result["must_find_missed"] == []
    assert result["false_positive_traps_triggered"] == []


def test_empty_run_scores_correctly(case_dir):
    """A run with NO findings must FAIL wherever the manifest demands findings.

    The two ZERO_FINDING_CASES invert this on purpose: their ground truth is that a
    correct assessment reports nothing, so zero findings is a legitimate PASS there.
    """
    expected = _load_expected(case_dir)
    result = score(expected, [])
    planted = expected.get("planted") or []
    must_find_ids = {p.get("id", "?") for p in planted if p.get("must_find")}

    if case_dir.name in ZERO_FINDING_CASES:
        assert not must_find_ids, (
            f"{case_dir.name}: listed as a zero-finding case but has must-find items "
            f"{sorted(must_find_ids)} - remove it from ZERO_FINDING_CASES"
        )
        assert result["passed"] is True
        assert result["false_positive_traps_triggered"] == []
    else:
        assert must_find_ids, (
            f"{case_dir.name}: no must-find planted items - if zero findings is the "
            "intended pass for this case, add it to ZERO_FINDING_CASES explicitly"
        )
        assert result["passed"] is False, (
            f"{case_dir.name}: an empty run PASSED despite must-find criteria - the "
            "scorer has stopped discriminating"
        )
        assert set(result["must_find_missed"]) == must_find_ids
