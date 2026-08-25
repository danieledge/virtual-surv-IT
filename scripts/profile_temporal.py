#!/usr/bin/env python3
"""Temporal profile of a dataset - time as a dimension, in pure stdlib.

WHY THIS EXISTS. Handed a pile of alert extracts, the team had no method for interrogating
them across time: `data-analyst` owns exploratory analysis and `data-quality-reviewer` owns
timeliness, but both as a *dimension they own*, never as a procedure. The review lenses are
code-only. So "are there gaps, is it stable, does the shape change" was left to whatever an
agent thought to try in the moment (2026-08-24 owner request).

The approach is lifted from the owner's own DataK9 profiler (MIT) - range, gaps, freshness,
future dates, cadence, distribution, and outliers judged against a peer subgroup rather than
globally. The CODE is not: DataK9 runs on pandas/polars/numpy/pyarrow, none of which can be
vendored here, so this is a stdlib reimplementation and the plugin carries no dependency.

WHAT MAKES IT SAFE TO POINT AT CLIENT DATA. It emits AGGREGATES ONLY - counts, dates,
intervals, per-period volumes. No row, field value or identifier is ever printed. That is the
point: an agent can characterise a dataset it must never read (CLAUDE.md §5 - anything an
agent reads goes to the model provider), because the statistics come back instead of the
records. Treat any future change that prints a cell as a safety regression, not a feature.

WHAT IT DELIBERATELY DOES NOT DO. It does not judge. A weekend gap and a broken feed look
identical here; a distribution shift may be a threshold change rather than a behaviour change
(docs/sme/tm-monitoring.md's data-drift vs behaviour-drift distinction). This tool measures;
the lens and the analyst interpret. Findings that skip that step are how a profiler becomes a
false-positive generator.

Usage:
    python -m scripts.profile_temporal DATA.csv [--date-column NAME] [--by COLUMN]
                                        [--as-of YYYY-MM-DD] [--calendar business|all]
                                        [--json]

The date column is auto-detected when not named. `--by` adds per-subgroup volumes, which is
the context-aware half: a volume that is ordinary for one venue or rule is glaring for another.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

# Formats tried in order, widest-first. Deliberately explicit rather than a fuzzy parser: a
# profile that silently misreads 03/04 as April 3rd in one row and March 4th in another is
# worse than one that says it could not parse the column.
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%b-%Y",
    "%Y%m%d",
)

_MAX_ROWS = 2_000_000  # a runaway file must not hang a session; reported when it bites


def parse_when(text: str):
    """A datetime, or None. Tries each known format; never guesses beyond them."""
    raw = (text or "").strip()
    if not raw:
        return None
    cleaned = raw.replace("Z", "").split(".")[0].split("+")[0].strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def detect_date_column(rows: list[dict], headers: list[str]) -> str | None:
    """The column that parses as a date most often - sampled, not exhaustive. Ties break on
    header order so two runs on the same file agree."""
    sample = rows[:200]
    best, best_hits = None, 0
    for name in headers:
        hits = sum(1 for row in sample if parse_when(row.get(name, "")))
        if hits > best_hits:
            best, best_hits = name, hits
    # A column that parses less than half the time is not a date column; saying so beats
    # profiling the wrong field confidently.
    return best if best_hits >= max(1, len(sample) // 2) else None


def infer_cadence(days: list[date]) -> tuple[str, float | None]:
    """(label, median interval in days) from the distinct dates present."""
    unique = sorted(set(days))
    if len(unique) < 2:
        return "single date" if unique else "no dates", None
    gaps = [(b - a).days for a, b in zip(unique, unique[1:])]
    median = statistics.median(gaps)
    spread = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    label = {1: "daily", 7: "weekly"}.get(int(median))
    if label is None:
        if 28 <= median <= 31:
            label = "monthly"
        elif 89 <= median <= 92:
            label = "quarterly"
        elif 2 <= median <= 6:
            label = "several times a week"
        else:
            label = f"every ~{median:g} days"
    # Regularity is about CONSISTENCY of the interval, not its size.
    steadiness = "regular" if spread <= max(1.0, median * 0.25) else "irregular"
    return f"{label} ({steadiness})", median


def find_gaps(days: list[date], median: float | None, calendar: str) -> list[dict]:
    """Runs of missing days, judged against the observed cadence.

    `calendar=business` skips Saturday and Sunday, because a naive gap check flags every
    weekend and would bury a real break in noise. It does NOT know exchange holidays or
    half-days - no calendar is vendored here - so a business-day gap of 1-2 days around a
    public holiday is expected and the caller is told to check, not told it is broken."""
    unique = sorted(set(days))
    if len(unique) < 2 or not median:
        return []
    threshold = max(2.0, median * 2)
    gaps = []
    for earlier, later in zip(unique, unique[1:]):
        span = (later - earlier).days
        if span <= threshold:
            continue
        missing = span - 1
        if calendar == "business":
            missing = sum(
                1
                for offset in range(1, span)
                if (earlier + timedelta(days=offset)).weekday() < 5
            )
            if missing == 0:
                continue  # a weekend, not a gap
        gaps.append(
            {"after": earlier.isoformat(), "before": later.isoformat(), "missing_days": missing}
        )
    return sorted(gaps, key=lambda g: -g["missing_days"])


def build_profile(path: Path, args) -> dict:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows, truncated = [], False
        for i, row in enumerate(reader):
            if i >= _MAX_ROWS:
                truncated = True
                break
            rows.append(row)

    column = args.date_column or detect_date_column(rows, headers)
    profile: dict = {
        "file": path.name,
        "rows": len(rows),
        "truncated_at": _MAX_ROWS if truncated else None,
        "date_column": column,
        "calendar": args.calendar,
    }
    if not column:
        profile["error"] = (
            "no date column found - name one with --date-column, or the dates are in a "
            "format this tool does not parse (it never guesses ambiguous ones)"
        )
        return profile

    parsed = [parse_when(row.get(column, "")) for row in rows]
    stamps = [p for p in parsed if p]
    profile["unparsed_rows"] = len(parsed) - len(stamps)
    if not stamps:
        profile["error"] = f"no parseable dates in {column!r}"
        return profile

    days = [s.date() for s in stamps]
    as_of = (
        datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else date.today()
    )
    # Freshness and gaps are measured on dates up to the as-of ONLY. A single future-dated
    # row (a timezone slip, a typo) otherwise becomes the "latest" date, turning freshness
    # negative and inventing a months-long gap that ends at a row nobody has yet lived
    # through - which is exactly what the first fixture run produced.
    future = [d for d in days if d > as_of]
    days = [d for d in days if d <= as_of] or days
    cadence, median = infer_cadence(days)
    counts = Counter(days)
    busiest = max(counts.items(), key=lambda kv: kv[1])
    profile.update(
        {
            "as_of": as_of.isoformat(),
            "earliest": min(days).isoformat(),
            "latest": max(days).isoformat(),
            "span_days": (max(days) - min(days)).days,
            "distinct_days": len(counts),
            "cadence": cadence,
            "median_interval_days": median,
            "days_since_latest": (as_of - max(days)).days,
            "future_dated_rows": len(future),
            "latest_excludes_future": bool(future),
            "busiest_day": {"date": busiest[0].isoformat(), "rows": busiest[1]},
            "median_rows_per_active_day": statistics.median(counts.values()),
            "gaps": find_gaps(days, median, args.calendar),
        }
    )

    # Per-period volumes: the shape over time, which is what a reader actually looks at.
    by_month = Counter(d.strftime("%Y-%m") for d in days)
    profile["rows_by_month"] = dict(sorted(by_month.items()))

    if args.by and args.by in headers:
        # The context-aware half - a volume ordinary for one venue or rule is glaring for
        # another, and a global outlier check on alert data is mostly noise. Names of
        # subgroups ARE values from the data, so this is opt-in and capped.
        per_group = Counter(
            (row.get(args.by) or "(blank)") for row, p in zip(rows, parsed) if p
        )
        profile["by_column"] = args.by
        profile["rows_by_group"] = dict(per_group.most_common(20))
        profile["distinct_groups"] = len(per_group)
    return profile


def render(profile: dict) -> str:
    out = [f"# Temporal profile - {profile['file']}", ""]
    if profile.get("error"):
        out += [f"UNPROFILED: {profile['error']}", ""]
        return "\n".join(out)
    out += [
        f"rows                  {profile['rows']:,}"
        + (f"  (truncated at {profile['truncated_at']:,})" if profile["truncated_at"] else ""),
        f"date column           {profile['date_column']}",
        f"unparsed rows         {profile['unparsed_rows']:,}",
        f"as-of                 {profile['as_of']}   (calendar: {profile['calendar']})",
        "",
        f"range                 {profile['earliest']} -> {profile['latest']}"
        f"  ({profile['span_days']:,} days)",
        f"active days           {profile['distinct_days']:,}",
        f"cadence               {profile['cadence']}",
        f"days since latest     {profile['days_since_latest']:,}",
        f"future-dated rows     {profile['future_dated_rows']:,}"
        + ("   (excluded from range/gaps above)" if profile.get("latest_excludes_future") else ""),
        f"busiest day           {profile['busiest_day']['date']}"
        f"  ({profile['busiest_day']['rows']:,} rows)",
        f"median rows/day       {profile['median_rows_per_active_day']:g}",
        "",
    ]
    gaps = profile["gaps"]
    out.append(f"## Gaps ({len(gaps)})")
    if not gaps:
        out.append("  none beyond the observed cadence")
    for gap in gaps[:10]:
        out.append(
            f"  {gap['missing_days']:>4} day(s) missing between {gap['after']} and {gap['before']}"
        )
    if len(gaps) > 10:
        out.append(f"  ... {len(gaps) - 10} more")
    out += ["", "## Rows by month"]
    for month, count in profile["rows_by_month"].items():
        out.append(f"  {month}  {count:,}")
    if profile.get("rows_by_group"):
        out += ["", f"## Rows by {profile['by_column']} (top {len(profile['rows_by_group'])}"
                f" of {profile['distinct_groups']})"]
        for name, count in profile["rows_by_group"].items():
            out.append(f"  {name}  {count:,}")
    out += [
        "",
        "> 📊 measured. This tool does NOT judge: a weekend or holiday gap and a broken feed",
        "> look identical here, and a change in shape may be a threshold or rule change rather",
        "> than a behaviour change. Interpret with the temporal lens before reporting.",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Temporal profile of a CSV - aggregates only.")
    ap.add_argument("path", help="CSV file (convert_file turns Excel/PDF into one)")
    ap.add_argument("--date-column", help="date/time column; auto-detected when omitted")
    ap.add_argument("--by", help="also break volumes down by this column")
    ap.add_argument("--as-of", help="reference date for freshness (default: today)")
    ap.add_argument(
        "--calendar",
        choices=("business", "all"),
        default="business",
        help="business skips weekends when measuring gaps (default)",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    try:
        profile = build_profile(path, args)
    except (OSError, csv.Error, ValueError) as exc:
        print(f"could not profile {path.name}: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    print(json.dumps(profile, indent=2) if args.json else render(profile))
    return 1 if profile.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
