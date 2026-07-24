"""
scripts/check_citations.py - ground regulatory citations against the register (ADR-001).

An LLM emits pinpoint legal citations ("MAR Article 12", "Rule 10b-5") from parametric memory,
where it confabulates confidently - a wrong citation in an audit pack is a control failure. This
tool implements the ADR-001 controls:

  * RETRIEVE, don't recall - `lookup(typology)` returns grounded obligations from the register
    (config/regulatory-register.yaml) so the team cites what it can support.
  * MECHANICAL CHECK at the gate - `check_text()` scans an artifact for pinpoint citations and
    flags any that are NOT in the register as TO-VERIFY, so they get confirmed before sign-off.

The register is a **verification ledger, NOT an allowlist that limits what may be cited.** The team
should use its full regulatory knowledge to surface the obligation that applies; a citation not in
the register is "not yet human-verified", **not** "wrong" or "forbidden". This tool flags those so
they can be confirmed against the primary source (and added to the register) - it does not decide a
citation is incorrect. The real failure mode it guards is a pinpoint *asserted as decided fact*
when it was only recalled from memory; an honestly-flagged to-verify citation is fine.

Usage:
    python -m scripts.check_citations artifacts/control-mapping.md      # scan an artifact
    python -m scripts.check_citations --typology spoofing               # retrieve obligations
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REGISTER = Path(__file__).resolve().parent.parent / "config" / "regulatory-register.yaml"

# Pinpoint-citation shapes we detect in free text: Article/Art N(...), Rule N, Section N, § N,
# and bare SEC-style refs like 17a-4(b)(4).
_CITE_RE = re.compile(
    r"\bart(?:icle)?\.?\s*\d+[\dA-Za-z()\.\-]*"
    r"|\brule\s*\d+[\dA-Za-z\-]*"
    r"|\bsection\s*\d+[\dA-Za-z()\-]*"
    r"|§\s*\d+[\dA-Za-z()\-]*"
    r"|\b\d{1,3}[A-Za-z]-\d+(?:\([\dA-Za-z]+\))*",
    re.IGNORECASE,
)

# Handbook-style citations (FCA sourcebooks, similar coded rulebooks): an UPPERCASE code +
# dotted number - "SYSC 6.1.1R", "MAR 1.6". Deliberately case-SENSITIVE (a separate pattern:
# inline (?-i:) needs Python 3.11+, and CI runs 3.10) and dot-required, so prose like
# "chapter 6" or "ISO 29119" stays out.
_CITE_RE_CS = re.compile(r"\b[A-Z]{2,6}\s+\d+(?:\.\d+){1,3}[RGE]?\b")


def _find_raw(text: str):
    """All citation-shaped matches from both pattern families, in document order."""
    hits = [(m.start(), m.group(0)) for m in _CITE_RE.finditer(text or "")]
    hits += [(m.start(), m.group(0)) for m in _CITE_RE_CS.finditer(text or "")]
    return [s for _, s in sorted(hits)]


def _load_register(path: str | Path = _REGISTER) -> dict:
    """Load the bundled register, merged with the WORKING PROJECT's overlay when present.

    In plugin mode the bundled register lives in the plugin cache - not a repo the user
    commits to, and replaced on every update - so engagement-verified entries need a home
    that travels with the project: `config/regulatory-register.yaml` in the working
    directory (same two-tier pattern as the codebase map). Overlay entries EXTEND the
    bundled set; an overlay entry with the same `id` overrides the bundled one (e.g. a
    project flips a seeded `status: example` to `verified` locally). In repo-as-project
    the two paths resolve to the same file and no merge happens.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover - exercised only without pyyaml
        raise RuntimeError("pyyaml is required: pip install -r requirements-dev.txt")
    base = yaml.safe_load(Path(path).read_text()) or {}
    overlay_path = Path.cwd() / "config" / "regulatory-register.yaml"
    try:
        same = overlay_path.resolve() == Path(path).resolve()
    except OSError:
        same = True
    if not same and overlay_path.is_file():
        overlay = yaml.safe_load(overlay_path.read_text()) or {}
        merged = {ob.get("id"): ob for ob in (base.get("obligations") or [])}
        for ob in overlay.get("obligations") or []:
            merged[ob.get("id")] = ob
        base["obligations"] = list(merged.values())
    return base


def _core(citation: str) -> str:
    """Normalise a citation to a comparable core: lower-case, 'article'->'art', strip spaces/dots.

    'Article 12(1)(a)' -> 'art12(1)(a)';  'Rule 10b-5' -> 'rule10b-5';  '§ 48' -> '§48'.
    """
    s = citation.lower().replace("article", "art")
    return re.sub(r"[\s.]", "", s)


def _register_cores(register: dict) -> set[str]:
    """Citation cores of HUMAN-VERIFIED obligations only. An entry with status other than
    'verified' (or no verified_on date) is in the ledger but still awaiting its human check -
    citing it must flag TO-VERIFY, not pass as verified (the seeds are exactly this state)."""
    cores: set[str] = set()
    for ob in register.get("obligations", []) or []:
        if (ob.get("status") or "").strip() != "verified":
            continue
        if not (ob.get("verified_on") or "").strip("- "):
            continue
        candidates = [ob.get("pinpoint", "")] + list(ob.get("aliases", []) or [])
        for c in candidates:
            for m in _find_raw(c or ""):
                cores.add(_core(m))
    return cores


def find_citations(text: str) -> list[str]:
    """Return the distinct pinpoint citations detected in *text* (original spelling)."""
    seen, out = set(), []
    for m in _find_raw(text or ""):
        key = _core(m)
        if key not in seen:
            seen.add(key)
            out.append(m.strip())
    return out


def check_text(text: str, register: dict | None = None) -> dict:
    """Scan *text* for pinpoint citations; classify each as verified (in register) or unverified.

    Returns {"verified": [...], "unverified": [...]} (original spellings). Pure - no I/O.
    """
    register = register if register is not None else _load_register()
    known = _register_cores(register)
    verified, unverified = [], []
    for cite in find_citations(text):
        (verified if _core(cite) in known else unverified).append(cite)
    return {"verified": verified, "unverified": unverified}


def lookup(typology: str, register: dict | None = None) -> list[dict]:
    """Retrieve register obligations whose typology mentions *typology* (case-insensitive)."""
    register = register if register is not None else _load_register()
    t = typology.lower().strip()
    return [
        ob
        for ob in register.get("obligations", []) or []
        if t in str(ob.get("typology", "")).lower()
    ]


def _main(argv: list[str] | None = None) -> int:
    # Force UTF-8 output so a cp1252 (Windows) console can't crash on non-ASCII (e.g. `§`) - 0.19.0.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Ground regulatory citations against the register.")
    ap.add_argument("artifact", nargs="?", type=Path, help="path to a .md/.txt artifact to scan")
    ap.add_argument("--typology", help="retrieve obligations for a typology (e.g. spoofing)")
    ap.add_argument("--register", type=Path, default=_REGISTER)
    args = ap.parse_args(argv)

    register = _load_register(args.register)

    if args.typology:
        hits = lookup(args.typology, register)
        if not hits:
            print(f"No register obligation found for typology '{args.typology}'.")
            return 0
        for ob in hits:
            print(
                f"- {ob['pinpoint']}  [{ob['id']}, {ob.get('status', '?')}]  {ob.get('source', '')}"
            )
        return 0

    if not args.artifact:
        ap.error("provide an artifact to scan, or --typology to retrieve")

    result = check_text(args.artifact.read_text(), register)
    for c in result["verified"]:
        print(f"[VERIFIED]  {c}")
    for c in result["unverified"]:
        print(
            f"[TO-VERIFY] {c} - not yet in the register; confirm against the primary source and add it"
        )
    print(
        f"\n{len(result['verified'])} verified, {len(result['unverified'])} to-verify "
        f"citation(s) in {args.artifact}. (To-verify = needs confirmation, NOT 'wrong'.)"
    )
    # Exit 1 is a REVIEW SIGNAL ("there are citations to confirm before sign-off"), not a verdict
    # that any citation is incorrect.
    return 1 if result["unverified"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
