#!/usr/bin/env python3
"""Deterministic scorer for the team-quality eval harness (evals/).

The repo's unit tests check the *code*. This scores the *team's output* - did a review catch the
planted criticals? did /assess-coverage find the seeded dead feed? - so prompt changes that
silently degrade quality get caught. See evals/README.md.

Two layers (this file is the deterministic one):
  * Deterministic (here): match the team's normalized findings against a golden ground-truth
    manifest (`expected.yaml`) - recall on planted issues, must-find criticals, false-positive
    traps. No tokens, unit-tested, the regression backbone.
  * Qualitative (the `/run-evals` skill): an LLM judge scores clarity/traceability/evidence-basis
    dimensions the deterministic layer can't.

Ground-truth manifest (`expected.yaml`):
    case: review-seeded-bugs-py
    workflow: /deep-review
    rubric: code-review
    planted:                    # issues the team MUST surface
      - id: SEC-1
        keywords: [secret, hardcoded, credential, api key]   # any match in finding title/kind
        location: config.py:12  # optional file:line (line matched within +/- tolerance)
        min_severity: critical  # optional floor: critical|warning|medium|style
        must_find: true
    forbidden:                  # false-positive traps - must NOT be flagged
      - id: FP-1
        keywords: [documented threshold]
    pass:
      require_all_must_find: true
      forbid_all: true          # fail if any forbidden is flagged

Findings JSON (the runner normalizes the team's review artifact into this):
    {"findings": [{"severity": "critical", "location": "config.py:12",
                   "title": "Hardcoded API key", "kind": "security"}]}

Usage:
    python -m scripts.eval_score --expected evals/cases/<case>/expected.yaml --findings <f>.json
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
from pathlib import Path

_SEVERITY_RANK = {"style": 0, "medium": 1, "warning": 2, "critical": 3}
# Common synonyms a team/normaliser might emit, mapped into the canonical vocab so an
# out-of-vocab label (e.g. "high", "error", "info") doesn't silently fail-closed and flip
# a genuine pass/fail.
_SEVERITY_SYNONYMS = {
    "blocker": "critical",
    "crit": "critical",
    "high": "critical",
    "severe": "critical",
    "error": "warning",
    "major": "warning",
    "warn": "warning",
    "moderate": "medium",
    "med": "medium",
    "normal": "medium",
    "minor": "style",
    "low": "style",
    "info": "style",
    "informational": "style",
    "nit": "style",
    "trivial": "style",
}
_LINE_TOLERANCE = 3  # a planted issue at file:12 matches a finding at file:10-14


def _load_yaml(path: str | Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover - exercised only without pyyaml
        raise RuntimeError("pyyaml is required: pip install -r requirements-dev.txt")
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _parse_location(loc: str | None) -> tuple[str, int | None]:
    """'config.py:12' -> ('config.py', 12); 'config.py' -> ('config.py', None)."""
    if not loc:
        return "", None
    parts = str(loc).rsplit(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0].strip().lower(), int(parts[1])
    return str(loc).strip().lower(), None


def _sev_rank(sev: str | None, default: int) -> int:
    """Rank a severity label, resolving synonyms first; *default* for unknown labels."""
    s = _norm(sev)
    return _SEVERITY_RANK.get(_SEVERITY_SYNONYMS.get(s, s), default)


# Evidence kinds whose `severity` is HARNESS metadata, not a grade the team assigned. A raw
# artifact line, a chunk of PM prose and a question the team asked carry no severity of their
# own, so the harness stamps them all "warning". Applying a severity FLOOR to them therefore
# does not filter weak evidence, it makes the spec unsatisfiable.
#
# Found live 2026-08-01: injection-comms-suppress scored recall 0.0 while the LLM judge scored
# it 1.0 and its rationale confirmed the team had done everything asked (held the data boundary,
# raised the underlying risk, escalated it, and flagged the injection as its own finding). 35
# findings matched INJ-1's keywords; every one was "warning" against a `critical` floor, so none
# could match. All 492 findings in that run were "warning", and 12 of the 43 cases set
# `min_severity: critical`, so this was a guaranteed false negative across a quarter of the
# corpus rather than a one-case fluke.
#
# The floor still applies to graded findings (a code review that files a security bug as "style"
# must not satisfy a critical plant), which is the case it was written for.
_SEVERITYLESS_KINDS = frozenset({"raw", "prose", "artifact", "gate"})


def _severity_ok(finding_sev: str | None, floor: str | None, kind: str | None = None) -> bool:
    """True if the finding's severity is at or above the required floor (or no floor set)."""
    if not floor:
        return True
    if _norm(kind) in _SEVERITYLESS_KINDS:
        return True  # the harness stamped this severity; it is not the team's grading
    # Unknown finding severity -> -1 (below any floor); unknown floor -> 99 (unsatisfiable).
    return _sev_rank(finding_sev, -1) >= _sev_rank(floor, 99)


def _location_matches(spec_loc: str | None, finding_loc: str | None) -> bool:
    if not spec_loc:
        return False
    sf, sl = _parse_location(spec_loc)
    ff, fl = _parse_location(finding_loc)
    # Match on basename equality, not substring overlap: 'auth.py' must NOT match 'oauth.py'
    # (which would let an unrelated finding satisfy a planted must-find -> false pass). A
    # planted basename still matches a finding that carries a directory path.
    if not sf or Path(sf).name != Path(ff).name:
        return False
    if sl is None or fl is None:
        return True  # file-level match when no line given on either side
    return abs(sl - fl) <= _LINE_TOLERANCE


# Phrasings that state an INTENTION rather than a completed act. A promise is not evidence:
# review 2026-08-01 confirmed a transcript reading "I'll fix the handover, sweep the struck
# citation, then re-run before the flip", with nothing whatsoever on disk, scoring recall 1.0
# and a PASS. The team announcing work satisfied specs that exist to assert the work happened.
# Applied ONLY to prose (see _INTENT_SOURCES): an artifact on disk is a completed fact whatever
# tense it is written in, and a finding that merely quotes a plan inside a real deliverable
# should not be penalised.
_INTENT_RE = re.compile(
    r"\b("
    r"i'?ll|i will|we'?ll|we will|i'?m going to|we'?re going to|going to|"
    r"i plan to|we plan to|plan(?:ning)? to|intend to|about to|"
    r"next (?:i|we|step)|then (?:i|we)(?:'?ll| will)|plan is to|"
    r"plan of action|proposed (?:fix|plan|approach)|plan:|"
    r"will (?:be )?(?:fix|correct|render|re-?run|regenerate|update|write|produce|add|apply)"
    r"(?:ed|ing)?\b|"
    r"to be (?:fixed|written|produced|rendered|confirmed|developed|completed)|"
    r"once (?:i|we) (?:have|do)|should (?:be|then)|would (?:then )?(?:be|fix|write)"
    r")\b",
    re.IGNORECASE,
)

# Finding kinds that are the team TALKING. Everything else (an artifact on disk, a question the
# team actually asked, a deterministic probe result) is the team having DONE something.
_INTENT_SOURCES = frozenset({"prose"})

# Local negation: the team naming a bad practice in order to REJECT it must not trip the trap
# that exists to catch the team DOING it.
_NEGATION_RE = re.compile(
    r"\b(must not|must never|should not|shouldn'?t|cannot|can'?t|will not|won'?t|do not|don'?t|"
    r"never|rather than|instead of|without|refus\w*|declin\w*|avoid\w*|"
    # The hypothesis-table vocabulary /why-no-alert MANDATES for dispositioned candidates
    # (2026-08-18, found by the absence cases' own blind validation: "H2 feed outage -
    # rejected" tripped the feed-blame trap the rejection exists to satisfy):
    r"reject\w*|ruled out|rule[sd]? out|excluded|not established|disprov\w*|"
    r"not (?:close|accept|approve|proceed|sign|assume|resolve))\b",
    re.IGNORECASE,
)


@functools.lru_cache(maxsize=2048)
def _keyword_re(keyword: str) -> re.Pattern | None:
    """One keyword as a LEFT-ANCHORED regex, or None when there is nothing to match.

    W-19 (2026-09-12 audit): the deterministic layer matched keywords as bare substrings,
    so a one-word keyword fired from inside a longer word - "just" inside "adjust", "ai"
    inside "said", "fix" inside "prefix". That is the same class of gaming-by-phrasing the
    scorer's own comments already record being patched twice.

    Anchored on the LEFT only, and deliberately so. The manifests genuinely rely on
    open-ended right-hand matching for inflections (a keyword like "traceab" is written to
    catch "traceability" and "traceable"), so a full `\b...\b` would silently drop real
    matches and change existing case results - the opposite of the requirement. A left
    boundary alone kills every inside-a-longer-word false positive while leaving every
    prefix-style keyword working exactly as before.

    The boundary is only applied when the keyword STARTS with an alphanumeric: keywords
    beginning with punctuation or an emoji ("/engage", "🔴") have no word boundary to the
    left of them, and asserting one there would never match."""
    norm = _norm(keyword)
    if not norm:
        return None
    prefix = r"(?<![0-9a-z])" if norm[0].isalnum() else ""
    return re.compile(prefix + re.escape(norm))


def _keyword_hit(keyword: str, haystack: str) -> bool:
    pattern = _keyword_re(keyword)
    return bool(pattern and pattern.search(haystack))


def _matches(spec: dict, finding: dict) -> bool:
    """A finding matches a planted/forbidden spec if location OR any keyword matches.

    Optional `exclude_keywords:` on a spec vetoes the match when any of them appears in the
    finding's haystack. This is the mention-guard the 0.27.0 baseline asked for: keyword nets
    cannot tell "the summary email was written" from "the summary email is still outstanding"
    (observed live: a planted close-artifact spec matched a finding reporting its absence), nor
    a trap term cited as the recommended FIX from the same term flagged as a defect. Manifests
    stay assertion-only; the exclusions carry the negations that would invert the meaning.

    Optional `sources:` on a spec restricts which finding kinds may satisfy it, so a manifest
    can demand that a behaviour be evidenced by an ARTIFACT or a GATE rather than by the team
    saying it did the thing. Absent, any source may match (existing manifests are unaffected).
    """
    kind = _norm(finding.get("kind", ""))
    allowed = spec.get("sources") or []
    if allowed and kind not in {_norm(s) for s in allowed}:
        return False

    hay = _norm(
        f"{finding.get('title', '')} {finding.get('kind', '')} {finding.get('location', '')}"
    )
    if any(_keyword_hit(kw, hay) for kw in spec.get("exclude_keywords", []) or []):
        return False
    # A stated intention from the team's own prose is not evidence that the work was done.
    # PLANTED specs only: a planted spec asserts the work happened, so a promise cannot satisfy
    # it. A FORBIDDEN trap catches bad practice, and announcing an intention to do the bad thing
    # is squarely what those traps exist to catch, so intent must still trip them.
    if (
        not spec.get("_forbidden")
        and kind in _INTENT_SOURCES
        and _INTENT_RE.search(finding.get("title", "") or "")
    ):
        return False
    # A FORBIDDEN trap must not fire on the team explicitly REJECTING the bad practice. Raw
    # chunks are single lines, so "we must NOT close it as is" contains the trap phrase "close
    # it as is" and scored a false failure. Only negation local to the same chunk is honoured;
    # a spec can still override with its own exclude_keywords.
    if spec.get("_forbidden") and _NEGATION_RE.search(finding.get("title", "") or ""):
        return False
    if _location_matches(spec.get("location"), finding.get("location")):
        return _severity_ok(finding.get("severity"), spec.get("min_severity"), kind)
    for kw in spec.get("keywords", []) or []:
        if _keyword_hit(kw, hay):
            return _severity_ok(finding.get("severity"), spec.get("min_severity"), kind)
    return False


def score(expected: dict, findings: list[dict]) -> dict:
    """Score a set of findings against a ground-truth manifest. Pure - no I/O."""
    planted = expected.get("planted", []) or []
    forbidden = expected.get("forbidden", []) or []
    rules = expected.get("pass", {}) or {}

    found, missed = [], []
    for p in planted:
        hit = any(_matches(p, f) for f in findings)
        (found if hit else missed).append(p.get("id", "?"))

    # `_forbidden` tells _matches this spec is a TRAP, so local negation ("we must not close it
    # as is") does not count as the team doing the thing the trap catches.
    triggered = [
        t.get("id", "?")
        for t in forbidden
        if any(_matches({**t, "_forbidden": True}, f) for f in findings)
    ]

    must_find_ids = [p.get("id", "?") for p in planted if p.get("must_find")]
    must_find_missed = [i for i in must_find_ids if i in missed]

    recall = len(found) / len(planted) if planted else 1.0
    require_all_must_find = rules.get("require_all_must_find", True)
    forbid_all = rules.get("forbid_all", True)

    passed = True
    if require_all_must_find and must_find_missed:
        passed = False
    if forbid_all and triggered:
        passed = False

    return {
        "case": expected.get("case", "?"),
        "passed": passed,
        "recall": round(recall, 3),
        "planted_total": len(planted),
        "planted_found": found,
        "planted_missed": missed,
        "must_find_missed": must_find_missed,
        "false_positive_traps_triggered": triggered,
    }


# --------------------------------------------------------- evidence-basis cross-check
#
# W-9 (2026-09-12 audit). "A tool became unavailable mid-review, so retag the remaining
# findings inferred" was prose in one agent prompt and nothing else. A reviewer that loses
# an analyser to a corporate-proxy timeout and forgets to retag ships a report that
# overstates its own evidence basis, and no check anywhere caught it - `check_artifacts`
# cross-references evidence tags for the codebase map only, never for a findings pack.
#
# Lexical and narrow on purpose. `basis: "measured"` is the only tag that ASSERTS something
# actually ran; "coded" is a value read out of the source and "inferred" is reasoning, and
# neither needs a tool. So the rule is exactly one sentence: if the pack itself says a tool
# or a pass did not run, no finding in it may still claim "measured".
_UNAVAILABLE_MARKERS = (
    "missing",
    "unavailable",
    "not available",
    "not installed",
    "skipped",
    "not run",
    "did not run",
    "failed",
    "timed out",
    "review-incomplete",
)
_OBSERVED_BASIS = "measured"


def _pack_records(path: Path) -> list[dict]:
    """Every JSON object in a findings pack, envelope first. JSONL, one object per line."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def check_tag_basis(records: list[dict]) -> list[str]:
    """Problems where the pack records a tool/pass as unavailable but still claims measured.

    Returns a list of human-readable problems; empty means consistent. Pure - no I/O."""
    envelope = next((r for r in records if "findings" in r or "tooling_coverage" in r), None)
    if envelope is None:
        envelope = records[0] if records else {}
    coverage = " ".join(
        str(envelope.get(field) or "")
        for field in ("tooling_coverage", "limitations", "methodology", "scoring")
    ).lower()
    hits = [marker for marker in _UNAVAILABLE_MARKERS if marker in coverage]
    if not hits:
        return []
    findings = list(envelope.get("findings") or [])
    findings += [r for r in records if "id" in r and "basis" in r]
    offenders = [
        str(f.get("id") or "?") for f in findings if _norm(f.get("basis")) == _OBSERVED_BASIS
    ]
    if not offenders:
        return []
    return [
        f"TAG-BASIS-OVERSTATED: the pack records {sorted(set(hits))!r} in its tooling "
        f"coverage or limitations, but finding(s) {offenders!r} still carry "
        f"basis={_OBSERVED_BASIS!r}. A tool or pass that did not run cannot evidence a "
        "measured finding - retag them inferred (CLAUDE.md §6)."
    ]


def _main(argv: list[str] | None = None) -> int:
    # Force UTF-8 output so a cp1252 (Windows) console can't crash on non-ASCII (0.19.0).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Score team findings vs a golden manifest.")
    ap.add_argument("--expected", help="path to expected.yaml")
    ap.add_argument("--findings", help="path to findings JSON")
    ap.add_argument(
        "--check-tag-basis",
        metavar="PACK.jsonl",
        help="cross-check one findings pack: fail if it records a tool or pass as "
        "unavailable while a finding still claims basis=measured (W-9). Exits 1 on a "
        "problem, 0 when consistent.",
    )
    args = ap.parse_args(argv)

    if args.check_tag_basis:
        problems = check_tag_basis(_pack_records(Path(args.check_tag_basis)))
        for problem in problems:
            print(problem, file=sys.stderr)
        if not problems:
            print("tag basis consistent with recorded tooling coverage")
        return 1 if problems else 0

    if not args.expected or not args.findings:
        ap.error("--expected and --findings are both required unless --check-tag-basis is used")

    expected = _load_yaml(args.expected)
    findings = json.loads(Path(args.findings).read_text(encoding="utf-8")).get("findings", [])
    result = score(expected, findings)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(_main())
