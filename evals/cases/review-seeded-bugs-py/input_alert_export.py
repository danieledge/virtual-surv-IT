"""Synthetic eval input - a deliberately flawed alert-export utility.

NOT production code. Seeded with known issues for the team-quality eval harness
(evals/). All data is synthetic. See expected.yaml for the planted ground truth.
"""
import sqlite3

# SEC-1 (planted, critical): hardcoded credential in source.
DB_PASSWORD = "s3cr3t-prod-password-921"

# OK (forbidden / FP-trap): a documented threshold with a clear rationale + tuning date.
# A reviewer must NOT flag this as a magic number - it is correctly documented.
LARGE_ORDER_MULTIPLE = 5.0  # >=5x trader median = outsized (calibrated 2026-06-18)


def get_alerts(db, trader_name):
    # SEC-2 (planted, critical): SQL injection - trader_name interpolated into the query.
    cur = db.cursor()
    cur.execute("SELECT * FROM alerts WHERE trader = '" + trader_name + "'")
    return cur.fetchall()


def dedupe_alerts(alerts):
    # PERF-1 (planted, medium): O(n^2) membership scan over a list; should use a set.
    unique = []
    for a in alerts:
        if a not in unique:
            unique.append(a)
    return unique


def open_db(path):
    # BUG-1 (planted, warning): connection opened but never closed (resource leak).
    conn = sqlite3.connect(path)
    return conn.cursor()


def score(order_qty, median):
    # Correct use of the documented threshold - must NOT be flagged.
    return order_qty >= LARGE_ORDER_MULTIPLE * median
