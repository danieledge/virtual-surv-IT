#!/usr/bin/env python3
"""Semantic tags for the columns of a dataset - what each field MEANS, not what it holds.

WHY THIS EXISTS. Handed an undocumented extract, the first question is always "what am I
looking at" - which column is the counterparty, which is the instrument, which is the money.
Today that is guesswork done column by column, and it is guesswork an agent should not be
doing by reading the data, because anything an agent reads goes to the model provider
(CLAUDE.md §5).

The taxonomy is ported from the owner's own DataK9 project (MIT) and is grounded in FIBO, the
Financial Industry Business Ontology - 29 tags across money, banking, loan, security, party,
identifier, temporal, category and risk. That grounding matters here: a tag that maps to a
published ontology class is defensible to a regulator in a way that an ad-hoc label is not.
The DATA came across unchanged; this matcher is a stdlib reimplementation, because DataK9's
own tagger leans on its reference-data loader and config layer, and the plugin carries no
third-party dependency.

WHAT MAKES IT SAFE TO POINT AT CLIENT DATA. Values are READ to test data properties (is this
column numeric, how many distinct values, how long are the strings) and are never PRINTED.
Output is column names, tags, confidences and counts. Treat any change that emits a cell
value as a safety regression.

WHAT IT IS NOT. Not an authority and not a clearance. Every tag is 🧠 INFERRED from a column
name pattern and coarse data properties: `party.counterparty` on a column called `cpty` is a
strong guess, not a fact, and a column named nothing useful will tag as nothing. Use it to
orient and to ask better questions of whoever owns the feed - never as the basis for a
finding on its own, and never as evidence that a field does NOT contain what it seems to.

Usage:
    python -m scripts.tag_columns DATA.csv [--min-confidence 0.6] [--json]
                                  [--taxonomy config/finance-taxonomy.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_TAXONOMY = _REPO_ROOT / "config" / "finance-taxonomy.json"

_SAMPLE_ROWS = 400  # enough to judge type and cardinality; bounded so a huge file is cheap
_MIN_CONFIDENCE = 0.60  # DataK9's own threshold, kept - below it the tags are noise

# A name match is the primary evidence; data properties can only ADJUST it. A column called
# `settlement_amount` that turns out to be text is still probably money with a formatting
# problem, which is itself worth seeing - so disagreement lowers confidence, never zeroes it.
_NAME_MATCH_CONFIDENCE = 0.75
_PROPERTY_AGREE_BONUS = 0.15
_PROPERTY_DISAGREE_PENALTY = 0.20


def load_taxonomy(path: Path) -> list[dict]:
    """Flatten the domain -> tags structure into one list of candidate tags."""
    data = json.loads(path.read_text(encoding="utf-8"))
    flat = []
    for domain, block in (data.get("taxonomy") or {}).items():
        for name, tag in (block.get("tags") or {}).items():
            flat.append(
                {
                    "tag": name,
                    "domain": domain,
                    "fibo_class": tag.get("fibo_class", ""),
                    "definition": tag.get("definition", ""),
                    "patterns": [re.compile(p) for p in tag.get("patterns", [])],
                    "properties": tag.get("data_properties") or {},
                }
            )
    return flat


def column_properties(values: list[str]) -> dict:
    """Coarse, honest facts about a column: nothing here identifies a record."""
    present = [v for v in values if (v or "").strip()]
    numeric, lengths = [], []
    for value in present:
        lengths.append(len(value))
        try:
            numeric.append(float(value.replace(",", "")))
        except ValueError:
            pass
    props = {
        "rows_sampled": len(values),
        "populated": len(present),
        "distinct": len(set(present)),
        "numeric_share": (len(numeric) / len(present)) if present else 0.0,
        "mean_length": (sum(lengths) / len(lengths)) if lengths else 0.0,
    }
    if numeric:
        props["min_value"], props["max_value"] = min(numeric), max(numeric)
    return props


def _property_verdict(expected: dict, actual: dict) -> int:
    """+1 agrees, -1 disagrees, 0 nothing to say. Deliberately coarse: this is a nudge on a
    name match, and pretending to more precision than the evidence supports is how a tagger
    starts being believed."""
    if not expected or not actual.get("populated"):
        return 0
    verdict = 0
    types = [t.lower() for t in (expected.get("type") or [])]
    if types:
        wants_number = any(t in ("float", "decimal", "int", "integer", "number") for t in types)
        is_number = actual["numeric_share"] >= 0.9
        verdict += 1 if wants_number == is_number else -1
    low, high = expected.get("cardinality_min"), expected.get("cardinality_max")
    if isinstance(high, (int, float)) and actual["distinct"] > high:
        verdict -= 1
    if isinstance(low, (int, float)) and actual["distinct"] >= low:
        verdict += 1
    length = expected.get("string_length")
    if isinstance(length, (int, float)) and actual["mean_length"]:
        verdict += 1 if abs(actual["mean_length"] - length) <= 2 else -1
    return 1 if verdict > 0 else (-1 if verdict < 0 else 0)


def tag_column(name: str, values: list[str], taxonomy: list[dict], floor: float) -> dict:
    """Best tag for one column, or an empty result. Name pattern first, properties second."""
    props = column_properties(values)
    scored = []
    for candidate in taxonomy:
        if not any(pattern.match(name) for pattern in candidate["patterns"]):
            continue
        confidence = _NAME_MATCH_CONFIDENCE
        verdict = _property_verdict(candidate["properties"], props)
        confidence += _PROPERTY_AGREE_BONUS if verdict > 0 else 0
        confidence -= _PROPERTY_DISAGREE_PENALTY if verdict < 0 else 0
        scored.append(
            {
                "tag": candidate["tag"],
                "domain": candidate["domain"],
                "fibo_class": candidate["fibo_class"],
                "definition": candidate["definition"],
                "confidence": round(min(confidence, 0.95), 2),
                "properties_agree": verdict,
            }
        )
    # Ties break on tag name so two runs on the same file agree - determinism is a property
    # every tool in this repo is expected to have.
    scored.sort(key=lambda s: (-s["confidence"], s["tag"]))
    best = next((s for s in scored if s["confidence"] >= floor), None)
    return {
        "column": name,
        "match": best,
        "other_candidates": [s["tag"] for s in scored if best and s["tag"] != best["tag"]][:3],
        "properties": props,
    }


def profile(path: Path, taxonomy: list[dict], floor: float) -> dict:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        sample: list[dict] = []
        for i, row in enumerate(reader):
            if i >= _SAMPLE_ROWS:
                break
            sample.append(row)
    columns = [
        tag_column(name, [row.get(name, "") for row in sample], taxonomy, floor)
        for name in headers
    ]
    return {
        "file": path.name,
        "columns_examined": len(headers),
        "rows_sampled": len(sample),
        "tagged": sum(1 for c in columns if c["match"]),
        "results": columns,
    }


def render(result: dict) -> str:
    out = [
        f"# Column semantics - {result['file']}",
        "",
        f"{result['tagged']} of {result['columns_examined']} columns tagged "
        f"(sampled {result['rows_sampled']:,} rows)",
        "",
    ]
    width = max((len(c["column"]) for c in result["results"]), default=6)
    for col in result["results"]:
        match = col["match"]
        if not match:
            out.append(f"  {col['column'].ljust(width)}  -")
            continue
        line = (
            f"  {col['column'].ljust(width)}  {match['tag']}"
            f"  ({match['confidence']:.2f})  {match['fibo_class']}"
        )
        if match["properties_agree"] < 0:
            line += "  [data disagrees with the name]"
        out.append(line)
        if col["other_candidates"]:
            out.append(f"  {' ' * width}  also matched: {', '.join(col['other_candidates'])}")
    out += [
        "",
        "> 🧠 INFERRED from column names and coarse data properties, never from reading",
        "> records. A tag is a strong guess to orient you and to ask the feed owner a better",
        "> question - never evidence on its own, and never proof that a field does NOT",
        "> contain what it appears to.",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Semantic tags for a CSV's columns (FIBO-grounded).")
    ap.add_argument("path", help="CSV file (convert_file turns Excel/PDF into one)")
    ap.add_argument("--taxonomy", default=str(_DEFAULT_TAXONOMY))
    ap.add_argument("--min-confidence", type=float, default=_MIN_CONFIDENCE)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    path, taxonomy_path = Path(args.path), Path(args.taxonomy)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    if not taxonomy_path.is_file():
        print(f"taxonomy not found: {taxonomy_path}", file=sys.stderr)
        return 2
    try:
        taxonomy = load_taxonomy(taxonomy_path)
        result = profile(path, taxonomy, args.min_confidence)
    except (OSError, csv.Error, ValueError, re.error) as exc:
        print(f"could not tag {path.name}: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
