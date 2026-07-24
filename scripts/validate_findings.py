#!/usr/bin/env python3
"""Validate a review findings pack against docs/review/findings-schema.json.

The pack (JSON) is the structured source of truth for a review/audit report; render_findings.py
turns it into the canonical REVIEW-<slug>.md. Validating here - required fields, enums, types - is
the enforcement that makes format drift impossible: a missing or renamed field is a hard error the
team must fix, not a silent three-C report. A tiny dependency-free JSON-Schema subset validator
(type / required / enum / minimum / maximum / properties / items), matching the repo's
no-third-party-deps posture (same as check_artifacts).

Packs live in a subfolder (artifacts/data/) so the top-level artifacts/ stays user-navigable
(.md/.txt/.html); this script takes an explicit pack path.

Exit 0 = valid; exit 1 = violations printed (one per line, `FINDINGS-INVALID:` prefix). Output is
forced to UTF-8 so it can't crash a Windows console.
Usage: python -m scripts.validate_findings <pack.json> [schema.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "docs" / "review" / "findings-schema.json"

_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def validate(instance: object, schema: dict, path: str = "$") -> list[str]:
    """Return a list of violation strings (empty = valid). Supports the JSON-Schema subset the
    findings schema uses."""
    errs: list[str] = []
    expected = schema.get("type")
    if expected:
        py = _TYPES[expected]
        # bool is a subclass of int in Python - keep them distinct.
        if expected == "integer" and isinstance(instance, bool):
            return [f"{path}: expected integer, got boolean"]
        if not isinstance(instance, py) or (expected != "boolean" and isinstance(instance, bool)):
            return [f"{path}: expected {expected}, got {type(instance).__name__}"]

    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} is not one of {schema['enum']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: {instance} below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: {instance} above maximum {schema['maximum']}")

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errs.append(f"{path}: missing required field '{req}'")
        for key, subschema in schema.get("properties", {}).items():
            if key in instance:
                errs.extend(validate(instance[key], subschema, f"{path}.{key}"))

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errs.extend(validate(item, schema["items"], f"{path}[{i}]"))

    return errs


def load_and_validate(pack_path: Path, schema_path: Path = _SCHEMA_PATH) -> list[str]:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    pack = json.loads(Path(pack_path).read_text(encoding="utf-8"))
    return validate(pack, schema)


def main(argv: list[str]) -> int:
    _force_utf8_output()
    if len(argv) < 2:
        print("usage: python -m scripts.validate_findings <pack.json> [schema.json]")
        return 2
    pack_path = Path(argv[1])
    schema_path = Path(argv[2]) if len(argv) > 2 else _SCHEMA_PATH
    try:
        errs = load_and_validate(pack_path, schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FINDINGS-INVALID: cannot read/parse {pack_path}: {exc}")
        return 1
    if errs:
        for err in errs:
            print(f"FINDINGS-INVALID: {err}")
        print(f"findings pack {pack_path}: {len(errs)} schema violation(s) - NOT valid")
        return 1
    print(f"findings pack OK: {pack_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
