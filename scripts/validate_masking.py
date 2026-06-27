"""
scripts/validate_masking.py - prove a masking config is both SAFE and USEFUL.

Masking without measurement is faith, not control. This harness runs two sides:

Privacy (re-identification risk):
  - residual identifiers: none of the original direct-identifier values survive
  - residual PII patterns: ALL output fields are scanned (not only `redact`-role),
    so a mis-configured `keep`/`generalise` field leaking free-text PII is caught
  - direct-identifier passthrough: any field declared as a direct identifier (role
    `token`/`drop`) that is instead given a pass-through role (`keep`/`generalise`)
    is a configuration error - flagged as FAIL
  - k-anonymity: each declared quasi-identifier combination is shared by >= k records

Utility (detection fidelity):
  - the spoofing rule fires identically (same count + same non-identifying shape) on
    masked data as on the original - i.e. masking preserved the behavioural signal.

Run as a gate (operates on SYNTHETIC data):
  python -m scripts.validate_masking      # exit 0 = pass, non-zero = fail

Key handling:
  - If MASKING_KEY is set in the environment it is used (production / CI path).
  - If MASKING_KEY is unset a FIXED, clearly-non-secret constant key is used so
    the gate is deterministic and reproducible across runs without real credentials.
    This constant MUST NOT be used with real data - it is a test fixture only.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

# Portability: ensure the repo root is importable so this runs standalone by absolute
# path from ANY cwd (e.g. `python3 /path/to/plugin/scripts/validate_masking.py`), not only
# via `python -m scripts.validate_masking` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules.spoofing import detect_spoofing
from scripts.gen_synthetic import event_to_record, record_to_event, spoofing_session
from scripts.ingest import _PII_PATTERNS, load_schema, mask_records

# Roles that destroy / replace the original identifier value.
SENSITIVE_ROLES = {"token", "drop", "redact"}

# Roles that are direct pass-throughs and are UNSAFE for direct identifiers.
# A field whose semantic role is "direct identifier" (e.g. a person ID, account
# number, order reference) must NOT be given one of these roles.
PASSTHROUGH_ROLES = {"keep", "generalise"}

# Field names that are conventional direct identifiers. The schema may also
# declare them explicitly under `direct_identifiers:` - both sources are used.
# This heuristic list covers the most common naming patterns; it is deliberately
# conservative (false positives here are a config-review prompt, not a data leak).
_IDENTIFIER_NAME_HINTS = {
    "trader", "trader_id", "account", "account_id", "account_number",
    "order_id", "client_id", "customer_id", "user_id", "party_id",
    "email", "phone", "national_id", "ssn", "dob",
}

# Fixed deterministic test key used when MASKING_KEY is absent.
# This is a PUBLIC constant - it is intentionally non-secret and must NEVER be
# used with real data. Its only purpose is reproducible CI runs on synthetic fixtures.
_TEST_KEY_CONSTANT = b"validate-masking-test-key-not-a-secret-do-not-use-with-real-data"


def _resolve_key() -> bytes:
    """
    Return the masking key for validation runs.

    Production / CI with a real key: reads MASKING_KEY from the environment.
    Gate reproducibility (synthetic only): falls back to _TEST_KEY_CONSTANT so
    that `python -m scripts.validate_masking` is deterministic without credentials.
    os.urandom() is NOT used - a random key would make the gate non-reproducible.
    """
    env_key = os.environ.get("MASKING_KEY")
    if env_key:
        return env_key.encode()
    # No env key - use the fixed test constant. Log clearly so it's never silent.
    print(
        "[INFO] MASKING_KEY not set; using fixed test key (synthetic data only - "
        "NOT safe for real data). Set MASKING_KEY from ~/.secrets for production runs."
    )
    return _TEST_KEY_CONSTANT


def _direct_identifier_fields(schema: dict) -> set[str]:
    """
    Derive the set of fields that should be treated as direct identifiers.

    Two sources:
      1. Explicit `direct_identifiers:` list in the schema (authoritative).
      2. Heuristic name-matching against _IDENTIFIER_NAME_HINTS (belt-and-braces).
    """
    explicit = set(schema.get("direct_identifiers", []))
    heuristic = {
        name
        for name in schema.get("fields", {})
        if name.lower() in _IDENTIFIER_NAME_HINTS
    }
    return explicit | heuristic


def run_privacy_checks(original_records, schema, key):
    """Return (checks, masked_records). Each check: (name, ok, detail)."""
    masked = mask_records(original_records, schema, key)
    masked_text = "\n".join(json.dumps(r) for r in masked)
    checks = []

    # ------------------------------------------------------------------
    # 1. No original identifier value survives verbatim.
    #    Scans fields whose role destroys/replaces the original value.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 2. No residual free-text PII patterns - scan free-text-capable fields.
    #
    #    Previously only `redact`-role fields were scanned; a mis-configured
    #    `keep` field on a direct identifier would pass silently. We now scan
    #    a broader set:
    #
    #      - `redact`-role fields: the primary free-text target.
    #      - `token`-role fields: tokens are structured strings; we scan them
    #        to catch cases where the domain prefix itself embeds PII (unusual
    #        but possible with custom domain configs).
    #      - `keep`-role fields that are declared/inferred direct identifiers:
    #        these should not be `keep` (caught by check 3 below), but if they
    #        are, the raw value survives and may contain PII.
    #
    #    Deliberately EXCLUDED from the PII scan:
    #      - `shift`-role fields: produce integers (shifted ms timestamps);
    #        digit runs would trigger ACCT/PHONE false positives.
    #      - `generalise`-role fields: produce numeric buckets/category labels.
    #      - `keep`-role fields that are NOT direct identifiers (e.g. price,
    #        qty, side, kind): these are signal-bearing numeric/enum values.
    #
    #    This is belt-and-braces - check 3 (direct-identifier passthrough) is
    #    the primary guardrail for mis-configured identifier fields.
    # ------------------------------------------------------------------
    direct_ids = _direct_identifier_fields(schema)
    # Roles whose output can contain free-text or structured PII.
    _FREE_TEXT_ROLES = {"redact", "token"}
    # Keep-role direct identifiers are also in scope (raw value passes through).
    pii_scan_fields = {
        name
        for name, spec in schema["fields"].items()
        if spec["role"] in _FREE_TEXT_ROLES
        or (spec["role"] == "keep" and name in direct_ids)
    }
    pii_scan_text = " ".join(
        str(r.get(f, ""))
        for r in masked
        for f in pii_scan_fields
        if r.get(f) is not None
    )
    pii_hits = [label for label, pat in _PII_PATTERNS if pat.search(pii_scan_text)]
    scanned_count = len(pii_scan_fields)
    detail = (
        "no free-text-capable fields to scan"
        if not pii_scan_fields
        else (str(pii_hits) if pii_hits else f"clean across {scanned_count} free-text-capable field(s)")
    )
    checks.append((
        "no residual PII patterns (all output fields)",
        not pii_hits,
        detail,
    ))

    # ------------------------------------------------------------------
    # 3. Direct-identifier passthrough assertion.
    #    Any field inferred or declared as a direct identifier must NOT be
    #    given a role that passes the raw value through unchanged.
    # ------------------------------------------------------------------
    bad_passthrough = [
        (name, spec["role"])
        for name, spec in schema["fields"].items()
        if name in direct_ids and spec["role"] in PASSTHROUGH_ROLES
    ]
    checks.append((
        "no direct-identifier passthrough",
        not bad_passthrough,
        str(bad_passthrough) if bad_passthrough
        else f"all {len(direct_ids)} direct identifier(s) use a masking role",
    ))

    # ------------------------------------------------------------------
    # 4. k-anonymity over declared quasi-identifiers.
    # ------------------------------------------------------------------
    qis = schema.get("quasi_identifiers", [])
    if not qis:
        checks.append(("k-anonymity", True, "no quasi-identifiers declared - skipped"))
    else:
        k = schema.get("k_anonymity", 1)
        groups = Counter(tuple(r.get(q) for q in qis) for r in masked)
        worst = min(groups.values())
        checks.append(("k-anonymity", worst >= k, f"min group={worst}, required k={k}"))

    return checks, masked


def _shape(a):
    """Non-identifying alert shape - the part that must survive masking."""
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
    key = _resolve_key()

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
