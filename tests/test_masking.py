"""
Tests for the masking pipeline (scripts/ingest.py) and its validation harness.
All data is synthetic (§5). A throwaway test key is used - it is not a secret.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from scripts.gen_synthetic import event_to_record, spoofing_session
from scripts.gen_synthetic import main as gen_synthetic_main
from scripts.ingest import (
    TOKEN_LEN,
    get_key_from_env,
    load_schema,
    mask_record,
    mask_records,
    validate_schema,
)
from scripts.ingest import main as ingest_main
from scripts.validate_masking import (
    _TEST_KEY_CONSTANT,
    _strip_masking_artifacts,
    detection_fidelity,
    run_privacy_checks,
    scan_masked_file,
    scan_masked_records,
    shaped_identifier_hits,
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


def test_redaction_handles_parenthesised_phone():
    """Regression: a US-style parenthesised number (+1 (555) 123-4567) must be redacted,
    not leaked because the digit run breaks at the parenthesis."""
    schema = {"on_unknown": "drop", "fields": {"body": {"role": "redact"}}}
    out = mask_record({"body": "reach me on +1 (555) 123-4567 today"}, schema, KEY)["body"]
    assert "555" not in out and "4567" not in out
    assert "[PHONE_" in out


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


def test_keep_free_text_field_is_scanned_for_pii():
    """Regression: a kept free-text field that is NOT a declared identifier (e.g. notes) must be
    scanned for residual PII by run_privacy_checks - previously only redact/token/keep-identifier
    fields were scanned, so such fields were a blind spot that the --in file scan would catch."""
    schema = {
        "on_unknown": "drop",
        "fields": {
            "order_id": {"role": "token", "domain": "order"},
            "notes": {"role": "keep"},  # free-text, NOT a declared direct identifier
        },
    }
    records = [{"order_id": "O1", "notes": "call john.smith@bank.com about the trade"}]
    checks, _ = run_privacy_checks(records, schema, KEY)
    by_name = {name: ok for name, ok, _ in checks}
    assert by_name["no residual PII patterns (free-text-capable fields)"] is False, (
        "residual PII in a kept free-text field must be caught"
    )


def test_scan_masked_file_scans_nested_strings(tmp_path):
    """Regression: residual PII nested inside a list/dict value must be caught, not only
    top-level string fields."""
    f = tmp_path / "nested.jsonl"
    f.write_text('{"order_id":"order_9f","meta":{"note":"email john.smith@bank.com"}}\n')
    checks = scan_masked_file(f, SCHEMA)
    by_name = {name: ok for name, ok, _ in checks}
    assert by_name["no residual PII in masked file (string fields)"] is False


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


# ---------------------------------------------------------------------------
# S-6: the free-text redaction surrogate is as wide as a structured identifier
# ---------------------------------------------------------------------------


def test_redaction_surrogate_uses_the_full_token_width():
    """The redact surrogate carries TOKEN_LEN hex chars (96 bits), not the old 6 (24 bits)."""
    schema = {"on_unknown": "drop", "fields": {"body": {"role": "redact"}}}
    out = mask_record({"body": "email jo.bloggs@example.invalid"}, schema, KEY)["body"]
    m = re.fullmatch(r"email \[EMAIL_([0-9a-f]+)\]", out)
    assert m is not None, f"unexpected surrogate shape: {out!r}"
    assert len(m.group(1)) == TOKEN_LEN
    assert TOKEN_LEN == 24, "TOKEN_LEN is the shared width for tokens AND redact surrogates"


def test_redaction_surrogate_is_not_itself_re_redacted():
    """A wide hex surrogate can contain a long digit run; a later pattern pass must not
    rewrite the middle of it, which would break the referential integrity the width buys."""
    schema = {"on_unknown": "drop", "fields": {"body": {"role": "redact"}}}
    shape = re.compile(r"\[EMAIL_[0-9a-f]{%d}\]" % TOKEN_LEN)
    for i in range(60):
        # Synthetic, invented addresses - varied so the surrogate hex varies too.
        out = mask_record({"body": f"user{i:03d}@example.invalid"}, schema, KEY)["body"]
        assert shape.fullmatch(out), f"surrogate was re-redacted or reshaped: {out!r}"


def test_redaction_surrogates_do_not_trip_the_pii_scan():
    """Both directions: ingest's own surrogate is stripped before the scan, but a bare
    digit run that merely LOOKS like one is still reported."""
    surrogate = "[ACCT_1234567890abcdef12345678]"  # 24 hex chars, invented
    assert len(surrogate) == len("[ACCT_") + TOKEN_LEN + 1
    assert _strip_masking_artifacts(surrogate).strip() == ""
    # A genuine leak sitting next to a surrogate must survive the strip.
    assert "12345678901" in _strip_masking_artifacts(f"{surrogate} acct 12345678901")

    clean = scan_masked_records([{"body": surrogate}], SCHEMA)
    assert {n: ok for n, ok, _ in clean}["no residual PII in masked file (string fields)"] is True
    # The same hex WITHOUT the surrogate brackets is just a digit run, and is flagged.
    leaky = scan_masked_records([{"body": "1234567890abcdef12345678"}], SCHEMA)
    assert {n: ok for n, ok, _ in leaky}["no residual PII in masked file (string fields)"] is False


# ---------------------------------------------------------------------------
# S-7: explicit encodings on every file write
# ---------------------------------------------------------------------------


def _spy_on_write_text(monkeypatch):
    """Record the encoding= kwarg every Path.write_text call is made with."""
    seen: list[str | None] = []
    real = Path.write_text

    def spy(self, data, *args, **kwargs):
        seen.append(kwargs.get("encoding"))
        return real(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy)
    return seen


def test_gen_synthetic_cli_writes_utf8(tmp_path, monkeypatch):
    """gen_synthetic's --out write pins UTF-8 rather than inheriting a cp1252 locale."""
    out = tmp_path / "synth.jsonl"
    seen = _spy_on_write_text(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["gen_synthetic", "--kind", "benign", "--out", str(out)])
    gen_synthetic_main()
    assert seen == ["utf-8"]
    assert out.read_text(encoding="utf-8").strip()


def test_ingest_cli_round_trips_non_ascii_as_utf8(tmp_path, monkeypatch, capsys):
    """A non-ASCII kept value survives the write/read round trip byte-for-byte, which it
    would not if either end fell back to the platform default encoding."""
    schema = "on_unknown: drop\nfields:\n  order_id:\n    role: token\n  note:\n    role: keep\n"
    out = tmp_path / "masked.jsonl"
    seen = _spy_on_write_text(monkeypatch)
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        schema,
        [{"order_id": "O1", "note": "café ☕ naïve"}],
        extra_args=("--out", str(out)),
    )
    capsys.readouterr()
    assert code == 0
    # Every write on the path (fixture files and the masked output) pins the encoding.
    assert seen and set(seen) == {"utf-8"}
    assert json.loads(out.read_text(encoding="utf-8").strip())["note"] == "café ☕ naïve"


# ---------------------------------------------------------------------------
# S-9: identifier-SHAPED values are flagged whatever the field is called
# ---------------------------------------------------------------------------


def test_shaped_identifier_heuristic_flags_identifier_formats():
    """IBAN, card/account digit runs, email and phone are caught on shape alone - the
    field names here are deliberately uninformative."""
    records = [
        {
            "ref1": "GB29NWBK60161331926819",  # invented IBAN
            "ref2": "GB29 NWBK 6016 1331 9268 19",  # same, printed grouped
            "ref3": 4111111111111111,  # card-shaped, stored as a JSON number
            "ref4": "jo.bloggs@example.invalid",
            "ref5": "+44 7700 900123",  # Ofcom drama-reserved range
            "ref6": "555-0100-1234",  # reserved fictional range
        }
    ]
    hits = dict(shaped_identifier_hits(records))
    assert hits["ref1"] == "IBAN"
    assert hits["ref2"] == "IBAN"
    assert hits["ref3"] == "ACCOUNT_OR_CARD"
    assert hits["ref4"] == "EMAIL"
    assert hits["ref5"] == "PHONE"
    assert hits["ref6"] == "PHONE"


def test_shaped_identifier_heuristic_ignores_ordinary_numerics():
    """The other direction: prices, quantities, epoch timestamps at every unit, small ints,
    ISO dates and version strings must NOT be flagged, or the check is noise."""
    records = [
        {
            "price": 100.25,
            "notional": 1234567.89,
            "qty": 50,
            "big_qty": 10000000,  # 8 digits - a real block size, not an account number
            "seq": 7,
            "ts_s": 1726099200,
            "ts_ms": 1726099200000,
            "ts_us": 1726099200000000,
            "ts_ns": 1726099200000000000,
            "trade_date": "2026-09-12",
            "booked_at": "2026-09-12T10:15:30Z",
            "version": "1.2.3",
            "side": "BUY",
            "flagged": True,
            "missing": None,
        }
    ]
    assert shaped_identifier_hits(records) == []


def test_shaped_identifier_heuristic_covers_numeric_keep_fields():
    """The gap this closes: a `keep`-role numeric field is excluded from the free-text PII
    scan, so only the shape heuristic can catch a card number hiding in it."""
    schema = {
        "on_unknown": "drop",
        "fields": {
            "order_id": {"role": "token", "domain": "order"},
            "ref": {"role": "keep"},  # numeric, and the name gives nothing away
        },
    }
    records = [{"order_id": "O1", "ref": 4111111111111111}]
    checks, _ = run_privacy_checks(records, schema, KEY)
    by_name = {name: ok for name, ok, _ in checks}
    assert by_name["no residual PII patterns (free-text-capable fields)"] is True, (
        "the free-text scan skips numeric keep fields - that is the gap being covered"
    )
    assert by_name["no identifier-shaped values (format heuristic)"] is False


def test_shaped_identifier_heuristic_reports_names_not_values():
    """§5: a finding names the field and the format, never the value."""
    records = [{"ref": "GB29NWBK60161331926819"}]
    detail = {name: d for name, _, d in scan_masked_records(records, SCHEMA)}
    line = detail["no identifier-shaped values (format heuristic)"]
    assert "ref" in line and "IBAN" in line
    assert "GB29NWBK60161331926819" not in line


def test_shaped_identifier_heuristic_recurses_into_nested_values():
    """A nested list/dict value is not a blind spot."""
    records = [{"meta": {"refs": [4111111111111111]}}]
    assert shaped_identifier_hits(records) == [("meta", "ACCOUNT_OR_CARD")]


def test_scan_masked_file_still_passes_on_clean_numeric_output(tmp_path):
    """Regression guard: the new heuristic must not fail an ordinary masked file."""
    f = tmp_path / "clean.jsonl"
    f.write_text(
        '{"trader":"party_a1","order_id":"order_9f","ts_ms":1726099200000,'
        '"price":100.0,"qty":50}\n',
        encoding="utf-8",
    )
    by_name = {name: ok for name, ok, _ in scan_masked_file(f, SCHEMA)}
    assert by_name["no identifier-shaped values (format heuristic)"] is True


# ---------------------------------------------------------------------------
# S-19 / S-20: ingest validates its own output, and on_unknown: keep is loud
# ---------------------------------------------------------------------------

# A schema that keeps a free-text field, so the masked output still carries PII and the
# post-mask scan has something real to fail on.
_LEAKY_SCHEMA = "on_unknown: drop\nfields:\n  order_id:\n    role: token\n  note:\n    role: keep\n"
# A schema that passes undeclared fields through - the S-20 path. The shipped config uses
# the safe `drop` default, so this posture is only ever exercised here.
_UNKNOWN_KEEP_SCHEMA = "on_unknown: keep\nfields:\n  order_id:\n    role: token\n"


def _run_ingest(tmp_path, monkeypatch, schema_yaml, records, extra_args=()):
    """Drive ingest.main() exactly as the CLI does; return its exit code (0 if it fell through)."""
    monkeypatch.setenv("MASKING_KEY", "test-key-not-a-secret")
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(schema_yaml, encoding="utf-8")
    in_path = tmp_path / "in.jsonl"
    in_path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ingest", "--schema", str(schema_path), "--in", str(in_path), *extra_args],
    )
    try:
        ingest_main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_ingest_exits_0_and_validates_when_output_is_clean(tmp_path, monkeypatch, capsys):
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _LEAKY_SCHEMA,
        [{"order_id": "O1", "note": "worked the order all morning"}],
        extra_args=("--out", str(out)),
    )
    err = capsys.readouterr().err
    assert code == 0
    assert "FAIL" not in err
    assert out.exists()


def test_ingest_exits_2_when_its_own_output_fails_validation(tmp_path, monkeypatch, capsys):
    """S-19: validation runs by default, and a failure is loud and non-zero."""
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _LEAKY_SCHEMA,
        [{"order_id": "O1", "note": "ring jo.bloggs@example.invalid about it"}],
        extra_args=("--out", str(out)),
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "post-mask validation" in err
    assert "no residual PII in masked file (string fields)" in err


def test_ingest_no_validate_skips_the_scan(tmp_path, monkeypatch, capsys):
    """S-19: --no-validate is the opt-out, and it really does skip the check."""
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _LEAKY_SCHEMA,
        [{"order_id": "O1", "note": "ring jo.bloggs@example.invalid about it"}],
        extra_args=("--out", str(out), "--no-validate"),
    )
    err = capsys.readouterr().err
    assert code == 0
    assert "post-mask validation" not in err


def test_ingest_writes_to_stdout_when_out_is_absent(tmp_path, monkeypatch, capsys):
    """S-19: validation still runs when there is no output FILE to read back."""
    code = _run_ingest(
        tmp_path, monkeypatch, _LEAKY_SCHEMA, [{"order_id": "O1", "note": "all good"}]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out.strip())["note"] == "all good"
    # Progress chatter must not pollute the JSONL on stdout.
    assert "Masked 1 records -> stdout" in captured.err


def test_ingest_validates_stdout_output_too(tmp_path, monkeypatch, capsys):
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _LEAKY_SCHEMA,
        [{"order_id": "O1", "note": "ring jo.bloggs@example.invalid"}],
        extra_args=("--out", "-"),
    )
    assert code == 2
    assert "post-mask validation" in capsys.readouterr().err


def test_unknown_keep_names_the_fields_and_exits_1(tmp_path, monkeypatch, capsys):
    """S-20: on_unknown: keep is loud - it lists what it let through and exits non-zero."""
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _UNKNOWN_KEEP_SCHEMA,
        [{"order_id": "O1", "desk_memo": "fine", "legacy_col": "fine"}],
        extra_args=("--out", str(out)),
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "passed UNDECLARED fields through UNMASKED" in err
    assert "desk_memo" in err and "legacy_col" in err


def test_allow_unknown_keep_still_warns_but_exits_0(tmp_path, monkeypatch, capsys):
    """S-20: the flag records a decision; it does not buy silence."""
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _UNKNOWN_KEEP_SCHEMA,
        [{"order_id": "O1", "desk_memo": "fine"}],
        extra_args=("--out", str(out), "--allow-unknown-keep"),
    )
    err = capsys.readouterr().err
    assert code == 0
    assert "desk_memo" in err


def test_unknown_keep_is_silent_when_nothing_is_actually_unknown(tmp_path, monkeypatch, capsys):
    """The warning tracks what was PASSED THROUGH, not merely what the schema permits."""
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _UNKNOWN_KEEP_SCHEMA,
        [{"order_id": "O1"}],
        extra_args=("--out", str(out)),
    )
    err = capsys.readouterr().err
    assert code == 0
    assert "passed UNDECLARED fields through UNMASKED" not in err


def test_validation_failure_and_unknown_keep_do_not_mask_each_other(tmp_path, monkeypatch, capsys):
    """Interaction: both conditions are REPORTED, and the higher exit code wins."""
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        _UNKNOWN_KEEP_SCHEMA,
        [{"order_id": "O1", "desk_memo": "ring jo.bloggs@example.invalid"}],
        extra_args=("--out", str(out)),
    )
    err = capsys.readouterr().err
    assert code == 2, "a validation failure outranks the unknown-field finding"
    assert "desk_memo" in err, "the unknown-field warning must still be visible"
    assert "post-mask validation" in err


def test_validate_schema_warns_when_on_unknown_is_keep(capsys):
    """S-20: the posture is flagged on the CONFIG, before any data is read."""
    validate_schema({"on_unknown": "keep", "fields": {"order_id": {"role": "token"}}})
    assert "on_unknown: keep" in capsys.readouterr().err


def test_validate_schema_is_silent_on_the_safe_default(capsys):
    validate_schema({"on_unknown": "drop", "fields": {"order_id": {"role": "token"}}})
    assert capsys.readouterr().err == ""


def test_structured_tokens_do_not_trip_the_pii_scan():
    """Both directions for the token strip: a 24-hex token carries long digit runs often
    enough that PHONE/ACCT would report the masker's own output as residual PII."""
    token = "party_714708994abcdef012345678"  # invented, 24 hex chars after the prefix
    assert len(token.split("_", 1)[1]) == TOKEN_LEN
    assert _strip_masking_artifacts(token).strip() == ""

    clean = scan_masked_records([{"trader": token}], SCHEMA)
    assert {n: ok for n, ok, _ in clean}["no residual PII in masked file (string fields)"] is True
    # The strip is narrow: the same hex WITHOUT a token prefix is a bare digit run, and fires.
    leaky = scan_masked_records([{"trader": "714708994abcdef012345678"}], SCHEMA)
    assert {n: ok for n, ok, _ in leaky}["no residual PII in masked file (string fields)"] is False


def test_ingest_passes_its_own_validation_on_the_shipped_schema(tmp_path, monkeypatch, capsys):
    """End-to-end regression for S-19: the default config on synthetic order flow must
    exit 0. This failed on the first real run - the tokens tripped the digit-run patterns."""
    out = tmp_path / "masked.jsonl"
    code = _run_ingest(
        tmp_path,
        monkeypatch,
        Path("config/masking-schema.yaml").read_text(encoding="utf-8"),
        _records(),
        extra_args=("--out", str(out)),
    )
    err = capsys.readouterr().err
    assert code == 0, f"the shipped schema must validate its own output cleanly: {err}"
