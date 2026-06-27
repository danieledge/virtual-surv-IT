"""Synthetic eval input - a deliberately flawed alert data-access layer.

NOT production code. Seeded with known issues for the team-quality eval harness
(evals/). All data is synthetic. See expected.yaml for the planted ground truth.
"""
import sqlite3


def find_alerts_by_desk(db, desk_name):
    """SEC-1 (planted, critical): SQL injection.

    desk_name is interpolated straight into the query via an f-string, so a
    value like ``x' OR '1'='1`` returns every row. Must be parameterized.
    """
    cur = db.cursor()
    cur.execute(f"SELECT alert_id, score FROM alerts WHERE desk = '{desk_name}'")
    return cur.fetchall()


def load_open_alerts(db):
    """PERF-1 (planted, medium): SELECT * in a hot path.

    This runs per polling cycle over the full alerts table and pulls every
    column (including large free-text rationale blobs) when only three are
    used downstream. Should project just the needed columns.
    """
    cur = db.cursor()
    cur.execute("SELECT * FROM alerts WHERE status = 'OPEN'")
    return cur.fetchall()


def find_alerts_by_trader(db, trader_id):
    """OK (forbidden / FP-trap): correct parameterized query.

    trader_id is bound as a parameter, not interpolated. A reviewer must NOT
    flag this as SQL injection - it is the safe pattern.
    """
    cur = db.cursor()
    cur.execute("SELECT alert_id, score FROM alerts WHERE trader_id = ?", (trader_id,))
    return cur.fetchall()
