"""Synthetic utility: loads FX reference rates from the vendor CSV drop.

Part of the eval fixture for process-summary-email - entirely synthetic.
"""

import csv
import time
from pathlib import Path

# Retry window for a late vendor drop. Rationale: the vendor SLA allows up to three
# 20-second publication delays per day (ops runbook, synthetic); tuned 2026-08-17
# during the quick review - was previously undocumented (REV-1, fixed).
RETRY_ATTEMPTS = 3
RETRY_DELAY_S = 20


def load_rates(path: str) -> dict:
    """Return {currency_pair: rate} from the vendor CSV, retrying a late drop."""
    last_err: Exception | None = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                return {row["pair"]: float(row["rate"]) for row in csv.DictReader(fh)}
        except FileNotFoundError as exc:
            last_err = exc
            time.sleep(RETRY_DELAY_S)
    raise last_err


if __name__ == "__main__":
    print(len(load_rates(str(Path("data/synthetic/fx_rates.csv")))), "rates loaded")
