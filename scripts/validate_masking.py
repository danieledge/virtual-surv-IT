"""
scripts/validate_masking.py - prove a masking config is both SAFE and USEFUL.

Masking without measurement is faith, not control. This harness runs two sides:

Privacy (re-identification risk):
  - residual identifiers: none of the original direct-identifier values survive
  - residual PII patterns: scanned across the FREE-TEXT-CAPABLE output fields (`redact`/
    `token` roles + any `keep`-role direct identifier). Numeric fields (`shift` timestamps,
    `keep` prices/qty, `generalise` buckets) are excluded to avoid digit-run false positives;
    the direct-identifier-passthrough check is the backstop for mis-roled identifier fields.
  - identifier-SHAPED values: covers exactly the gap the exclusion above opens. Every value
    in the output, numeric fields included, is matched against anchored identifier FORMATS
    (IBAN, long account/card digit runs, email, phone) so a mis-roled field is caught on the
    shape of what it holds even when its name gives nothing away.
  - direct-identifier passthrough: any field declared as a direct identifier (role
    `token`/`drop`) that is instead given a pass-through role (`keep`/`generalise`)
    is a configuration error - flagged as FAIL
  - k-anonymity: each declared quasi-identifier combination is shared by >= k records
    (only runs if the schema declares `quasi_identifiers`; skipped otherwise)

Utility (detection fidelity):
  - the spoofing rule fires identically (same count + same non-identifying shape) on
    masked data as on the original - i.e. masking preserved the behavioural signal.

Two modes:
  python -m scripts.validate_masking                       # CONFIG self-test on a synthetic
      fixture: proves the schema + masking logic are sound (privacy checks + detection fidelity).
      This does NOT inspect any user data - it is a regression/config gate.
  python -m scripts.validate_masking --in data/masked/x.jsonl   # inspect YOUR actual masked
      file: scans its string fields for residual free-text PII and runs k-anonymity over it.
      (Cannot check 'no original identifier survived' or detection fidelity without the originals.)
  exit 0 = pass, non-zero = fail.

Key handling:
  - If MASKING_KEY is set in the environment it is used (production / CI path).
  - If MASKING_KEY is unset a FIXED, clearly-non-secret constant key is used so
    the gate is deterministic and reproducible across runs without real credentials.
    This constant MUST NOT be used with real data - it is a test fixture only.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# Portability: ensure the repo root is importable so this runs standalone by absolute
# path from ANY cwd (e.g. `python3 /path/to/plugin/scripts/validate_masking.py`), not only
# via `python -m scripts.validate_masking` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules.spoofing import detect_spoofing
from scripts.gen_synthetic import event_to_record, record_to_event, spoofing_session
from scripts.ingest import _PII_PATTERNS, TOKEN_LEN, load_schema, mask_records

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
    "trader",
    "trader_id",
    "account",
    "account_id",
    "account_number",
    "order_id",
    "client_id",
    "customer_id",
    "user_id",
    "party_id",
    "email",
    "phone",
    "national_id",
    "ssn",
    "dob",
}

# ---------------------------------------------------------------------------
# Identifier SHAPE heuristics - the companion to _IDENTIFIER_NAME_HINTS above.
#
# Names only catch the fields someone remembered to name conventionally. A column
# called `ref7` or `cust_val` holding an IBAN is invisible to a name list, and the
# free-text PII scan deliberately skips numeric `keep` fields so that shifted
# timestamps and prices do not trip the digit-run patterns. That exclusion is the
# gap these checks close: they look at the VALUE's format, not the field's name.
#
# Conservatism is the whole design constraint - a false positive here sends a human
# to re-review a clean config, so every pattern is anchored (fullmatch on the whole
# value, never a substring), length-bounded, and guarded against the numerics that
# legitimately live in surveillance data:
#   - floats are never checked at all: prices, rates and quantities are floats, and
#     no identifier format is a float.
#   - epoch-shaped integers are excluded by width + leading digit (see below).
#   - ISO dates/datetimes are excluded explicitly.
#   - digit runs shorter than _ACCOUNT_MIN_DIGITS are ignored, so quantities, small
#     ints, years and reference numbers do not fire.
# ---------------------------------------------------------------------------

# A value must carry at least this many digits before a bare digit run is treated as an
# account/card number. 12 sits above realistic quantities and below the 13-19 of a payment
# card, and above the 10 digits of an epoch-second timestamp.
_ACCOUNT_MIN_DIGITS = 12
_ACCOUNT_MAX_DIGITS = 19
# Phone numbers: E.164 tops out at 15 digits; below 9 the run is too short to tell apart
# from an ordinary reference number.
_PHONE_MIN_DIGITS = 9
_PHONE_MAX_DIGITS = 15
# Digit widths at which an integer is a plausible epoch timestamp (seconds, millis,
# micros, nanos). Combined with a leading "1" this covers roughly 2001-2033 in every
# unit, which is the whole range surveillance data realistically holds. Payment cards
# in issue start 3/4/5/6, so excluding leading-1 runs at these widths costs almost
# nothing and removes the single largest source of false positives.
_EPOCH_DIGIT_WIDTHS = {10, 13, 16, 19}

_EMAIL_VALUE_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# ISO 13616: 2-letter country + 2 check digits + 11-30 alphanumeric BBAN chars.
_IBAN_VALUE_RE = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")
# Phone shape, checked only when the value carries a "+" or a separator - a bare digit
# run is handled by the account/card rule instead, so the two cannot both fire.
_PHONE_VALUE_RE = re.compile(r"\+?\d[\d\s\-().]{5,20}\d")
# Dates are not identifiers. Matches YYYY-MM-DD and the ISO 8601 datetimes built on it.
_ISO_DATE_VALUE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)
# Separator characters stripped before a format is matched, because printed IBANs, cards
# and phone numbers are all conventionally grouped.
_SEPARATORS_RE = re.compile(r"[\s\-()]")

# Masking artifacts ingest itself produces: the `[EMAIL_<24 hex>]` redaction surrogate and
# the `party_<24 hex>` structured token. Both are TOKEN_LEN wide, and at 24 hex chars a token
# carries a 9+ digit run often enough to matter - roughly one masked file in a handful - which
# the PHONE and ACCT patterns then report as residual PII. That is the masker's own output
# being flagged as the PII it just removed, and it is not a hypothetical: the first end-to-end
# run of the shipped schema through the post-mask scan failed on exactly this.
#
# So the artifacts are removed before the pattern scan. Deliberately narrow - an underscore
# followed by EXACTLY TOKEN_LEN lowercase hex characters, nothing else - so a genuine leak
# sitting next to a token still survives the strip and is still reported.
_MASKING_ARTIFACT_RES = (
    re.compile(rf"\[[A-Z][A-Z_]*_[0-9a-f]{{{TOKEN_LEN}}}\]"),  # redaction surrogate
    re.compile(rf"\b[A-Za-z][A-Za-z0-9]*_[0-9a-f]{{{TOKEN_LEN}}}\b"),  # structured token
)

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
        name for name in schema.get("fields", {}) if name.lower() in _IDENTIFIER_NAME_HINTS
    }
    return explicit | heuristic


def _strip_masking_artifacts(text: str) -> str:
    """Remove ingest's own surrogates and tokens before a PII pattern scan."""
    for pat in _MASKING_ARTIFACT_RES:
        text = pat.sub(" ", text)
    return text


def _looks_like_epoch(digits: str) -> bool:
    """True if a bare digit run is a plausible epoch timestamp rather than an identifier."""
    return len(digits) in _EPOCH_DIGIT_WIDTHS and digits.startswith("1")


def _shaped_identifier_label(value) -> str | None:
    """
    Return an identifier-format label if `value` IS an identifier by shape, else None.

    Shape only - the field name plays no part, which is the point: this catches the
    mis-roled column whose name gave nothing away. See the heuristics block above for
    why each exclusion exists.
    """
    # bool is an int subclass in Python, and True/False are never identifiers.
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        # Prices, rates, quantities. No identifier format is a float.
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    if not text:
        return None
    if _ISO_DATE_VALUE_RE.fullmatch(text):
        return None

    if _EMAIL_VALUE_RE.fullmatch(text):
        return "EMAIL"

    compact = _SEPARATORS_RE.sub("", text)
    if _IBAN_VALUE_RE.fullmatch(compact):
        return "IBAN"

    plus = compact.startswith("+")
    digits = compact[1:] if plus else compact
    if not digits.isdigit():
        return None
    n = len(digits)
    # An explicit international prefix is a phone number and nothing else.
    if plus and _PHONE_MIN_DIGITS <= n <= _PHONE_MAX_DIGITS:
        return "PHONE"
    if _ACCOUNT_MIN_DIGITS <= n <= _ACCOUNT_MAX_DIGITS and not _looks_like_epoch(digits):
        return "ACCOUNT_OR_CARD"
    # Grouped (separated) runs that are too short to be an account number but long
    # enough to be a dialled number. A bare run never reaches here.
    if (
        text != compact
        and _PHONE_MIN_DIGITS <= n <= _PHONE_MAX_DIGITS
        and _PHONE_VALUE_RE.fullmatch(text)
    ):
        return "PHONE"
    return None


def _iter_shaped_labels(value):
    """Yield identifier-format labels found in `value`, recursing into dicts and lists."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _iter_shaped_labels(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _iter_shaped_labels(v)
    else:
        label = _shaped_identifier_label(value)
        if label is not None:
            yield label


def shaped_identifier_hits(records) -> list[tuple[str, str]]:
    """
    Return sorted (field_name, format_label) pairs for identifier-SHAPED values.

    Field names and format labels only - the offending VALUE is never returned or
    logged (§5). Knowing that `ref7` holds something IBAN-shaped is enough to act on;
    printing the IBAN would be the leak this tool exists to prevent.
    """
    hits: set[tuple[str, str]] = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for name, value in rec.items():
            for label in _iter_shaped_labels(value):
                hits.add((name, label))
    return sorted(hits)


def _shaped_identifier_check(records) -> tuple[str, bool, str]:
    """Build the standard (name, ok, detail) check tuple for the shape heuristic."""
    hits = shaped_identifier_hits(records)
    return (
        "no identifier-shaped values (format heuristic)",
        not hits,
        str(hits[:5]) if hits else f"clean across {len(records)} record(s)",
    )


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
    checks.append(
        ("no residual identifiers", not leaked, str(leaked[:5]) if leaked else "none survive")
    )

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
    # Any `keep`-role field whose masked value is a STRING is also free-text-capable and must be
    # scanned - not only declared identifiers. This closes the blind spot where a kept free-text
    # field (e.g. `notes`, `comment`) bypassed the scan while `scan_masked_file` (the --in mode)
    # caught it. Numeric `keep` fields (price/qty) are str-typed-excluded here, so digit-run
    # false positives are still avoided. Check 3 remains the primary guardrail for mis-roled IDs.
    keep_str_fields = {
        name
        for name, spec in schema["fields"].items()
        if spec["role"] == "keep" and any(isinstance(r.get(name), str) for r in masked)
    }
    pii_scan_fields = {
        name
        for name, spec in schema["fields"].items()
        if spec["role"] in _FREE_TEXT_ROLES or (spec["role"] == "keep" and name in direct_ids)
    } | keep_str_fields
    pii_scan_text = _strip_masking_artifacts(
        " ".join(
            str(r.get(f, "")) for r in masked for f in pii_scan_fields if isinstance(r.get(f), str)
        )
    )
    pii_hits = [label for label, pat in _PII_PATTERNS if pat.search(pii_scan_text)]
    scanned_count = len(pii_scan_fields)
    detail = (
        "no free-text-capable fields to scan"
        if not pii_scan_fields
        else (
            str(pii_hits)
            if pii_hits
            else f"clean across {scanned_count} free-text-capable field(s)"
        )
    )
    checks.append(
        (
            "no residual PII patterns (free-text-capable fields)",
            not pii_hits,
            detail,
        )
    )

    # ------------------------------------------------------------------
    # 2b. Identifier-SHAPED values, across EVERY field including the numeric ones
    #     check 2 excludes. Name-blind and role-blind on purpose: this is the only
    #     check that would catch a `keep`-role integer column quietly carrying card
    #     numbers. See the heuristics block at the top for the conservatism rules.
    # ------------------------------------------------------------------
    checks.append(_shaped_identifier_check(masked))

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
    checks.append(
        (
            "no direct-identifier passthrough",
            not bad_passthrough,
            str(bad_passthrough)
            if bad_passthrough
            else f"all {len(direct_ids)} direct identifier(s) use a masking role",
        )
    )

    # ------------------------------------------------------------------
    # 4. k-anonymity over declared quasi-identifiers.
    # ------------------------------------------------------------------
    qis = schema.get("quasi_identifiers", [])
    if not qis:
        checks.append(("k-anonymity", True, "no quasi-identifiers declared - skipped"))
    else:
        k = schema.get("k_anonymity", 1)
        groups = Counter(tuple(r.get(q) for q in qis) for r in masked)
        worst = min(groups.values()) if groups else 0
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


def _iter_strings(obj):
    """Yield every string value in obj, recursing into nested dicts and lists."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def scan_masked_records(
    records: list[dict], schema: dict, extra_checks: list | None = None
) -> list:
    """Run the data-independent checks over already-parsed masked records.

    Split out of scan_masked_file() so ingest can validate its own output in-process,
    with no temp file and no second parse - and, when it is writing to stdout, with no
    file to read back at all.
    """
    checks = list(extra_checks or [])

    # Residual free-text PII across all STRING values, including those nested inside list/dict
    # fields (a flat record is the norm, but nested values must not be a blind spot).
    text = _strip_masking_artifacts(" ".join(s for r in records for s in _iter_strings(r)))
    hits = [label for label, pat in _PII_PATTERNS if pat.search(text)]
    checks.append(
        (
            "no residual PII in masked file (string fields)",
            not hits,
            str(hits) if hits else f"clean across {len(records)} record(s)",
        )
    )

    # Identifier-shaped values across EVERY value, numerics included - the string-only
    # scan above cannot see a card number stored as an integer.
    checks.append(_shaped_identifier_check(records))

    # k-anonymity over declared quasi-identifiers (skipped if none declared).
    qis = schema.get("quasi_identifiers", [])
    if not qis:
        checks.append(
            ("k-anonymity", True, "no quasi-identifiers declared - skipped (declare to enforce)")
        )
    else:
        k = schema.get("k_anonymity", 1)
        groups = Counter(tuple(r.get(q) for q in qis) for r in records)
        worst = min(groups.values()) if groups else 0
        checks.append(("k-anonymity", worst >= k, f"min group={worst}, required k={k}"))

    return checks


def scan_masked_file(path: str | Path, schema: dict) -> list:
    """Inspect a user's ACTUAL masked file (not a fixture). Data-independent checks only.

    Scans every STRING field value for residual free-text PII (numbers are skipped so shifted
    timestamps / prices don't trigger digit-run false positives), applies the identifier-shape
    heuristic to every value including the numeric ones, and runs k-anonymity over any declared
    quasi-identifiers. It CANNOT verify 'no original identifier survived' or detection fidelity -
    those need the original data, which by design never reaches this tool.
    """
    records = []
    bad_lines = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Count malformed lines (by position only - never echo content) rather than
            # crashing the whole scan on one bad row.
            bad_lines += 1
    parse_checks = []
    if bad_lines:
        parse_checks.append(("file parse", False, f"{bad_lines} malformed JSON line(s) skipped"))

    return scan_masked_records(records, schema, extra_checks=parse_checks)


def main() -> None:
    # Force UTF-8 output so a cp1252 (Windows) console can't crash on non-ASCII (0.19.0).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    import argparse

    ap = argparse.ArgumentParser(
        description="Validate masking: config self-test, or scan a masked file."
    )
    ap.add_argument(
        "--in",
        dest="inp",
        type=Path,
        default=None,
        help="optional: scan YOUR masked .jsonl for residual PII + k-anonymity",
    )
    ap.add_argument("--schema", type=Path, default=Path("config/masking-schema.yaml"))
    args = ap.parse_args()

    schema = load_schema(args.schema)

    if args.inp is not None:
        # Inspect the user's actual masked output (data-independent checks).
        print(
            f"[INFO] Scanning masked file {args.inp} (residual PII + k-anonymity). "
            "Note: 'no original identifier survived' and detection fidelity need the originals "
            "and are NOT checked in this mode."
        )
        checks = scan_masked_file(args.inp, schema)
    else:
        # Config self-test on a synthetic fixture (regression/config gate; no user data).
        key = _resolve_key()
        events = spoofing_session(seed=1)
        checks, _ = run_privacy_checks([event_to_record(e) for e in events], schema, key)
        ok_fid, n_real, n_masked = detection_fidelity(events, schema, key)
        checks.append(
            ("detection fidelity (spoofing)", ok_fid, f"alerts real={n_real} masked={n_masked}")
        )
        print(
            "[INFO] Config self-test on a synthetic fixture (no user data inspected). "
            "Use --in <file> to scan your actual masked output."
        )

    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    passed = all(ok for _, ok, _ in checks)
    print("RESULT:", "PASS" if passed else "FAIL")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
