"""
scripts/validate_masking.py — prove a masking config is both SAFE and USEFUL.

Masking without measurement is faith, not control. This harness runs two sides:

Privacy (re-identification risk):
  - residual identifiers: none of the original direct-identifier values survive
  - residual PII patterns: no emails / phones / long account numbers in the output
  - k-anonymity: each declared quasi-identifier combination is shared by >= k records

Utility (detection fidelity):
  - the spoofing rule fires identically (same count + same non-identifying shape) on
    masked data as on the original — i.e. masking preserved the behavioural signal.

Run as a gate (operates on SYNTHETIC data, so no real key/data needed):
  python -m scripts.validate_masking      # exit 0 = pass, non-zero = fail
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from rules.spoofing import detect_spoofing
from scripts.gen_synthetic import event_to_record, record_to_event, spoofing_session
from scripts.ingest import _PII_PATTERNS, load_schema, mask_records

SENSITIVE_ROLES = {"token", "drop", "redact"}


def run_privacy_checks(original_records, schema, key):
    """Return (checks, masked_records). Each check: (name, ok, detail)."""
    masked = mask_records(original_records, schema, key)
    masked_text = "\n".join(json.dumps(r) for r in masked)
    checks = []

    # 1. No original identifier value survives verbatim.
    sensitive = [f for f, s in schema["fields"].items() if s["role"] in SENSITIVE_ROLES]
    leaked = sorted(
        {
            (f, str(rec[f]))
            for rec in original_records
            for f in sensitive
            if rec.get(f) is not None and str(rec[f]) and str(rec[f]) in masked_text
        }
    )
    checks.append(("no residual identifiers", not leaked, str(leaked[:5]) if leaked else "none survive"))

    # 2. No residual free-text PII patterns — scan only `redact`-role (free-text) fields;
    #    signal numerics (kept timestamps/prices/qty) legitimately contain digit runs.
    redact_fields = [f for f, s in schema["fields"].items() if s["role"] == "redact"]
    pii_text = " ".join(str(r.get(f, "")) for r in masked for f in redact_fields)
    hits = [label for label, pat in _PII_PATTERNS if pat.search(pii_text)]
    detail = (
        "no free-text fields to scan"
        if not redact_fields
        else (str(hits) if hits else f"clean across {len(redact_fields)} free-text field(s)")
    )
    checks.append(("no residual PII patterns", not hits, detail))

    # 3. k-anonymity over declared quasi-identifiers.
    qis = schema.get("quasi_identifiers", [])
    if not qis:
        checks.append(("k-anonymity", True, "no quasi-identifiers declared — skipped"))
    else:
        k = schema.get("k_anonymity", 1)
        groups = Counter(tuple(r.get(q) for q in qis) for r in masked)
        worst = min(groups.values())
        checks.append(("k-anonymity", worst >= k, f"min group={worst}, required k={k}"))

    return checks, masked


def _shape(a):
    """Non-identifying alert shape — the part that must survive masking."""
    return (
        a.spoof_side,
        a.spoof_qty,
        a.spoof_lifetime_ms,
        a.spoof_fill_ratio,
        a.benefiting_side,
        a.benefiting_qty,
        a.time_gap_ms,
    )


def detection_fidelity(original_events, schema, key):
    """Same alerts on masked data as on the original? Returns (ok, n_real, n_masked)."""
    real = detect_spoofing(original_events)
    masked_events = [
        record_to_event(r)
        for r in mask_records([event_to_record(e) for e in original_events], schema, key)
    ]
    masked = detect_spoofing(masked_events)
    ok = len(real) == len(masked) and sorted(map(_shape, real)) == sorted(map(_shape, masked))
    return ok, len(real), len(masked)


def main() -> None:
    schema = load_schema(Path("config/masking-schema.yaml"))
    # Operates on synthetic data: use MASKING_KEY if present, else an ephemeral key.
    env_key = os.environ.get("MASKING_KEY")
    key = env_key.encode() if env_key else os.urandom(32)

    events = spoofing_session(seed=1)
    checks, _ = run_privacy_checks([event_to_record(e) for e in events], schema, key)
    ok_fid, n_real, n_masked = detection_fidelity(events, schema, key)
    checks.append(
        ("detection fidelity (spoofing)", ok_fid, f"alerts real={n_real} masked={n_masked}")
    )

    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    passed = all(ok for _, ok, _ in checks)
    print("RESULT:", "PASS" if passed else "FAIL")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
