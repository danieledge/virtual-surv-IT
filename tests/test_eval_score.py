"""Unit tests for the eval-harness scorer (scripts/eval_score.py).

Verifies the deterministic matching/scoring logic so the regression backbone is itself
trustworthy - independent of ever running the team.
"""

from scripts.eval_score import score


def _expected(**over):
    base = {
        "case": "demo",
        "planted": [
            {
                "id": "SEC-1",
                "keywords": ["hardcoded secret", "credential"],
                "location": "config.py:12",
                "min_severity": "critical",
                "must_find": True,
            },
            {"id": "PERF-1", "keywords": ["o(n^2)", "nested loop"], "must_find": False},
        ],
        "forbidden": [
            {"id": "FP-1", "keywords": ["documented threshold"]},
        ],
        "pass": {"require_all_must_find": True, "forbid_all": True},
    }
    base.update(over)
    return base


def test_perfect_run_passes():
    findings = [
        {
            "severity": "critical",
            "location": "config.py:12",
            "title": "Hardcoded secret in config",
            "kind": "security",
        },
        {"severity": "medium", "title": "O(n^2) nested loop over orders", "kind": "performance"},
    ]
    r = score(_expected(), findings)
    assert r["passed"] is True
    assert r["recall"] == 1.0
    assert r["planted_missed"] == []
    assert r["false_positive_traps_triggered"] == []


def test_missing_must_find_critical_fails():
    findings = [{"severity": "medium", "title": "O(n^2) nested loop", "kind": "performance"}]
    r = score(_expected(), findings)
    assert r["passed"] is False
    assert "SEC-1" in r["must_find_missed"]
    assert r["recall"] == 0.5


def test_severity_floor_enforced():
    # The secret is flagged, but only as 'style' - below the required 'critical' floor.
    findings = [
        {
            "severity": "style",
            "location": "config.py:12",
            "title": "hardcoded secret",
            "kind": "security",
        }
    ]
    r = score(_expected(), findings)
    assert "SEC-1" in r["must_find_missed"]
    assert r["passed"] is False


def test_false_positive_trap_fails_the_run():
    findings = [
        {
            "severity": "critical",
            "location": "config.py:12",
            "title": "hardcoded credential",
            "kind": "security",
        },
        {"severity": "warning", "title": "the documented threshold looks wrong", "kind": "logic"},
    ]
    r = score(_expected(), findings)
    assert r["false_positive_traps_triggered"] == ["FP-1"]
    assert r["passed"] is False  # forbid_all -> any trap fails the run


def test_location_match_within_line_tolerance():
    # planted at :12, finding reports :14 -> within +/-3 tolerance, still a match.
    findings = [
        {
            "severity": "critical",
            "location": "config.py:14",
            "title": "secret leaked",
            "kind": "security",
        }
    ]
    r = score(_expected(), findings)
    # keyword 'hardcoded secret'/'credential' not present, but the location matches.
    assert "SEC-1" in r["planted_found"]


def test_keyword_match_without_location():
    findings = [
        {"severity": "critical", "title": "found a hardcoded secret value", "kind": "security"}
    ]
    r = score(_expected(), findings)
    assert "SEC-1" in r["planted_found"]


def test_non_must_find_miss_still_passes():
    # Only the must-find critical is found; the optional PERF-1 is missed -> still passes.
    findings = [
        {
            "severity": "critical",
            "location": "config.py:12",
            "title": "hardcoded credential",
            "kind": "security",
        }
    ]
    r = score(_expected(), findings)
    assert r["passed"] is True
    assert "PERF-1" in r["planted_missed"]
    assert r["recall"] == 0.5
