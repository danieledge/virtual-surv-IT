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
      --in data/raw/orders.jsonl --out data/masked/orders.jsonl
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

TOKEN_LEN = 12

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
    # 3. Payment card - 13–19 digits, optionally grouped by spaces or dashes.
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
    # 6. Phone number - international (+CC) or long local (7–14 digits).
    #    Lookbehind/ahead excludes '/' and '-' so a phone run cannot start mid-date.
    ("PHONE", re.compile(r"(?<![\d/\-])\+?\d[\d \-]{7,}\d(?![\d/\-])")),
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
    return yaml.safe_load(Path(path).read_text())


def validate_schema(schema: dict) -> None:
    """
    Up-front schema validation: verify structural constraints before processing data.

    Checks:
    - Every `shift`-role field references an `entity` key that exists in the schema.
    - Every `shift`-role field's `entity` value is present in the schema fields.

    Raises ValueError with an explanation if the schema is invalid.
    This is called once before the record loop so a config error is caught early,
    not per-row, and never with record content in the error message.
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
    if not isinstance(text, str):
        return text
    out = text
    for label, pat in _PII_PATTERNS:

        def repl(m, label=label):
            return f"[{label}_{_hmac_hex(key, f'{label}:{m.group(0)}')[:6]}]"

        out = pat.sub(repl, out)
    return out


def mask_record(record: dict, schema: dict, key: bytes) -> dict:
    fields = schema["fields"]
    out: dict = {}
    for name, value in record.items():
        spec = fields.get(name)
        if spec is None:
            if schema.get("on_unknown", "drop") == "keep":
                out[name] = value
            continue
        role = spec["role"]
        if role == "drop":
            continue
        elif role == "keep":
            out[name] = value
        elif role == "token":
            out[name] = _token(value, spec.get("domain", name), key)
        elif role == "shift":
            # validate_schema() guarantees spec["entity"] exists in the SCHEMA. Per record,
            # if the entity field is absent the field is simply skipped (this loop is over
            # record.items()); if present-but-non-numeric the per-record wrapper in
            # mask_records() skips the whole row by index.
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


def mask_records(records: list[dict], schema: dict, key: bytes) -> list[dict]:
    """
    Mask a list of records, skipping (not aborting on) individual bad rows.

    Bad rows are collected by INDEX only - record content is never echoed into
    error messages or logs (CLAUDE.md §5: PII must not egress into logs).
    A summary count is printed at the end if any rows were skipped.
    """
    out = []
    failures: list[int] = []  # row indices only - no record content
    for idx, record in enumerate(records):
        try:
            out.append(mask_record(record, schema, key))
        except Exception:
            # Swallow the per-row error; do NOT include record content.
            # Failures are reported as a count + index list only.
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
    ap = argparse.ArgumentParser(description="Mask raw records into the governed pipeline.")
    ap.add_argument("--schema", type=Path, default=Path("config/masking-schema.yaml"))
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    key = get_key_from_env()
    schema = load_schema(args.schema)

    # Validate schema up front before touching any data.
    validate_schema(schema)

    # Parse input JSONL with per-line error handling.
    # Failures are logged by line number only - never with line content (§5).
    records = []
    parse_failures = []
    for lineno, line in enumerate(args.inp.read_text().splitlines(), start=1):
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

    masked = mask_records(records, schema, key)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(r) for r in masked) + "\n")
    print(f"Masked {len(masked)} records -> {args.out}")
    if len(masked) < len(records):
        print(
            f"WARNING: {len(records) - len(masked)} record(s) were skipped; "
            "review stderr output for row indices.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
