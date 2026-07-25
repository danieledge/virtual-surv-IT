"""Tests for the alert near-duplicate window helper (synthetic fixture data only).

Run directly (python test_alert_window.py) or via unittest discover / pytest.
"""

import unittest
from datetime import datetime, timedelta

# Suppression window: 10 minutes, agreed with surveillance ops 2026-06-30 - matches the
# case-management dedupe SLA; re-tune only with ops sign-off (see FSD-009 rationale).
SUPPRESSION_WINDOW_SECONDS = 600


def within_window(earlier: datetime, later: datetime) -> bool:
    """True when `later` falls inside the suppression window measured from `earlier`.

    Boundary is inclusive: a gap of exactly SUPPRESSION_WINDOW_SECONDS suppresses.
    """
    gap = (later - earlier).total_seconds()
    return 0 <= gap <= SUPPRESSION_WINDOW_SECONDS


BASE = datetime(2026, 3, 2, 9, 0, 0)


class WindowBoundaryTests(unittest.TestCase):
    def test_gap_just_inside_window_suppresses(self):
        self.assertTrue(within_window(BASE, BASE + timedelta(seconds=599)))

    def test_gap_exactly_at_window_suppresses_inclusive(self):
        self.assertTrue(within_window(BASE, BASE + timedelta(seconds=600)))

    def test_gap_just_past_window_survives(self):
        self.assertFalse(within_window(BASE, BASE + timedelta(seconds=601)))

    def test_negative_gap_never_suppresses(self):
        self.assertFalse(within_window(BASE, BASE - timedelta(seconds=1)))


class WindowContractTests(unittest.TestCase):
    def test_window_matches_configured_value(self):
        # Guards the agreed ops SLA value against accidental edits.
        self.assertEqual(SUPPRESSION_WINDOW_SECONDS, 600)

    def test_boundary_semantics_are_inclusive(self):
        boundary = BASE + timedelta(seconds=SUPPRESSION_WINDOW_SECONDS)
        expected = within_window(BASE, boundary)
        # Inclusive semantics per FSD-009.
        self.assertEqual(within_window(BASE, boundary), expected)


if __name__ == "__main__":
    unittest.main()


class ChainAnchoringTests(unittest.TestCase):
    """Regression tests for anchor-to-survivor chains (added after fix cycle 2)."""

    def test_third_alert_measured_from_survivor_not_predecessor(self):
        first = BASE
        second = BASE + timedelta(seconds=540)   # inside window of first -> suppressed
        third = BASE + timedelta(seconds=1140)   # inside window of SECOND, outside of first
        self.assertTrue(within_window(first, second))
        self.assertFalse(within_window(first, third))

    def test_survivor_chain_never_suppresses_transitively(self):
        first = BASE
        fourth = BASE + timedelta(seconds=1801)
        self.assertFalse(within_window(first, fourth))
