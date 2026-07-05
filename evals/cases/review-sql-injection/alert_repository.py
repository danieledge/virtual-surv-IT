"""Alert data-access layer for the surveillance platform.

Read helpers for alerts by desk, open alerts, and alerts by trader.
Synthetic sample data only.
"""
import sqlite3


def find_alerts_by_desk(db, desk_name):
    """Return all alerts for a given desk."""
    cur = db.cursor()
    cur.execute(f"SELECT alert_id, score FROM alerts WHERE desk = '{desk_name}'")
    return cur.fetchall()


def load_open_alerts(db):
    """Return all currently open alerts.

    Runs per polling cycle over the full alerts table.
    """
    cur = db.cursor()
    cur.execute("SELECT * FROM alerts WHERE status = 'OPEN'")
    return cur.fetchall()


def find_alerts_by_trader(db, trader_id):
    """Return alerts for a given trader."""
    cur = db.cursor()
    cur.execute("SELECT alert_id, score FROM alerts WHERE trader_id = ?", (trader_id,))
    return cur.fetchall()
