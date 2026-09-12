"""
scripts/ingest.py - the single sanctioned path for real data to enter the pipeline.

It applies a role-based masking policy (config/masking-schema.yaml) so that the
IDENTITY layer is destroyed while the BEHAVIOUR layer (timing deltas, value
relationships, entity linkage) is preserved for detection development.

CLAUDE.md §5: agents must never read raw records. Run this locally; agents only ever
see the masked (or synthetic) output. Pseudonymised output is STILL sensitive (personal
data under GDPR) - keep it governed; do not treat masking as anonymisation.

Key handling (host secrets standard): the HMAC key is read from the MASKING_KEY
environment variable (sourced from ~/.secrets). There is NO insecure default - if it is
unset the tool refuses to run.

Roles (per field):
  drop        remove the field entirely
  token       deterministic keyed HMAC token; preserves referential integrity
  shift       consistent per-entity time shift; preserves intra-entity deltas
  keep        pass through unchanged (signal-bearing values, side, lifecycle kind)
  generalise  bucket a numeric / map a category to reduce quasi-identifier risk
  redact      replace PII patterns in free text with consistent typed surrogates

Usage:
  export MASKING_KEY=...            # from ~/.secrets, never hard-coded
  python -m scripts.ingest --schema config/masking-schema.yaml \\
      --in <the governed raw input>.jsonl --out data/masked/orders.jsonl

Flags:
  --out                 optional; omit it (or pass '-') to stream JSONL to stdout.
  --no-validate         skip the post-mask validate_masking scan, which otherwise
                        runs on every masked output by default. Masking that is
                        never checked is faith, not control, so the check is opt-OUT.
  --allow-unknown-keep  accept `on_unknown: keep` passthrough without a non-zero
                        exit. The warning still prints - the flag only says the
                        passthrough was a deliberate decision, not an oversight.

Exit codes: a run reports EVERY condition it found on stderr and THEN returns the
highest code, so a validation failure can never quietly swallow an unknown-field
warning (or the reverse) - you always see both reasons.
  0  masked cleanly; the post-mask scan passed (or was skipped with --no-validate)
  1  findings exist: record(s) were skipped, and/or `on_unknown: keep` passed
     unknown fields through without --allow-unknown-keep. The output was still
     written; a human decides whether the findings matter.
  2  the post-mask validate_masking scan FAILED - the output may still carry PII.
     Treat the file as unsafe (it is not safe to hand to an agent) until the
     reported check is resolved.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - import guard
    yaml = None

# Hex chars of the HMAC kept per token. 24 hex = 96 bits: the birthday bound is ~2^48, so
# identifier-domain (e.g. order_id) tokens stay collision-free at realistic venue volumes -
# 12 hex (48 bits) collided around ~17M distinct ids, silently merging order lifecycles.
TOKEN_LEN = 24

# ---------------------------------------------------------------------------
# Free-text PII patterns for the `redact` role.
#
# NOTE: regex redaction is a dependency-light baseline suitable for structured
# fields with predictable formats.  Production communications surveillance
# (email body, chat, voice transcripts) MUST swap in a trained NER model -
# regexes will miss obfuscated identifiers and novel formats.
#
# Pattern ordering rationale (most-specific-first):
#   1. EMAIL   - must come before PHONE and ACCT to prevent the local-part or
#                domain being consumed by the more-general digit/char rules.
#   2. IBAN    - fixed format (2-letter country + 2 digits + up to 30 alphanum);
#                must precede ACCT (which matches any 8+ digit run) so the full
#                IBAN is replaced rather than just its numeric suffix.
#   3. CARD    - 13-19 digits, optionally space/dash separated; before ACCT.
#   4. NATIONAL_ID - common patterns (SSN, NI); before PHONE/ACCT to avoid
#                partial matches.
#   5. PHONE   - international/local; after EMAIL (email local-parts can look
#                like phone numbers) and after NATIONAL_ID.
#   6. DATE    - date-like strings that are NOT phone numbers (e.g. DOB); after
#                PHONE to avoid mislabelling phone numbers as dates.
#   7. ACCT    - any remaining long digit run (8+ digits); catch-all; must be
#                last to avoid shadowing more-specific patterns above.
# ---------------------------------------------------------------------------
_PII_PATTERNS = [
    # 1. Email address - most specific; consume before digit patterns.
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    # 2. IBAN - ISO 13616: CC + 2 check digits + up to 30 BBAN chars.
    #    Allow optional spaces/dashes (printed IBANs are often grouped).
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[\s\-]?(?:[A-Z0-9]{4}[\s\-]?){2,7}[A-Z0-9]{1,4}\b")),
    # 3. Payment card - 13-19 digits, optionally grouped by spaces or dashes.
    #    Luhn validation is not done here (would require more logic); the regex
    #    catches the structural pattern only.
    ("CARD", re.compile(r"\b(?:\d[\s\-]?){13,18}\d\b")),
    # 4. National ID - UK NI (AA999999A), US SSN (NNN-NN-NNNN / NNNNNNNNN).
    ("NATIONAL_ID", re.compile(r"\b(?:[A-Z]{2}\d{6}[A-D]|\d{3}[\-]\d{2}[\-]\d{4}|\d{9})\b")),
    # 5. Date of birth / date literals - placed BEFORE phone so YYYY-MM-DD is not
    #    consumed as a phone-number digit run (ordering matters; see overlap test).
    #    Matches common date formats (YYYY-MM-DD, DD/MM/YYYY, DD-MMM-YYYY).
    (
        "DATE",
        re.compile(
            r"\b(?:\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4}|\d{1,2}[\s\-][A-Za-z]{3}[\s\-]\d{4})\b"
        ),
    ),
    # 6. Phone number - international (+CC) or long local (7-14 digits).
    #    Lookbehind/ahead excludes '/' and '-' so a phone run cannot start mid-date.
    ("PHONE", re.compile(r"(?<![\d/\-])\+?\d[\d \-().]{7,}\d(?![\d/\-])")),
    # 7. Account number - any unmatched run of 8+ digits (catch-all, must be last).
    ("ACCT", re.compile(r"(?<!\d)\d{8,}(?!\d)")),
]


def get_key_from_env() -> bytes:
    """Read the masking key from the environment. No insecure default (secrets standard)."""
    key = os.environ.get("MASKING_KEY")
    if not key:
        raise RuntimeError(
            "MASKING_KEY is not set. Source it from ~/.secrets - refusing to run with no "
            "key (no insecure default; see CLAUDE.md secrets standard)."
        )
    return key.encode()


def load_schema(path: str | Path) -> dict:
    if yaml is None:
        raise RuntimeError("pyyaml is required: pip install -r requirements-dev.txt")
    # Explicit encoding: a schema authored on Linux must load identically on a Windows
    # console whose locale default is cp1252, or a non-ASCII comment silently breaks it.
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def validate_schema(schema: dict) -> None:
    """
    Up-front schema validation: verify structural constraints before processing data.

    Checks:
    - Every `shift`-role field references an `entity` key that exists in the schema.
    - Every `shift`-role field's `entity` value is present in the schema fields.

    Raises ValueError with an explanation if the schema is invalid.
    This is called once before the record loop so a config error is caught early,
    not per-row, and never with record content in the error message.

    `on_unknown: keep` is not an error - a config may legitimately need it - but it is
    warned about here because it inverts the safe default: every field the author did
    not think about survives into the masked output. The warning fires on the CONFIG,
    before any data is read, so the operator sees the posture even on a run where no
    unknown field happens to appear.
    """
    fields = schema.get("fields", {})
    errors = []
    for field_name, spec in fields.items():
        if spec.get("role") == "shift":
            entity_key = spec.get("entity")
            if not entity_key:
                errors.append(
                    f"Field '{field_name}': role=shift requires an 'entity' key in the schema."
                )
            elif entity_key not in fields:
                errors.append(
                    f"Field '{field_name}': shift entity '{entity_key}' is not declared "
                    f"in schema fields. Available fields: {sorted(fields)}."
                )
    if errors:
        raise ValueError(
            "Masking schema validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    if schema.get("on_unknown", "drop") == "keep":
        print(
            "WARNING: schema sets on_unknown: keep - any field NOT declared in `fields:` "
            "will pass through UNMASKED. The safe default is `drop`. Change it unless the "
            "passthrough is a deliberate, reviewed decision.",
            file=sys.stderr,
        )


def _hmac_hex(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def _token(value, domain: str, key: bytes) -> str:
    """Deterministic, keyed token. Same (domain, value) -> same token everywhere."""
    return f"{domain}_{_hmac_hex(key, f'{domain}:{value}')[:TOKEN_LEN]}"


def _shift_offset(entity_value, key: bytes, max_shift_ms: int) -> int:
    """Deterministic per-entity offset in [-max_shift_ms, +max_shift_ms]."""
    n = int(_hmac_hex(key, f"shift:{entity_value}")[:16], 16)
    span = 2 * max_shift_ms + 1
    return (n % span) - max_shift_ms


def _generalise(value, spec: dict):
    if "bucket" in spec:
        b = spec["bucket"]
        return (float(value) // b) * b
    if "mapping" in spec:
        return spec["mapping"].get(str(value), spec.get("default", "OTHER"))
    return value


def _redact_text(text, key: bytes):
    """Replace PII in free text with typed, deterministic surrogates.

    Surrogates are TOKEN_LEN wide - the same 96 bits as a structured identifier token,
    and for the same reason: a surrogate is a referential-integrity handle too. An analyst
    links "[EMAIL_xxx] appears in these 40 chats" exactly as they link an order_id token,
    so a collision merges two people's correspondence. The old 6 hex chars were 24 bits,
    colliding at roughly 1 in 16M - tolerable for one field, reckless across a comms corpus.

    Patterns are applied in _PII_PATTERNS order (most-specific-first; see the table above),
    but text already replaced is CLOSED to further matching. That protection is what makes
    the widening safe: a 24-char hex token has a real chance of containing a 9+ digit run,
    and a later pattern pass would happily rewrite the middle of it into a nested surrogate,
    destroying the very referential integrity the extra bits were bought for.
    """
    if not isinstance(text, str):
        return text
    # Segments of (still-open-to-matching?, text).
    segments: list[tuple[bool, str]] = [(True, text)]
    for label, pat in _PII_PATTERNS:
        rewritten: list[tuple[bool, str]] = []
        for is_open, chunk in segments:
            if not is_open:
                rewritten.append((False, chunk))
                continue
            pos = 0
            for m in pat.finditer(chunk):
                if m.start() > pos:
                    rewritten.append((True, chunk[pos : m.start()]))
                token = _hmac_hex(key, f"{label}:{m.group(0)}")[:TOKEN_LEN]
                rewritten.append((False, f"[{label}_{token}]"))
                pos = m.end()
            if pos < len(chunk):
                rewritten.append((True, chunk[pos:]))
        segments = rewritten
    return "".join(chunk for _, chunk in segments)


def mask_record(
    record: dict, schema: dict, key: bytes, unknown_seen: set[str] | None = None
) -> dict:
    """Mask one record.

    `unknown_seen`, when given, collects the NAMES of fields that were not declared in
    the schema and were passed through anyway under `on_unknown: keep`. Names only -
    never values (§5) - so the caller can name the leak without echoing the data.
    """
    fields = schema["fields"]
    out: dict = {}
    for name, value in record.items():
        spec = fields.get(name)
        if spec is None:
            if schema.get("on_unknown", "drop") == "keep":
                out[name] = value
                if unknown_seen is not None:
                    unknown_seen.add(name)
            continue
        role = spec["role"]
        if role == "drop":
            continue
        elif role == "keep":
            out[name] = value
        elif role == "token":
            out[name] = _token(value, spec.get("domain", name), key)
        elif role == "shift":
            # validate_schema() guarantees spec["entity"] exists in the SCHEMA. Per record, if
            # the entity field is absent, record[spec["entity"]] raises KeyError and the
            # per-record wrapper in mask_records() skips the WHOLE row by index (not just this
            # field); a present-but-non-numeric value is caught the same way.
            offset = _shift_offset(
                record[spec["entity"]], key, int(spec.get("max_shift_ms", 2592000000))
            )
            out[name] = int(value) + offset
        elif role == "generalise":
            out[name] = _generalise(value, spec)
        elif role == "redact":
            out[name] = _redact_text(value, key)
        else:
            raise ValueError(f"Unknown masking role '{role}' for field '{name}'")
    return out


def mask_records(
    records: list[dict], schema: dict, key: bytes, unknown_seen: set[str] | None = None
) -> list[dict]:
    """
    Mask a list of records, skipping (not aborting on) individual bad rows.

    Bad rows are collected by INDEX only - record content is never echoed into
    error messages or logs (CLAUDE.md §5: PII must not egress into logs).
    A summary count is printed at the end if any rows were skipped.

    `unknown_seen` is passed straight through to mask_record(); see its docstring.
    """
    out = []
    failures: list[int] = []  # row indices only - no record content
    for idx, record in enumerate(records):
        try:
            out.append(mask_record(record, schema, key, unknown_seen))
        except (ValueError, KeyError, TypeError, IndexError, ArithmeticError):
            # Skip DATA-shaped row errors (bad/missing/non-numeric fields), by INDEX only -
            # never echo record content. A schema/programming error (e.g. NameError, a bad
            # role) is NOT caught here: it propagates and aborts, so config bugs fail loudly
            # instead of silently dropping every row.
            failures.append(idx)
    if failures:
        print(
            f"WARNING: {len(failures)} record(s) skipped due to processing errors "
            f"(row indices: {failures}). "
            "Check schema config and input file format.",
            file=sys.stderr,
        )
    return out


def main() -> None:
    # Force UTF-8 output so a cp1252 (Windows) console can't crash on non-ASCII (0.19.0).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(
        description="Mask raw records into the governed pipeline.",
        epilog=(
            "Exit codes: 0 = clean; 1 = findings exist (rows skipped, and/or unknown "
            "fields passed through under on_unknown: keep); 2 = the post-mask "
            "validate_masking scan FAILED, so the output may still carry PII. Every "
            "condition found is printed on stderr before the highest code is returned, "
            "so the two never mask each other."
        ),
    )
    ap.add_argument("--schema", type=Path, default=Path("config/masking-schema.yaml"))
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output .jsonl; omit or pass '-' to write JSONL to stdout",
    )
    ap.add_argument(
        "--no-validate",
        action="store_true",
        help="skip the post-mask validate_masking scan (it runs by default)",
    )
    ap.add_argument(
        "--allow-unknown-keep",
        action="store_true",
        help="accept on_unknown: keep passthrough without exiting non-zero",
    )
    args = ap.parse_args()

    key = get_key_from_env()
    schema = load_schema(args.schema)

    # Validate schema up front before touching any data.
    validate_schema(schema)

    # Parse input JSONL with per-line error handling.
    # Failures are logged by line number only - never with line content (§5).
    records = []
    parse_failures = []
    for lineno, line in enumerate(args.inp.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            parse_failures.append(lineno)

    if parse_failures:
        print(
            f"WARNING: {len(parse_failures)} line(s) could not be parsed as JSON "
            f"(line numbers: {parse_failures}) - skipped.",
            file=sys.stderr,
        )

    # Names of undeclared fields that `on_unknown: keep` let through (S-20).
    unknown_seen: set[str] = set()
    masked = mask_records(records, schema, key, unknown_seen)

    payload = "\n".join(json.dumps(r) for r in masked) + "\n"
    to_stdout = args.out is None or str(args.out) == "-"
    if to_stdout:
        # No --out: stream the JSONL so the tool composes in a pipeline. Everything
        # else this function prints already goes to stderr, so stdout stays pure data.
        sys.stdout.write(payload)
        print(f"Masked {len(masked)} records -> stdout", file=sys.stderr)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(f"Masked {len(masked)} records -> {args.out}")

    # Collect every reason to exit non-zero BEFORE exiting on any one of them, so a
    # validation failure cannot hide an unknown-field warning (or the reverse).
    findings = False  # -> exit 1
    validation_failed = False  # -> exit 2 (outranks findings)

    if len(masked) < len(records):
        print(
            f"WARNING: {len(records) - len(masked)} record(s) were skipped; "
            "review stderr output for row indices.",
            file=sys.stderr,
        )
        findings = True

    if unknown_seen:
        # Field NAMES only - never values (§5). Loud, because the whole point of
        # `on_unknown: keep` going wrong is that nobody notices the extra columns.
        names = ", ".join(sorted(unknown_seen))
        print(
            "=" * 72 + "\nWARNING: on_unknown: keep passed UNDECLARED fields through UNMASKED.\n"
            f"  Fields: {names}\n"
            "  These were never reviewed against a masking role, so whatever they hold "
            "(PII, MNPI, free text) is in the output verbatim.\n"
            "  Fix: declare a role for each in the schema, or set on_unknown: drop.\n"
            "  If the passthrough IS intended, re-run with --allow-unknown-keep.\n" + "=" * 72,
            file=sys.stderr,
        )
        if not args.allow_unknown_keep:
            findings = True

    if not args.no_validate:
        # Import lazily: validate_masking imports from this module, so a module-level
        # import here would be circular. In-process, never a subprocess - the checks are
        # this repo's own tooling, not the untrusted code the exec gate covers (§7).
        from scripts.validate_masking import scan_masked_records

        checks = scan_masked_records(masked, schema)
        failed = [(name, detail) for name, ok, detail in checks if not ok]
        if failed:
            print(
                "FAIL: post-mask validation of the output found problems:",
                file=sys.stderr,
            )
            for name, detail in failed:
                print(f"  - {name}: {detail}", file=sys.stderr)
            print(
                "  The masked output may still carry PII - do not share it or hand it "
                "to an agent until this is resolved. Re-run with --no-validate only if "
                "you have another control in place.",
                file=sys.stderr,
            )
            validation_failed = True

    if validation_failed:
        sys.exit(2)
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
