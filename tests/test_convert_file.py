"""
Tests for scripts/convert_file.py - the file-conversion front door.

Each test targets a real, named failure mode from the field: long IDs mangled by float
typing, date serials, encoding surprises, delimiter mis-sniffs, ragged/truncated extracts,
and the schema/reconciliation gates that must FAIL LOUDLY rather than pass corrupt data
downstream. Fixtures are built in-test (synthetic data only, CLAUDE.md §5).
"""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from pathlib import Path

from scripts import convert_file as cf

# Importing scripts.convert_file puts vendor/ on sys.path, so the vendored openpyxl
# (reader AND writer) is available to build fixtures with.
import openpyxl  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders (all synthetic).
# ---------------------------------------------------------------------------
def make_xlsx(path: Path, rows: list[list], extra_sheets: dict | None = None) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    for row in rows:
        ws.append(row)
    for name, srows in (extra_sheets or {}).items():
        ws2 = wb.create_sheet(name)
        for row in srows:
            ws2.append(row)
    wb.save(path)


def make_docx(path: Path, paragraphs: list[str], table: list[list[str]] | None = None) -> None:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body: list[str] = [f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs]
    if table:
        trs = "".join(
            "<w:tr>"
            + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
            + "</w:tr>"
            for row in table
        )
        body.append(f"<w:tbl>{trs}</w:tbl>")
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{w}"><w:body>{"".join(body)}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def make_pdf(path: Path, text: str | None) -> None:
    """Minimal single-page PDF; text=None makes a page with no extractable text."""
    stream = b"" if text is None else f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    path.write_bytes(bytes(out))


def run(*argv: str) -> int:
    return cf.main(list(argv))


def read_report(out: Path) -> dict:
    return json.loads((out.parent / (out.name + ".report.json")).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Lossless rendering (no schema): the "nothing is guessed" contract.
# ---------------------------------------------------------------------------
def test_xlsx_lossless_values(tmp_path):
    src = tmp_path / "trades.xlsx"
    make_xlsx(
        src,
        [
            ["trade_id", "account_id", "trade_date", "quantity", "price", "is_cancel"],
            ["TR00000001", "0012345678", dt.date(2026, 3, 4), 100, 1.5, True],
        ],
    )
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    # Leading zeros survive (text cell), dates are ISO, ints have no ".0", bools lowercase.
    assert lines[1] == "TR00000001,0012345678,2026-03-04,100,1.5,true"


def test_render_cell_determinism():
    assert cf.render_cell(None) == ("", "")
    assert cf.render_cell(True) == ("true", "b")
    assert cf.render_cell(100) == ("100", "n")
    assert cf.render_cell(100.0) == ("100", "n")  # never "100.0"
    assert cf.render_cell(dt.datetime(2026, 3, 4)) == ("2026-03-04", "d")  # midnight -> date
    assert cf.render_cell(dt.datetime(2026, 3, 4, 9, 30, 1)) == ("2026-03-04 09:30:01", "d")


def test_xlsx_multisheet_warns_and_sheet_flag(tmp_path):
    src = tmp_path / "book.xlsx"
    make_xlsx(src, [["a"], ["1"]], extra_sheets={"Second": [["b"], ["2"]]})
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    assert any("2 sheets" in w for w in read_report(out)["warnings"])
    assert run(str(src), "--sheet", "Second", "--out", str(out)) == 0
    assert out.read_text(encoding="utf-8").splitlines() == ["b", "2"]


def test_xlsx_trailing_empty_rows_trimmed(tmp_path):
    src = tmp_path / "pad.xlsx"
    make_xlsx(src, [["a", "b"], ["1", "2"], [None, None], [None, None]])
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    report = read_report(out)
    assert report["trailing_empty_rows_trimmed"] == 2
    assert report["rows_output"] == 1


# ---------------------------------------------------------------------------
# Schema gates: violations are failures, not warnings.
# ---------------------------------------------------------------------------
SCHEMA = {
    "feed": "test",
    "columns": [
        {"name": "account_id", "type": "string", "required": True, "pattern": "^[0-9]{10}$"},
        {"name": "trade_date", "type": "date"},
        {"name": "quantity", "type": "integer"},
    ],
    "expect": {"min_rows": 1, "control_totals": {"quantity": 300}},
}


def write_schema(tmp_path: Path, schema: dict) -> Path:
    p = tmp_path / "feed.json"  # JSON: stdlib-only, works without PyYAML
    p.write_text(json.dumps(schema), encoding="utf-8")
    return p


def good_csv(tmp_path: Path) -> Path:
    src = tmp_path / "feed.csv"
    src.write_text(
        "account_id,trade_date,quantity\n0000000001,2026-01-02,100\n0000000002,2026-01-03,200\n",
        encoding="utf-8",
    )
    return src


def test_schema_pass_with_control_total(tmp_path):
    out = tmp_path / "out.csv"
    code = run(
        str(good_csv(tmp_path)), "--schema", str(write_schema(tmp_path, SCHEMA)), "--out", str(out)
    )
    assert code == 0
    checks = read_report(out)["checks"]
    assert checks["control_total:quantity"]["passed"] is True


def test_schema_control_total_mismatch_fails(tmp_path):
    schema = json.loads(json.dumps(SCHEMA))
    schema["expect"]["control_totals"]["quantity"] = 999
    out = tmp_path / "out.csv"
    code = run(
        str(good_csv(tmp_path)), "--schema", str(write_schema(tmp_path, schema)), "--out", str(out)
    )
    assert code == 1


def test_schema_row_count_mismatch_fails(tmp_path):
    schema = json.loads(json.dumps(SCHEMA))
    schema["expect"] = {"row_count": 5}
    code = run(
        str(good_csv(tmp_path)),
        "--schema",
        str(write_schema(tmp_path, schema)),
        "--out",
        str(tmp_path / "out.csv"),
    )
    assert code == 1


def test_schema_header_mismatch_fails(tmp_path):
    src = tmp_path / "renamed.csv"
    src.write_text("acct,trade_date,quantity\n0000000001,2026-01-02,100\n", encoding="utf-8")
    code = run(
        str(src),
        "--schema",
        str(write_schema(tmp_path, SCHEMA)),
        "--out",
        str(tmp_path / "out.csv"),
    )
    assert code == 1


def test_schema_pattern_violation_fails(tmp_path):
    src = tmp_path / "badid.csv"
    src.write_text("account_id,trade_date,quantity\n12345,2026-01-02,100\n", encoding="utf-8")
    code = run(
        str(src),
        "--schema",
        str(write_schema(tmp_path, SCHEMA)),
        "--out",
        str(tmp_path / "out.csv"),
    )
    assert code == 1


def test_schema_warns_when_string_column_stored_numeric(tmp_path):
    # The classic: account IDs entered as NUMBERS in Excel. The damage (leading zeros,
    # >15-digit rounding) happened at source - the converter must surface it.
    src = tmp_path / "numeric_ids.xlsx"
    make_xlsx(
        src,
        [["account_id", "trade_date", "quantity"], [12345678, dt.date(2026, 1, 2), 300]],
    )
    schema = {
        "columns": [
            {"name": "account_id", "type": "string"},
            {"name": "trade_date", "type": "date"},
            {"name": "quantity", "type": "integer"},
        ]
    }
    out = tmp_path / "out.csv"
    assert run(str(src), "--schema", str(write_schema(tmp_path, schema)), "--out", str(out)) == 0
    assert any("stored as NUMBER" in w for w in read_report(out)["warnings"])


def test_schema_date_format_override(tmp_path):
    src = tmp_path / "ukdates.csv"
    src.write_text("d\n04/03/2026\n", encoding="utf-8")
    schema = {"columns": [{"name": "d", "type": "date", "format": "%d/%m/%Y"}]}
    out = tmp_path / "out.csv"
    assert run(str(src), "--schema", str(write_schema(tmp_path, schema)), "--out", str(out)) == 0
    assert out.read_text(encoding="utf-8").splitlines()[1] == "2026-03-04"


def test_schema_ambiguous_date_rejected_without_format(tmp_path):
    src = tmp_path / "ukdates.csv"
    src.write_text("d\n04/03/2026\n", encoding="utf-8")
    schema = {"columns": [{"name": "d", "type": "date"}]}
    code = run(
        str(src),
        "--schema",
        str(write_schema(tmp_path, schema)),
        "--out",
        str(tmp_path / "out.csv"),
    )
    assert code == 1  # no format guessing, ever


# ---------------------------------------------------------------------------
# CSV defences: encoding, delimiter, ragged rows, truncation.
# ---------------------------------------------------------------------------
def test_csv_utf8_bom_stripped(tmp_path):
    src = tmp_path / "bom.csv"
    src.write_bytes(b"\xef\xbb\xbfa,b\n1,2\n")
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    assert out.read_text(encoding="utf-8").splitlines()[0] == "a,b"  # no BOM residue
    assert "BOM" in read_report(out)["encoding"]


def test_csv_cp1252_fallback_is_recorded(tmp_path):
    src = tmp_path / "legacy.csv"
    src.write_bytes(b"name\ncaf\xe9\n")  # 0xE9 = e-acute in cp1252; invalid UTF-8
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    report = read_report(out)
    assert "cp1252" in report["encoding"]
    assert any("not valid UTF-8" in w for w in report["warnings"])
    assert "café" in out.read_text(encoding="utf-8")


def test_csv_utf16_bom(tmp_path):
    src = tmp_path / "utf16.csv"
    src.write_bytes("a,b\n1,2\n".encode("utf-16"))
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    assert out.read_text(encoding="utf-8").splitlines() == ["a,b", "1,2"]


def test_csv_semicolon_sniffed(tmp_path):
    src = tmp_path / "semi.csv"
    src.write_text("a;b;c\n1;2;3\n4;5;6\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    assert "';'" in read_report(out)["delimiter"]
    assert out.read_text(encoding="utf-8").splitlines()[1] == "1,2,3"


def test_csv_ragged_rows_fail(tmp_path):
    src = tmp_path / "ragged.csv"
    src.write_text("a,b,c\n1,2,3\n4,5\n", encoding="utf-8")
    assert run(str(src), "--out", str(tmp_path / "out.csv")) == 1


def test_csv_missing_final_newline_warns_truncation(tmp_path):
    src = tmp_path / "cut.csv"
    src.write_text("a,b\n1,2\n3,4", encoding="utf-8")  # no trailing newline
    out = tmp_path / "out.csv"
    assert run(str(src), "--out", str(out)) == 0
    assert any("TRUNCATED" in w for w in read_report(out)["warnings"])


def test_jsonl_output(tmp_path):
    src = tmp_path / "j.csv"
    src.write_text("a,b\n1,x\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    assert run(str(src), "--to", "jsonl", "--out", str(out)) == 0
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0]) == {"a": "1", "b": "x"}


# ---------------------------------------------------------------------------
# Documents: docx and pdf.
# ---------------------------------------------------------------------------
def test_docx_paragraphs_and_table_to_md(tmp_path):
    src = tmp_path / "spec.docx"
    make_docx(src, ["Intro para"], table=[["h1", "h2"], ["v1", "v2"]])
    out = tmp_path / "out.md"
    assert run(str(src), "--out", str(out)) == 0
    text = out.read_text(encoding="utf-8")
    assert "Intro para" in text
    assert "| h1 | h2 |" in text


def test_docx_table_to_csv(tmp_path):
    src = tmp_path / "spec.docx"
    make_docx(src, ["ignored"], table=[["a", "b"], ["1", "2"]])
    out = tmp_path / "out.csv"
    assert run(str(src), "--to", "csv", "--table", "1", "--out", str(out)) == 0
    assert out.read_text(encoding="utf-8").splitlines() == ["a,b", "1,2"]


def test_docx_no_table_to_csv_fails(tmp_path):
    src = tmp_path / "prose.docx"
    make_docx(src, ["just text"])
    assert run(str(src), "--to", "csv", "--out", str(tmp_path / "out.csv")) == 1


def test_pdf_text_extracted(tmp_path):
    src = tmp_path / "doc.pdf"
    make_pdf(src, "Hello Surveillance")
    out = tmp_path / "out.md"
    assert run(str(src), "--out", str(out)) == 0
    assert "Hello Surveillance" in out.read_text(encoding="utf-8")
    # The tables-are-unreliable caveat must always be on the record for PDFs.
    assert any("TEXT only" in w for w in read_report(out)["warnings"])


def test_pdf_scanned_page_flagged_as_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cf, "_pdftotext_pages", lambda _src: None)  # poppler absent/failed
    src = tmp_path / "scan.pdf"
    make_pdf(src, None)
    out = tmp_path / "out.txt"
    assert run(str(src), "--to", "txt", "--out", str(out)) == 0
    assert any("NO extractable text" in w for w in read_report(out)["warnings"])
    assert read_report(out)["pdf_engine"] == "pypdf"


def test_pdf_poppler_fallback_recovers_unreadable_page(tmp_path, monkeypatch):
    """A page pypdf can't read is recovered via pdftotext when poppler is present."""
    monkeypatch.setattr(cf, "_pdftotext_pages", lambda _src: ["Recovered via poppler"])
    src = tmp_path / "scan.pdf"
    make_pdf(src, None)
    out = tmp_path / "out.txt"
    assert run(str(src), "--to", "txt", "--out", str(out)) == 0
    assert "Recovered via poppler" in out.read_text(encoding="utf-8")
    rep = read_report(out)
    assert rep["pdf_engine"] == "pypdf+pdftotext"
    assert any("recovered via pdftotext" in w for w in rep["warnings"])
    # Recovery means the page is no longer reported as MISSING.
    assert not any("NO extractable text" in w for w in rep["warnings"])


# ---------------------------------------------------------------------------
# Safety and evidence.
# ---------------------------------------------------------------------------
def test_refuses_raw_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    rawdir = tmp_path / "data" / "raw"
    rawdir.mkdir(parents=True)
    src = rawdir / "real.csv"
    src.write_text("a\n1\n", encoding="utf-8")
    assert run(str(src), "--out", str(tmp_path / "out.csv")) == 1


def test_report_written_even_on_failure(tmp_path):
    src = tmp_path / "ragged.csv"
    src.write_text("a,b\n1\n", encoding="utf-8")
    assert run(str(src), "--out", str(tmp_path / "out.csv")) == 1
    report = json.loads((tmp_path / "ragged.csv.report.json").read_text(encoding="utf-8"))
    assert report["errors"]
    assert report["source_sha256"]


def test_unsupported_format_fails_clearly(tmp_path):
    src = tmp_path / "book.xlsb"
    src.write_bytes(b"not really")
    assert run(str(src), "--out", str(tmp_path / "out.csv")) == 1
