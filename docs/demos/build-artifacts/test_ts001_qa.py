"""
Independent QA test suite - TS-001 Wash Trade / Self-Match (DEMO).
Author: Linh (qa-engineer) - independent of the builder (Mateo / rules-developer).
Synthetic data only (CLAUDE.md ss.5).

PRIOR-FILE FINDING (recorded here as part of the QA audit trail):
  The pre-existing test_ts001_qa.py (overwritten by this file) failed at collection with
  ImportError: cannot import name 'UBOGraphStaleError' from 'ts001_wash_trade'.
  That name does not exist in the actual detector. The prior file also used wrong argument
  order and wrong DetectionParams field name ('off_market_threshold_bps' vs
  'off_market_spread_multiple'). It provided zero coverage. All tests here are freshly
  designed against the real API.

Coverage targets:
  - Spread-multiple threshold boundary (DR-002): at / just-over / just-under
  - Notional floor boundary (DR-004): exactly at / just below
  - Lookback-window boundary (DR-001): exactly at / one-over
  - UBO freshness boundary (DR-005): exactly at limit / one-over / partial-stale
  - Empty and edge inputs (no crash, unknown side, unmapped account)
  - Multiple pairs in one window (cross-product, cross-instrument isolation)
  - Alert field completeness (obligation fields, sequential IDs, field arithmetic consistency)
  - Safe-harbour variants (account register, strategy tag, non-exempt tag)
  - Zero / negative spread snapshot (DR-002 denominator guard)
  - Snapshot fallback (buy-date absent, sell-date present)

Run: cd docs/demos/build-artifacts && python3 -m pytest test_ts001_qa.py -v
"""

from datetime import date, timedelta

import pytest

from ts001_wash_trade import (
    BUY,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_PAIR_NOTIONAL,
    DEFAULT_OFF_MARKET_SPREAD_MULTIPLE,
    DEFAULT_UBO_GRAPH_MAX_AGE_DAYS,
    SELL,
    DetectionParams,
    MarketSnapshot,
    Trade,
    UBOLink,
    detect_wash_trades,
)

# ---------------------------------------------------------------------------
# Shared fixtures - all values synthetic (CLAUDE.md ss.5)
# ---------------------------------------------------------------------------

AS_OF = date(2026, 6, 30)
FRESH = AS_OF - timedelta(days=1)   # graph 1 day old, well within 90-day limit
INSTR = "SYNTH-EQ-QA-001"
MID = 100.0
SPREAD_BPS = 5.0   # time-weighted average spread
_BPS_FACTOR = 10_000.0  # same constant used in the detector's _price_deviation_bps

SNAP = MarketSnapshot(INSTR, AS_OF, mid_price=MID, time_weighted_spread_bps=SPREAD_BPS)


def _ubo(*accounts: str, group: str = "UBO-QA-X", as_of: date = FRESH) -> list[UBOLink]:
    """Build UBO links for all accounts into one group (synthetic identifiers)."""
    return [UBOLink(acc, group, as_of) for acc in accounts]


def _trade(
    tid: str,
    acct: str,
    side: str,
    price: float,
    qty: float = 100.0,
    instr: str = INSTR,
    d: date = AS_OF,
    tag: str | None = None,
) -> Trade:
    return Trade(tid, acct, instr, side, price, qty, d, tag)


def _run(trades, ubo, snapshots=(SNAP,), params=None, as_of=AS_OF):
    return detect_wash_trades(trades, ubo, snapshots, as_of, params)


# ---------------------------------------------------------------------------
# 1. Spread-multiple threshold boundary (DR-002)
#
#    The early-continue condition is: normalised <= off_market_spread_multiple
#    => at exactly the threshold, no alert; strictly greater than fires the alert.
#
#    Float-measured values (python3 arithmetic - verified before writing these tests):
#      price=100.05 -> normalised = 0.9999...  (<  1.0)  -> no alert with default threshold 1.0
#      price=100.06 -> normalised = 1.2000...  (>  1.0)  -> alert
#      price=100.60 -> normalised = 11.9999... (>> 1.0)  -> alert
# ---------------------------------------------------------------------------

class TestSpreadMultipleBoundary:

    def test_normalised_below_threshold_no_alert(self):
        """DR-002: normalised (0.9999..) < default threshold (1.0) -> early-continue, no alert.
        price=100.05 produces a deviation just under 1 spread-multiple (confirmed by float check).
        """
        trades = [_trade("B1", "ACCT-A", BUY, 100.05), _trade("S1", "ACCT-B", SELL, 100.05)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        assert result.alerts == [], (
            "Normalised deviation below the threshold must not alert (early-continue condition is <=)."
        )

    def test_normalised_above_threshold_alerts(self):
        """DR-002: normalised (1.2000..) > default threshold (1.0) -> alert fires.
        price=100.06 is comfortably above 1 spread-multiple.
        """
        trades = [_trade("B1", "ACCT-A", BUY, 100.06), _trade("S1", "ACCT-B", SELL, 100.06)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        assert len(result.alerts) == 1, "Normalised deviation above the threshold must alert."
        assert result.alerts[0].spread_normalised_deviation > DEFAULT_OFF_MARKET_SPREAD_MULTIPLE

    def test_threshold_set_to_computed_normalised_no_alert(self):
        """DR-002 boundary (<=): when off_market_spread_multiple == computed normalised, no alert fires.
        Sets the threshold to the exact float value the detector will compute, so the comparison is
        normalised <= normalised which is trivially True -> early-continue -> no alert.
        This tests the <= (inclusive) semantics directly, without depending on a specific float literal.
        """
        price = 100.60
        # Mirror the detector's _price_deviation_bps + normalisation (same float arithmetic)
        computed_dev_bps = abs(price - MID) / MID * _BPS_FACTOR
        computed_normalised = computed_dev_bps / SPREAD_BPS
        params = DetectionParams(off_market_spread_multiple=computed_normalised)
        trades = [_trade("B1", "ACCT-A", BUY, price), _trade("S1", "ACCT-B", SELL, price)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), params=params)
        assert result.alerts == [], (
            f"Threshold set to computed normalised ({computed_normalised:.6f}); "
            "condition (normalised <= threshold) is True -> no alert."
        )

    def test_threshold_below_normalised_alerts(self):
        """DR-002 boundary: threshold set 1.0 below normalised -> condition False -> alert fires."""
        price = 100.60
        computed_dev_bps = abs(price - MID) / MID * _BPS_FACTOR
        computed_normalised = computed_dev_bps / SPREAD_BPS   # ~12.0
        params = DetectionParams(off_market_spread_multiple=computed_normalised - 1.0)  # ~11.0
        trades = [_trade("B1", "ACCT-A", BUY, price), _trade("S1", "ACCT-B", SELL, price)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), params=params)
        assert len(result.alerts) == 1, (
            "Threshold below computed normalised -> condition (normalised <= threshold) is False -> alert."
        )

    def test_asymmetric_leg_prices_avg_governs(self):
        """DR-002 uses the AVERAGE of the two leg prices, not each leg individually.
        buy=100.02 (below threshold alone), sell=100.14 (above threshold alone):
        avg = 100.08 -> normalised > 1.0 -> alert fires.
        """
        trades = [_trade("B1", "ACCT-A", BUY, 100.02), _trade("S1", "ACCT-B", SELL, 100.14)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        assert len(result.alerts) == 1
        assert abs(result.alerts[0].avg_leg_price - 100.08) < 0.001


# ---------------------------------------------------------------------------
# 2. Materiality floor boundary (DR-004)
#
#    Condition: matched_notional < min_pair_notional -> skip (no alert)
#    => at exactly the floor, NOT < -> alert; just below -> no alert.
#    matched_notional = min(buy.price * buy.quantity, sell.price * sell.quantity)
# ---------------------------------------------------------------------------

class TestNotionalBoundary:

    def test_exactly_at_notional_floor_alerts(self):
        """DR-004: matched_notional == min_pair_notional -> condition (< floor) is False -> alert.
        Sets floor = price * qty so the notionals are exactly equal.
        """
        price, qty = 100.60, 100.0
        notional = price * qty  # 10060.0
        params = DetectionParams(min_pair_notional=notional)
        trades = [_trade("B1", "ACCT-A", BUY, price, qty=qty), _trade("S1", "ACCT-B", SELL, price, qty=qty)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), params=params)
        assert len(result.alerts) == 1, (
            "At exactly the notional floor the condition (< floor) is False; alert must fire."
        )
        assert result.alerts[0].matched_notional == pytest.approx(notional)

    def test_just_below_notional_floor_no_alert(self):
        """DR-004: matched_notional marginally below floor -> alert suppressed."""
        price, qty = 100.60, 100.0
        notional = price * qty          # 10060.0
        params = DetectionParams(min_pair_notional=notional + 0.01)  # floor set 0.01 above
        trades = [_trade("B1", "ACCT-A", BUY, price, qty=qty), _trade("S1", "ACCT-B", SELL, price, qty=qty)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), params=params)
        assert result.alerts == [], "Just below notional floor must not alert."

    def test_notional_uses_smaller_leg(self):
        """DR-004 matched_notional is min(buy_notional, sell_notional), not the larger.
        buy=200 units (notional 20120), sell=100 units (notional 10060).
        Floor set to 10060 -> smaller leg equals floor -> alert (not < floor).
        """
        price = 100.60
        buy_qty, sell_qty = 200.0, 100.0
        params = DetectionParams(min_pair_notional=price * sell_qty)  # floor = 10060
        trades = [
            _trade("B1", "ACCT-A", BUY, price, qty=buy_qty),
            _trade("S1", "ACCT-B", SELL, price, qty=sell_qty),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), params=params)
        assert len(result.alerts) == 1
        assert result.alerts[0].matched_notional == pytest.approx(price * sell_qty)


# ---------------------------------------------------------------------------
# 3. Lookback-window boundary (DR-001)
#
#    Condition: abs(days_apart) > lookback_days -> skip
#    => at exactly lookback_days apart: NOT > -> in window -> alert
#    => lookback_days + 1 days apart: > -> out of window -> no alert
# ---------------------------------------------------------------------------

class TestLookbackWindowBoundary:

    def test_exactly_at_lookback_days_pairs(self):
        """DR-001: legs exactly DEFAULT_LOOKBACK_DAYS (1) apart -> in window -> alert.
        abs(1) > 1 is False, so the pair is within the window.
        """
        buy_date = date(2026, 6, 29)   # 1 day before AS_OF
        sell_date = AS_OF              # 1-day gap == DEFAULT_LOOKBACK_DAYS
        snap_prev = MarketSnapshot(INSTR, buy_date, MID, SPREAD_BPS)
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60, d=buy_date),
            _trade("S1", "ACCT-B", SELL, 100.60, d=sell_date),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(SNAP, snap_prev))
        assert len(result.alerts) == 1, (
            f"Legs {DEFAULT_LOOKBACK_DAYS} day(s) apart must be in-window (condition is >, not >=)."
        )

    def test_one_over_lookback_days_no_alert(self):
        """DR-001: legs DEFAULT_LOOKBACK_DAYS+1 (2) days apart -> out of window -> no alert.
        abs(2) > 1 is True -> pair excluded.
        """
        buy_date = date(2026, 6, 28)   # 2 days before AS_OF
        sell_date = AS_OF              # 2-day gap > DEFAULT_LOOKBACK_DAYS=1
        snap_prev = MarketSnapshot(INSTR, buy_date, MID, SPREAD_BPS)
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60, d=buy_date),
            _trade("S1", "ACCT-B", SELL, 100.60, d=sell_date),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(SNAP, snap_prev))
        assert result.alerts == [], (
            f"Legs {DEFAULT_LOOKBACK_DAYS + 1} day(s) apart must be out-of-window."
        )


# ---------------------------------------------------------------------------
# 4. UBO graph freshness boundary (DR-005)
#
#    Condition: age_days > ubo_graph_max_age_days -> stale (excluded + DQ warning)
#    => at exactly max_age_days: NOT > -> included (fresh)
#    => at max_age_days+1: > -> stale, excluded, DQ warning
# ---------------------------------------------------------------------------

class TestUboFreshnessBoundary:

    def test_ubo_age_exactly_at_limit_is_included(self):
        """DR-005: graph age == DEFAULT_UBO_GRAPH_MAX_AGE_DAYS -> NOT stale -> account included -> alert.
        The condition is age_days > limit (strict greater-than); at exactly the limit it is not stale.
        """
        exactly_at = AS_OF - timedelta(days=DEFAULT_UBO_GRAPH_MAX_AGE_DAYS)  # age = 90 days
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B", as_of=exactly_at))
        assert len(result.alerts) == 1, (
            "Graph at exactly the freshness limit must be treated as current (condition is >, not >=)."
        )
        assert result.data_quality_warnings == [], "No DQ warning expected for a graph exactly at the limit."

    def test_ubo_age_one_over_limit_excluded_with_dq_warning(self):
        """DR-005: graph age == DEFAULT_UBO_GRAPH_MAX_AGE_DAYS+1 -> stale -> excluded, DQ warning, no alert."""
        one_over = AS_OF - timedelta(days=DEFAULT_UBO_GRAPH_MAX_AGE_DAYS + 1)  # age = 91 days
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B", as_of=one_over))
        assert result.alerts == [], "Stale graph must produce no alert."
        assert len(result.data_quality_warnings) >= 2, (
            "A DQ warning must be raised for each excluded account (two accounts here)."
        )
        dq_text = " ".join(result.data_quality_warnings).lower()
        assert "old" in dq_text or "days" in dq_text, "DQ warning must mention the graph age."

    def test_partial_stale_excludes_stale_account_fresh_pair_still_alerts(self):
        """DR-005: one stale account excluded; the fresh pair (A/B) in the same UBO group still alerts.
        Tests that DR-005 exclusion is per-account, not a run-level abort.
        """
        stale_date = AS_OF - timedelta(days=DEFAULT_UBO_GRAPH_MAX_AGE_DAYS + 1)
        ubo = [
            UBOLink("ACCT-A", "UBO-QA-X", FRESH),
            UBOLink("ACCT-B", "UBO-QA-X", FRESH),
            UBOLink("ACCT-C", "UBO-QA-X", stale_date),   # stale - must be excluded
        ]
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60),
            _trade("S1", "ACCT-B", SELL, 100.60),
            _trade("S2", "ACCT-C", SELL, 100.60),   # stale account - should be skipped
        ]
        result = _run(trades, ubo)
        assert len(result.alerts) == 1, (
            "Fresh A/B pair must still alert; stale ACCT-C must be excluded, not abort the run."
        )
        assert result.alerts[0].buy_account_id == "ACCT-A"
        assert result.alerts[0].sell_account_id == "ACCT-B"
        assert any("ACCT-C" in w for w in result.data_quality_warnings), (
            "DQ warning must name the excluded stale account."
        )


# ---------------------------------------------------------------------------
# 5. Empty and edge inputs
# ---------------------------------------------------------------------------

class TestEdgeInputs:

    def test_empty_trades_no_crash(self):
        """Empty trade list returns empty result without raising."""
        result = _run([], _ubo("ACCT-A", "ACCT-B"))
        assert result.alerts == []
        assert result.data_quality_warnings == []

    def test_empty_ubo_links_no_crash(self):
        """No UBO links: all accounts unknown to the graph -> no pairs formed, no crash."""
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, [])
        assert result.alerts == []

    def test_completely_empty_input_no_crash(self):
        """All inputs empty -> returns empty result without raising."""
        result = _run([], [], snapshots=())
        assert result.alerts == []
        assert result.data_quality_warnings == []
        assert result.suppressions == []

    def test_unknown_side_is_not_treated_as_buy_or_sell(self):
        """A trade with side 'BOTH' (not BUY/SELL) is silently excluded from both buy/sell lists."""
        trades = [
            _trade("X1", "ACCT-A", "BOTH", 100.60),   # invalid side
            _trade("S1", "ACCT-B", SELL, 100.60),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        assert result.alerts == [], "Invalid side must not be paired."

    def test_trade_account_not_in_ubo_graph_is_silently_excluded(self):
        """A trade whose account has no UBO link is excluded from pairing (not in ubo_index)."""
        trades = [
            _trade("B1", "ACCT-ORPHAN", BUY, 100.60),  # account absent from UBO graph
            _trade("S1", "ACCT-B", SELL, 100.60),
        ]
        result = _run(trades, _ubo("ACCT-B"))  # ACCT-ORPHAN has no link
        assert result.alerts == []


# ---------------------------------------------------------------------------
# 6. Multiple pairs in one window
# ---------------------------------------------------------------------------

class TestMultiplePairs:

    def test_two_buys_two_sells_same_ubo_full_cross_product(self):
        """DR-001: 2 buys x 2 sells in the same UBO group -> 4 alerts (full cross-product).
        Verifies the detector iterates all combinations, not just first-found.
        """
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60),
            _trade("B2", "ACCT-B", BUY, 100.60),
            _trade("S1", "ACCT-C", SELL, 100.60),
            _trade("S2", "ACCT-D", SELL, 100.60),
        ]
        ubo = _ubo("ACCT-A", "ACCT-B", "ACCT-C", "ACCT-D")
        result = _run(trades, ubo)
        assert len(result.alerts) == 4, (
            "All buy-sell combinations within the same UBO group and lookback must alert."
        )

    def test_cross_instrument_pairs_are_not_formed(self):
        """DR-001: a buy in SYNTH-EQ-QA-001 must not pair with a sell in SYNTH-EQ-QA-002."""
        snap2 = MarketSnapshot("SYNTH-EQ-QA-002", AS_OF, MID, SPREAD_BPS)
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60, instr="SYNTH-EQ-QA-001"),
            _trade("S1", "ACCT-B", SELL, 100.60, instr="SYNTH-EQ-QA-002"),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(SNAP, snap2))
        assert result.alerts == [], "Cross-instrument pairs must never alert."

    def test_cross_ubo_group_does_not_pair(self):
        """DR-001: accounts in different UBO groups must not pair, regardless of price deviation."""
        ubo = _ubo("ACCT-A", group="UBO-QA-X") + _ubo("ACCT-B", group="UBO-QA-Y")
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, ubo)
        assert result.alerts == [], "Different UBO groups must not produce a pair."


# ---------------------------------------------------------------------------
# 7. Alert field completeness and ID sequencing
# ---------------------------------------------------------------------------

class TestAlertFields:

    def test_alert_carries_all_mandatory_obligation_fields(self):
        """Every alert must carry obligation_reference, obligation_status, and ubo_group_id as
        typed fields (not free text), per SCN-001 DR-004 and CLAUDE.md ss.4.
        """
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        assert len(result.alerts) == 1
        a = result.alerts[0]
        assert a.obligation_reference == "EU MAR Art.12(1)(a)", (
            "Obligation reference must be the exact string from the spec; it is audit-facing."
        )
        assert a.obligation_status == "PROVISIONAL", (
            "Obligation status must be PROVISIONAL until SME Q1/Q3/Q4 resolved (SMV-001 ss.5)."
        )
        assert a.ubo_group_id == "UBO-QA-X", "UBO group id is the keystone linkage field."

    def test_alert_ids_are_sequential_and_embed_as_of_date(self):
        """Multiple alerts in one run must receive sequential IDs embedding the as_of_date."""
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60),
            _trade("B2", "ACCT-B", BUY, 100.60),
            _trade("S1", "ACCT-C", SELL, 100.60),
            _trade("S2", "ACCT-D", SELL, 100.60),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B", "ACCT-C", "ACCT-D"))
        ids = [a.alert_id for a in result.alerts]
        assert ids == sorted(ids), "Alert IDs must be in ascending (sequential) order."
        assert all(AS_OF.isoformat() in aid for aid in ids), (
            "Alert ID must embed the as_of_date so it is deterministic and date-bound."
        )
        assert all(aid.startswith("TS001-") for aid in ids), "Alert ID prefix must be TS001-."

    def test_alert_spread_deviation_arithmetic_consistency(self):
        """spread_normalised_deviation in the alert must equal price_deviation_bps / time_weighted_spread_bps.
        Verifies the three related numeric fields are internally consistent.
        """
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        a = result.alerts[0]
        expected = a.price_deviation_bps / a.time_weighted_spread_bps
        assert a.spread_normalised_deviation == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 8. Safe-harbour suppression (DR-003)
# ---------------------------------------------------------------------------

class TestSafeHarbour:

    def test_exempt_via_account_register_suppressed_and_logged(self):
        """DR-003: account on the static exempt_account_ids register -> suppression logged, no alert.
        Logging (not silent discard) is the evidential requirement: the suppression trail must exist.
        """
        params = DetectionParams(exempt_account_ids=frozenset({"MM-ACCT-QA-001"}))
        ubo = _ubo("MM-ACCT-QA-001", "ACCT-B")
        trades = [
            _trade("B1", "MM-ACCT-QA-001", BUY, 100.60),
            _trade("S1", "ACCT-B", SELL, 100.60),
        ]
        result = _run(trades, ubo, params=params)
        assert result.alerts == [], "Exempt-register account must not alert."
        assert any("MM-ACCT-QA-001" in s for s in result.suppressions), (
            "Suppression record must name the exempt account for the audit trail."
        )

    def test_exempt_via_strategy_tag_suppressed_and_logged(self):
        """DR-003: RISKLESS_PRINCIPAL strategy tag -> suppression logged, no alert."""
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60, tag="RISKLESS_PRINCIPAL"),
            _trade("S1", "ACCT-B", SELL, 100.60),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        assert result.alerts == [], "Strategy-tagged leg must not alert."
        assert any("RISKLESS_PRINCIPAL" in s for s in result.suppressions), (
            "Suppression record must name the strategy tag."
        )

    def test_non_exempt_strategy_tag_does_not_suppress(self):
        """DR-003: a strategy tag not in exempt_strategy_tags must not suppress an off-market pair.
        ALGO_TWAP is not in the default exempt set; the pair should alert normally.
        """
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60, tag="ALGO_TWAP"),
            _trade("S1", "ACCT-B", SELL, 100.60),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
        assert len(result.alerts) == 1, (
            "ALGO_TWAP is not an exempt tag; the off-market pair must alert."
        )


# ---------------------------------------------------------------------------
# 9. Zero / negative spread snapshot (DR-002 denominator guard)
# ---------------------------------------------------------------------------

class TestZeroAndNegativeSpread:

    def test_zero_spread_raises_dq_warning_and_no_alert(self):
        """DR-002 denominator guard: spread == 0.0 -> cannot normalise -> DQ warning, no alert."""
        zero_snap = MarketSnapshot(INSTR, AS_OF, mid_price=MID, time_weighted_spread_bps=0.0)
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(zero_snap,))
        assert result.alerts == [], "Zero-spread snapshot must not produce an alert."
        dq_text = " ".join(result.data_quality_warnings).lower()
        assert "spread" in dq_text or "non-positive" in dq_text, (
            "A data-quality warning must flag the zero-spread condition."
        )

    def test_negative_spread_raises_dq_warning_and_no_alert(self):
        """DR-002 denominator guard: spread < 0.0 -> cannot normalise -> DQ warning, no alert."""
        neg_snap = MarketSnapshot(INSTR, AS_OF, mid_price=MID, time_weighted_spread_bps=-1.0)
        trades = [_trade("B1", "ACCT-A", BUY, 100.60), _trade("S1", "ACCT-B", SELL, 100.60)]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(neg_snap,))
        assert result.alerts == [], "Negative-spread snapshot must not produce an alert."
        assert len(result.data_quality_warnings) > 0, "A DQ warning must be raised."


# ---------------------------------------------------------------------------
# 10. Snapshot fallback logic
#     The detector first tries (instrument, buy_date); falls back to (instrument, sell_date).
# ---------------------------------------------------------------------------

class TestSnapshotFallback:

    def test_missing_buy_date_snapshot_falls_back_to_sell_date(self):
        """When the buy-date snapshot is absent, the detector falls back to the sell-date snapshot.
        This means one-sided snapshot gaps still allow the pair to be evaluated.
        """
        buy_date = date(2026, 6, 29)  # 1 day before AS_OF (within default lookback of 1)
        # Provide only the AS_OF (sell-date) snapshot, not the buy-date one
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60, d=buy_date),
            _trade("S1", "ACCT-B", SELL, 100.60, d=AS_OF),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(SNAP,))
        assert len(result.alerts) == 1, (
            "Fallback to sell-date snapshot must allow the pair to alert "
            "when the buy-date snapshot is missing."
        )
        assert result.alerts[0].snapshot_date == AS_OF, "Alert must record the snapshot date used."

    def test_both_dates_missing_snapshot_raises_dq_warning(self):
        """When no snapshot exists for either leg's date, a DQ warning is raised and no alert fires."""
        buy_date = date(2026, 6, 29)
        trades = [
            _trade("B1", "ACCT-A", BUY, 100.60, d=buy_date),
            _trade("S1", "ACCT-B", SELL, 100.60, d=AS_OF),
        ]
        result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=())  # no snapshots at all
        assert result.alerts == []
        assert any("snapshot" in w.lower() for w in result.data_quality_warnings), (
            "Missing snapshot must surface as a data-quality warning, not silent omission."
        )
