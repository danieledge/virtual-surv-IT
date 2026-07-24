"""Structured findings pack: schema validation + deterministic rendering.

The pack is the source of truth; the renderer owns the layout, so a finding cannot drift format.
These pin: a valid pack passes, missing/invalid fields fail, and the render produces the canonical
five named fields (never C-words / "5C").
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.render_findings import render
from scripts.validate_findings import load_and_validate, validate

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = json.loads(
    (_ROOT / "docs" / "review" / "findings-schema.json").read_text(encoding="utf-8")
)
_GOLD_PATH = _ROOT / "docs" / "review" / "gold-findings.json"
_GOLD = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))


def test_gold_pack_is_valid():
    assert load_and_validate(_GOLD_PATH) == []


def test_missing_required_field_fails():
    pack = copy.deepcopy(_GOLD)
    del pack["findings"][0]["likely_cause"]
    errs = validate(pack, _SCHEMA)
    assert any("likely_cause" in e for e in errs)


def test_bad_severity_enum_fails():
    pack = copy.deepcopy(_GOLD)
    pack["findings"][0]["severity"] = "showstopper"
    assert any("severity" in e for e in validate(pack, _SCHEMA))


def test_confidence_out_of_range_fails():
    pack = copy.deepcopy(_GOLD)
    pack["findings"][0]["confidence"] = 150
    assert any("maximum" in e for e in validate(pack, _SCHEMA))


def test_render_uses_the_five_named_fields_never_cwords(tmp_path):
    md = render(_GOLD)
    for field in (
        "**Standard:**",
        "**Problem:**",
        "**Likely cause:**",
        "**Impact if unaddressed:**",
        "**Fix:**",
    ):
        assert field in md
    # never the drift form
    assert "5C" not in md and "5-C" not in md
    assert (
        "**Condition:**" not in md and "**Consequence:**" not in md and "**Correction:**" not in md
    )
    # every finding gets all five - the count of each field == number of findings
    assert md.count("**Standard:**") == len(_GOLD["findings"])
    assert md.count("**Likely cause:**") == len(_GOLD["findings"])


def test_render_empty_findings_is_explicit(tmp_path):
    pack = copy.deepcopy(_GOLD)
    pack["findings"] = []
    assert "_No findings._" in render(pack)
