#!/usr/bin/env python3
"""Render a validated findings pack to the canonical REVIEW-<slug>.md (and optionally .html).

This script owns 100% of the report layout, so the model can never drift a finding's format
(5C / C-word labels / inline runs / inconsistent fields): it supplies the pack's field VALUES;
this renderer lays them out - the same five fields, in order, on their own lines, for every
finding, every time. It refuses to render an invalid pack (validate_findings), so a missing field
is caught, not silently dropped.

Folder convention: the JSON pack lives in a subfolder (artifacts/data/findings-<slug>.json) so the
top-level artifacts/ stays user-navigable; by default the rendered REVIEW-<slug>.md is written UP to
that top-level artifacts/ (the pack's grandparent when the pack is in a `data/` dir), keeping the
.md/.html beside the other user-facing deliverables.

Output is forced to UTF-8 (Windows-safe). No third-party deps for the Markdown; `--html` imports
the bundled render_html.py in-process (resolved dual-mode, so it works in repo and
installed-plugin modes - no subprocess spawn, 2026-08-05).
Usage: python -m scripts.render_findings <pack.json> [--out REVIEW-<slug>.md] [--html]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Robust in both invocation modes: `python -m scripts.render_findings` (package context) AND
# `python <path>/scripts/render_findings.py` (direct path, e.g. from check_artifacts --fix or an
# installed plugin) - the latter puts scripts/ on sys.path[0], so the sibling import resolves.
try:
    from scripts.validate_findings import load_and_validate
except ImportError:  # pragma: no cover - direct-path invocation
    from validate_findings import load_and_validate  # type: ignore[no-redef]

_SEV = {"critical": "🔴", "warning": "🟠", "medium": "🟡", "style": "🔵"}
_SEV_ORDER = ["critical", "warning", "medium", "style"]
_BASIS = {"measured": "📊 measured", "coded": "📄 coded", "inferred": "🧠 inferred"}
_DISP = {"open": "🔴 Open", "fixed": "✅ Fixed", "accepted": "⚖️ Accepted", "deferred": "⏭️ Deferred"}
# kind -> (artifact filename prefix, default report title). Same five-field finding shape for all;
# performance findings add the optional cost/gain fields (rendered when present).
_KIND = {
    "review": ("REVIEW", "Review report"),
    "security-audit": ("SECURITY-AUDIT", "Security audit"),
    "performance": ("PERF", "Performance review"),
}


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _finding_block(f: dict) -> str:
    sev = _SEV.get(f["severity"], "•")
    basis = _BASIS.get(f.get("basis", ""), f.get("basis", ""))
    conf = f.get("confidence")
    conf_str = f"  ·  **Confidence:** {conf}/100" if conf is not None else ""
    impact = f["impact"]
    if f.get("impact_basis"):
        impact = f"{impact}  ({_BASIS.get(f['impact_basis'], f['impact_basis'])})"
    fix = f["fix"]
    return "\n".join(
        [
            f"### {sev} {f['id']} — {f['title']}",
            f"**Location:** `{f['location']}`{conf_str}  ·  **Basis:** {basis}",
            "",
            f"**Standard:** {f['standard']}",
            "",
            f"**Problem:** {f['problem']}",
            "",
            f"**Likely cause:** {f['likely_cause']}",
            "",
            f"**Impact if unaddressed:** {impact}",
            "",
            "**Fix:**",
            "```diff",
            fix["diff"].rstrip("\n"),
            "```",
            f"*Why this works:* {fix['why']}",
        ]
        + (
            # Performance findings: show the cost/gain line when present.
            [
                "",
                f"**Performance:** {f.get('current_cost', '?')} → {f.get('projected_cost', '?')}"
                + (f"  (gain: {f['gain']})" if f.get("gain") else ""),
            ]
            if any(f.get(k) for k in ("current_cost", "projected_cost", "gain"))
            else []
        )
        + [
            "",
            f"**Disposition:** {_DISP.get(f['disposition'], f['disposition'])}",
        ]
    )


def render(pack: dict) -> str:
    findings = pack.get("findings", [])
    counts = {sev: sum(1 for f in findings if f.get("severity") == sev) for sev in _SEV_ORDER}
    scoreboard = "  ·  ".join(f"{_SEV[s]} {counts[s]}" for s in _SEV_ORDER)
    disp_counts = {
        d: sum(1 for f in findings if f.get("disposition") == d)
        for d in ("fixed", "open", "accepted", "deferred")
    }
    tally = (
        f"✅ {disp_counts['fixed']}  ·  🔴 {disp_counts['open']}  ·  "
        f"⚖️ {disp_counts['accepted']}  ·  ⏭️ {disp_counts['deferred']}"
    )
    # Findings ordered by severity so the report reads worst-first.
    ordered = sorted(findings, key=lambda f: _SEV_ORDER.index(f.get("severity", "style")))

    kind = pack.get("kind", "review")
    title = pack.get("title") or f"{_KIND.get(kind, _KIND['review'])[1]} — {pack['slug']}"
    lines = [
        f"# {title}",
        "",
        f"> Generated by `render_findings` from the findings pack · **Mode** {pack['mode']} · "
        f"**Verdict** {pack['verdict']}",
        f"> **Scope:** {pack['scope']}"
        + (f"  ·  **Commit:** `{pack['commit']}`" if pack.get("commit") else "")
        + (
            f"  ·  **Reviewer independence:** {pack['reviewer_independence']}"
            if pack.get("reviewer_independence")
            else ""
        ),
        "",
        "**Contents**",
        "",
        "[TOC]",
        "",
        "## Executive summary",
        pack.get("executive_summary", "_(none provided)_"),
        "",
    ]
    if pack.get("methodology"):
        lines += ["## Method", pack["methodology"], ""]
    lines += [
        "## Scoreboard",
        scoreboard,
        "",
        f"**Tooling coverage:** {pack['tooling_coverage']}" if pack.get("tooling_coverage") else "",
        "",
        "## Findings",
    ]
    if ordered:
        for f in ordered:
            lines.append("")
            lines.append(_finding_block(f))
    else:
        lines.append("")
        lines.append("_No findings._")
    lines += [
        "",
        "## 🔵 Developer guidance - improving future code",
        pack.get("developer_guidance", "_(none provided)_"),
        "",
        "## Limitations & residual risk",
        pack.get("limitations", "_(none stated)_"),
        "",
        f"**Disposition tally:** {tally}",
        "",
    ]
    return "\n".join(line for line in lines if line is not None) + "\n"


def _default_out(pack_path: Path, slug: str, prefix: str = "REVIEW") -> Path:
    # Pack in artifacts/data/ -> report up in artifacts/; otherwise alongside the pack.
    # The prefix is the kind's (REVIEW- / SECURITY-AUDIT- / PERF-).
    root = pack_path.parent.parent if pack_path.parent.name == "data" else pack_path.parent
    return root / f"{prefix}-{slug}.md"


def render_pack_file(pack_path: Path, out_path: Path | None = None, want_html: bool = False) -> Path:
    """Validate + render one findings pack to its canonical REVIEW-<slug>.md, in-process.
    Shared by main() (CLI) and check_artifacts.apply_fixes() (2026-08-05 perf fix - apply_fixes
    used to shell out to this script once per pack, immediately followed by a subprocess per
    un-rendered .md - on a host where every python.exe spawn is inflated by endpoint-security
    scanning (corp Windows), that chain of untimed spawns could present as the whole close step
    hanging). Raises ValueError (with the schema violations) on an invalid pack - never renders
    a bad report silently."""
    errs = load_and_validate(pack_path)
    if errs:
        raise ValueError(f"{len(errs)} schema violation(s): " + "; ".join(errs))
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    prefix = _KIND.get(pack.get("kind", "review"), _KIND["review"])[0]
    out = out_path or _default_out(pack_path, pack["slug"], prefix)
    out.write_text(render(pack), encoding="utf-8")
    if want_html:
        try:
            from scripts.render_html import render_file as _render_html_file
        except ImportError:  # pragma: no cover - direct-path invocation
            from render_html import render_file as _render_html_file  # type: ignore[no-redef]
        _render_html_file(out)
    return out


def main(argv: list[str]) -> int:
    _force_utf8_output()
    args = [a for a in argv[1:] if not a.startswith("--")]
    do_html = "--html" in argv[1:]
    out_flag = next(
        (argv[i + 1] for i, a in enumerate(argv) if a == "--out" and i + 1 < len(argv)), None
    )
    if not args:
        print("usage: python -m scripts.render_findings <pack.json> [--out FILE] [--html]")
        return 2
    pack_path = Path(args[0])
    out_override = Path(out_flag) if out_flag else None
    try:
        out = render_pack_file(pack_path, out_override, want_html=do_html)
    except ValueError as exc:
        print(f"REFUSING to render {pack_path}: {exc} - run validate_findings")
        return 1
    print(f"Rendered findings pack -> {out}" + (" (+ HTML)" if do_html else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
