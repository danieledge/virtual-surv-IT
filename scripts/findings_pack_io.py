"""JSONL read/write for review findings packs (2026-08-07 format migration).

A findings pack used to be one JSON object (`{...envelope fields..., "findings": [...]}`) in a
single `findings-<slug>.json` file. That format made incremental writes fragile: a JSON array
must stay syntactically whole (matched brackets/commas) at every step, so appending more
findings after an initial Write meant carefully patching the existing file rather than safely
adding to it. It also meant the entire pack - however large - had to be generated as one
continuous blob to be valid at all, which is what tripped a corporate proxy's request timeout
on a live run (2026-08-05, cited in `guard-findings-pack-write.py`; traced again as the likely
cause of a live-reported ~3-hour deep review, 2026-08-07).

The fix is JSONL: `findings-<slug>.jsonl`, line 1 the "envelope" (every pack field except
`findings`), each following line one finding. Every line is independently valid JSON, so
appending more findings is a genuine append - never touching what's already on disk, no
bracket/comma bookkeeping. This module is the one place that knows the on-disk shape;
`render_findings.py`, `validate_findings.py`, `check_artifacts.py`, `convert_sarif.py` and the
findings-pack write guard all import it rather than re-implementing the parse, so they can
never disagree on what a pack file means.

Import-only - no CLI, no `__main__` - so it never needs its own guard-allowlist entry (same
precedent as `scripts/map_fingerprint.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

PACK_SUFFIX = ".jsonl"


def read_pack(path: Path) -> dict:
    """Parse a `.jsonl` findings pack into the same in-memory shape the old single-JSON-object
    format produced: `{**envelope, "findings": [...]}`. Line 1 is the envelope (every pack
    field except `findings`); every following non-blank line is one finding object, appended
    to `findings` in file order. A blank line (e.g. a trailing newline) is skipped, never
    treated as a malformed finding."""
    lines = path.read_text(encoding="utf-8").splitlines()
    non_blank = [ln for ln in lines if ln.strip()]
    if not non_blank:
        raise ValueError(f"{path}: empty pack - no envelope line")
    pack = json.loads(non_blank[0])
    if not isinstance(pack, dict):
        raise ValueError(f"{path}:1: envelope line is not a JSON object")
    findings = [json.loads(ln) for ln in non_blank[1:]]
    pack["findings"] = findings
    return pack


def envelope_line(pack: dict) -> str:
    """The envelope line for `pack` - every top-level field except `findings`, one line of
    JSON. `ensure_ascii=False` keeps 📊/🧠 tags and other non-ASCII content readable in the
    raw file rather than escaped."""
    envelope = {k: v for k, v in pack.items() if k != "findings"}
    return json.dumps(envelope, ensure_ascii=False) + "\n"


def finding_line(finding: dict) -> str:
    """One finding as its own line of JSON."""
    return json.dumps(finding, ensure_ascii=False) + "\n"


def write_pack(path: Path, pack: dict) -> None:
    """Write a full pack (envelope + every finding) as JSONL. Convenience for tests, gold
    fixtures and `convert_sarif.py`, which already build the whole pack dict in memory in one
    step - not used by the reviewer agents themselves, which construct lines directly via
    Write/Edit the same way they did for the old JSON format."""
    lines = [envelope_line(pack)]
    lines += [finding_line(f) for f in pack.get("findings") or []]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
