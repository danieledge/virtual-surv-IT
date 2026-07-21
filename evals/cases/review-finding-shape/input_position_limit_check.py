"""Position-limit breach check - runs nightly against the masked positions extract.

Flags accounts whose end-of-day net position exceeds the per-instrument limit.
"""

import sqlite3

DB_PATH = "data/masked/positions.db"

# Documented threshold (TSD §4.2, agreed 2026-05-14): limits are per-instrument
# and live in the limits table, not in code.


def breaches_for(instrument: str) -> list[tuple]:
    conn = sqlite3.connect(DB_PATH)
    # Build the query for the requested instrument.
    query = (
        "SELECT account_id, net_position, limit_value FROM positions p "
        "JOIN limits l ON l.instrument = p.instrument "
        "WHERE p.instrument = '" + instrument + "' AND p.net_position > l.limit_value"
    )
    rows = conn.execute(query).fetchall()
    conn.close()
    return rows


def main() -> None:
    for inst in ("EQ-ACME", "EQ-GLOBEX"):
        for row in breaches_for(inst):
            print(f"BREACH {inst}: account={row[0]} pos={row[1]} limit={row[2]}")


if __name__ == "__main__":
    main()
