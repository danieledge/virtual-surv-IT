#!/usr/bin/env python3
"""Deterministic scorer for the team-quality eval harness (evals/).

The 58 unit tests check the *code*. This scores the *team's output* - did a review catch the
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
import json
import sys
from pathlib import Path

_SEVERITY_RANK = {"style": 0, "medium": 1, "warning": 2, "critical": 3}
_LINE_TOLERANCE = 3  # a planted issue at file:12 matches a finding at file:10-14


def _load_yaml(path: str | Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover - exercised only without pyyaml
        raise RuntimeError("pyyaml is required: pip install -r requirements-dev.txt")
    return yaml.safe_load(Path(path).read_text())


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


def _severity_ok(finding_sev: str | None, floor: str | None) -> bool:
    """True if the finding's severity is at or above the required floor (or no floor set)."""
    if not floor:
        return True
    return _SEVERITY_RANK.get(_norm(finding_sev), -1) >= _SEVERITY_RANK.get(_norm(floor), 99)


def _location_matches(spec_loc: str | None, finding_loc: str | None) -> bool:
    if not spec_loc:
        return False
    sf, sl = _parse_location(spec_loc)
    ff, fl = _parse_location(finding_loc)
    if not sf or sf not in ff and ff not in sf:  # file must overlap
        return False
    if sl is None or fl is None:
        return True  # file-level match when no line given on either side
    return abs(sl - fl) <= _LINE_TOLERANCE


def _matches(spec: dict, finding: dict) -> bool:
    """A finding matches a planted/forbidden spec if location OR any keyword matches."""
    hay = _norm(
        f"{finding.get('title', '')} {finding.get('kind', '')} {finding.get('location', '')}"
    )
    if _location_matches(spec.get("location"), finding.get("location")):
        return _severity_ok(finding.get("severity"), spec.get("min_severity"))
    for kw in spec.get("keywords", []) or []:
        if _norm(kw) in hay:
            return _severity_ok(finding.get("severity"), spec.get("min_severity"))
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

    triggered = [t.get("id", "?") for t in forbidden if any(_matches(t, f) for f in findings)]

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


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score team findings vs a golden manifest.")
    ap.add_argument("--expected", required=True, help="path to expected.yaml")
    ap.add_argument("--findings", required=True, help="path to findings JSON")
    args = ap.parse_args(argv)

    expected = _load_yaml(args.expected)
    findings = json.loads(Path(args.findings).read_text()).get("findings", [])
    result = score(expected, findings)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(_main())
