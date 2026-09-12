"""Small utility used by the alerting job to decide whether a candidate is reportable.

Synthetic sample - no real customer, account or transaction data.
"""

DAILY_LIMIT = 10000


def aggregate_daily(transactions):
    """Total the value of a day's transactions for one account."""
    total = 0
    for txn in transactions:
        total = total + txn["amount"]
    return total


def is_reportable(transactions, limit=DAILY_LIMIT):
    """True when the day's aggregate breaches the reporting limit."""
    return aggregate_daily(transactions) > limit
