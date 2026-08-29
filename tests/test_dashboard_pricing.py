"""Model normalisation in the one rate table (2026-08-25).

Found while removing a duplicate table: no model id carrying a context suffix
(`claude-opus-5[1m]`) or a release date (`claude-haiku-4-5-20251001`) matched, so every
message from the models this machine actually runs priced as None and was counted as
"partially priced". `budget-status` measures an unattended run against its ceiling using this
code, so the ceiling was being compared against an under-counted spend.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _dashboard():
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "dashboard", REPO_ROOT / "scripts" / "dashboard.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dashboard"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_context_window_suffix_does_not_change_the_rate():
    d = _dashboard()
    assert d.normalise_model("claude-opus-5[1m]") == "claude-opus-5"


def test_a_release_date_suffix_does_not_change_the_rate():
    d = _dashboard()
    assert d.normalise_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5"


def test_both_suffixes_together():
    d = _dashboard()
    assert d.normalise_model("claude-sonnet-5-20260101[1m]") == "claude-sonnet-5"


def test_an_unknown_model_is_still_unpriced():
    """Only those two suffixes are stripped. A model nobody has set a rate for stays
    unpriced, which is the honest answer - guessing from a neighbour would look
    authoritative and be wrong."""
    d = _dashboard()
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    assert d.price_usage("some-other-vendor-model", usage) is None
    assert d.price_usage("", usage) is None
    assert d.price_usage(None, usage) is None


def test_the_models_actually_seen_in_transcripts_all_price():
    """The point of the fix: these are the ids that appear in real files."""
    d = _dashboard()
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    for model in (
        "claude-opus-5[1m]",
        "claude-opus-5",
        "claude-fable-5",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
    ):
        assert d.price_usage(model, usage) is not None, f"{model} priced as unknown"
