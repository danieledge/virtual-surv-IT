"""Outsized-order threshold helper for trade-surveillance triage.

A small, self-contained utility with a single documented constant and one
pure function. Synthetic sample data only.
"""

# Outsized-order threshold: an order at or above this multiple of the desk's
# rolling median notional is treated as outsized for trade-surveillance triage.
# Calibrated against 12 months of synthetic desk data (tuning date 2026-05-30);
# see calibration note CAL-2026-05. Documented constant - rationale recorded here.
OUTSIZED_NOTIONAL_MULTIPLE = 4.0


def is_outsized_order(order_notional, desk_median_notional):
    """Return True if an order is outsized relative to its desk's median.

    Args:
        order_notional: Notional value of the order under assessment. Must be
            non-negative.
        desk_median_notional: Rolling median notional for the order's desk over
            the calibration window. Must be positive.

    Returns:
        bool: True if ``order_notional`` is at or above
        ``OUTSIZED_NOTIONAL_MULTIPLE`` times the desk median, else False.

    Raises:
        ValueError: If ``desk_median_notional`` is not positive, since a median
            of zero or below cannot anchor the comparison.
    """
    if desk_median_notional <= 0:
        # Early return guards against a divide-by-zero-style meaningless
        # comparison; an explicit error is clearer than silently returning False.
        raise ValueError("desk_median_notional must be positive")

    return order_notional >= OUTSIZED_NOTIONAL_MULTIPLE * desk_median_notional
