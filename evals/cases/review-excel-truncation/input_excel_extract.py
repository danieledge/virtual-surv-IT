"""Synthetic eval input - a deliberately flawed Excel-extraction utility.

NOT production code. Seeded with known issues for the team-quality eval harness
(evals/). All data is synthetic; openpyxl is reviewed statically, not installed.
See expected.yaml for the planted ground truth.
"""

import csv

from openpyxl import load_workbook

# OK (forbidden / FP-trap): a documented, correct column bound derived from the attested
# source schema - a reviewer must NOT flag this as truncation or a magic number.
EXPECTED_COLUMNS = 9  # order-extract schema v2.1 (attested 2026-06); header validated below


def extract_orders(xlsx_path, csv_path):
    # RECON-1 (planted, critical): no source-vs-output reconciliation anywhere in this
    # module - nothing compares rows written against the workbook's row count or a control
    # total, so every truncation below is invisible to downstream analysis.
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    header_cells = next(ws.iter_rows(min_row=1, max_row=1, max_col=EXPECTED_COLUMNS))
    header = [c.value for c in header_cells]
    rows_out = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        # TRUNC-1 (planted, critical): hardcoded row cap - anything past row 1000 is
        # silently dropped from the extract, and nothing reports it.
        for row in ws.iter_rows(min_row=2, max_row=1000, max_col=EXPECTED_COLUMNS):
            try:
                writer.writerow([normalise(c.value) for c in row])
                rows_out += 1
            # TRUNC-2 (planted, critical): except-and-continue swallows failing rows -
            # records vanish with no count, log or error.
            except Exception:
                continue
    return rows_out


def normalise(value):
    if value is None:
        return ""
    # TRUNC-3 (planted, warning): silent value truncation - long free-text fields lose
    # everything past 32 characters.
    return str(value)[:32]
