"""
Tests for the masking pipeline (scripts/ingest.py) and its validation harness.
All data is synthetic (§5). A throwaway test key is used - it is not a secret.
"""

from __future__ import annotations

import pytest

from scripts.gen_synthetic import event_to_record, spoofing_session
from scripts.ingest import (
    get_key_from_env,
    load_schema,
    mask_record,
    mask_records,
    validate_schema,
)
from scripts.validate_masking import (
    _TEST_KEY_CONSTANT,
    detection_fidelity,
    run_privacy_checks,
    scan_masked_file,
)

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
    """price/qty/side/kind must pass through unchanged - they carry the detection signal."""
    orig, masked = _records(), mask_records(_records(), SCHEMA, KEY)
    for o, m in zip(orig, masked):
        assert (m["price"], m["qty"], m["side"], m["kind"]) == (
            o["price"],
            o["qty"],
            o["side"],
            o["kind"],
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
    # Scans the free-text-capable output fields (redact/token + keep-direct-id).
    assert by_name["no residual PII patterns (free-text-capable fields)"][0]


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


# ---------------------------------------------------------------------------
# Tests for new behaviour added by the data-safety remediation
# ---------------------------------------------------------------------------


def test_validate_schema_passes_on_good_schema():
    """validate_schema() is a no-op on a correctly configured schema."""
    # The canonical schema has a valid shift->entity reference.
    validate_schema(SCHEMA)  # must not raise


def test_validate_schema_rejects_shift_without_entity():
    """validate_schema() raises ValueError if a shift field has no entity key."""
    bad = {
        "fields": {
            "ts_ms": {"role": "shift"},  # missing 'entity'
            "trader": {"role": "token"},
        }
    }
    with pytest.raises(ValueError, match="entity"):
        validate_schema(bad)


def test_validate_schema_rejects_missing_entity_field():
    """validate_schema() raises ValueError if the shift entity field is not in the schema."""
    bad = {
        "fields": {
            "ts_ms": {"role": "shift", "entity": "nonexistent_field"},
            "trader": {"role": "token"},
        }
    }
    with pytest.raises(ValueError, match="nonexistent_field"):
        validate_schema(bad)


def test_mask_records_skips_bad_rows_not_abort(capsys):
    """A bad row (missing entity field) skips that record; the rest are still masked."""
    # Build a schema with a shift field so a missing entity causes a per-record error.
    schema = {
        "on_unknown": "drop",
        "fields": {
            "ts_ms": {"role": "shift", "entity": "trader", "max_shift_ms": 1000},
            "trader": {"role": "token", "domain": "party"},
        },
    }
    records = [
        {"ts_ms": 1000000, "trader": "T1"},  # good
        {"ts_ms": 2000000},  # bad - missing 'trader' (shift entity)
        {"ts_ms": 3000000, "trader": "T1"},  # good
    ]
    out = mask_records(records, schema, KEY)
    # Two good records survive; the bad one is skipped without aborting.
    assert len(out) == 2
    captured = capsys.readouterr()
    assert "1 record(s) skipped" in captured.err
    # Row INDEX (1) appears in warning; no record content must appear.
    assert "1" in captured.err


def test_redaction_catches_iban_and_card():
    """Extended PII patterns (FIX 5): IBAN and payment card numbers are redacted."""
    schema = {"on_unknown": "drop", "fields": {"body": {"role": "redact"}}}
    iban = "GB29NWBK60161331926819"
    card = "4111 1111 1111 1111"
    rec = {"body": f"IBAN: {iban}, card: {card}"}
    out = mask_record(rec, schema, KEY)["body"]
    assert iban not in out, "IBAN must be redacted"
    assert "4111" not in out or "1111 1111 1111 1111" not in out  # card pattern redacted


def test_validate_masking_test_key_is_deterministic(monkeypatch):
    """validate_masking uses a fixed test key when MASKING_KEY is unset - not os.urandom."""
    monkeypatch.delenv("MASKING_KEY", raising=False)
    # Two runs with same inputs must produce identical results (os.urandom would differ).
    events = spoofing_session(seed=1)
    records = [event_to_record(e) for e in events]
    checks1, masked1 = run_privacy_checks(records, SCHEMA, _TEST_KEY_CONSTANT)
    checks2, masked2 = run_privacy_checks(records, SCHEMA, _TEST_KEY_CONSTANT)
    assert masked1 == masked2
    assert [(n, ok) for n, ok, _ in checks1] == [(n, ok) for n, ok, _ in checks2]


def test_direct_identifier_passthrough_is_flagged():
    """FIX 3: run_privacy_checks fails if a direct-identifier field has a keep/generalise role."""
    bad_schema = {
        "on_unknown": "drop",
        "fields": {
            "trader": {"role": "keep"},  # direct identifier with pass-through role
            "order_id": {"role": "token", "domain": "order"},
        },
    }
    records = [{"trader": "T1", "order_id": "O1"}]
    checks, _ = run_privacy_checks(records, bad_schema, KEY)
    by_name = {name: ok for name, ok, _ in checks}
    assert not by_name["no direct-identifier passthrough"], (
        "A trader field with role=keep must fail the direct-identifier passthrough check"
    )


def test_scan_masked_file_passes_clean(tmp_path):
    """--in mode: a clean masked file (tokens + numbers) passes."""
    f = tmp_path / "clean.jsonl"
    f.write_text('{"trader":"party_a1","order_id":"order_9f","ts_ms":123,"price":100.0,"qty":50}\n')
    checks = scan_masked_file(f, SCHEMA)
    by_name = {name: ok for name, ok, _ in checks}
    assert by_name["no residual PII in masked file (string fields)"] is True


def test_scan_masked_file_catches_residual_pii(tmp_path):
    """--in mode: residual free-text PII (email/IBAN) in a string field is caught."""
    f = tmp_path / "leaky.jsonl"
    f.write_text(
        '{"trader":"party_a1","note":"reach john.smith@bank.com or GB29NWBK60161331926819"}\n'
    )
    checks = scan_masked_file(f, SCHEMA)
    by_name = {name: ok for name, ok, _ in checks}
    assert by_name["no residual PII in masked file (string fields)"] is False, (
        "A leaked email/IBAN in a masked-file string field must fail the scan"
    )
