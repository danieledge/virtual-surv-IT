"""scripts/explain_rule.py - the "why did this NOT alert?" trace (absence plan Phase 2).

The rule's non-fire paths are silent by design; the explainer re-evaluates without
short-circuit and must (a) agree with detect_spoofing about what fired, (b) name the
first failing condition in the rule's own order, and (c) quantify distance-to-threshold
counterfactuals - the case-level generalisation of BTL."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rules.spoofing import SpoofingThresholds, detect_spoofing
from scripts.explain_rule import explain_events
from scripts.gen_synthetic import benign_session, spoofing_session

REPO_ROOT = Path(__file__).resolve().parents[1]


def _orders(result):
    return {o["order_id"]: o for g in result["groups"] for o in g["orders"]}


def test_agrees_with_detect_spoofing_on_what_fired():
    for gen, seed in ((spoofing_session, 1), (benign_session, 3)):
        events = gen(seed=seed)
        result = explain_events(events)
        fired = {a.spoof_order_id for a in detect_spoofing(events)}
        assert {a["order_id"] for a in result["alerts"]} == fired
        for oid, o in _orders(result).items():
            assert o["alerted"] == (oid in fired)


def test_benign_orders_get_a_first_failing_condition():
    result = explain_events(benign_session(seed=1))
    assert not result["alerts"]
    for o in _orders(result).values():
        assert o["first_failing_condition"] is not None
        failed = [c for c in o["conditions"] if not c["pass"]]
        assert failed and failed[0]["id"] == o["first_failing_condition"]


def test_near_miss_names_the_suppressing_threshold_with_distance():
    """Tighten the outsized multiple so the true spoof misses on C4 alone - the
    explainer must localise it there and quantify the distance (the tests file already
    proves thresholds are injectable and change the outcome; this proves the explainer
    NARRATES that suppression instead of leaving a silent skip)."""
    events = spoofing_session(seed=1)
    tight = SpoofingThresholds(large_qty_multiple=50.0)
    assert not detect_spoofing(events, tight)  # suppressed by the tightened threshold
    result = explain_events(events, thresholds=tight)
    spoof = _orders(result)["SPOOF1"]
    assert spoof["first_failing_condition"] == "C4"
    c4 = next(c for c in spoof["conditions"] if c["id"] == "C4")
    assert not c4["pass"]
    assert "would alert at large_qty_multiple <=" in c4["counterfactual"]


def test_order_focus_filters_the_report():
    result = explain_events(spoofing_session(seed=1), order_id="SPOOF1")
    assert list(_orders(result)) == ["SPOOF1"]


def test_cli_json_is_machine_readable_and_cli_md_is_clean(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.explain_rule", "--generator", "benign", "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "groups" in data and "alerts" in data
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.explain_rule", "--generator", "spoofing"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "Alerts fired: 1" in proc.stdout
    assert "first failing" in proc.stdout  # the absence narration exists alongside the alert
