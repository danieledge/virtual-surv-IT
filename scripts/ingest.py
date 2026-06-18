"""
scripts/ingest.py — the single sanctioned path for real data to enter the pipeline.

It applies a role-based masking policy (config/masking-schema.yaml) so that the
IDENTITY layer is destroyed while the BEHAVIOUR layer (timing deltas, value
relationships, entity linkage) is preserved for detection development.

CLAUDE.md §5: agents must never read raw records. Run this locally; agents only ever
see the masked (or synthetic) output. Pseudonymised output is STILL sensitive (personal
data under GDPR) — keep it governed; do not treat masking as anonymisation.

Key handling (host secrets standard): the HMAC key is read from the MASKING_KEY
environment variable (sourced from ~/.secrets). There is NO insecure default — if it is
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
  python -m scripts.ingest --schema config/masking-schema.yaml \
      --in data/raw/orders.jsonl --out data/masked/orders.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - import guard
    yaml = None

TOKEN_LEN = 12

# Free-text PII patterns for the `redact` role. NOTE: regex redaction is a dependency-light
# baseline; production comms surveillance should swap in a trained NER model. Patterns are
# ordered most-specific-first so emails are not partially eaten by the account-number rule.
_PII_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("PHONE", re.compile(r"(?<![\d/])\+?\d[\d \-]{7,}\d(?![\d/])")),
    ("ACCT", re.compile(r"(?<!\d)\d{8,}(?!\d)")),
]


def get_key_from_env() -> bytes:
    """Read the masking key from the environment. No insecure default (secrets standard)."""
    key = os.environ.get("MASKING_KEY")
    if not key:
        raise RuntimeError(
            "MASKING_KEY is not set. Source it from ~/.secrets — refusing to run with no "
            "key (no insecure default; see CLAUDE.md secrets standard)."
        )
    return key.encode()


def load_schema(path: str | Path) -> dict:
    if yaml is None:
        raise RuntimeError("pyyaml is required: pip install -r requirements-dev.txt")
    return yaml.safe_load(Path(path).read_text())


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


def mask_records(records, schema: dict, key: bytes) -> list[dict]:
    return [mask_record(r, schema, key) for r in records]


def main() -> None:
    ap = argparse.ArgumentParser(description="Mask raw records into the governed pipeline.")
    ap.add_argument("--schema", type=Path, default=Path("config/masking-schema.yaml"))
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    key = get_key_from_env()
    schema = load_schema(args.schema)
    records = [json.loads(line) for line in args.inp.read_text().splitlines() if line.strip()]
    masked = mask_records(records, schema, key)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(r) for r in masked) + "\n")
    print(f"Masked {len(masked)} records -> {args.out}")


if __name__ == "__main__":
    main()
