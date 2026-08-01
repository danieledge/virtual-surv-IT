"""
Tests for the RTM traceability validator (scripts/validate_rtm.py).

`docs/templates/rtm.md` has always specified a bidirectional-coverage check - orphan tests,
requirements with no obligation, orphan obligations - and the BRD → FSD → code → test →
obligation spine is what makes a surveillance solution auditable. These tests hold the
validator to that spec: every Code/Test cell resolves on disk, every requirement carries an
obligation or a justified gap, the register's obligations are traced back, and the noisy
sweeps stay opt-in. A missing RTM is never a finding.
"""

from __future__ import annotations

import json

from scripts.validate_rtm import (
    find_rtm,
    format_findings,
    main as rtm_main,
    parse_register,
    parse_rtm,
    validate,
)

_HEADER = (
    "| BRD | FSD | Design / ADR | Code (module / fn) | Test | Regulatory obligation "
    "| Status | Gap / exception disposition |\n"
    "|-----|-----|--------------|--------------------|------|------------------------"
    "|--------|-----------------------------|\n"
)

_REGISTER = """\
# a minimal register in the shipped schema
obligations:
  - id: MAR-ART12-1A
    regime: EU MAR
    typology: spoofing, layering
    pinpoint: MAR Art.12(1)(a)
    aliases: ["Article 12(1)(a)", "Art.12(1)(a)"]
    verified_on: "2026-06-29"
    status: verified
"""

# A second in-scope obligation, so a matrix that covers only the first has a real orphan.
_REGISTER_TWO = (
    _REGISTER
    + """
  - id: MAR-ART16
    regime: EU MAR
    typology: surveillance coverage
    pinpoint: MAR Art.16
    aliases: ["Article 16"]
    verified_on: "2026-06-29"
    status: verified
"""
)


def _row(
    brd="BRD-001",
    code="`rules/spoofing.py::detect_spoofing`",
    test="`test_spoofing.py::test_known_spoof_is_flagged`",
    obligation="MAR Art.12(1)(a)",
    status="done",
    disposition="-",
):
    return (
        f"| {brd} | FSD-001 | ADR-001 | {code} | {test} | {obligation} | {status} "
        f"| {disposition} |\n"
    )


def _project(tmp_path, register=_REGISTER):
    """A working project with the code, test and register the example row cites."""
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "spoofing.py").write_text("def detect_spoofing():\n    ...\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_spoofing.py").write_text(
        "def test_known_spoof_is_flagged():\n    ...\n"
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "regulatory-register.yaml").write_text(register, encoding="utf-8")
    pack = tmp_path / "artifacts" / "spoofing"
    pack.mkdir(parents=True)
    return pack


def _rtm(pack, *rows, name="rtm.md", header=_HEADER):
    path = pack / name
    path.write_text("# Requirements Traceability Matrix\n\n" + header + "".join(rows), "utf-8")
    return path


def _validate(rtm, root, **kwargs):
    """validate() against the project's OWN register - test isolation from the bundled one
    (the two-tier merge is exercised by its own test below)."""
    kwargs.setdefault("register_path", root / "config" / "regulatory-register.yaml")
    return validate(rtm, project_root=root, **kwargs)


def _codes(result):
    return [f["code"] for f in result["findings"]]


# --------------------------------------------------------------- the clean case


def test_clean_rtm_has_no_findings(tmp_path):
    pack = _project(tmp_path, register=_REGISTER_TWO)
    rtm = _rtm(pack, _row(), _row(brd="BRD-002", obligation="MAR Art.16"))
    result = _validate(rtm, tmp_path)
    assert result["findings"] == [], format_findings(result["findings"])
    assert result["rows"] == 2


def test_document_control_and_signoff_tables_are_ignored(tmp_path):
    """Only the table whose header carries Code/Test/obligation is read - the template's
    document-control and sign-off tables must not be parsed as requirement rows."""
    pack = _project(tmp_path)
    body = (
        "> | Version | Date | Author | Change |\n> |---|---|---|---|\n"
        "> | 0.1 | 2026-08-01 | a | draft |\n\n"
        + _HEADER
        + _row()
        + "\n## Sign-off\n\n| Role | Name | Decision | Date |\n|---|---|---|---|"
        "\n| Author | | | |\n"
    )
    rtm = pack / "rtm.md"
    rtm.write_text("# RTM\n\n" + body, encoding="utf-8")
    result = _validate(rtm, tmp_path)
    assert result["rows"] == 1
    assert _codes(result) == []


# --------------------------------------------------------------- unresolved paths


def test_missing_code_path_is_flagged(tmp_path):
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(code="`rules/renamed.py::detect_spoofing`"))
    result = _validate(rtm, tmp_path)
    assert _codes(result) == ["RTM-CODE-MISSING"]
    assert "rules/renamed.py" in result["findings"][0]["detail"]
    assert result["findings"][0]["row"] == "BRD-001 / FSD-001"


def test_missing_test_file_is_flagged(tmp_path):
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(test="`tests/test_gone.py::test_x`"))
    result = _validate(rtm, tmp_path)
    assert _codes(result) == ["RTM-TEST-MISSING"]
    assert "tests/test_gone.py" in result["findings"][0]["detail"]


def test_code_delivered_beside_the_rtm_resolves(tmp_path):
    """Code shipped inside the engagement pack resolves against the RTM's own directory,
    not only the project root."""
    pack = _project(tmp_path)
    (pack / "dedupe.py").write_text("x = 1\n")
    rtm = _rtm(pack, _row(code="`dedupe.py::run`"))
    assert _codes(_validate(rtm, tmp_path)) == []


def test_dotted_module_path_resolves(tmp_path):
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(code="`rules.spoofing::detect_spoofing`"))
    assert _codes(_validate(rtm, tmp_path)) == []


def test_multiple_refs_in_one_cell_are_each_resolved(tmp_path):
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(code="`rules/spoofing.py`, `rules/absent.py`"))
    result = _validate(rtm, tmp_path)
    assert _codes(result) == ["RTM-CODE-MISSING"]
    assert "rules/absent.py" in result["findings"][0]["detail"]


def test_placeholder_cells_are_gaps_not_broken_paths(tmp_path):
    """The template writes an open gap as `-` and tracks it in the disposition column - a
    placeholder must never be reported as a path that does not exist."""
    pack = _project(tmp_path)
    rtm = _rtm(
        pack,
        _row(code="-", test="N/A", obligation="MAR Art.12(1)(a)", disposition="Gap owner: BA"),
    )
    assert _codes(_validate(rtm, tmp_path)) == []


def test_non_file_shaped_cells_are_left_alone(tmp_path):
    """Prose in a Code cell ('manual control') is a wording question for the reviewer, not a
    missing file - the check exists to catch stale paths."""
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(code="manual control - no code", test="`test_spoofing.py`"))
    assert _codes(_validate(rtm, tmp_path)) == []


# --------------------------------------------------------------- obligations


def test_requirement_without_obligation_is_flagged(tmp_path):
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(obligation="-", disposition="-"))
    result = _validate(rtm, tmp_path)
    assert "RTM-NO-OBLIGATION" in _codes(result)
    assert result["findings"][0]["row"] == "BRD-001 / FSD-001"


def test_requirement_without_obligation_but_with_disposition_is_justified(tmp_path):
    """'must be justified or removed' - an owner and target-close date in the disposition
    column IS the template's sanctioned justification."""
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(obligation="-", disposition="Gap owner: BA · Target close: 2026-09-01"))
    assert "RTM-NO-OBLIGATION" not in _codes(_validate(rtm, tmp_path))


def test_orphan_obligation_is_flagged(tmp_path):
    pack = _project(tmp_path, register=_REGISTER_TWO)
    rtm = _rtm(pack, _row())  # cites MAR Art.12(1)(a) only; the register also holds Art.16
    result = _validate(rtm, tmp_path)
    assert _codes(result) == ["RTM-ORPHAN-OBLIGATION"]
    assert "MAR-ART16" in result["findings"][0]["detail"]


def test_register_is_bundled_plus_project_overlay(tmp_path):
    """With no explicit --register, the scope is the BUNDLED register extended by the working
    project's overlay (the two-tier pattern check_citations uses) - so an obligation the repo
    ships and the RTM never cites is reported."""
    pack = _project(tmp_path, register=_REGISTER_TWO)
    rtm = _rtm(pack, _row())
    details = " ".join(f["detail"] for f in validate(rtm, project_root=tmp_path)["findings"])
    assert "MAR-ART16" in details  # from the project overlay
    assert "MAR-ART15" in details  # from the bundled register


def test_obligation_cited_by_alias_is_not_orphaned(tmp_path):
    pack = _project(tmp_path, register=_REGISTER_TWO)
    rtm = _rtm(pack, _row(obligation="Article 12(1)(a)"), _row(brd="BRD-002", obligation="Art.16"))
    result = validate(
        rtm, project_root=tmp_path, register_path=tmp_path / "config" / "regulatory-register.yaml"
    )
    assert _codes(result) == []


def test_obligation_cited_by_register_id_is_not_orphaned(tmp_path):
    pack = _project(tmp_path, register=_REGISTER_TWO)
    rtm = _rtm(pack, _row(obligation="MAR-ART12-1A"), _row(brd="BRD-002", obligation="MAR-ART16"))
    result = validate(
        rtm, project_root=tmp_path, register_path=tmp_path / "config" / "regulatory-register.yaml"
    )
    assert _codes(result) == []


# --------------------------------------------------------------- orphan tests (opt-in)


def test_orphan_tests_are_not_reported_by_default(tmp_path):
    pack = _project(tmp_path)
    (tmp_path / "tests" / "test_unrelated.py").write_text("def test_x():\n    ...\n")
    rtm = _rtm(pack, _row())
    assert "RTM-ORPHAN-TEST" not in _codes(_validate(rtm, tmp_path))


def test_orphan_tests_reported_when_opted_in(tmp_path):
    pack = _project(tmp_path)
    (tmp_path / "tests" / "test_unrelated.py").write_text("def test_x():\n    ...\n")
    rtm = _rtm(pack, _row())
    result = validate(
        rtm,
        project_root=tmp_path,
        tests_dirs=[tmp_path / "tests"],
        register_path=tmp_path / "config" / "regulatory-register.yaml",
        check_orphan_tests=True,
    )
    orphans = [f for f in result["findings"] if f["code"] == "RTM-ORPHAN-TEST"]
    assert [f["detail"].split()[0] for f in orphans] == ["test_unrelated.py"]


# --------------------------------------------------------------- malformed / missing


def test_no_table_is_malformed(tmp_path):
    pack = _project(tmp_path)
    rtm = pack / "rtm.md"
    rtm.write_text("# RTM\n\nWe will add the matrix later.\n", encoding="utf-8")
    result = _validate(rtm, tmp_path)
    assert _codes(result)[0] == "RTM-MALFORMED"
    assert result["rows"] == 0


def test_table_without_the_required_columns_is_malformed(tmp_path):
    pack = _project(tmp_path)
    rtm = pack / "rtm.md"
    rtm.write_text("# RTM\n\n| BRD | Owner |\n|---|---|\n| BRD-001 | Amara |\n", encoding="utf-8")
    assert _codes(_validate(rtm, tmp_path))[0] == "RTM-MALFORMED"


def test_ragged_row_is_malformed(tmp_path):
    """A row with fewer cells than the header shifts every value into the wrong column - the
    failure mode that makes a matrix quietly lie."""
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(), "| BRD-002 | FSD-002 | - | - |\n")
    result = _validate(rtm, tmp_path)
    assert [c for c in _codes(result) if c == "RTM-MALFORMED"] == ["RTM-MALFORMED"]
    assert result["rows"] == 1


def test_missing_rtm_is_not_a_finding(tmp_path, capsys):
    """Absence is the normal case - most engagements never author an RTM."""
    pack = _project(tmp_path)
    assert find_rtm(pack) is None
    assert rtm_main(["--project-root", str(pack)]) == 0
    assert "No RTM found" in capsys.readouterr().out


def test_find_rtm_picks_up_numbered_variants(tmp_path):
    pack = _project(tmp_path)
    _rtm(pack, _row(), name="rtm-001.md")
    assert find_rtm(pack).name == "rtm-001.md"


# --------------------------------------------------------------- parsing helpers & CLI


def test_parse_rtm_keys_rows_by_header_column():
    rows, problems = parse_rtm(_HEADER + _row())
    assert problems == []
    assert rows[0]["cells"]["test"].startswith("`test_spoofing.py")
    assert rows[0]["label"] == "BRD-001 / FSD-001"


def test_parse_register_reads_ids_pinpoints_and_aliases():
    obligations = parse_register(_REGISTER_TWO)
    assert [o["id"] for o in obligations] == ["MAR-ART12-1A", "MAR-ART16"]
    assert obligations[0]["pinpoint"] == "MAR Art.12(1)(a)"
    assert obligations[0]["aliases"] == ["Article 12(1)(a)", "Art.12(1)(a)"]


def test_cli_reports_findings_and_exits_one(tmp_path, capsys):
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(code="`rules/gone.py`"))
    code = rtm_main(
        [
            str(rtm),
            "--project-root",
            str(tmp_path),
            "--register",
            str(tmp_path / "config" / "regulatory-register.yaml"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "RTM-CODE-MISSING: row BRD-001 / FSD-001 cites 'rules/gone.py'" in out
    assert "NOT satisfied" in out


def test_cli_clean_run_exits_zero(tmp_path, capsys):
    pack = _project(tmp_path)
    _rtm(pack, _row(), _row(brd="BRD-002", obligation="MAR Art.16"))
    code = rtm_main(
        [
            "--project-root",
            str(tmp_path),
            str(pack / "rtm.md"),
            "--register",
            str(tmp_path / "config" / "regulatory-register.yaml"),
        ]
    )
    assert code == 0
    assert "RTM traceability: OK" in capsys.readouterr().out


def test_cli_json_output(tmp_path, capsys):
    pack = _project(tmp_path)
    rtm = _rtm(pack, _row(test="`test_gone.py`"))
    code = rtm_main([str(rtm), "--project-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["rows"] == 1
    assert "RTM-TEST-MISSING" in [f["code"] for f in payload["findings"]]


def test_cli_explicit_missing_path_is_an_error(tmp_path, capsys):
    assert rtm_main([str(tmp_path / "nope.md")]) == 1
    assert "RTM-NOT-FOUND" in capsys.readouterr().err
