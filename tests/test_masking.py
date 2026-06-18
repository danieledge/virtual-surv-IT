"""
Tests for the masking pipeline (scripts/ingest.py) and its validation harness.
All data is synthetic (§5). A throwaway test key is used — it is not a secret.
"""
from __future__ import annotations

import pytest

from rules.spoofing import EventKind, Side, detect_spoofing
from scripts.gen_synthetic import event_to_record, record_to_event, spoofing_session
from scripts.ingest import get_key_from_env, load_schema, mask_record, mask_records
from scripts.validate_masking import detection_fidelity, run_privacy_checks

KEY = b"test-key-not-a-secret"
SCHEMA = load_schema("config/masking-schema.yaml")


def _records():
    return [event_to_record(e) for e in spoofing_session(seed=1)]


def test_tokenisation_is_deterministic_and_referential():
    """Same input -> same token; one order's NEW/CANCEL/FILL keep a shared order_id token."""
    masked = mask_records(_records(), SCHEMA, KEY)
    # All events of the original SPOOF1 order map to one token across NEW + CANCEL.
    orig = _records()
    spoof_ids = {i for i, r in enumerate(orig) if r["order_id"] == "SPOOF1"}
    tokens = {masked[i]["order_id"] for i in spoof_ids}
    assert len(tokens) == 1
    # Determinism across runs.
    assert mask_records(_records(), SCHEMA, KEY) == masked


def test_signal_fields_are_preserved():
    """price/qty/side/kind must pass through unchanged — they carry the detection signal."""
    orig, masked = _records(), mask_records(_records(), SCHEMA, KEY)
    for o, m in zip(orig, masked):
        assert (m["price"], m["qty"], m["side"], m["kind"]) == (
            o["price"], o["qty"], o["side"], o["kind"],
        )


def test_timing_deltas_are_preserved_within_entity():
    """Per-trader shift keeps inter-event intervals exactly (what trade surveillance needs)."""
    orig, masked = _records(), mask_records(_records(), SCHEMA, KEY)
    orig_ts = [r["ts_ms"] for r in orig]
    masked_ts = [r["ts_ms"] for r in masked]
    offset = masked_ts[0] - orig_ts[0]
    assert offset != 0  # absolute time actually moved
    assert all(m - o == offset for o, m in zip(orig_ts, masked_ts))  # deltas identical


def test_no_original_identifiers_survive():
    checks, _ = run_privacy_checks(_records(), SCHEMA, KEY)
    by_name = {name: (ok, detail) for name, ok, detail in checks}
    assert by_name["no residual identifiers"][0]
    assert by_name["no residual PII patterns"][0]


def test_detection_fidelity_is_exact():
    """The spoofing rule fires identically on masked data as on the original."""
    ok, n_real, n_masked = detection_fidelity(spoofing_session(seed=1), SCHEMA, KEY)
    assert ok
    assert n_real == n_masked == 1


def test_missing_key_refuses_to_run(monkeypatch):
    """No insecure default: masking refuses without MASKING_KEY (secrets standard)."""
    monkeypatch.delenv("MASKING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MASKING_KEY"):
        get_key_from_env()


def test_redaction_of_free_text():
    """The redact role replaces emails / phones / account numbers with typed surrogates."""
    schema = {
        "on_unknown": "drop",
        "fields": {"body": {"role": "redact"}},
    }
    rec = {"body": "call me on +44 7700 900123 or email jo.bloggs@example.com re acct 12345678"}
    out = mask_record(rec, schema, KEY)["body"]
    assert "jo.bloggs@example.com" not in out
    assert "900123" not in out
    assert "12345678" not in out
    assert "[EMAIL_" in out and "[PHONE_" in out and "[ACCT_" in out
